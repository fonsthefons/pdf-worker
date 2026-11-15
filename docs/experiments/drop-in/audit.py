"""Drop-in audit: books through the inbox as dropped, what came out scored without a
reference, and pages picked for a model to check (docs/experiments/drop-in/README.md).

Usage (repo root, .venv/bin/python):
  audit.py manifest OUT.json            the README's audit set: kind, language, pages by code
  audit.py run OUT_DIR MANIFEST.json    each book through inbox.process, one at a time
  audit.py score OUT_DIR                OUT_DIR/audit.tsv and OUT_DIR/audit.md
  audit.py pages OUT_DIR [--per-book 5] pages to audit, under OUT_DIR/pages/<book>/
  audit.py selftest

``run`` copies each book into OUT_DIR/file_inbox and runs ``inbox.process`` on it alone in a
child process (formats epub and pdf: the "pdf" format is the Typst-typeset one; tesseract,
no marks, no options, so margin references as the inbox sets them: when found; the layout
model's rows cached in scratch/paddle-home). A book that raises or runs over 90 minutes is
recorded as failed and the next one starts. State, detail and seconds: OUT_DIR/run.json,
the books' output: OUT_DIR/logs/<book>.log.

``score`` measures, per book (our book: the EPUB in file_outbox, or its draft):
- state; human: a step asked of the user (draft, waiting, mark);
- words in / out: tokens with a letter in the source (the PDF the book was built from,
  page by page, or the source EPUB's spine) and in our EPUB's body and notes;
- contents: our nav's entries and how many resolve (file and id exist); headings per level;
- outline: the source's own (``get_toc()`` or its nav/NCX) and the share of its titles found
  in one of our headings (one's words inside the other's);
- garble per 10,000 of our words: Latin-script words the book language's dictionary
  doesn't know (``ai_client.check.Words``; es and en only), spaced-hyphen splits ("pala-
  bra"), tokens mixing scripts, runs of three or more single letters;
- notes, by shared 5-grams with the source's notes and body: our body words found only in
  source notes (note in body), our note words found only in the source body (body in notes),
  source note words found nowhere in ours (lost; only counted). A PDF's notes are its lines
  smaller than the body size below the page's last body-size line that isn't a running
  head or foot (seen on 3 sampled pages); all small lines on a page without body-size
  lines where two or more start with a number (endnotes); an EPUB's, ``book_score.read_epub``'s;
- margin references: Stephanus labels ours carries ("[17a]") and Bekker ones in the text
  ("402a5"); gaps (a label or column skipped) and back steps in their order;
- review rows per kind (``.fixes.tsv``); report.md's grade.

``pages`` picks, per book, the page with most garble, one with notes, one with margin
references, one chapter start, one at random (seed 0), then random ones up to
``--per-book``; and writes ``pNNN.png`` (the source page at 100 dpi; for an EPUB source
``pNNN.source.txt``, the chapter's text) and ``pNNN.txt``: our text for it (by our EPUB's
page marks, else where the page's first and last eight words are found in our text), at
most 60 lines, with its notes and margin references. On a ``tools/quality.py build``
folder (no run.json) the books are quality.py's and ours their Markdown.
"""

import argparse
import json
import os
import posixpath
import random
import re
import shutil
import signal
import subprocess
import sys
import time
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from html import unescape
from itertools import pairwise
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))

import book_score  # noqa: E402
from ai_client import check  # noqa: E402
from book_score import BODY, NOTE, Text, words  # noqa: E402
from regression import _blocks, _write_atomic  # noqa: E402

from pdf_worker import inbox  # noqa: E402
from pdf_worker.convert import guess_language  # noqa: E402
from pdf_worker.document import open_pdf  # noqa: E402
from pdf_worker.fixes import default_fixes_path, read_fixes  # noqa: E402
from pdf_worker.margin_estimates import label_value  # noqa: E402
from pdf_worker.ocr_check import assess_text_layer  # noqa: E402

AUDIT_SET = [
    *(
        f"test_pdfs/books_sd/{name}"
        for name in (
            "Antropología Filosófica.pdf",
            "De Anima - Aristóteles (traduccion_tomas_calvo_martinez).pdf",
            "Filosofia del Hombre - Roger Verneaux bad 1.pdf",
            "Metafisica - Tomas Alvira bad 1.pdf",
            "Epistemología General Verneaux.pdf",
            "La Biblia en su entorno.pdf",
            "reale_y_antiseri/Historia de Filosofía Antigua Tomo 1.pdf",
            "reale_y_antiseri/Historia De La Filosofía Tomo V.pdf",
            "Introduction to Christianity by Ratzinger.epub",
            "copleston/4 - De Descartes a Leibniz Frederick Copleston.epub",
            "AF/Prometeo Encadenado Bilingüe.epub",
            "AF/The Four Loves by C.S. Lewis.epub",
        )
    ),
    "test_pdfs/Timeo_by_Platón_no_intro.pdf",
    "test_pdfs/platon_dialogos_vi_bad.pdf",
]
FORMATS = ["epub", "pdf"]  # "pdf" is typeset by Typst: convert.FORMATS has no other
TIME_LIMIT = 90 * 60  # seconds per book
RESULT = "AUDIT-RESULT "  # the child's last line: its BookResult as JSON
HUMAN = ("draft", "waiting", "mark")
MAX_LINES = 60
ANCHOR = 8  # words: a page found in our text by its first and last eight
SEED = 0
SMALL = 0.92  # a line under this share of the body size is small print
PAGE = "\x00pg"  # a page mark's line while reading our EPUB

_LETTERS_RE = re.compile(r"[^\W\d_]+")
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(
    r"</?(?:p|div|h[1-6]|li|ul|ol|blockquote|section|aside|article|table|tr|td|th|dd|dt|"
    r"pre|figure|figcaption|header|footer|nav|br|hr|body)\b[^>]*>",
    re.I,
)
_HEAD_OPEN_RE = re.compile(r"<h([1-6])\b[^>]*>", re.I)
_ASIDE_RE = re.compile(r'<aside\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</aside>', re.S)
_NOTEREF_RE = re.compile(
    r'<a\b[^>]*\bhref="[^"#]*#([^"]+)"[^>]*epub:type="noteref"[^>]*>.*?</a>', re.S
)
_PAGEBREAK_RE = re.compile(r'<span\b[^>]*\bid="pg(\d+)"[^>]*>\s*</span>')
# A page mark first in a heading: moved before it, so the heading stays one line.
_HEAD_PAGE_RE = re.compile(f"(<h[1-6]\\b[^>]*>)(\\s*{_PAGEBREAK_RE.pattern})")
_A_RE = re.compile(r'<a\b[^>]*\bhref="([^"]*)"[^>]*>(.*?)</a>', re.S)
_NCX_RE = re.compile(r"<text>(.*?)</text>\s*</navLabel>\s*<content[^>]*\bsrc=\"([^\"]*)\"", re.S)
_MD_NOTE_RE = re.compile(r"^\[\^([^\]]+)\]:\s*")
_MD_MREF_RE = re.compile(r"\*\*\\\[([^\]\\]+)\\\]\*\*")
_REF_RE = re.compile(r"\[\^([^\]]+)\]")  # a note reference in our lines
_MREF_RE = re.compile(r"\[~?(\d{1,4}[a-e])\]")  # a margin reference in our lines
_BEKKER_RE = re.compile(r"\b(\d{3,4})([ab])(\d{1,2})?\b")
_SPLIT_RE = re.compile(r"[^\W\d_]- +[a-zß-ÿ]")
_SINGLES_RE = re.compile(r"(?<!\S)[^\W\d_](?:\s+[^\W\d_](?!\S)){2,}")
_NOTE_START_RE = re.compile(r"^\(?\d{1,3}[\s.)]")
_GRADE_RE = re.compile(r"\*\*Grade (\w)\*\*")
GARBLE = ("unknown", "splits", "mixed", "singles")
COLUMNS = (
    "book", "kind", "state", "human", "seconds", "outputs", "words_in", "words_out",
    "kept", "toc", "toc_ok", "headings", "outline", "outline_found", "garble_10k",
    *GARBLE, "note_in_body", "body_in_notes", "notes_lost", "source_note_words",
    "margin_refs", "margin_gaps", "margin_back", "fixes", "grade",
)  # fmt: skip


# --- reading -----------------------------------------------------------------------------


def _html_lines(html: str) -> list[str]:
    text = unescape(_TAG_RE.sub("", _BLOCK_RE.sub("\n", html)))
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


def _plain(line: str) -> str:
    """A line of ours without its note and margin references, Markdown marks or escapes."""
    return re.sub(r"[*\\]|^#+ ", "", _MREF_RE.sub(" ", _REF_RE.sub("", line)))


@dataclass
class Out:
    """Our book: body lines ("## " before a heading, "[^id]" note and "[17a]" margin
    references in place), notes by id, and each PDF page's first line (EPUB page marks)."""

    lines: list[str] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)
    pages: dict[int, int] = field(default_factory=dict)
    toc: list[tuple[str, str]] = field(default_factory=list)  # (target, title)
    toc_ok: int = 0

    @property
    def headings(self) -> list[tuple[int, str]]:
        return [
            (len(line) - len(line.lstrip("#")), line.lstrip("# "))
            for line in self.lines
            if line.startswith("#")
        ]


def read_output(path: Path) -> Out:
    out = Out()
    if path.suffix == ".md":
        note = None
        for block in _blocks(path):
            for line in block.split("\n"):
                line = _MD_MREF_RE.sub(r"[\1]", line)
                if m := _MD_NOTE_RE.match(line):
                    note = m[1]
                    out.notes[note] = line[m.end() :]
                elif note:
                    out.notes[note] += " " + line.strip()
                elif not line.startswith("!["):
                    out.lines.append(line.strip())
            note = None
        return out
    with zipfile.ZipFile(path) as z:
        for doc in book_score._spine(z):
            html = z.read(doc).decode("utf-8", "replace")
            for m in _ASIDE_RE.finditer(html):
                out.notes[m[1]] = " ".join(_html_lines(m[2]))
            html = _HEAD_PAGE_RE.sub(r"\2\1", _ASIDE_RE.sub("\n", html))
            html = _HEAD_OPEN_RE.sub(lambda m: "\n" + "#" * int(m[1]) + " ", html)
            html = _NOTEREF_RE.sub(lambda m: f"[^{m[1]}]", html)
            html = _PAGEBREAK_RE.sub(lambda m: f"<br/>{PAGE}{m[1]}<br/>", html)
            for line in _html_lines(html):
                if line.startswith(PAGE):
                    out.pages.setdefault(int(line[len(PAGE) :]), len(out.lines))
                elif line.strip("# "):
                    out.lines.append(line)
        out.toc = _toc(z)
        out.toc_ok = sum(_resolves(z, target) for target, _ in out.toc)
    return out


def _toc(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    """(file#anchor, title) of each contents entry: the EPUB 3 nav's, else the NCX's."""
    container = ElementTree.fromstring(z.read("META-INF/container.xml"))
    opf = next(e.get("full-path") for e in container.iter() if e.tag.endswith("rootfile"))
    items = [e for e in ElementTree.fromstring(z.read(opf)).iter() if e.tag.endswith("item")]
    nav = [e for e in items if "nav" in (e.get("properties") or "").split()]
    ncx = [e for e in items if e.get("media-type") == "application/x-dtbncx+xml"]
    if not nav and not ncx:
        return []
    path = posixpath.normpath(posixpath.join(posixpath.dirname(opf), (nav or ncx)[0].get("href")))
    text = z.read(path).decode("utf-8", "replace")
    if nav:
        toc = re.search(r'<nav\b[^>]*epub:type="toc"[^>]*>(.*?)</nav>', text, re.S)
        found = _A_RE.findall(toc[1] if toc else text)
    else:
        found = [(src, title) for title, src in _NCX_RE.findall(text)]
    base = posixpath.dirname(path)
    return [
        (posixpath.normpath(posixpath.join(base, unquote(href))), " ".join(_html_lines(title)))
        for href, title in found
    ]


def _resolves(z: zipfile.ZipFile, target: str) -> bool:
    file, _, anchor = target.partition("#")
    if file not in z.namelist():
        return False
    return not anchor or f'id="{anchor}"' in z.read(file).decode("utf-8", "replace")


def _line_parts(page) -> list[tuple[float, str, float]]:
    """(size, text, top) of each text line: the size most of its letters are set in."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            sizes = Counter()
            for span in line["spans"]:
                sizes[round(span["size"] * 2) / 2] += len(span["text"].strip())
            text = "".join(span["text"] for span in line["spans"])
            if text.strip():
                out.append((sizes.most_common(1)[0][0], text, line["bbox"][1]))
    return out


def _letters(text: str) -> str:
    return " ".join(_LETTERS_RE.findall(text.lower()))


def read_pdf(pdf: Path) -> tuple[Text, list[int]]:
    """The PDF's words page by page, as BODY or NOTE (see the module's notes rule), and
    each page's first word."""
    out, starts = Text(), []
    with open_pdf(pdf) as doc:
        sizes, seen = Counter(), Counter()
        for index in range(0, doc.page_count, max(1, doc.page_count // 40)):
            parts = _line_parts(doc[index])
            for size, text, _ in parts:
                sizes[size] += len(text)
            seen.update({_letters(text) for _, text, _ in parts})
        body = sizes.most_common(1)[0][0] if sizes else 0
        # Running heads and feet (on 3 or more sampled pages) don't end the body.
        furniture = {key for key, n in seen.items() if n >= 3}
        for page in doc:
            starts.append(len(out.words))
            lines = _line_parts(page)
            last = max(
                (
                    top
                    for size, text, top in lines
                    if size >= body * SMALL and _letters(text) not in furniture
                ),
                default=None,
            )
            small = [(text, top) for size, text, top in lines if size < body * SMALL]
            endnotes = last is None and sum(bool(_NOTE_START_RE.match(t)) for t, _ in small) >= 2
            for size, text, top in lines:
                note = size < body * SMALL and (
                    endnotes or (last is not None and top > last and top > page.rect.height / 2)
                )
                if out.kind and (out.kind[-1] == NOTE) != note:
                    out.blocks += 1
                out.add(words(text), NOTE if note else BODY, out.blocks)
            out.blocks += 1
    return out, starts


def _outline(source: Path) -> list[str]:
    if source.suffix.lower() == ".epub":
        with zipfile.ZipFile(source) as z:
            return [title for _, title in _toc(z)]
    with open_pdf(source) as doc:
        return [title for _, title, _ in doc.get_toc()]


# --- measures ----------------------------------------------------------------------------


def _checker(language: str) -> check.Words | None:
    return check.Words(language) if language in check.config.LANGUAGES else None


def garble(lines, checker: check.Words | None) -> tuple[Counter, int]:
    """Garble counts (``GARBLE``) in ``lines`` of ours, and their words."""
    counts, n = Counter(), 0
    for line in lines:
        line = _plain(line)
        found = _LETTERS_RE.findall(line)
        n += len(found)
        if checker:
            counts["unknown"] += sum(
                len(w) > 1 and _latin(w) and not checker.known(w) for w in found
            )
        counts["splits"] += len(_SPLIT_RE.findall(line))
        counts["singles"] += len(_SINGLES_RE.findall(line))
        counts["mixed"] += sum(len(_scripts(token)) > 1 for token in line.split())
    return counts, n


def _latin(word: str) -> bool:
    return word.isascii() or all("LATIN" in unicodedata.name(c, "") for c in word)


def _scripts(token: str) -> set[str]:
    return {unicodedata.name(c, "?").split(" ")[0] for c in token if c.isalpha()}


def _grams(runs: list[list[str]]) -> set[tuple]:
    return {tuple(r[k : k + 5]) for r in runs for k in range(len(r) - 4)}


def _covered(run: list[str], grams: set[tuple]) -> int:
    """Words of ``run`` inside a 5-gram of ``grams``."""
    hit = [False] * len(run)
    for k in range(len(run) - 4):
        if tuple(run[k : k + 5]) in grams:
            hit[k : k + 5] = [True] * 5
    return sum(hit)


def _runs(text: Text, note: bool) -> list[list[str]]:
    """Runs of ``text``'s words that are (or aren't) notes, a run per block."""
    runs: dict[int, list[str]] = {}
    for w, kind, block in zip(text.words, text.kind, text.block, strict=True):
        if (kind == NOTE) == note:
            runs.setdefault(block, []).append(w)
    return list(runs.values())


def note_errors(source: Text, body: list[list[str]], notes: list[list[str]]) -> dict:
    """Our ``body`` and ``notes`` (runs of words) against the source's notes and body."""
    src_notes, src_body = _runs(source, True), _runs(source, False)
    note_g, body_g = _grams(src_notes), _grams(src_body)
    ours = _grams(body + notes)
    return {
        "note_in_body": sum(_covered(r, note_g - body_g) for r in body),
        "body_in_notes": sum(_covered(r, body_g - note_g) for r in notes),
        "notes_lost": sum(len(r) - _covered(r, ours) for r in src_notes),
        "source_note_words": sum(map(len, src_notes)),
    }


def margin_sequence(lines: list[str]) -> dict:
    """Margin references in ``lines`` of ours: how many, gaps and back steps. Stephanus
    labels count by section ("17e" -> "18a" is one step), Bekker ones by column ("402a"
    -> "402b" one step; lines within a column only need to climb)."""
    stephanus, bekker = [], []
    for line in lines:
        stephanus += [(label_value(m[1]), 0) for m in _MREF_RE.finditer(line)]
        for m in _BEKKER_RE.finditer(_MREF_RE.sub(" ", _REF_RE.sub("", line))):
            bekker.append((int(m[1]) * 2 + (m[2] == "b"), int(m[3] or 0)))
    gaps = back = 0
    for keys in (stephanus, bekker):
        for a, b in pairwise(keys):
            back += b <= a
            gaps += b > a and b[0] - a[0] > 1
    return {"margin_refs": len(stephanus) + len(bekker), "margin_gaps": gaps, "margin_back": back}


def _found(title: str, headings: list[str]) -> bool:
    key = f" {' '.join(words(title))} "
    return key.strip() != "" and any(key in h or h in key for h in headings)


def _has_letter(w: str) -> bool:
    return any(c.isalpha() for c in w)


# --- run ---------------------------------------------------------------------------------


def manifest(path: Path) -> None:
    books = []
    for rel in AUDIT_SET:
        source = ROOT / rel
        if source.suffix == ".epub":
            with zipfile.ZipFile(source) as z:
                docs = book_score._spine(z)
                middle = docs[len(docs) // 3 : len(docs) // 3 + 5]
                sample = " ".join(
                    " ".join(_html_lines(z.read(d).decode("utf-8", "replace"))) for d in middle
                )
            books.append(
                {
                    "path": rel,
                    "kind": "epub",
                    "language": guess_language(sample),
                    "pages": len(docs),
                }
            )
            continue
        with open_pdf(source) as doc:
            layer = assess_text_layer(doc)
            n = doc.page_count
            sample = " ".join(doc[i].get_text() for i in range(n // 3, min(n, n // 3 + 10)))
        scan = layer.scanned_pages >= 0.5 or layer.mode == "skip"
        books.append(
            {
                "path": rel,
                "kind": "scan" if scan else "born digital",
                "ocr": layer.mode or "none",
                "language": guess_language(sample) if sample.strip() else "?",
                "pages": n,
            }
        )
    _write_atomic(path, json.dumps(books, ensure_ascii=False, indent=1) + "\n")


def run(out: Path, manifest_path: Path) -> None:
    books = json.loads(manifest_path.read_text(encoding="utf-8"))
    os.environ.setdefault("PDF_WORKER_PADDLE_CACHE", str(ROOT / "scratch" / "paddle-home"))
    for folder in (out / inbox.INBOX, out / "logs"):
        folder.mkdir(parents=True, exist_ok=True)
    record_path = out / "run.json"
    record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
    for book in books:
        source = ROOT / book["path"]
        label, start = source.stem, time.monotonic()
        state, detail = "failed", ""
        try:
            target = out / inbox.INBOX / source.name
            shutil.copy2(source, target)
            log = out / "logs" / f"{label}.log"
            with log.open("w", encoding="utf-8") as f:
                child = subprocess.Popen(
                    [sys.executable, __file__, "one", str(out), str(target)],
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,  # its own group: a timeout kills OCR and models too
                    cwd=ROOT,
                )
                try:
                    code = child.wait(TIME_LIMIT)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                    code, detail = None, f"over {TIME_LIMIT // 60} minutes"
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            said = [json.loads(x[len(RESULT) :]) for x in lines if x.startswith(RESULT)]
            if said:
                state, detail = said[-1]["state"], said[-1]["detail"]
            elif code is not None:
                detail = f"exit {code}: {lines[-1] if lines else ''}"
        except Exception as exc:  # one book must never stop the rest
            detail = f"{type(exc).__name__}: {exc}"
        seconds = round(time.monotonic() - start)
        record[label] = {
            **book,
            "name": source.name,
            "state": state,
            "detail": detail,
            "seconds": seconds,
        }
        _write_atomic(record_path, json.dumps(record, ensure_ascii=False, indent=1) + "\n")
        print(f"{label}: {state} in {seconds} s; {detail}", flush=True)


def one(out: Path, book: Path) -> None:
    """In the child: the inbox on ``book`` alone; its result as the last line."""
    results = inbox.process(
        out, book=book, settings={"formats": FORMATS}, say=lambda m: print(m, flush=True)
    )
    state, detail = (
        (results[0].state, results[0].detail) if results else ("skipped", "not processed")
    )
    print(RESULT + json.dumps({"state": state, "detail": detail}), flush=True)


# --- score -------------------------------------------------------------------------------


def _output(out: Path, stem: str, suffix: str) -> tuple[Path | None, str]:
    for folder, how in ((out / inbox.OUTBOX, ""), (out / inbox.OUTBOX / inbox.DRAFTS, "draft ")):
        if (folder / f"{stem}{suffix}").exists():
            return folder / f"{stem}{suffix}", how
    return None, ""


def _built(out: Path, book: dict) -> Path:
    """The PDF the book was built from (OCR'd for a scan), else the source."""
    built = out / inbox.WORK / book["name"] / f"{Path(book['name']).stem}.pdf"
    return built if built.exists() else ROOT / book["path"]


def score_book(out: Path, label: str, book: dict) -> dict:
    stem = Path(book["name"]).stem
    row = dict.fromkeys(COLUMNS, "")
    row |= {"book": label, "kind": book["kind"], "state": book["state"], "seconds": book["seconds"]}
    row["human"] = "yes" if book["state"] in HUMAN else "no"
    found = {ext: _output(out, stem, f".{ext}") for ext in FORMATS}
    row["outputs"] = " ".join(f"{how}{ext}" for ext, (path, how) in found.items() if path) or "none"
    work = out / inbox.WORK / book["name"]
    if (work / "report.md").exists():
        grade = _GRADE_RE.search((work / "report.md").read_text(encoding="utf-8"))
        row["grade"] = grade[1] if grade else ""
    fixes = Counter(fix.kind for fix in read_fixes(default_fixes_path(_built(out, book))))
    row["fixes"] = " ".join(f"{kind}:{n}" for kind, n in fixes.most_common())
    epub = found["epub"][0]
    if epub is None:
        return row
    ours = read_output(epub)
    source_path = ROOT / book["path"]
    if source_path.suffix.lower() == ".epub":
        source = book_score.read_epub(source_path)
    else:
        source = read_pdf(_built(out, book))[0]
    body = [w for line in ours.lines for w in words(_plain(line))]
    notes = [words(_plain(n)) for n in ours.notes.values()]
    row["words_in"] = sum(map(_has_letter, source.words))
    row["words_out"] = sum(map(_has_letter, body)) + sum(_has_letter(w) for n in notes for w in n)
    row["kept"] = f"{row['words_out'] / row['words_in']:.0%}" if row["words_in"] else ""
    row["toc"], row["toc_ok"] = len(ours.toc), ours.toc_ok
    levels = Counter(level for level, _ in ours.headings)
    row["headings"] = " ".join(f"h{level}:{n}" for level, n in sorted(levels.items()))
    heads = [f" {' '.join(words(text))} " for _, text in ours.headings]
    outline = _outline(source_path)
    row["outline"] = len(outline)
    if outline:
        row["outline_found"] = f"{sum(_found(t, heads) for t in outline) / len(outline):.0%}"
    language = book.get("language", "?")
    if language not in check.config.LANGUAGES:
        language = guess_language(" ".join(ours.lines[:3000]))
    counts, n = garble([*ours.lines, *ours.notes.values()], _checker(language))
    row |= {k: counts[k] for k in GARBLE}
    row["garble_10k"] = f"{counts.total() / max(n, 1) * 10_000:.0f}"
    row |= note_errors(source, [body], notes)
    row |= margin_sequence(ours.lines)
    return row


def score(out: Path) -> None:
    record = json.loads((out / "run.json").read_text(encoding="utf-8"))
    rows = []
    for label, book in record.items():
        try:
            rows.append(score_book(out, label, book))
        except Exception as exc:  # one unreadable book must not hide the others
            rows.append(
                dict.fromkeys(COLUMNS, "") | {"book": label, "state": f"score failed: {exc}"}
            )
        print(f"{label}: scored", flush=True)
    tsv = ["\t".join(COLUMNS)] + ["\t".join(str(r[c]) for c in COLUMNS) for r in rows]
    _write_atomic(out / "audit.tsv", "\n".join(tsv) + "\n")
    md = [
        "# Drop-in audit",
        "",
        "How each column is counted: `docs/experiments/drop-in/audit.py` (module docstring).",
        "Notes and garble columns are words; garble_10k is all garble per 10,000 of our words.",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
        *("| " + " | ".join(str(r[c]).replace("|", "/") for c in COLUMNS) + " |" for r in rows),
    ]
    _write_atomic(out / "audit.md", "\n".join(md) + "\n")


# --- pages -------------------------------------------------------------------------------


def _anchors(lines: list[str]) -> tuple[dict[tuple, int], list[int]]:
    """Each ``ANCHOR``-gram of our words that occurs once -> its first word; each word's
    line."""
    ws, line_of = [], []
    for k, line in enumerate(lines):
        found = words(_plain(line))
        ws += found
        line_of += [k] * len(found)
    index: dict[tuple, int] = {}
    for k in range(len(ws) - ANCHOR + 1):
        gram = tuple(ws[k : k + ANCHOR])
        index[gram] = -1 if gram in index else k
    return index, line_of


def find_slice(unit: list[str], index, line_of) -> tuple[int, int] | None:
    """Our lines holding ``unit`` (a page's words): from where its first eight words
    are to where its last eight are (the first and last that occur once in ours, within
    40 words of each end)."""
    reach = range(min(40, len(unit) - ANCHOR + 1))
    firsts = (index.get(tuple(unit[k : k + ANCHOR]), -1) for k in reach)
    lasts = (index.get(tuple(unit[len(unit) - ANCHOR - k : len(unit) - k]), -1) for k in reach)
    a = next((p for p in firsts if p >= 0), None)
    b = next((p for p in lasts if p >= 0), None)
    if a is None and b is None:
        return None
    if a is None or b is None or b < a:
        start = line_of[a if a is not None else b]
        return start, start + MAX_LINES
    return line_of[a], line_of[b + ANCHOR - 1] + 1


def _units(source: Path, built: Path) -> list[list[str]]:
    """The source's pages' body words (an EPUB's: its spine files')."""
    if source.suffix.lower() == ".epub":
        with zipfile.ZipFile(source) as z:
            return [
                words(" ".join(_html_lines(z.read(d).decode("utf-8", "replace"))))
                for d in book_score._spine(z)
            ]
    text, starts = read_pdf(built)
    ends = [*starts[1:], len(text.words)]
    return [
        [w for w, kind in zip(text.words[s:e], text.kind[s:e], strict=True) if kind != NOTE]
        for s, e in zip(starts, ends, strict=True)
    ]


def _slices(ours: Out, units: list[list[str]], marks: bool) -> dict[int, tuple[int, int]]:
    """Each unit's lines of ours; ``marks``: by our page marks (units are the PDF's pages;
    an EPUB rebuilt from an EPUB has marks of its own layout)."""
    if marks and ours.pages:
        marks = sorted(ours.pages.items())
        ends = [line for _, line in marks[1:]] + [len(ours.lines)]
        return {page: (line, end) for (page, line), end in zip(marks, ends, strict=True)}
    index, line_of = _anchors(ours.lines)
    found = {u: find_slice(unit, index, line_of) for u, unit in enumerate(units)}
    return {u: s for u, s in found.items() if s}


def pick(ours: Out, slices: dict, count: int, units: int, checker) -> list[tuple[int, str]]:
    rng = random.Random(SEED)
    lines = {u: ours.lines[a:b] for u, (a, b) in slices.items()}
    garbled = {u: garble(ls, checker)[0].total() for u, ls in lines.items()}
    picks: list[tuple[int, str]] = []

    def add(unit, why):
        if unit is not None and unit not in [u for u, _ in picks]:
            picks.append((unit, why))

    def some(test):
        return rng.choice([u for u, ls in sorted(lines.items()) if any(map(test, ls))] or [None])

    add(max(garbled, key=garbled.get, default=None), "most garble")
    add(some(_REF_RE.search), "notes")
    add(some(_MREF_RE.search), "margin references")
    add(some(lambda line: line.startswith("#")), "chapter start")
    for _ in range(count * 10):
        if len(picks) >= min(count, units):
            break
        add(rng.randrange(units), "random")
    return picks[:count]


def write_unit(dest: Path, label: str, unit: int, why: str, ours: Out, slices: dict) -> None:
    head = [f"{label}, page {unit + 1}: {why}"]
    if unit not in slices:
        _write_atomic(
            dest / f"p{unit + 1:03d}.txt", "\n".join(head + ["(not found in the output)"]) + "\n"
        )
        return
    a, b = slices[unit]
    lines = ours.lines[a:b]
    refs = dict.fromkeys(m[1] for line in lines for m in _REF_RE.finditer(line))
    mrefs = [m[1] for line in lines for m in _MREF_RE.finditer(line)]
    text = head + [f"our lines {a + 1}-{b} (at most {MAX_LINES})", "---", *lines[:MAX_LINES]]
    text += ["--- notes", *(f"[^{r}] {ours.notes.get(r, '(no note)')}" for r in refs)]
    text += ["--- margin references", " ".join(mrefs)]
    _write_atomic(dest / f"p{unit + 1:03d}.txt", "\n".join(text) + "\n")


def _books(out: Path) -> list[tuple[str, Path, Path, Path | None, str]]:
    """(label, source, PDF built from, ours, language) of each book of the folder."""
    if (out / "run.json").exists():
        record = json.loads((out / "run.json").read_text(encoding="utf-8"))
        return [
            (
                label,
                ROOT / b["path"],
                _built(out, b),
                _output(out, Path(b["name"]).stem, ".epub")[0],
                b.get("language", "?"),
            )
            for label, b in record.items()
        ]
    import quality

    return [(label, pdf, pdf, out / f"{label}.md", "?") for label, pdf, *_ in quality.PAIRS]


def pages(out: Path, per_book: int) -> None:
    for label, source, built, ours_path, language in _books(out):
        if not ours_path or not ours_path.exists():
            print(f"{label}: no output, skipped", flush=True)
            continue
        ours = read_output(ours_path)
        if language not in check.config.LANGUAGES:
            language = guess_language(" ".join(ours.lines[:3000]))
        units = _units(source, built)
        slices = _slices(ours, units, source.suffix.lower() != ".epub")
        dest = out / "pages" / label
        dest.mkdir(parents=True, exist_ok=True)
        picks = pick(ours, slices, per_book, len(units), _checker(language))
        for unit, why in picks:
            write_unit(dest, label, unit, why, ours, slices)
            name = dest / f"p{unit + 1:03d}"
            if source.suffix.lower() == ".epub":
                with zipfile.ZipFile(source) as z:
                    doc = book_score._spine(z)[unit]
                    chapter = _html_lines(z.read(doc).decode("utf-8", "replace"))
                _write_atomic(
                    name.with_suffix(".source.txt"), "\n".join(chapter[:MAX_LINES]) + "\n"
                )
            else:
                with open_pdf(source) as doc:
                    tmp = name.with_name(f".{name.name}.png.tmp")
                    doc[unit].get_pixmap(dpi=100).save(str(tmp), output="png")
                    os.replace(tmp, name.with_suffix(".png"))
        print(f"{label}: {', '.join(f'p{u + 1} ({why})' for u, why in picks)}", flush=True)


# --- selftest ----------------------------------------------------------------------------


def selftest() -> None:
    known = dict.fromkeys(["la", "casa", "es", "roja", "y"], 10**6)
    checker = check.Words("es", hunspell=False, lexicon=known)
    counts, n = garble(["la casa es rxja", "pala- bra y la ca- sa", "Πλάτωνa l e t r a"], checker)
    # Unknown: rxja, pala, bra, ca, sa (one-letter words and Greek aren't checked).
    assert [counts[k] for k in GARBLE] == [5, 2, 1, 1], counts
    assert n == 4 + 6 + 6, n

    m = margin_sequence(
        ["[17a] uno [17b] dos", "[17d] [17c] tres [18a]", "402a5 x 402a10 402b 403b"]
    )
    # St: 17b->17d gap, 17d->17c back, 17c->18a gap; Bk: 402b->403b gap (403a missed)
    assert m == {"margin_refs": 9, "margin_gaps": 3, "margin_back": 1}, m

    src = Text()
    body1 = words("el alma es la forma del cuerpo vivo según aristóteles en su tratado")
    note1 = words("véase también la edición de bekker página cuarenta y dos")
    src.add(body1, BODY, 0)
    src.add(note1, NOTE, 1)
    errors = note_errors(src, [body1[:7] + note1], [body1[7:]])
    assert errors == {
        "note_in_body": 10, "body_in_notes": 6, "notes_lost": 0, "source_note_words": 10
    }, errors  # fmt: skip
    assert note_errors(src, [body1], [])["notes_lost"] == 10

    work = ROOT / "scratch" / "drop-in" / "audit_selftest"
    work.mkdir(parents=True, exist_ok=True)
    chapter = (
        '<html xmlns:epub="http://www.idpf.org/2007/ops"><body>'
        '<span epub:type="pagebreak" role="doc-pagebreak" id="pg4" aria-label="5"></span>'
        '<h1 id="c1">Capítulo uno</h1><p><span class="mref" id="m1">[17a]</span> El texto'
        '<a class="noteref" id="r1" href="notes.xhtml#n1" epub:type="noteref"><sup>1</sup></a>'
        ' sigue.</p><h2 id="s1"><span epub:type="pagebreak" id="pg5" aria-label="6"></span>'
        "Sección</h2><p>Otra página.</p></body></html>"
    )
    notes = (
        '<html><body><aside class="note" id="n1" epub:type="footnote">'
        "<p>1. Una nota.</p></aside></body></html>"
    )
    nav = (
        '<html><body><nav epub:type="toc" id="toc"><ol>'
        '<li><a href="c.xhtml#c1">Capítulo uno</a></li><li><a href="c.xhtml#s1">Sección</a></li>'
        '<li><a href="c.xhtml#gone">Perdido</a></li></ol></nav></body></html>'
    )
    opf = (
        '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
        '<item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/>'
        '<item id="c" href="c.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="n" href="notes.xhtml" media-type="application/xhtml+xml"/></manifest>'
        '<spine><itemref idref="nav"/><itemref idref="c"/><itemref idref="n"/></spine></package>'
    )
    container = (
        '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>'
    )
    epub = work / "ours.epub"
    with zipfile.ZipFile(epub, "w") as z:
        for name, text in [
            ("META-INF/container.xml", container),
            ("OEBPS/content.opf", opf),
            ("OEBPS/nav.xhtml", nav),
            ("OEBPS/c.xhtml", chapter),
            ("OEBPS/notes.xhtml", notes),
        ]:
            z.writestr(name, text)
    ours = read_output(epub)
    assert ours.lines == [
        "# Capítulo uno",
        "[17a] El texto[^n1] sigue.",
        "## Sección",
        "Otra página.",
    ], ours.lines
    assert ours.notes == {"n1": "1. Una nota."} and ours.pages == {4: 0, 5: 2}, (
        ours.notes,
        ours.pages,
    )
    assert ours.headings == [(1, "Capítulo uno"), (2, "Sección")]
    assert (len(ours.toc), ours.toc_ok) == (3, 2), ours.toc
    heads = [f" {' '.join(words(t))} " for _, t in ours.headings]
    assert _found("1. Capítulo uno", heads) and not _found("Perdido", heads)
    assert _slices(ours, [], True) == {4: (0, 2), 5: (2, 4)} and not _slices(ours, [], False)

    md = work / "ours.md"
    _write_atomic(
        md, "---\ntitle: t\n---\n\n# Uno\n\n**\\[17a\\]** Texto[^3]\n\n[^3]: La nota\nsigue.\n"
    )
    m = read_output(md)
    assert m.lines == ["# Uno", "[17a] Texto[^3]"] and m.notes == {"3": "La nota sigue."}, m
    # A page found by its first and last eight words; running heads before them skipped.
    lines = [f"línea {k} " + " ".join(f"w{k}x{j}" for j in range(10)) for k in range(30)]
    index, line_of = _anchors(lines)
    page = ["cabecera", "7", *words(" ".join(lines[5:9]))]
    assert find_slice(page, index, line_of) == (5, 9), find_slice(page, index, line_of)
    out = Out(lines=lines)
    picks = pick(out, {u: (u, u + 1) for u in range(30)}, 5, 30, None)
    assert len(picks) == 5 and picks == pick(out, {u: (u, u + 1) for u in range(30)}, 5, 30, None)

    # A footnote above a body-size running foot is still a note.
    import pymupdf

    doc = pymupdf.open()
    for k, word in enumerate(["uno", "dos", "tres"]):
        page = doc.new_page()
        page.insert_text((72, 100), f"cuerpo del texto {word} sigue aquí", fontsize=11)
        page.insert_text((72, 700), f"{k + 1} una nota al pie", fontsize=8)
        page.insert_text((72, 780), "libro de prueba", fontsize=11)
    doc.save(work / "notes.pdf")
    text, starts = read_pdf(work / "notes.pdf")
    noted = [w for w, kind in zip(text.words, text.kind, strict=True) if kind == NOTE]
    assert noted == words("1 una nota al pie 2 una nota al pie 3 una nota al pie"), noted
    assert starts == [0, 14, 28], starts
    print("ok")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("manifest").add_argument("out", type=Path)
    p = sub.add_parser("run")
    p.add_argument("out", type=Path)
    p.add_argument("manifest", type=Path)
    sub.add_parser("score").add_argument("out", type=Path)
    p = sub.add_parser("pages")
    p.add_argument("out", type=Path)
    p.add_argument("--per-book", type=int, default=5)
    p = sub.add_parser("one")  # the child of ``run``
    p.add_argument("out", type=Path)
    p.add_argument("book", type=Path)
    sub.add_parser("selftest")
    args = parser.parse_args(argv)
    if args.command == "manifest":
        manifest(args.out)
    elif args.command == "run":
        run(args.out, args.manifest)
    elif args.command == "score":
        score(args.out)
    elif args.command == "pages":
        pages(args.out, args.per_book)
    elif args.command == "one":
        one(args.out, args.book)
    else:
        selftest()


if __name__ == "__main__":
    main(sys.argv[1:])

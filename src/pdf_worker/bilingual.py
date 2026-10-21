"""Bilingual editions: the original on facing pages, its words quoted in the translation.

Editions like the Abada Timeo print the Greek on the left-hand pages and the Spanish
on the right, and quote Greek words in the introduction and notes. A text layer made
by a Latin-script OCR reads the Greek as look-alikes ("ἔμφρονος" -> "eµ<j>Qovoi;").

The book is converted in its own language: a page that doesn't read as it, between two
that do, or one set mostly in Greek letters, is a facing page and is left out
(``facing_pages``); so is a long Greek paragraph on the other pages (``drop_greek``,
bilingual books only: elsewhere a Greek quotation is the author's). Quoted words that look
garbled are read again, their line at a time, with Tesseract in Greek and in the book's
language (as ``pdf_worker.mixed_script`` does): a confident Greek reading replaces the
token, else a confident reading in the book's language ("Ref>ública" -> "República").
The replacements are stored on the page in memory (``/PdfWorkerWords``) and applied by
``pdf_worker.layout.page_lines``.
"""

import json
import re
import unicodedata
from collections.abc import Callable, Collection, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import TYPE_CHECKING

import pymupdf

from pdf_worker.consensus import _union
from pdf_worker.inline import PAGE_MARK_RE, plain
from pdf_worker.margin_refs import has_bracketed
from pdf_worker.mixed_script import _DPI, GREEK, _overlap, _tsv

if TYPE_CHECKING:
    from pdf_worker.structure import Block, Paragraph

WORDS_KEY = "PdfWorkerWords"
_WORD_RE = re.compile(r"[^\W\d_]+")
# Stopword share of a page's words: below FOREIGN it is in another language, from
# NATIVE it is in the book's (Spanish pages 0.25-0.37, Greek read as Latin 0.00-0.09).
_FOREIGN, _NATIVE = 0.15, 0.25
_MIN_WORDS = 40
_MIN_FACING = 10  # facing pages a bilingual edition has at least
# A token that looks like Greek read as Latin: odd signs, digits or case flips inside.
_ODD_RE = re.compile(r"[µ<>!_|{}\\$%&*+=~^;]")
_DIGIT_IN_WORD_RE = re.compile(r"[^\W\d_]\d+[^\W\d_]")
_CASE_FLIP_RE = re.compile(r"[a-zß-ÿ][A-Z]")
_EDGES = "()[]«»¿?¡!.,;:'\"’‘“”-—–•*"
_GREEK_SHARE = 0.6
_MIN_GREEK_WORDS = 15  # a Greek paragraph dropped; shorter ones are quotations
# Greek pages are 0.94-0.99 Greek letters; a bibliography entry with a Greek title, 0.8.
_GREEK_PARAGRAPH_SHARE = 0.9
_MIN_GREEK_CONF, _MIN_NATIVE_CONF = 60, 85


def facing_pages(doc: pymupdf.Document) -> tuple[str, set[int]]:
    """The book's language and the indexes of its facing pages in another language."""
    from pdf_worker.convert import stopword_scores

    pages = []
    totals: dict[str, int] = {}
    for page in doc:
        text = page.get_text()
        scores = stopword_scores(text)
        for language, hits in scores.items():
            totals[language] = totals.get(language, 0) + hits
        pages.append((len(_WORD_RE.findall(text)), scores, _greek_share(text)))
    language = max(totals, key=totals.get) if totals else "en"

    def share(i: int) -> float | None:
        words, scores, _ = pages[i]
        return scores[language] / words if words >= _MIN_WORDS else None

    shares = [share(i) for i in range(len(pages))] + [None, None]  # [-1], [-2]: past the end

    def foreign(i: int) -> bool:
        return shares[i] is not None and shares[i] < _FOREIGN

    def native(i: int) -> bool:
        return shares[i] is not None and shares[i] >= _NATIVE

    # Between pages in the book's language (or a title page with few words)...
    between = {
        i
        for i in range(len(pages))
        if foreign(i)
        and not foreign(i - 1)
        and not foreign(i + 1)
        and (native(i - 1) or native(i + 1))
    }
    # ...and every other page: a lone one is a table or a figure.
    facing = {i for i in between if i - 2 in between or i + 2 in between}
    # Pages set in Greek letters need no neighbours: a split-word text layer ("p rin cip
    # io") leaves the translation's pages too few stopwords to count as its language.
    facing |= {
        i
        for i, (words, _, greek) in enumerate(pages)
        if words >= _MIN_WORDS and greek >= _GREEK_SHARE
    }
    return language, facing if len(facing) >= _MIN_FACING else set()


def drop_greek(blocks: Iterable["Block"], dropped: list["Paragraph"]) -> Iterator["Block"]:
    """Leave out paragraphs of ``_MIN_GREEK_WORDS`` or more words, nearly all in Greek
    letters, appending them to ``dropped``. Their page marks go on to the next block."""
    from pdf_worker.structure import Heading, Note, Paragraph  # it imports layout, which imports us

    marks = ""
    for block in blocks:
        if isinstance(block, Paragraph):
            text = plain(block.text)
            if (
                len(text.split()) >= _MIN_GREEK_WORDS
                and _greek_share(text) >= _GREEK_PARAGRAPH_SHARE
            ):
                dropped.append(block)
                marks += "".join(m.group() for m in PAGE_MARK_RE.finditer(block.text))
                continue
        if marks and isinstance(block, Heading | Paragraph | Note):
            block = replace(block, text=marks + block.text)
            marks = ""
        yield block


def suspect(token: str) -> bool:
    """A token that looks garbled ("i(CllQLOµóB"); not a reference ("[I7d]") or address."""
    if has_bracketed(token) or "/" in token or "@" in token:
        return False
    core = re.sub(r"\d+$", "", token.strip(_EDGES)).strip(_EDGES)  # a note number
    if sum(c.isalpha() for c in core) < 2:
        return False
    return any(r.search(core) for r in (_ODD_RE, _DIGIT_IN_WORD_RE, _CASE_FLIP_RE))


def mark_words(
    doc: pymupdf.Document,
    tesseract: str,
    language: str,
    skip: Collection[int] = (),
    jobs: int = 4,
    on_line: Callable[[int, int], None] | None = None,
) -> int:
    """Store re-read words on the pages of ``doc`` (in memory); returns how many.
    ``on_line(done, total)`` follows the lines read."""
    lines = [line for i in range(doc.page_count) if i not in skip for line in _lines(doc, i)]

    def read(line: tuple) -> list:
        _, rect, png, _ = line
        return [_read(png, tesseract, GREEK, rect), _read(png, tesseract, language, rect)]

    # Tesseract runs as a subprocess, so threads read lines in parallel (MuPDF stays
    # in this thread: it isn't thread-safe).
    readings = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for reading in pool.map(read, lines):
            readings.append(reading)
            if on_line:
                on_line(len(readings), len(lines))
    words: dict[int, list[list]] = {}
    for (index, _, _, bad), (greek, native) in zip(lines, readings, strict=True):
        for old, box in bad:
            new = _choose(_over(greek, box), _over(native, box))
            if new and new != old:
                words.setdefault(index, []).append([*box, old, new])
    for index, found in words.items():
        page = doc.load_page(index)
        doc.xref_set_key(page.xref, WORDS_KEY, pymupdf.get_pdf_str(json.dumps(found)))
    return sum(len(found) for found in words.values())


def page_words(page: pymupdf.Page) -> list[list]:
    kind, value = page.parent.xref_get_key(page.xref, WORDS_KEY)
    return json.loads(value) if kind == "string" else []


def apply_words(chars: list[dict], words: list[list]) -> None:
    """Put re-read words into a line's ``rawdict`` characters: the old token's first
    character takes the new text and the rest go empty, so positions stay the same."""
    for token in _tokens(chars):
        text = "".join(c["c"] for c in token)
        x0, y0, x1, y1 = _union(token)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for fx0, fy0, fx1, fy1, old, new in words:
            if old == text and fx0 <= cx <= fx1 and fy0 <= cy <= fy1:
                token[0]["c"] = new
                for other in token[1:]:
                    other["c"] = ""
                break


def _lines(doc: pymupdf.Document, index: int) -> list[tuple]:
    """(page index, line rect, line image, [(token, box)]) for lines with suspect tokens."""
    page = doc.load_page(index)
    out = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", ()):
            chars = [c for span in line["spans"] for c in span["chars"]]
            texts = [("".join(c["c"] for c in t), _union(t)) for t in _tokens(chars)]
            bad = [(text, box) for text, box in texts if suspect(text)]
            if bad:
                rect = pymupdf.Rect(line["bbox"]) + (-3, -3, 3, 3)
                pix = page.get_pixmap(dpi=_DPI, clip=rect, colorspace=pymupdf.csGRAY, annots=False)
                out.append((index, rect, pix.tobytes("png"), bad))
    return out


def _choose(greek: list[tuple[str, float]], native: list[tuple[str, float]]) -> str | None:
    """Greek when it reads as Greek, confidently and more so than the book's language;
    else the book's language when it is confident and itself looks clean."""
    g_text, g_conf = _joined(greek)
    n_text, n_conf = _joined(native)
    if g_text and _greek_share(g_text) >= _GREEK_SHARE and g_conf >= max(_MIN_GREEK_CONF, n_conf):
        return g_text
    if n_text and n_conf >= _MIN_NATIVE_CONF and not any(suspect(t) for t in n_text.split()):
        return n_text
    return None


def _read(png: bytes, tesseract: str, language: str, rect: pymupdf.Rect) -> list:
    """Tesseract's words in page coordinates: (box, text, confidence)."""
    scale = 72 / _DPI
    return [
        (
            (
                rect.x0 + w.box[0] * scale,
                rect.y0 + w.box[1] * scale,
                rect.x0 + w.box[2] * scale,
                rect.y0 + w.box[3] * scale,
            ),
            w.text,
            w.conf,
        )
        for w in _tsv(png, tesseract, language)
    ]


def _over(words: list, box: tuple) -> list[tuple[str, float]]:
    return [(text, conf) for b, text, conf in words if _overlap(b, box) >= 0.5]


def _joined(words: list[tuple[str, float]]) -> tuple[str, float]:
    if not words:
        return "", 0.0
    return " ".join(t for t, _ in words), sum(c for _, c in words) / len(words)


def _greek_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    greek = sum("GREEK" in unicodedata.name(c, "") for c in letters)
    return greek / len(letters) if letters else 0.0


def _tokens(chars: list[dict]) -> list[list[dict]]:
    """Runs of characters between spaces."""
    runs: list[list[dict]] = [[]]
    for char in chars:
        if char["c"].isspace():
            runs.append([])
        else:
            runs[-1].append(char)
    return [run for run in runs if run]

"""OCR with PaddleOCR-VL-1.6 (opt-in, slow, much better on diacritics).

PaddleOCR needs its own Python environment (PaddlePaddle has no wheels for every Python
version), so it runs out of process:

1. an MLX-VLM server serves the PaddleOCR-VL model on Apple Silicon;
2. ``paddle_worker.py`` runs the PaddleOCR-VL pipeline (layout model + server) on the
   page images and writes blocks with labels and boxes as JSON lines;
3. this module writes the blocks into the PDF as an invisible text layer, in Paddle's
   reading order, so every other feature works on the result as on a Tesseract OCR.

Setup (see docs/ocr-plan.md): a venv with ``paddlepaddle==3.2.1``,
``paddleocr[doc-parser]`` and ``mlx-vlm``, by default ``.venv-paddle`` next to the
project. Override with ``PDF_WORKER_PADDLE_PYTHON``. Model files are cached in
``PDF_WORKER_PADDLE_CACHE`` (default ``~/.cache/pdf-worker/paddle``).
"""

import collections
import difflib
import functools
import hashlib
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from pdf_worker.convert import guess_language, stopword_scores
from pdf_worker.document import open_pdf
from pdf_worker.errors import PdfOpenError
from pdf_worker.macrons import reads_as_latin, restore_macrons_if_latin
from pdf_worker.margin_refs import (
    MARKS_KEY,
    PageScan,
    ScanWord,
    is_mark,
    mark_paddle_blocks,
    norm,
    outer_marks,
    scan_page,
)
from pdf_worker.note_numbers import (
    SUPERSCRIPT_RE,
    fix_refs,
    from_sup,
    left_open,
    number_notes,
    sup,
)
from pdf_worker.ocr import (
    DEFAULT_LANGUAGE,
    MODES,
    TESSERACT_CODES,
    OcrEngineMissingError,
    OcrError,
    OcrReport,
    tesseract_path,
)

MODEL = "PaddlePaddle/PaddleOCR-VL-1.6"
_WORKER = Path(__file__).with_name("paddle_worker.py")
_DEFAULT_PYTHON = Path(__file__).resolve().parents[2] / ".venv-paddle" / "bin" / "python"
_SERVER_TIMEOUT = 900  # seconds; the first start downloads the model (about 2 GB)
_FONT = "notos"  # Noto Sans from pymupdf-fonts: has macrons and accents
# Paddle labels that carry no text for the text layer.
_SKIP_LABELS = {"image", "chart", "seal", "figure", "formula_number"}
# LaTeX that the model sometimes wraps around words: "$ \text{Āfricā} $".
_LATEX_TEXT_RE = re.compile(r"\$\s*\\text\{([^}]*)\}\s*\$")
# Note references come as LaTeX: "interlocutor $ ^{1} $." -> "interlocutor¹."
_LATEX_WRAP_RE = re.compile(r"\\[a-zA-Z]+\s*\{([^{}]*)\}")
_LATEX_SUB_RE = re.compile(r"_\{([^{}]*)\}")
_LATEX_COMMAND_RE = re.compile(r"\\[a-zA-Z]+")
_LATEX_SUP_RE = re.compile(r"\s*\$?\s*\^\{([^}]{1,3}|\d{4})\}\s*\$?")  # "^{A}" -> plain "A"
_TO_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_NOTE_RATIO = 0.8  # footnote size against the body (structure reads < 0.92 as notes)
# A table of at least this many words with fewer distinct words than this share is
# the model looping, not a real table.
_MIN_TABLE_WORDS, _MIN_TABLE_VARIETY = 30, 0.3
_MIN_FONT, _MAX_FONT = 3.0, 40.0
_PARAGRAPH_WIDTH = 0.4  # blocks wider than this share of the page are rewrapped
_UNHYPHEN_RE = re.compile(r"(\w)-\n(?=[a-zà-ÿā-ž])")
_DIGIT_IN_WORD_RE = re.compile(r"[^\W\d_][0-9]|[0-9][^\W\d_]")  # "FILE0", "S1"
# A printer's signature: "160. — 18", "160. -4", "160. ~2", "160. - S" (not "31. 7.").
_SIGNATURE_RE = re.compile(r"^\d{1,4}\.?\s*[—–~-]\s*\S{1,3}$")
# Vietnamese-only letters (Latin Extended Additional vowels, ă ơ ư đ), Arabic, CJK.
_FOREIGN_RE = re.compile(r"[Ạ-ỹăơưđĂƠƯĐ؀-ۿ぀-ヿ一-鿿]")
_MIN_FOREIGN, _FOREIGN_SHARE = 3, 0.05
_MIXED_LABEL = "algorithm"  # what Paddle calls a table of Greek variants
_NOTE_START_RE = re.compile(r"^\d{1,3}\.?$")  # a scan line opening a note: "45."
# "11D Cf. Leyes", "16. De l'esprit", "15. C.S., III" (not "160. - S", a signature)
_FOOTER_NOTE_RE = re.compile(r"^\d[\dA-Za-z]{0,3}\.?\s+[^\W\d_]")
_WORKER_PAGE_RE = re.compile(r"paddle: page (\d+)/\d+")  # paddle_worker's progress line


def paddle_python() -> Path:
    path = Path(os.environ.get("PDF_WORKER_PADDLE_PYTHON", _DEFAULT_PYTHON))
    if not path.is_file():
        raise OcrEngineMissingError(
            f"PaddleOCR environment not found at {path}; create it as described in "
            "docs/ocr-plan.md, or set PDF_WORKER_PADDLE_PYTHON"
        )
    return path


def cache_dir() -> Path:
    default = Path.home() / ".cache" / "pdf-worker" / "paddle"
    return Path(os.environ.get("PDF_WORKER_PADDLE_CACHE", default))


def ocr_pdf_paddle(
    pdf_path: str | Path,
    output_path: str | Path,
    mode: str = "skip",
    progress: bool = False,
    latin_macrons: bool | None = None,
) -> OcrReport:
    """OCR ``pdf_path`` with PaddleOCR-VL into ``output_path`` (written atomically)."""
    if mode not in MODES:
        raise OcrError(f"Unknown OCR mode {mode!r}; choose from {', '.join(MODES)}")
    pdf_path, output_path = Path(pdf_path), Path(output_path)
    paddle_python()  # a clear error before any work when the environment is missing
    report = OcrReport(output_path=output_path, mode=mode, languages=["paddle"])
    with open_pdf(pdf_path) as doc:
        report.page_count = doc.page_count
        report.empty_pages_before = [
            i + 1 for i in range(doc.page_count) if not doc.load_page(i).get_text().strip()
        ]
    pages = (
        [p - 1 for p in report.empty_pages_before]
        if mode == "skip"
        else list(range(report.page_count))
    )
    rows = paddle_pages(pdf_path, pages, progress) if pages else []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        report.macrons_restored = _write_text_layer(pdf_path, rows, tmp, mode, latin_macrons)
        with open_pdf(tmp) as doc:
            report.empty_pages_after = [
                i + 1 for i in range(doc.page_count) if not doc.load_page(i).get_text().strip()
            ]
        os.replace(tmp, output_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return report


def paddle_pages(
    pdf_path: str | Path,
    pages: list[int],
    progress: bool = False,
    on_page: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Paddle's blocks for ``pages`` (0-based), one row per page as the worker writes it.

    Pages are read once per file and kept in ``cache_dir()/pages``: a rerun is fast and
    gives the same result (the model's reading varies from run to run), and a run that
    stops halfway goes on where it stopped. ``on_page(done, total)`` is called as pages
    are read; ``done`` counts the cached pages too."""
    pdf_path = Path(pdf_path)
    cache = _pages_cache(pdf_path)
    rows = _read_rows(cache)
    missing = [p for p in pages if p not in rows]
    if missing:
        python = paddle_python()
        cache.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(dir=cache.parent, prefix=".paddle."))
        cached = len(pages) - len(missing)
        report = on_page and (lambda done: on_page(cached + done, len(pages)))
        try:
            with _mlx_server(python, progress) as server:
                _run_worker(
                    python, pdf_path, missing, work / "pages.jsonl", work, server, progress, report
                )
        finally:
            # Keep the pages finished before a failure too.
            done = _read_rows(work / "pages.jsonl")
            if done:
                with cache.open("a", encoding="utf-8") as out:
                    for row in done.values():
                        out.write(json.dumps(row, ensure_ascii=False) + "\n")
            shutil.rmtree(work, ignore_errors=True)
        rows = _read_rows(cache)
    return [rows[p] for p in pages if p in rows]


def _pages_cache(pdf_path: Path) -> Path:
    digest = hashlib.sha256(MODEL.encode())
    with pdf_path.open("rb") as data:
        for chunk in iter(lambda: data.read(1 << 20), b""):
            digest.update(chunk)
    return cache_dir() / "pages" / f"{digest.hexdigest()[:32]}.jsonl"


def _read_rows(path: Path) -> dict[int, dict]:
    rows = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a line cut short when a run stopped
            rows[row["page"]] = row
    return rows


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _mlx_server(python: Path, progress: bool = False) -> Iterator[str]:
    """Start the MLX-VLM server, wait until it answers, and stop it afterwards."""
    port = _free_port()
    url = f"http://127.0.0.1:{port}/"
    env = _paddle_env()
    process = subprocess.Popen(
        [str(python), "-m", "mlx_vlm.server", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        # The server downloads the model (~2 GB) on the first request; show its progress.
        stderr=None if progress else subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + _SERVER_TIMEOUT
        while True:
            if process.poll() is not None:
                raise OcrError("The MLX-VLM server for PaddleOCR-VL stopped while starting")
            try:
                urllib.request.urlopen(url, timeout=5)
                break
            except urllib.error.HTTPError:
                break  # any HTTP answer means it is up
            except OSError:
                if time.monotonic() > deadline:
                    raise OcrError("The MLX-VLM server did not start in time") from None
                time.sleep(2)
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()


def _paddle_env() -> dict[str, str]:
    """Keep the model caches in one folder (``cache_dir``)."""
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        # Paddle tools also write to ~/.paddlex etc.; keep that inside the cache too.
        HOME=str(root),
        HF_HOME=str(root / "hf"),
        PADDLE_PDX_CACHE_HOME=str(root / "paddlex"),
        MODELSCOPE_CACHE=str(root / "modelscope"),
        XDG_CACHE_HOME=str(root / "cache"),
        PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True",
    )
    return env


def _run_worker(
    python, pdf_path, pages, results, work, server, progress, on_page=None, dpi=None
) -> None:
    """Run ``paddle_worker.py``; ``on_page(done)`` hears of each page it finishes."""
    command = [
        str(python),
        str(_WORKER),
        "--pdf",
        str(pdf_path),
        "--pages",
        ",".join(map(str, pages)),
        "--out",
        str(results),
        "--work",
        str(work / "images"),
        "--server",
        server,
        "--model",
        MODEL,
        *(["--dpi", str(dpi)] if dpi else []),
    ]
    process = subprocess.Popen(
        command,
        env=_paddle_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    tail: collections.deque[str] = collections.deque(maxlen=5)
    for line in process.stderr:
        if done := _WORKER_PAGE_RE.match(line):
            if on_page:
                on_page(int(done.group(1)))
            continue
        if progress:
            sys.stderr.write(line)
        if line.strip():
            tail.append(line.strip())
    if process.wait() != 0:
        raise OcrError("PaddleOCR-VL failed: " + " | ".join(tail))


def clean_text(text: str) -> str:
    """Undo the model's markup quirks: LaTeX around words, stray ``$``, HTML tables.

    A table that just repeats a few phrases is a hallucination (the model reads
    dotted pictures such as mosaics as tables) and becomes empty."""
    text = _LATEX_TEXT_RE.sub(r"\1", text)
    text = _LATEX_SUP_RE.sub(_latex_sup, text)
    # "\underline{\text{Creación}}" -> "Creación" (innermost first), "T_{M}" -> "TM",
    # then any command left ("\cdot") goes.
    while (unwrapped := _LATEX_WRAP_RE.sub(r"\1", text)) != text:
        text = unwrapped
    text = _LATEX_COMMAND_RE.sub("", _LATEX_SUB_RE.sub(r"\1", text))
    # What LaTeX leaves: "S_i", a lone "{Cuéntasela" (books have no braces in prose).
    text = re.sub(r"[{}]|(?<=\w)_(?=\w)", "", text)
    text = re.sub(r"</?su[bp]>", "", text.replace("$", ""))
    if "<table" not in text:
        return text
    text = re.sub(r"</t[dh]>", " ", text.replace("</tr>", "\n"))
    text = html.unescape(re.sub(r"<[^>]*>", "", text))
    text = "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
    words = text.split()
    if len(words) >= _MIN_TABLE_WORDS and len(set(words)) < len(words) * _MIN_TABLE_VARIETY:
        return ""
    return text


def _recover_notes(
    scan: PageScan,
    refs: list[int],
    numbers: list[int | None],
    notes_top: float,
    last: int | None = None,
) -> list[tuple[int, str]]:
    """Notes the model skipped ("44." between 43 and 45, or the page's first or last),
    for references in the text, from Tesseract's lines at the foot of the page: (number,
    text). ``last`` is the previous page's last note: earlier numbers are not looked for."""
    have = {n for n in numbers if n is not None}
    if have:
        lo, hi = min(have) - 2, max(have) + 2
    elif last is not None:  # the model saw no note at all on the page
        lo, hi = last + 1, last + 3
    else:
        return []
    wanted = [
        n
        for n in sorted(set(refs))
        if n not in have and (last is None or n > last) and lo <= n <= hi
    ]
    lines: dict[int, list[ScanWord]] = {}
    for word in scan.words:
        if not word.margin and word.box and word.box[3] > notes_top:
            lines.setdefault(word.line, []).append(word)
    ordered = [words for _, words in sorted(lines.items())]
    found = []
    for n in wanted:
        for k, words in enumerate(ordered):
            if words[0].text.rstrip(".") != str(n):
                continue
            text = [w.text for w in words[1:]]
            for more in ordered[k + 1 :]:  # its next lines, up to the next note
                if _NOTE_START_RE.match(more[0].text):
                    break
                text += [w.text for w in more]
            if text:
                found.append((n, " ".join(text)))
            break
    return found


def _relabel(block: dict, text: str, number: list | None) -> str:
    """Paddle's label, corrected: a title on the page number's row is the running head
    ("FILEBO" beside "91"); a footer that opens with a number and words is a footnote
    ("11D Cf. Leyes 863a-c." for note 110)."""
    label = block.get("label", "")
    y0, y1 = block["bbox"][1], block["bbox"][3]
    if label in ("paragraph_title", "doc_title") and number and y0 < number[3] and number[1] < y1:
        return "header"
    if label == "footer" and _FOOTER_NOTE_RE.match(text):
        return "footnote"
    return label


def _foreign_script(text: str) -> bool:
    """Letters of a script the book can't be in: the model making up Vietnamese
    ("R1 (lỗi) đến") for transliterated Greek ("iōn de autōn"). One odd letter ("Sốc.")
    is a slip, not a made-up block."""
    foreign = len(_FOREIGN_RE.findall(text))
    letters = sum(c.isalpha() for c in text)
    return foreign >= _MIN_FOREIGN and foreign >= letters * _FOREIGN_SHARE


def _scan_text(scan: PageScan, rect: pymupdf.Rect) -> str:
    """Tesseract's words inside ``rect`` (page units), in reading order."""
    return " ".join(
        w.text
        for w in scan.words
        if w.box
        and rect.contains(pymupdf.Point((w.box[0] + w.box[2]) / 2, (w.box[1] + w.box[3]) / 2))
    )


def text_settings(
    rows: list[dict], latin_macrons: bool | None = None
) -> tuple[str, bool, bool, set[str]]:
    """What the book's Paddle text says about itself: its language code, and the macron
    settings for ``prepare_blocks`` (restore them, Latin by default, rival languages)."""
    texts = [clean_text(b.get("text", "")) for row in rows for b in row["blocks"]]
    sample = " ".join(texts)[:20_000]
    language = guess_language(sample)
    # Undecided blocks (headings, names) count as Latin only in a Latin book.
    latin_default = bool(latin_macrons) or language == "la"
    # Paddle reports no languages: Latin competes with those the book clearly uses.
    rivals = {lang for lang, score in stopword_scores(sample).items() if score >= 5}
    rivals.discard("la")
    macrons = (
        # Some block has Latin stopwords and reads as Latin (not just a "-um" heading).
        any(stopword_scores(t)["la"] and reads_as_latin(t, False, rivals) for t in texts)
        if latin_macrons is None
        else latin_macrons
    )
    return language, macrons, latin_default, rivals


def page_scanner(language: str):
    """``scan(page)``: Tesseract's look at the page for margin references and dropped
    note numbers, or None without Tesseract."""
    try:
        tesseract = tesseract_path()
    except OcrEngineMissingError:
        return lambda page: None
    code = TESSERACT_CODES.get(language, DEFAULT_LANGUAGE)
    return lambda page: scan_page(page, tesseract, code)


def mixed_reader(language: str):
    """``read(page, rect)``: lines of Greek and ``language`` read word by word with
    Tesseract's better model (``pdf_worker.mixed_script``), or None without Tesseract
    or its Greek model."""
    from pdf_worker import mixed_script
    from pdf_worker.ocr import available_languages

    try:
        tesseract = tesseract_path()
    except OcrEngineMissingError:
        return None
    if mixed_script.GREEK not in available_languages():
        return None
    code = TESSERACT_CODES.get(language, DEFAULT_LANGUAGE)
    return lambda page, rect: mixed_script.read_mixed(page, rect, tesseract, code)


def _latex_sup(match: re.Match) -> str:
    """A superscript: a note reference ("^{12}"; a misread "^{2k}" keeps its digits for
    ``fix_refs`` to renumber) or plain letters ("M.^{A}")."""
    inner = match.group(1)
    digits = re.sub(r"\D", "", inner)
    if len(digits) == 4 and digits.endswith("7"):
        # No note has four digits: a question mark after the reference read as a
        # 7 ("filósofos¹²⁶?" -> "^{1267}").
        return digits[:3].translate(_TO_SUPERSCRIPT) + "?"
    return (digits or inner).translate(_TO_SUPERSCRIPT)


def _write_text_layer(
    pdf_path: Path, rows: list[dict], out: Path, mode: str, latin_macrons: bool | None
) -> bool:
    language, macrons, latin_default, rivals = text_settings(rows, latin_macrons)
    scan_of = page_scanner(language)
    try:
        doc = pymupdf.open(pdf_path)
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise PdfOpenError(f"Could not open {pdf_path}: {exc}") from exc
    with doc:
        font = _font()
        last_note, last_open = None, False
        for row in rows:
            page = doc.load_page(row["page"])
            scan = scan_of(page)  # finds the margin references Paddle drops
            if mode != "skip":
                _remove_text(page)
            page.insert_font(fontname=_FONT, fontbuffer=font.buffer)
            _, last_note, last_open = write_blocks(
                page, row, macrons, latin_default, rivals, scan, last_note, last_open
            )
        doc.save(out, garbage=3, deflate=True)
    return macrons


def write_blocks(
    page: pymupdf.Page,
    row: dict,
    macrons: bool = False,
    latin_default: bool = True,
    rivals: Collection[str] | None = None,
    scan: PageScan | None = None,
    last_note: int | None = None,
    last_open: bool = False,
) -> tuple[int, int | None, bool]:
    """Write a page's Paddle blocks as invisible text; returns the blocks written, the
    page's last footnote number and whether that note breaks off (``last_note`` and
    ``last_open`` are the previous page's).

    With ``macrons``, blocks that read as Latin rather than one of the ``rivals``
    languages get their macrons restored; blocks too short to tell follow
    ``latin_default``. The margin references found in the ``scan`` are stored on the
    page (see ``pdf_worker.margin_refs``); its words help put back dropped footnote
    references (``pdf_worker.note_numbers``)."""
    blocks, anchors, last_note = prepare_blocks(
        page, row, macrons, latin_default, rivals, scan, last_note, last_open
    )
    written = 0
    # One body size per page: the model's boxes are tight, so a short paragraph would
    # fit only at a smaller size and read as a different (note-sized) font.
    body = _body_size(page, [b for b in blocks if b[0] == "text"])
    caps = {"text": body, "footnote": body * _NOTE_RATIO}  # titles keep their own size
    stored = []
    for i, (label, rect, text) in enumerate(blocks):
        if label == "text":  # a one-line box is too low to start at the body size
            rect.y1 = max(rect.y1, rect.y0 + body * 1.6)
        before = {tuple(w[:5]) for w in page.get_text("words")} if i in anchors else set()
        _fit_text(page, rect, text, caps.get(label, _MAX_FONT))
        written += 1
        if i in anchors:
            # The block's words as written, to store each mark at its word's box.
            new = [w for w in page.get_text("words") if tuple(w[:5]) not in before]
            if len(new) == len(text.split()):
                stored += [[*new[k][:4], reading] for k, reading in anchors[i] if k < len(new)]
    if scan is not None:
        page.parent.xref_set_key(
            page.xref, MARKS_KEY, pymupdf.get_pdf_str(json.dumps(stored)) if stored else "null"
        )
    return written, last_note, left_open(blocks)


def prepare_blocks(
    page: pymupdf.Page,
    row: dict,
    macrons: bool = False,
    latin_default: bool = True,
    rivals: Collection[str] | None = None,
    scan: PageScan | None = None,
    last_note: int | None = None,
    last_open: bool = False,
    read_mixed: Callable[[pymupdf.Page, pymupdf.Rect], list[str]] | None = None,
) -> tuple[list[list], dict[int, list[tuple[int, str]]], int | None]:
    """A page's Paddle blocks, cleaned: ``[label, rect (page units), text]`` in reading
    order (footnotes numbered, references fixed, margin marks taken out), the margin
    references per block (``{block: [(word index, reading)]}``) and the last note.
    ``last_open``: the previous page's last note broke off (``note_numbers.left_open``).
    ``read_mixed`` (``mixed_reader``) re-reads tables of Greek variants, line by line."""
    sx = page.rect.width / (row.get("width") or page.rect.width)
    sy = page.rect.height / (row.get("height") or page.rect.height)
    font = _font()
    number = next(
        (b["bbox"] for b in row["blocks"] if b.get("label") == "number" and len(b["bbox"]) == 4),
        None,
    )
    if scan and number and row.get("width"):
        # Margin references sit in the outer margin, on the page number's side.
        outer = "left" if number[0] + number[2] < row["width"] else "right"
        scan = outer_marks(scan, outer)
    # Wide blocks (body paragraphs) share one left edge: the model's boxes wobble by
    # several points, which would read as indentation on every line.
    wide = [
        (b["bbox"][0] * sx, b["bbox"][2] * sx)
        for b in row["blocks"]
        if len(b.get("bbox", [])) == 4
        and (b["bbox"][2] - b["bbox"][0]) * sx > page.rect.width * _PARAGRAPH_WIDTH
    ]
    column_left = min(x0 for x0, _ in wide) if wide else None
    column_right = max(x1 for _, x1 in wide) if wide else None
    blocks = []  # (label, rect, text)
    for block in row["blocks"]:
        text = clean_text(block.get("text", "")).strip()
        if not text or block.get("label") in _SKIP_LABELS or len(block.get("bbox", [])) != 4:
            continue
        block = {**block, "label": _relabel(block, text, number)}
        if block.get("label") == "aside_text" and is_mark(text):
            continue  # a margin reference ("12", "e"): found in the scan instead
        if block.get("label") == "footnote" and _SIGNATURE_RE.match(text):
            continue  # a printer's signature at the foot ("160. — 18"), not a note
        if macrons:
            text = restore_macrons_if_latin(text, latin_default, rivals)
        text = _printable(text, font)
        x0, y0, x1, y1 = block["bbox"]
        rect = pymupdf.Rect(x0 * sx, y0 * sy, x1 * sx, y1 * sy)
        if scan and _foreign_script(text):
            text = _scan_text(scan, rect) or text
        if read_mixed and block.get("label") == _MIXED_LABEL:
            # Paddle reads the Greek as Latin look-alikes ("tà šèovta"); keep the lines.
            lines = read_mixed(page, rect + (-3, -3, 3, 3))
            if lines:
                blocks.append([_MIXED_LABEL, rect, _printable("\n".join(lines), font)])
                continue
        in_column = (
            block.get("label") == "text"
            and column_left is not None
            and column_left <= rect.x0 < column_right
        )
        if column_left is not None and (
            rect.width > page.rect.width * _PARAGRAPH_WIDTH or in_column
        ):
            # A body paragraph (or a short one in the column: "PRO. — Sí."): rewrap it
            # (the model keeps the printed line breaks), align it with the column, and
            # mark its start with typed indentation, which the structure pass reads as
            # a new paragraph. Narrow blocks such as margin glosses keep their lines.
            text = _UNHYPHEN_RE.sub(r"\1", text).replace("\n", " ")
            rect.x0 = column_left
            # A block opening in lowercase continues the previous page's sentence.
            if block.get("label") == "text" and not text[0].islower():
                text = "  " + text
        blocks.append([block.get("label"), rect, text])
    notes = [b for b in blocks if b[0] == "footnote"]
    body_blocks = [b for b in blocks if b[0] != "footnote"]
    refs = [from_sup(r) for b in body_blocks for r in SUPERSCRIPT_RE.findall(b[2])]
    texts, numbers = number_notes([b[2] for b in notes], refs, last_note, last_open)
    for note, text in zip(notes, texts, strict=True):
        note[2] = text
    if scan and refs and body_blocks:
        top = min((b[1].y0 for b in notes), default=page.rect.y1)
        # From the end of the body text: a skipped first note is above the others.
        top = max((b[1].y1 for b in body_blocks if b[1].y1 <= top), default=top)
        for n, text in _recover_notes(scan, refs, numbers, top, last_note):
            # After the note numbered just below it (or at the end, with no notes).
            before = max(
                (k for k, m in enumerate(numbers[: len(notes)]) if m is not None and m < n),
                default=-1,
            )
            if not notes:
                at, rect = len(blocks), pymupdf.Rect(page.rect.x0, top, page.rect.x1, top)
            elif before >= 0:
                at, rect = blocks.index(notes[before]) + 1, pymupdf.Rect(notes[before][1])
            else:
                at, rect = blocks.index(notes[0]), pymupdf.Rect(notes[0][1])
            blocks.insert(at, ["footnote", rect, f"{sup(n)} {text}"])
            numbers.append(n)
    fixed = fix_refs([b[2] for b in body_blocks], numbers, scan.words if scan else [])
    if scan:
        fixed = _fix_digit_words(fixed, scan.words)
    for block, text in zip(body_blocks, fixed, strict=True):
        block[2] = text
    last_note = max((n for n in numbers if n is not None), default=last_note)
    anchors: dict[int, list[tuple[int, str]]] = {}  # block -> [(word index, reading)]
    if scan and scan.marks:
        main = [i for i, b in enumerate(blocks) if b[0] != "footnote"]
        texts, marks = mark_paddle_blocks([blocks[i][2] for i in main], scan)
        for i, text in zip(main, texts, strict=True):
            blocks[i][2] = text
        for b, index, reading in marks:
            anchors.setdefault(main[b], []).append((index, reading))
    return blocks, anchors, last_note


def _fix_digit_words(texts: list[str], scan_words: list[ScanWord]) -> list[str]:
    """Words the model read with a digit among letters ("FILE0", "S1.") take
    Tesseract's reading of the same word when that is all letters ("FILEBO", "SÍ.")."""
    words = [(b, m) for b, text in enumerate(texts) for m in re.finditer(r"\S+", text)]
    body = [w.text for w in scan_words if not w.margin]
    matcher = difflib.SequenceMatcher(
        None, [norm(w) for w in body], [norm(m.group()) for _, m in words], autojunk=False
    )
    fixes = {}
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op != "replace" or i2 - i1 != j2 - j1:
            continue
        for k in range(i2 - i1):
            ours, theirs = words[j1 + k][1].group(), body[i1 + k]
            if _DIGIT_IN_WORD_RE.search(ours) and norm(theirs).isalpha():
                letters = [c for c in ours if c.isalpha()]
                new = theirs.lower()
                if len(letters) > 1 and all(c.isupper() for c in letters):
                    new = new.upper()
                elif letters and letters[0].isupper():
                    new = new[:1].upper() + new[1:]
                fixes[j1 + k] = new
    out = list(texts)
    for g in sorted(fixes, reverse=True):
        b, m = words[g]
        out[b] = out[b][: m.start()] + fixes[g] + out[b][m.end() :]
    return out


def _body_size(page: pymupdf.Page, texts: list[list]) -> float:
    """The size the page's longest text block fits at (a dry run on a scratch page)."""
    if not texts:
        return _MAX_FONT
    _, rect, text = max(texts, key=lambda b: len(b[2]))
    with pymupdf.open() as scratch:
        dry = scratch.new_page(width=page.rect.width, height=page.rect.height)
        dry.insert_font(fontname=_FONT, fontbuffer=_font().buffer)
        return _fit_text(dry, rect, text)


@functools.cache
def _font() -> pymupdf.Font:
    return pymupdf.Font(_FONT)


def _printable(text: str, font: pymupdf.Font) -> str:
    """Characters the font lacks become their base letter ("ἐ" -> "ε"), else "?"."""
    out = []
    for char in text:
        if char.isspace() or font.has_glyph(ord(char)):
            out.append(char)
            continue
        base = unicodedata.normalize("NFD", char)[0]
        out.append(base if font.has_glyph(ord(base)) else "?")
    return "".join(out)


def _fit_text(
    page: pymupdf.Page, rect: pymupdf.Rect, text: str, max_size: float = _MAX_FONT
) -> float:
    """Write ``text`` into ``rect`` at the largest size up to ``max_size`` that fits
    (invisible); returns the size.

    Justified, so wrapped lines reach the right edge like the printed paragraph: a
    ragged edge would read as paragraph ends.
    """
    size = min(max_size, _MAX_FONT, max(_MIN_FONT, rect.height * 0.8))
    while size >= _MIN_FONT:
        # insert_textbox writes nothing and returns < 0 when the text doesn't fit. The
        # model's box ends at the last line's ink: allow that line its leading below.
        written = page.insert_textbox(
            rect + (0, 0, 0, size * 0.4),
            text,
            fontname=_FONT,
            fontsize=size,
            render_mode=3,
            align=pymupdf.TEXT_ALIGN_JUSTIFY,
        )
        if written >= 0:
            return size
        # Small steps: one wrapped line too many must not make a body paragraph
        # note-sized (< 0.92 of the body).
        size *= 0.96
    # Very dense text: let it overflow the box rather than lose it.
    page.insert_textbox(
        rect + (0, 0, 0, rect.height * 3), text, fontname=_FONT, fontsize=_MIN_FONT, render_mode=3
    )
    return _MIN_FONT


def _remove_text(page: pymupdf.Page) -> None:
    """Drop an existing (bad) text layer, keeping images and drawings."""
    page.add_redact_annot(page.rect)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE
    )

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

import functools
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from pdf_worker.convert import guess_language
from pdf_worker.document import open_pdf
from pdf_worker.errors import PdfOpenError
from pdf_worker.macrons import restore_macrons
from pdf_worker.ocr import MODES, OcrEngineMissingError, OcrError, OcrReport

MODEL = "PaddlePaddle/PaddleOCR-VL-1.6"
_WORKER = Path(__file__).with_name("paddle_worker.py")
_DEFAULT_PYTHON = Path(__file__).resolve().parents[2] / ".venv-paddle" / "bin" / "python"
_SERVER_TIMEOUT = 900  # seconds; the first start downloads the model (about 2 GB)
_FONT = "notos"  # Noto Sans from pymupdf-fonts: has macrons and accents
# Paddle labels that carry no text for the text layer.
_SKIP_LABELS = {"image", "chart", "seal", "figure", "formula_number"}
# LaTeX that the model sometimes wraps around words: "$ \text{Āfricā} $".
_LATEX_TEXT_RE = re.compile(r"\$\s*\\text\{([^}]*)\}\s*\$")
_MIN_FONT, _MAX_FONT = 3.0, 40.0
_PARAGRAPH_WIDTH = 0.4  # blocks wider than this share of the page are rewrapped
_UNHYPHEN_RE = re.compile(r"(\w)-\n(?=[a-zà-ÿā-ž])")


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
    python = paddle_python()
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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=output_path.parent, prefix=f".{output_path.name}.paddle."))
    try:
        results = work / "pages.jsonl"
        if pages:
            with _mlx_server(python) as server:
                _run_worker(python, pdf_path, pages, results, work, server, progress)
        tmp = work / "out.pdf"
        report.macrons_restored = _write_text_layer(pdf_path, results, tmp, mode, latin_macrons)
        with open_pdf(tmp) as doc:
            report.empty_pages_after = [
                i + 1 for i in range(doc.page_count) if not doc.load_page(i).get_text().strip()
            ]
        os.replace(tmp, output_path)
    finally:
        for path in sorted(work.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        work.rmdir()
    return report


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _mlx_server(python: Path) -> Iterator[str]:
    """Start the MLX-VLM server, wait until it answers, and stop it afterwards."""
    port = _free_port()
    url = f"http://127.0.0.1:{port}/"
    env = _paddle_env()
    process = subprocess.Popen(
        [str(python), "-m", "mlx_vlm.server", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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


def _run_worker(python, pdf_path, pages, results, work, server, progress) -> None:
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
    ]
    result = subprocess.run(
        command,
        env=_paddle_env(),
        stdout=subprocess.DEVNULL,
        stderr=None if progress else subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-5:]
        raise OcrError("PaddleOCR-VL failed: " + " | ".join(tail))


def clean_text(text: str) -> str:
    """Undo the model's markup quirks: LaTeX around words, stray ``$``."""
    text = _LATEX_TEXT_RE.sub(r"\1", text)
    return text.replace("$", "")


def _write_text_layer(
    pdf_path: Path, results: Path, out: Path, mode: str, latin_macrons: bool | None
) -> bool:
    rows = []
    if results.is_file():
        with results.open(encoding="utf-8") as lines:
            rows = [json.loads(line) for line in lines if line.strip()]
    sample = " ".join(b["text"] for row in rows for b in row["blocks"])[:20_000]
    macrons = guess_language(sample) == "la" if latin_macrons is None else latin_macrons
    try:
        doc = pymupdf.open(pdf_path)
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise PdfOpenError(f"Could not open {pdf_path}: {exc}") from exc
    with doc:
        font = _font()
        for row in rows:
            page = doc.load_page(row["page"])
            if mode != "skip":
                _remove_text(page)
            page.insert_font(fontname=_FONT, fontbuffer=font.buffer)
            write_blocks(page, row, macrons)
        doc.save(out, garbage=3, deflate=True)
    return macrons


def write_blocks(page: pymupdf.Page, row: dict, macrons: bool = False) -> int:
    """Write a page's Paddle blocks as invisible text; returns the blocks written."""
    sx = page.rect.width / (row.get("width") or page.rect.width)
    sy = page.rect.height / (row.get("height") or page.rect.height)
    font = _font()
    written = 0
    # Wide blocks (body paragraphs) share one left edge: the model's boxes wobble by
    # several points, which would read as indentation on every line.
    wide = [
        b["bbox"][0] * sx
        for b in row["blocks"]
        if len(b.get("bbox", [])) == 4
        and (b["bbox"][2] - b["bbox"][0]) * sx > page.rect.width * _PARAGRAPH_WIDTH
    ]
    column_left = min(wide) if wide else None
    for block in row["blocks"]:
        text = clean_text(block.get("text", "")).strip()
        if not text or block.get("label") in _SKIP_LABELS or len(block.get("bbox", [])) != 4:
            continue
        if macrons:
            text = restore_macrons(text)
        text = _printable(text, font)
        x0, y0, x1, y1 = block["bbox"]
        rect = pymupdf.Rect(x0 * sx, y0 * sy, x1 * sx, y1 * sy)
        if rect.width > page.rect.width * _PARAGRAPH_WIDTH and column_left is not None:
            # A body paragraph: rewrap it (the model keeps the printed line breaks),
            # align it with the column, and mark its start with typed indentation,
            # which the structure pass reads as a new paragraph. Narrow blocks such
            # as margin glosses keep their lines.
            text = _UNHYPHEN_RE.sub(r"\1", text).replace("\n", " ")
            rect.x0 = column_left
            if block.get("label") == "text":
                text = "  " + text
        if _fit_text(page, rect, text):
            written += 1
    return written


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


def _fit_text(page: pymupdf.Page, rect: pymupdf.Rect, text: str) -> bool:
    """Write ``text`` into ``rect`` at the largest size that fits (invisible).

    Justified, so wrapped lines reach the right edge like the printed paragraph: a
    ragged edge would read as paragraph ends.
    """
    size = min(_MAX_FONT, max(_MIN_FONT, rect.height * 0.8))
    while size >= _MIN_FONT:
        # insert_textbox writes nothing and returns < 0 when the text doesn't fit.
        written = page.insert_textbox(
            rect,
            text,
            fontname=_FONT,
            fontsize=size,
            render_mode=3,
            align=pymupdf.TEXT_ALIGN_JUSTIFY,
        )
        if written >= 0:
            return True
        size *= 0.9
    # Very dense text: let it overflow the box rather than lose it.
    page.insert_textbox(
        rect + (0, 0, 0, rect.height * 3), text, fontname=_FONT, fontsize=_MIN_FONT, render_mode=3
    )
    return True


def _remove_text(page: pymupdf.Page) -> None:
    """Drop an existing (bad) text layer, keeping images and drawings."""
    page.add_redact_annot(page.rect)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE
    )

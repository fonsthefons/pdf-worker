"""OCR: give scanned PDFs a searchable text layer (Tesseract via OCRmyPDF).

The result is a normal PDF with invisible text over the page images, so every other
feature (text extraction, footnotes, conversion) works on it unchanged. OCRmyPDF works
page by page in parallel and never holds the whole document in memory.

See ``docs/ocr-plan.md`` for why Tesseract/OCRmyPDF was chosen.
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from pdf_worker.convert import guess_language
from pdf_worker.document import open_pdf
from pdf_worker.errors import PdfOpenError, PdfWorkerError

# skip: OCR only pages without text. redo: replace an existing OCR layer (keeps real
# digital text). force: rasterize every page and OCR it (loses digital text).
MODES = ("skip", "redo", "force")
ENGINES = ("tesseract", "paddle")
DEFAULT_LANGUAGE = "eng"
INSTALL_HINT = "install it with: brew install tesseract tesseract-lang"
# OCRmyPDF plugin (by module name) that restores Latin macrons.
LATIN_PLUGIN = "pdf_worker.ocr_latin_plugin"

# ISO 639-1 (what guess_language returns) -> Tesseract language code.
TESSERACT_CODES = {
    "en": "eng",
    "es": "spa",
    "fr": "fra",
    "de": "deu",
    "it": "ita",
    "pt": "por",
    "la": "lat",
}
# Text needed before we trust a language guess, and how many pages to sample for it.
_MIN_SAMPLE_CHARS = 500
_SAMPLE_PAGES = 12
_PROBE_PAGES = 3
_PROBE_DPI = 150
# Greek passages (often Ancient Greek in classics books) need Tesseract's "grc" model
# alongside the main language; a few stray letters (a misread "o", a "π") don't count.
GREEK_LANGUAGE = "grc"
_GREEK_RE = re.compile(r"[Ͱ-Ͽἀ-῿]")
_MIN_GREEK_LETTERS = 20

log = logging.getLogger(__name__)


class OcrError(PdfWorkerError):
    """OCR failed."""


class OcrEngineMissingError(OcrError):
    """Tesseract or OCRmyPDF is not installed."""


class OcrLanguageMissingError(OcrError):
    """A requested Tesseract language model is not installed."""


@dataclass
class OcrReport:
    output_path: Path
    mode: str
    languages: list[str]
    languages_guessed: bool = False
    macrons_restored: bool = False
    page_count: int = 0
    # Pages with no text layer before and after OCR (1-based).
    empty_pages_before: list[int] = field(default_factory=list)
    empty_pages_after: list[int] = field(default_factory=list)


def tesseract_path() -> str:
    path = shutil.which("tesseract") or shutil.which("/opt/homebrew/bin/tesseract")
    if not path:
        raise OcrEngineMissingError(f"Tesseract is not installed; {INSTALL_HINT}")
    return path


def available_languages() -> set[str]:
    """Language models Tesseract has installed, e.g. ``{"eng", "spa", "lat"}``."""
    result = subprocess.run(
        [tesseract_path(), "--list-langs"], capture_output=True, text=True, check=False
    )
    # The first line is a header ("List of available languages in ...").
    return {line.strip() for line in result.stdout.splitlines()[1:] if line.strip()}


def parse_languages(value: str | Sequence[str] | None) -> list[str] | None:
    """``"lat+eng"`` or ``["lat", "eng"]`` -> ``["lat", "eng"]``; None stays None."""
    if value is None:
        return None
    parts = value.split("+") if isinstance(value, str) else list(value)
    languages = [part.strip() for part in parts if part.strip()]
    return languages or None


def guess_ocr_languages(pdf_path: str | Path) -> list[str]:
    """Guess the Tesseract language(s) of a PDF, e.g. ``["spa"]`` or ``["lat", "grc"]``.

    Uses the existing text layer when there is enough of it; otherwise OCRs a couple
    of pages with English (stopwords survive misread accents) and guesses from that.
    Ancient Greek is added when the sample has Greek passages.
    """
    with open_pdf(pdf_path) as doc:
        sample = _sample_text_layer(doc)
        if len(sample) < _MIN_SAMPLE_CHARS:
            sample += _probe_ocr(doc)
    languages = [TESSERACT_CODES.get(guess_language(sample), DEFAULT_LANGUAGE)]
    if len(_GREEK_RE.findall(sample)) >= _MIN_GREEK_LETTERS:
        languages.append(GREEK_LANGUAGE)
    return languages


def ocr_pdf(
    pdf_path: str | Path,
    output_path: str | Path,
    languages: str | Sequence[str] | None = None,
    mode: str = "skip",
    jobs: int | None = None,
    progress: bool = False,
    latin_macrons: bool | None = None,
    engine: str = "tesseract",
) -> OcrReport:
    """OCR ``pdf_path`` into a searchable PDF at ``output_path`` (written atomically).

    ``languages`` are Tesseract codes (``"spa"``, ``"lat+eng"``); by default they are
    guessed from the document. ``latin_macrons`` turns accented vowels into macrons in
    the paragraphs that read as Latin (see ``pdf_worker.macrons``); by default it is on
    when Latin is a language.
    ``engine="paddle"`` uses PaddleOCR-VL instead (``pdf_worker.paddle_ocr``; slow,
    better on diacritics; ``languages`` and ``jobs`` don't apply).
    """
    if engine not in ENGINES:
        raise OcrError(f"Unknown OCR engine {engine!r}; choose from {', '.join(ENGINES)}")
    if engine == "paddle":
        from pdf_worker.paddle_ocr import ocr_pdf_paddle

        return ocr_pdf_paddle(
            pdf_path, output_path, mode=mode, progress=progress, latin_macrons=latin_macrons
        )
    if mode not in MODES:
        raise OcrError(f"Unknown OCR mode {mode!r}; choose from {', '.join(MODES)}")
    pdf_path, output_path = Path(pdf_path), Path(output_path)
    ocrmypdf = _import_ocrmypdf()
    installed = available_languages()

    report = OcrReport(output_path=output_path, mode=mode, languages=[])
    report.page_count, report.empty_pages_before = _empty_pages(pdf_path)
    chosen = parse_languages(languages)
    if chosen is None:
        chosen = guess_ocr_languages(pdf_path)
        report.languages_guessed = True
    missing = [language for language in chosen if language not in installed]
    if missing:
        raise OcrLanguageMissingError(
            f"Tesseract language(s) not installed: {', '.join(missing)}; {INSTALL_HINT}"
        )
    report.languages = chosen
    report.macrons_restored = "lat" in chosen if latin_macrons is None else latin_macrons
    plugins = [LATIN_PLUGIN] if report.macrons_restored else []

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=output_path.parent, prefix=f".{output_path.name}.", suffix=".pdf"
    )
    os.close(fd)
    try:
        _run_ocrmypdf(ocrmypdf, pdf_path, Path(tmp_name), chosen, mode, jobs, progress, plugins)
        _, report.empty_pages_after = _empty_pages(Path(tmp_name))
        os.replace(tmp_name, output_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return report


@contextmanager
def ocr_temporary_copy(
    pdf_path: str | Path, work_dir: str | Path, **options
) -> Iterator[tuple[Path, OcrReport]]:
    """OCR ``pdf_path`` into a temporary PDF inside ``work_dir``; delete it afterwards.

    Used by ``extract-text --ocr`` and ``convert --ocr``. ``options`` are passed to
    :func:`ocr_pdf`.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=work_dir, prefix=f".{Path(pdf_path).stem}.ocr.", suffix=".pdf")
    os.close(fd)
    path = Path(name)
    try:
        yield path, ocr_pdf(pdf_path, path, **options)
    finally:
        path.unlink(missing_ok=True)


def default_output_path(pdf_path: str | Path) -> Path:
    """``book.pdf`` -> ``book.ocr.pdf`` alongside the input."""
    return Path(pdf_path).with_suffix(".ocr.pdf")


def _import_ocrmypdf():
    tesseract_path()
    try:
        import ocrmypdf
    except ImportError as exc:
        raise OcrEngineMissingError(
            "OCRmyPDF is not installed; install pdf-worker with the 'ocr' extra: "
            "pip install 'pdf-worker[ocr]'"
        ) from exc
    return ocrmypdf


def _run_ocrmypdf(ocrmypdf, source, target, languages, mode, jobs, progress, plugins) -> None:
    from ocrmypdf import exceptions

    try:
        ocrmypdf.ocr(
            source,
            target,
            language=languages,
            mode=mode,
            # Plain PDF: PDF/A would need Ghostscript and changes nothing we use.
            output_type="pdf",
            jobs=jobs,
            progress_bar=progress,
            plugins=plugins,
        )
    except exceptions.MissingDependencyError as exc:
        raise OcrEngineMissingError(f"OCR dependency missing: {exc}") from exc
    except (exceptions.EncryptedPdfError, exceptions.InputFileError) as exc:
        raise PdfOpenError(f"Could not OCR {source}: {exc}") from exc
    except exceptions.ExitCodeException as exc:
        message = str(exc).strip() or type(exc).__name__
        raise OcrError(f"OCR failed for {source}: {message}") from exc


def _empty_pages(pdf_path: Path) -> tuple[int, list[int]]:
    with open_pdf(pdf_path) as doc:
        empty = [
            index + 1
            for index in range(doc.page_count)
            if not doc.load_page(index).get_text("text").strip()
        ]
        return doc.page_count, empty


def _sample_text_layer(doc: pymupdf.Document) -> str:
    step = max(1, doc.page_count // _SAMPLE_PAGES)
    return " ".join(
        doc.load_page(index).get_text("text") for index in range(0, doc.page_count, step)
    )


def _probe_ocr(doc: pymupdf.Document) -> str:
    """OCR a few pages spread over the book with English (plus Greek, so Greek passages
    show up as Greek letters), for a language guess."""
    probe = DEFAULT_LANGUAGE
    if GREEK_LANGUAGE in available_languages():
        probe += "+" + GREEK_LANGUAGE
    # Spread out: an introduction or a run of Greek text can fill several pages.
    indexes = {doc.page_count * (k + 1) // (_PROBE_PAGES + 1) for k in range(_PROBE_PAGES)}
    texts = []
    for index in sorted(indexes):
        png = doc.load_page(index).get_pixmap(dpi=_PROBE_DPI, colorspace=pymupdf.csGRAY)
        result = subprocess.run(
            [tesseract_path(), "stdin", "stdout", "-l", probe],
            input=png.tobytes("png"),
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            log.warning("language probe OCR failed on page %d", index + 1)
            continue
        texts.append(result.stdout.decode("utf-8", errors="replace"))
    return " ".join(texts)

"""OCRmyPDF plugin: Tesseract, with Latin macrons restored before the text layer is built.

Loaded by ``pdf_worker.ocr`` (by module name, so OCRmyPDF's worker processes can
import it too) when Latin is the OCR language. Only paragraphs that read as Latin are
changed, so the accents of Spanish or French passages survive. See ``pdf_worker.macrons``.
"""

import html
import re
from pathlib import Path

from ocrmypdf import hookimpl
from ocrmypdf.builtin_plugins.tesseract_ocr import TesseractOcrEngine

from pdf_worker.macrons import reads_as_latin, restore_macrons, restore_macrons_if_latin

_HOCR_PAR_RE = re.compile(r"<p class=['\"]ocr_par['\"].*?</p>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_LINE_RE = re.compile(r"(\n\s*\n)")
# shortcut: only Greek is known to be non-Latin script; add others (rus, heb...) if used.
_NON_LATIN_SCRIPT = {"grc", "ell"}


def restore_hocr(hocr: str, default: bool) -> str:
    """Restore macrons in the hOCR paragraphs that read as Latin. Ties (a heading, a
    name) follow the whole page, and the page follows ``default``."""
    page_default = reads_as_latin(_hocr_text(hocr), default)
    return _HOCR_PAR_RE.sub(
        lambda par: (
            restore_macrons(par.group(0))
            if reads_as_latin(_hocr_text(par.group(0)), page_default)
            else par.group(0)
        ),
        hocr,
    )


def restore_text(text: str, default: bool) -> str:
    """Like :func:`restore_hocr` for plain text, whose paragraphs end at a blank line."""
    page_default = reads_as_latin(text, default)
    return "".join(
        restore_macrons_if_latin(part, page_default) for part in _BLANK_LINE_RE.split(text)
    )


def _hocr_text(hocr: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", hocr))


class LatinTesseractOcrEngine(TesseractOcrEngine):
    @staticmethod
    def generate_hocr(input_file, output_hocr, output_text, options):
        TesseractOcrEngine.generate_hocr(input_file, output_hocr, output_text, options)
        # Undecided pages count as Latin unless another Latin-script language was asked for.
        default = not set(options.languages) - {"lat"} - _NON_LATIN_SCRIPT
        for path, restore in ((Path(output_hocr), restore_hocr), (Path(output_text), restore_text)):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                path.write_text(restore(text, default), encoding="utf-8")


@hookimpl
def get_ocr_engine(options):
    # Registered after the built-in plugins, so this hook runs first and wins.
    return LatinTesseractOcrEngine()

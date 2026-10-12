"""OCRmyPDF plugin: Tesseract, with Latin macrons restored before the text layer is built.

Loaded by ``pdf_worker.ocr`` (by module name, so OCRmyPDF's worker processes can
import it too) when Latin is the OCR language. See ``pdf_worker.macrons``.
"""

from pathlib import Path

from ocrmypdf import hookimpl
from ocrmypdf.builtin_plugins.tesseract_ocr import TesseractOcrEngine

from pdf_worker.macrons import restore_macrons


class LatinTesseractOcrEngine(TesseractOcrEngine):
    @staticmethod
    def generate_hocr(input_file, output_hocr, output_text, options):
        TesseractOcrEngine.generate_hocr(input_file, output_hocr, output_text, options)
        for path in (Path(output_hocr), Path(output_text)):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                path.write_text(restore_macrons(text), encoding="utf-8")


@hookimpl
def get_ocr_engine(options):
    # Registered after the built-in plugins, so this hook runs first and wins.
    return LatinTesseractOcrEngine()

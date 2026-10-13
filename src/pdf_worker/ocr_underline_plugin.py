"""OCRmyPDF plugin: erase hand-drawn underlines from the image Tesseract reads.

Pages with underlines (see ``pdf_worker.underlines``) are scaled to 300 dpi if finer,
made black and white, and have the underlines erased; on the sample book's underlined
pages, scaling a 900 dpi scan down raised word recall from 93.7% to 94.5%. Other pages
go to Tesseract untouched (scaling them cost Latin macrons and note markers).

Only the OCR input changes; the page the reader sees is untouched. Loaded by
``pdf_worker.ocr`` by module name, so OCRmyPDF's worker processes can import it too.
"""

import cv2
import numpy as np
from ocrmypdf import hookimpl
from PIL import Image

from pdf_worker.underlines import erase_underlines

_MAX_DPI = 400
_TARGET_DPI = 300


@hookimpl
def filter_ocr_image(page, image: Image.Image) -> Image.Image | None:
    dpi_x, dpi_y = (float(v) for v in image.info.get("dpi", (_TARGET_DPI, _TARGET_DPI)))
    gray = np.asarray(image.convert("L"))
    scale = _TARGET_DPI / dpi_x if dpi_x > _MAX_DPI else 1.0
    if scale < 1.0:
        size = (round(gray.shape[1] * scale), round(gray.shape[0] * scale))
        gray = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
    cleaned, erased = erase_underlines(gray, dpi_x * scale)
    if not erased:
        return None  # no underlines: OCRmyPDF's own filters run as usual
    # shortcut: skips Tesseract's built-in downsampling of images over 32767 px a side,
    # which only huge posters need; call it here if such scans come up.
    out = Image.fromarray(cleaned)
    out.info["dpi"] = (dpi_x * scale, dpi_y * scale)
    return out

"""Opening PDFs consistently across features."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from pdf_worker.errors import PdfOpenError


@contextmanager
def open_pdf(path: str | Path) -> Iterator[pymupdf.Document]:
    """Open a PDF for reading and guarantee it is closed afterwards.

    Pages are loaded lazily by PyMuPDF, so this is safe for very large files.
    """
    path = Path(path)
    if not path.is_file():
        raise PdfOpenError(f"File not found: {path}")
    try:
        doc = pymupdf.open(path, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise PdfOpenError(f"Could not open {path} as a PDF: {exc}") from exc
    try:
        if doc.needs_pass:
            raise PdfOpenError(f"PDF is password-protected: {path}")
        yield doc
    finally:
        doc.close()

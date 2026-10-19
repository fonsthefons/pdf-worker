"""Lay out an EPUB (or FB2, MOBI, plain text) as an A5 PDF with its table of contents."""

import os
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from pdf_worker.errors import PdfWorkerError

A5 = (420, 595)  # points
# Invisible characters that MuPDF draws as a space, swallowing the next real space:
# Standard Ebooks' "pity﻿—for I" came out as "pity —forI".
_INVISIBLE = ("﻿", "⁠")


@contextmanager
def quiet_mupdf() -> Iterator[None]:
    """Hide MuPDF's messages about ebooks' broken CSS: harmless, and alarming to read."""
    shown = pymupdf.TOOLS.mupdf_display_errors()
    pymupdf.TOOLS.mupdf_display_errors(False)
    try:
        yield
    finally:
        pymupdf.TOOLS.mupdf_display_errors(shown)


def default_output_path(ebook_path: str | Path) -> Path:
    return Path(ebook_path).with_suffix(".pdf")


def ebook_to_pdf(ebook_path: str | Path, output_path: str | Path, fontsize: float = 11) -> int:
    """Write the PDF atomically; return its page count."""
    ebook_path, output_path = Path(ebook_path), Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        quiet_mupdf(),
        tempfile.TemporaryDirectory(dir=output_path.parent, prefix=".ebook-to-pdf.") as tmp,
    ):
        source = ebook_path
        if zipfile.is_zipfile(ebook_path):
            source = _without_invisible_characters(ebook_path, Path(tmp) / "book.epub")
        try:
            book = pymupdf.open(source, filetype=ebook_path.suffix.lstrip(".") or None)
        except (pymupdf.FileDataError, RuntimeError) as exc:
            raise PdfWorkerError(f"Could not open {ebook_path} as an ebook: {exc}") from exc
        with book:
            if book.is_reflowable:
                book.apply_css("@page { margin: 1.6cm 1.4cm; }")  # else edge to edge
                book.layout(width=A5[0], height=A5[1], fontsize=fontsize)
            # shortcut: the whole PDF is built in memory (convert_to_pdf fails on page
            # ranges not starting at 0); fine for books of a few MB, not huge archives.
            with pymupdf.open("pdf", book.convert_to_pdf()) as pdf:
                pdf.set_toc(book.get_toc())
                meta = book.metadata
                pdf.set_metadata({k: meta[k] for k in ("title", "author") if meta.get(k)})
                pdf.save(Path(tmp) / "book.pdf", garbage=3, deflate=True)
                count = pdf.page_count
        os.replace(Path(tmp) / "book.pdf", output_path)
    return count


def _without_invisible_characters(epub: Path, copy: Path) -> Path:
    with zipfile.ZipFile(epub) as src, zipfile.ZipFile(copy, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename.endswith((".xhtml", ".html", ".htm")):
                text = data.decode("utf-8", "replace")
                for char in _INVISIBLE:
                    text = text.replace(char, "")
                data = text.encode("utf-8")
            # The EPUB's "mimetype" entry must stay uncompressed; keep each entry's mode.
            dst.writestr(info, data, compress_type=info.compress_type)
    return copy

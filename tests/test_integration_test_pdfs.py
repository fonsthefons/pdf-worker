"""Runs extraction against the real sample PDFs in test_pdfs/.

These are slower than the unit tests; skip them with ``pytest -m "not integration"``.
"""

import pytest
from conftest import TEST_PDFS_DIR

from pdf_worker.text_extraction import extract_text_to_file

pytestmark = pytest.mark.integration

GOOD_TEXT_PDF = TEST_PDFS_DIR / "Critica de la Razon Pura - Immanuel Kant.pdf"
BAD_TEXT_PDF = TEST_PDFS_DIR / "Familia Romana Lingua Latina.pdf"


def _require(path):
    if not path.is_file():
        pytest.skip(f"sample PDF not present: {path.name}")


def test_good_text_pdf_extracts_cleanly(tmp_path):
    _require(GOOD_TEXT_PDF)
    out = tmp_path / "kant.txt"

    report = extract_text_to_file(GOOD_TEXT_PDF, out)

    assert report.page_count == 206
    assert report.empty_pages == []
    head = out.read_text(encoding="utf-8")[:2000]
    assert "Crítica de la razón pura" in head


def test_bad_text_pdf_extracts_and_flags_image_only_pages(tmp_path):
    _require(BAD_TEXT_PDF)
    out = tmp_path / "familia.txt"

    report = extract_text_to_file(BAD_TEXT_PDF, out)

    assert report.page_count == 332
    # Cover and back pages are scanned images with no text layer.
    assert report.empty_pages == [1, 2, 331, 332]
    assert report.char_count > 0

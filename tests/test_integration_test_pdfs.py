"""Runs extraction against the real sample PDFs in test_pdfs/.

These are slower than the unit tests; skip them with ``pytest -m "not integration"``.
"""

import pytest
from conftest import TEST_PDFS_DIR

from pdf_worker.text_extraction import extract_text_to_file

pytestmark = pytest.mark.integration

GOOD_TEXT_PDF = TEST_PDFS_DIR / "Critica de la Razon Pura - Immanuel Kant.pdf"
BAD_TEXT_PDF = TEST_PDFS_DIR / "Familia Romana Lingua Latina.pdf"
ENDNOTES_PDF = TEST_PDFS_DIR / "Magnifica Humanitas Encíclica May 15 2026.pdf"


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
    # Margin glosses, line numbers and numbered exercises must not look like notes.
    assert report.footnote_count == 0


def test_bracketed_endnotes_are_all_linked(tmp_path):
    _require(ENDNOTES_PDF)
    out = tmp_path / "humanitas.txt"

    report = extract_text_to_file(ENDNOTES_PDF, out)

    assert report.footnote_count == 224
    assert report.footnote_reference_count == 224
    assert report.undefined_footnotes == report.unreferenced_footnotes == []
    text = out.read_text(encoding="utf-8")
    assert "esclarece en el misterio del Verbo encarnado».[^1]" in text
    assert "\n[^1]: Conc. Ecum. Vat. II, Const. past. Gaudium et spes, 22" in text


def test_footnote_mode_matches_raw_text_when_no_notes(tmp_path):
    _require(GOOD_TEXT_PDF)
    marked = extract_text_to_file(GOOD_TEXT_PDF, tmp_path / "marked.txt")
    raw = extract_text_to_file(GOOD_TEXT_PDF, tmp_path / "raw.txt", footnotes=False)

    assert marked.footnote_count == 0
    assert (tmp_path / "marked.txt").read_bytes() == (tmp_path / "raw.txt").read_bytes()
    assert raw.char_count == marked.char_count

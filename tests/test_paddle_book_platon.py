"""Regression check: test_platon_bad_3 built from Paddle's (cached) blocks, scored
against platon_dialogos_vi_good.pdf (the same text from a well-made ePub).

Needs both PDFs in test_pdfs/, Tesseract, and the Paddle pages cached in
scratch/paddle-home (a Paddle run of the whole file takes about 40 minutes; any
``convert --ocr redo --ocr-engine paddle`` with that cache fills it)."""

import shutil

import pytest
from conftest import REPO_ROOT
from platon_score import GOOD, score

from pdf_worker import paddle_ocr
from pdf_worker.convert import convert_pdf
from pdf_worker.document import open_pdf

BAD = REPO_ROOT / "test_pdfs" / "test_platon_bad_3.pdf"
CACHE = REPO_ROOT / "scratch" / "paddle-home"


@pytest.mark.integration
def test_platon_bad_3_matches_the_good_book(tmp_path, monkeypatch):
    if not (BAD.is_file() and REPO_ROOT.joinpath(GOOD).is_file()):
        pytest.skip("test_platon_bad_3.pdf or platon_dialogos_vi_good.pdf missing")
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract not installed")
    monkeypatch.setenv("PDF_WORKER_PADDLE_CACHE", str(CACHE))
    if not paddle_ocr._pages_cache(BAD).is_file():
        pytest.skip("Paddle pages of test_platon_bad_3 not cached")
    with open_pdf(BAD) as doc:
        pages = list(range(doc.page_count))
    rows = paddle_ocr.paddle_pages(BAD, pages)
    if len(rows) < len(pages):
        pytest.skip("Paddle pages of test_platon_bad_3 only partly cached")
    out = tmp_path / "book.txt"

    convert_pdf(BAD, out, "txt", paddle_rows=rows)

    scores = score(str(out))
    # Measured 2026-10-15: 1.7%, 4 extra breaks, 56/57 refs (note 8's from the text
    # layer, see missing_refs), notes 0.87, 53/54 margin.
    assert scores["word_error_rate"] < 0.025
    assert scores["paragraph_extra"] <= 6
    assert scores["refs_ok"] >= 55
    assert scores["notes_mean"] >= 0.85
    assert scores["margin_ok"] >= 52

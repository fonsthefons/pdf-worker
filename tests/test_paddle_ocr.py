"""PaddleOCR-VL engine: the text-layer writer is tested without Paddle; the full run
only where the Paddle environment exists (it is slow and needs the model)."""

import os

import pymupdf
import pytest
from conftest import REPO_ROOT

from pdf_worker import paddle_ocr
from pdf_worker.ocr import OcrEngineMissingError, OcrError, ocr_pdf

pytest.importorskip("pymupdf_fonts")

ROW = {
    "width": 1190,
    "height": 1684,  # A4 at 144 dpi: 2 px per point
    "blocks": [
        {"label": "paragraph_title", "bbox": [144, 144, 700, 200], "text": "TEMPESTAS"},
        {
            "label": "text",
            "bbox": [144, 240, 1046, 400],
            "text": "Urbs Rôma nôn ad mare, sed ad Tiberim flūmen sita est "
            "$ \\text{Āfricā} $ quod paulum aquae est in Tiberī.",
        },
        {"label": "image", "bbox": [144, 420, 1046, 900], "text": ""},
        {"label": "footnote", "bbox": [144, 1500, 1046, 1540], "text": "1 A small note."},
    ],
}


def test_blocks_become_an_invisible_text_layer():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="notos", fontbuffer=pymupdf.Font("notos").buffer)

    written = paddle_ocr.write_blocks(page, ROW, macrons=True)

    text = page.get_text()
    assert written == 3  # the image block has no text
    assert text.index("TEMPESTAS") < text.index("Urbs") < text.index("A small note")
    assert "Rōma nōn" in text and "Āfricā" in text and "$" not in text
    lines = page.get_text("dict")["blocks"]
    sizes = {
        round(span["size"], 1): span["text"]
        for block in lines
        for line in block["lines"]
        for span in line["spans"]
    }
    title_size = max(s for s, t in sizes.items() if "TEMPESTAS" in t)
    note_size = max(s for s, t in sizes.items() if "small note" in t)
    assert title_size > note_size  # box heights carry the typography over


def test_clean_text_removes_latex_wrappers():
    assert paddle_ocr.clean_text("in $ \\text{Āfricā} $ est") == "in Āfricā est"


def test_missing_environment_is_a_clean_error(tmp_path, monkeypatch, make_pdf):
    monkeypatch.setenv("PDF_WORKER_PADDLE_PYTHON", str(tmp_path / "nope" / "python"))

    with pytest.raises(OcrEngineMissingError, match="PaddleOCR environment not found"):
        ocr_pdf(make_pdf(["x"]), tmp_path / "out.pdf", engine="paddle")


def test_unknown_engine(tmp_path, make_pdf):
    with pytest.raises(OcrError, match="engine"):
        ocr_pdf(make_pdf(["x"]), tmp_path / "out.pdf", engine="magic")


@pytest.mark.integration
@pytest.mark.skipif(
    not paddle_ocr._DEFAULT_PYTHON.is_file() and "PDF_WORKER_PADDLE_PYTHON" not in os.environ,
    reason="PaddleOCR environment not installed",
)
def test_paddle_ocrs_an_image_only_page(tmp_path, monkeypatch):
    # Use the model files already downloaded for this repo, if any (about 2 GB).
    local_cache = REPO_ROOT / "scratch" / "paddle-home"
    if local_cache.is_dir():
        monkeypatch.setenv("PDF_WORKER_PADDLE_CACHE", str(local_cache))
    source = pymupdf.open()
    page = source.new_page()
    page.insert_font(fontname="notos", fontbuffer=pymupdf.Font("notos").buffer)
    page.insert_text((72, 100), "Mārcus et Iūlia in hortō sunt.", fontsize=18, fontname="notos")
    picture = page.get_pixmap(dpi=150)
    scan = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_image(doc[0].rect, pixmap=picture)
    doc.save(scan)

    report = ocr_pdf(scan, tmp_path / "out.pdf", engine="paddle")

    with pymupdf.open(tmp_path / "out.pdf") as out:
        text = out[0].get_text()
    assert report.empty_pages_after == []
    assert "Iūlia" in text or "Iulia" in text

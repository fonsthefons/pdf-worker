"""PaddleOCR-VL engine: the text-layer writer is tested without Paddle; the full run
only where the Paddle environment exists (it is slow and needs the model)."""

import os

import pymupdf
import pytest
from conftest import REPO_ROOT

from pdf_worker import paddle_ocr
from pdf_worker.layout import SUPERSCRIPT, page_lines
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

    written, last_note, _ = paddle_ocr.write_blocks(page, ROW, macrons=True)

    text = page.get_text()
    assert written == 3  # the image block has no text
    assert last_note == 1
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


def test_footnotes_are_numbered_small_and_referenced():
    # From test_platon_bad p. 8: the reference comes as LaTeX, the note without its number.
    long = "El diálogo va a concluir positivamente dejando establecida la jerarquía. " * 12
    row = {
        "width": 1190,
        "height": 1684,
        "blocks": [
            {
                "label": "text",
                "bbox": [144, 144, 1046, 210],
                "text": "el cambio de interlocutor $ ^{1} $.",
            },
            {"label": "text", "bbox": [144, 212, 1046, 900], "text": long},
            {
                "label": "footnote",
                "bbox": [144, 1400, 1046, 1440],
                "text": "Estos cambios ocurren.",
            },
        ],
    }
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="notos", fontbuffer=pymupdf.Font("notos").buffer)

    paddle_ocr.write_blocks(page, row)

    lines = page_lines(page)
    ref = next(ln for ln in lines if "interlocutor" in ln.text)
    note = next(ln for ln in lines if "Estos" in ln.text)
    body = next(ln for ln in lines if "jerarquía" in ln.text)
    assert [s["text"] for s in ref.spans if s["flags"] & SUPERSCRIPT] == ["1"]
    assert note.spans[0]["text"] == "1" and note.spans[0]["flags"] & SUPERSCRIPT
    assert ref.size == body.size and note.size < body.size * 0.92


def test_words_with_a_digit_take_tesseracts_letters():
    from pdf_worker.margin_refs import ScanWord

    words = ["FILEBO", "PRO.", "—", "SÍ.", "en", "13b.", "Cf.", "1)d6."]
    scan = [ScanWord(w, 0, False) for w in words]
    texts = paddle_ocr._fix_digit_words(["FILE0", "PRO. — S1. en 13b. Cf. 11d6."], scan)
    assert texts == ["FILEBO", "PRO. — Sí. en 13b. Cf. 11d6."]


def test_short_speeches_are_body_paragraphs():
    long = "Que ahora cada uno de nosotros intentará poner de manifiesto un estado. " * 6
    row = {
        "width": 1190,
        "height": 1684,
        "blocks": [
            {"label": "text", "bbox": [144, 144, 1046, 400], "text": long},
            {"label": "text", "bbox": [200, 404, 450, 434], "text": "PRO. — Así es."},
        ],
    }
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="notos", fontbuffer=pymupdf.Font("notos").buffer)

    paddle_ocr.write_blocks(page, row)

    lines = page_lines(page)
    short = next(ln for ln in lines if "Así" in ln.text)
    assert short.size == lines[0].size and short.text.startswith("  PRO.")


def test_clean_text_turns_latex_superscripts_into_references():
    assert paddle_ocr.clean_text("interlocutor $ ^{1} $.") == "interlocutor¹."
    assert paddle_ocr.clean_text("Tome 2<sup>e</sup>, M.$^{A}$") == "Tome 2e, M.A"
    # Note 28 misread as "2k": the digits stay a reference, renumbered later.
    assert paddle_ocr.clean_text("o eristicamente^{2k}.") == "o eristicamente²."


def test_clean_text_removes_latex_wrappers():
    assert paddle_ocr.clean_text("in $ \\text{Āfricā} $ est") == "in Āfricā est"


def test_clean_text_flattens_tables():
    table = "<table><tr><td>Rōma</td><td>Rōmam</td></tr><tr><td>A &amp; B</td></tr></table>"
    assert paddle_ocr.clean_text(table) == "Rōma Rōmam\nA & B"


def test_clean_text_drops_looping_tables():
    # From a real run: the model read the cover's dog mosaic as this table.
    rows = "<tr><td>Nīlus fluvius est.</td><td>Corsica insula est.</td></tr>" * 10
    assert paddle_ocr.clean_text(f"<table>{rows}</table>") == ""


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

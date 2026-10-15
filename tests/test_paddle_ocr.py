"""PaddleOCR-VL engine: the text-layer writer is tested without Paddle; the full run
only where the Paddle environment exists (it is slow and needs the model)."""

import os

import pymupdf
import pytest
from conftest import REPO_ROOT

from pdf_worker import paddle_ocr
from pdf_worker.layout import SUPERSCRIPT, page_lines
from pdf_worker.margin_refs import PageScan, ScanWord
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
    # "¹²⁶?" read as one number: the "?" became a 7.
    assert paddle_ocr.clean_text("los que son filósofos^{1267}") == "los que son filósofos¹²⁶?"


def test_made_up_vietnamese_is_replaced_by_tesseracts_words():
    words = [
        ScanWord("iōn", 0, False, (10, 10, 30, 20)),
        ScanWord("de", 0, False, (32, 10, 40, 20)),
        ScanWord("autōn", 0, False, (42, 10, 70, 20)),
        ScanWord("Otra", 1, False, (10, 50, 30, 60)),
    ]
    scan = PageScan(words, [])
    assert paddle_ocr._foreign_script("R1 (lỗi) đến (để) đến, sức gắn (số) los códices.")
    assert not paddle_ocr._foreign_script("SốC. — Pues bien, Protarco, dime qué opinas.")
    assert paddle_ocr._scan_text(scan, pymupdf.Rect(0, 0, 100, 30)) == "iōn de autōn"


def test_mixed_script_keeps_the_more_confident_reading_of_each_word():
    from pdf_worker.mixed_script import Word, merge_readings

    line = ("1", "1", "1")
    spanish = [
        Word((0, 0, 40, 10), 90, "21b1", line),
        Word((50, 0, 70, 10), 20, "tà", line),
        Word((75, 0, 120, 10), 30, "šèovta", line),
        Word((130, 0, 190, 10), 85, "Badham", line),
    ]
    greek = [
        Word((0, 0, 40, 10), 40, "210]", line),
        Word((50, 0, 70, 10), 88, "τὰ", line),
        Word((76, 0, 121, 10), 80, "δέοντα", line),
        Word((130, 0, 190, 10), 30, "Βδάδβιο", line),
    ]
    assert merge_readings(spanish, greek) == ["21b1 τὰ δέοντα Badham"]


def test_a_note_the_model_skipped_comes_from_tesseracts_lines():
    words = [
        ScanWord("Body", 0, False, (10, 100, 40, 110)),
        ScanWord("43.", 5, False, (10, 500, 20, 510)),
        ScanWord("Ibid.,", 5, False, (25, 500, 50, 510)),
        ScanWord("44.", 6, False, (10, 512, 20, 522)),
        ScanWord("Ibid.", 6, False, (25, 512, 50, 522)),
        ScanWord("y", 7, False, (25, 524, 30, 534)),
        ScanWord("45.", 8, False, (10, 536, 20, 546)),
    ]
    found = paddle_ocr._recover_notes(PageScan(words, []), [43, 44, 45], [43, 45], 495)
    assert found == [(44, "Ibid. y")]


def test_a_printers_signature_is_no_note_but_a_short_note_is():
    for signature in ("160. — 18", "160. -4", "160. ~2", "160. - S"):
        assert paddle_ocr._SIGNATURE_RE.match(signature)
    for note in ("31. 7.", "30. I, 7.", "36. 13.", "²¹ Cf. Tym. 2Sa-b."):
        assert not paddle_ocr._SIGNATURE_RE.match(note)


def test_running_heads_and_notes_paddle_mislabels():
    number = [799, 126, 832, 153]
    head = {"label": "paragraph_title", "bbox": [435, 131, 517, 156]}
    title = {"label": "paragraph_title", "bbox": [400, 500, 800, 560]}
    note = {"label": "footer", "bbox": [149, 1351, 356, 1379]}
    sign = {"label": "footer", "bbox": [149, 1351, 356, 1379]}
    assert paddle_ocr._relabel(head, "FILEBO", number) == "header"
    assert paddle_ocr._relabel(title, "FILEBO", number) == "paragraph_title"
    assert paddle_ocr._relabel(note, "11D Cf. Leyes 863a-c.", number) == "footnote"
    assert paddle_ocr._relabel(note, "16. De l'esprit des lois, XI, 6.", number) == "footnote"
    assert paddle_ocr._relabel(sign, "160. — 18", number) == "footer"


def test_clean_text_removes_latex_wrappers():
    assert paddle_ocr.clean_text("in $ \\text{Āfricā} $ est") == "in Āfricā est"
    assert paddle_ocr.clean_text("1. \\underline{\\text{Creación de los seres}} (30c)") == (
        "1. Creación de los seres (30c)"
    )
    assert paddle_ocr.clean_text("T_{M\\cdot} - x") == "TM - x"
    assert paddle_ocr.clean_text("S_i saga. {Cuéntasela") == "Si saga. Cuéntasela"


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

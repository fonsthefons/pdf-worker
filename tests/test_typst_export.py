import re

import pymupdf
import pytest
from conftest import TEST_PDFS_DIR

from pdf_worker import convert, typst_export
from pdf_worker.docx_export import PandocMissingError, pandoc_path
from pdf_worker.inline import margin_ref
from pdf_worker.output import Metadata
from pdf_worker.structure import Note, Paragraph


def _has_pandoc() -> bool:
    try:
        return bool(pandoc_path())
    except PandocMissingError:
        return False


pytestmark = pytest.mark.skipif(not _has_pandoc(), reason="needs Pandoc")

FILLER = " ".join(["palabra"] * 400)
META = Metadata("Timeo", "Platón", "es", "Francisco Lisi")
TEXT_RIGHT = pymupdf.paper_rect("a5").width - 42  # right edge of the text


def _write(tmp_path, blocks, **kwargs):
    out = tmp_path / "book.pdf"
    typst_export.write_pdf(blocks, out, META, **kwargs)
    return pymupdf.open(out)


def _note_blocks():
    return [Paragraph("Texto con nota[^1] aquí. " + FILLER), Note("1", "Única nota del libro.")]


def test_the_pdf_is_tagged(tmp_path):
    with _write(tmp_path, [Paragraph("Hola.")]) as doc:
        assert doc.xref_get_key(doc.pdf_catalog(), "StructTreeRoot")[0] != "null"
        assert doc.metadata["title"] == "Timeo" and doc.metadata["author"] == "Platón"


def test_footnotes_at_the_foot_of_their_page(tmp_path):
    with _write(tmp_path, _note_blocks(), notes_at="page") as doc:
        first = doc[0].get_text()
    assert "Texto con nota" in first and "Única nota del libro." in first


def test_notes_at_the_end_in_a_notes_section(tmp_path):
    with _write(tmp_path, _note_blocks(), notes_at="end") as doc:
        first, last = doc[0].get_text(), doc[-1].get_text()
    assert "Texto con nota" in first and "Única nota" not in first
    assert "Notas" in last and "Única nota del libro." in last


def test_margin_references_sit_in_the_right_margin(tmp_path):
    text = "muchos " + margin_ref("22a") + "honores " + FILLER + " " + margin_ref("~22b") + "(fin)"
    with _write(tmp_path, [Paragraph(text)]) as doc:
        spans = {
            span["text"]: span
            for page in doc
            for block in page.get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
        }
        words = doc[0].get_text("words")
    assert spans["22a"]["bbox"][0] > TEXT_RIGHT
    honores = next(w for w in words if w[4] == "honores")
    assert abs(spans["22a"]["bbox"][3] - honores[3]) < 4  # level with its line
    assert spans["22a"]["color"] >> 16 < 0x80 < spans["~22b"]["color"] >> 16  # green, pink


def test_the_cover_is_page_one_without_a_number(tmp_path):
    with _write(tmp_path, [Paragraph("Hola.")], cover=True) as doc:
        assert doc[0].get_images() and not doc[0].get_text().strip()
        assert doc[1].get_text().split()[-1] == "2"


def test_greek_has_glyphs(tmp_path):
    with _write(tmp_path, [Paragraph("Dice λόγος καὶ ψυχή.")]) as doc:
        chars = [c for s in doc[0].get_texttrace() for c in s["chars"]]
    greek = [c for c in chars if "Ͱ" <= chr(c[0]) <= "Ͽ" or "ἀ" <= chr(c[0]) <= "῿"]
    assert greek and all(c[1] != 0 for c in greek)


@pytest.mark.integration
def test_timeo_with_notes_on_the_page(tmp_path, monkeypatch):
    pdf = TEST_PDFS_DIR / "Timeo_by_Platón_no_intro.pdf"
    if not pdf.is_file():
        pytest.skip(f"sample PDF not present: {pdf.name}")
    monkeypatch.setattr(convert, "write_pdf", typst_export.write_pdf)
    out = tmp_path / "timeo.pdf"

    convert.convert_pdf(pdf, out, "pdf", notes_at="page", fixes_path=tmp_path / "f.tsv")

    with pymupdf.open(out) as doc:
        assert doc.xref_get_key(doc.pdf_catalog(), "StructTreeRoot")[0] != "null"
        refs = [
            w
            for page in doc
            for w in page.get_text("words")
            if re.fullmatch(r"~?\d+[a-e]", w[4]) and w[0] > TEXT_RIGHT
        ]
    assert refs

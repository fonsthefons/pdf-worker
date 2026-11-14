import pymupdf

from pdf_worker.cover import cover_jpeg, find_translator
from pdf_worker.output import Metadata
from pdf_worker.structure import Paragraph
from pdf_worker.typst_export import write_pdf


def test_translator_from_title_pages():
    assert find_translator(["© 1960", "Traducción de MANUEL SACRISTÁN"]) == "Manuel Sacristán"
    platon = "TRADUCCIONES, INTRODUCCIONES Y NOTAS\nPOR\nM. ^ ÁNGELES DURÁN Y FRANCISCO LISI"
    assert find_translator([platon]) == "M. Ángeles Durán y Francisco Lisi"
    assert find_translator(["Translated by Jane Doe, 1990"]) == "Jane Doe"
    assert find_translator(["las traducciones de este volumen han sido revisadas"]) == ""


def test_cover_jpeg():
    assert cover_jpeg(Metadata("Timeo", "Platón", "es", "Francisco Lisi"))[:2] == b"\xff\xd8"


def test_reflowed_pdf_has_cover_and_page_numbers(tmp_path):
    out = tmp_path / "book.pdf"
    meta = Metadata("Timeo", "Platón", "es", "Francisco Lisi")

    write_pdf([Paragraph("Texto " * 2000)], out, meta, cover=True)

    with pymupdf.open(out) as doc:
        assert doc[0].get_images() and not doc[0].get_text().strip()  # the cover is a picture
        for number, page in enumerate(doc[1:], 2):
            foot = page.get_text(clip=(0, page.rect.height - 40, page.rect.width, page.rect.height))
            assert foot.strip() == str(number)

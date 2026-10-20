import re
import zipfile

from pdf_worker.epub import write_epub
from pdf_worker.index_links import link_index
from pdf_worker.inline import END_ITALIC, ITALIC, page_mark, plain
from pdf_worker.output import Metadata
from pdf_worker.structure import Heading, Paragraph


def test_index_page_numbers_become_numbered_links_to_the_word_on_the_page(tmp_path):
    blocks = [
        Paragraph(page_mark(0, "10") + "Opening words." + page_mark(1, "11"), page=0),
        Paragraph("Something about Kant here."),  # no page (OCR path): the last one started
        Paragraph("Other text" + page_mark(2, "12") + " goes on with Hume.", page=1),
        Heading("ÍNDICE ONOMÁSTICO", 1),
        Heading("H", 2),
        Paragraph(
            page_mark(3, "12")  # its digits are no page reference
            + f"Hume, David (1711-1776), 12. Kant, 10, {ITALIC}11s{END_ITALIC}; véase 99."
        ),
    ]

    linked = list(link_index(blocks))
    write_epub(linked, tmp_path / "b.epub", Metadata("T"))

    assert linked[-1].text.startswith(page_mark(3, "12") + "Hume")
    assert plain(linked[-1].text) == "Hume, David (1711-1776) [1]. Kant [1] [2]; véase 99."
    with zipfile.ZipFile(tmp_path / "b.epub") as z:
        html = "".join(z.read(n).decode() for n in z.namelist() if n.endswith(".xhtml"))
    links = re.findall(r'<a href="(c\d+\.xhtml#\w+)">\[\d\]</a>', html)
    # Hume: the page-12 part of a paragraph; Kant: no Kant on page 10 -> page start,
    # then the paragraph on page 11 that names him.
    assert links == ["c001.xhtml#pg2", "c001.xhtml#pg0", "c001.xhtml#b2"]


def test_numbers_outside_the_index_stay():
    blocks = [Paragraph(page_mark(0, "10") + "In 10, 11 years.", page=0)]

    assert list(link_index(blocks)) == blocks

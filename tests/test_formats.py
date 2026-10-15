import re
import shutil
import zipfile

import pymupdf
import pytest

from pdf_worker import pdf_export
from pdf_worker.cli import main
from pdf_worker.convert import convert_pdf, default_output_path

BODY = 11
NOTE = 8
FULL = [
    "The quick brown fox jumps over the lazy dog and keeps running far",
    "away across the green fields until the evening light finally fades",
    "into a calm and quiet night where every sound seems to have gone.",
]
HAS_PANDOC = bool(shutil.which("pandoc") or shutil.which("/opt/homebrew/bin/pandoc"))


def _book(make_layout_pdf):
    marker_x = 72 + pymupdf.get_text_length("A claim", fontsize=BODY)
    pages = [
        [
            (72, 80, "Chapter One", 18),
            (72, 120, "A claim", BODY),
            (marker_x + 0.5, 115, "1", 7),
            *[(72, 150 + 14 * i, t, BODY) for i, t in enumerate(FULL * 2)],
            (72, 760, "1 The footnote text.", NOTE),
        ],
        [(72, 80, "Chapter Two", 18), *[(72, 120 + 14 * i, t, BODY) for i, t in enumerate(FULL)]],
    ]
    return make_layout_pdf(pages, name="book.pdf")


def test_html_is_one_page_with_linked_notes(make_layout_pdf, tmp_path):
    out = tmp_path / "book.html"

    convert_pdf(_book(make_layout_pdf), out, "html")

    html = out.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert '<nav class="contents"' in html and "Chapter Two" in html
    ref = re.search(r'<a class="noteref" id="(r\d+)" href="(#n\d+)"', html)
    assert ref, "footnote reference links within the page"
    note_id = ref.group(2)[1:]
    assert f'id="{note_id}"' in html and f'href="#{ref.group(1)}"' in html
    assert ".xhtml" not in html  # no links to EPUB files left
    assert "The footnote text." in html


def test_clean_text_has_notes_at_the_end(make_layout_pdf, tmp_path):
    out = tmp_path / "book.txt"

    convert_pdf(_book(make_layout_pdf), out, "txt")

    text = out.read_text(encoding="utf-8")
    assert "A claim[1]" in text
    assert text.rstrip().endswith("[1] The footnote text.")
    assert "\nChapter Two\n" in text
    assert "\f" not in text


def test_reflowed_pdf_has_text_and_links(make_layout_pdf, tmp_path):
    out = tmp_path / "out.pdf"

    report = convert_pdf(_book(make_layout_pdf), out, "pdf")

    with pymupdf.open(out) as doc:
        text = "".join(page.get_text() for page in doc)
        internal = [link for page in doc for link in page.get_links() if link["kind"] == 1]
        assert doc.metadata["title"] == report.metadata.title
    assert "Chapter Two" in text and "The footnote text." in text
    assert internal  # contents and note links work in the PDF


def test_reflowed_pdf_puts_footnotes_at_the_foot_of_their_page(make_layout_pdf, tmp_path):
    out = tmp_path / "out.pdf"

    convert_pdf(_book(make_layout_pdf), out, "pdf")

    with pymupdf.open(out) as doc:
        texts = [page.get_text() for page in doc]
        page_no = next(i for i, t in enumerate(texts) if "A claim" in t)
        page = doc[page_no]
        note = page.search_for("The footnote text.")[0]
        body = [b for b in page.get_text("blocks") if "footnote" not in b[4]]
        goto = [link for link in page.get_links() if link["kind"] == pymupdf.LINK_GOTO]
    assert max(b[3] for b in body) < note.y0  # under the text, on the page that refers to it
    assert sum("The footnote text." in t for t in texts) == 1  # not repeated at the end
    assert not any(t.strip().startswith("Notes") for t in texts)
    to_note = [link for link in goto if link["from"].y0 < note.y0 <= link["to"].y + 1]
    back = [link for link in goto if link["from"].y0 >= note.y0 - 1]
    assert to_note and back  # reference -> note and back
    assert "↩" not in "".join(texts)  # a note under its reference needs no arrow


def test_reflowed_pdf_notes_at_the_end_link_back_with_an_arrow(make_layout_pdf, tmp_path):
    out = tmp_path / "out.pdf"

    convert_pdf(_book(make_layout_pdf), out, "pdf", notes_at="end")

    with pymupdf.open(out) as doc:
        ref_page = next(p.number for p in doc if "A claim" in p.get_text())
        page = next(p for p in doc if "The footnote text." in p.get_text())
        arrow = page.search_for("↩")
        back = [link["page"] for link in page.get_links() if link["from"].intersects(arrow[0])]
    assert back == [ref_page]


def test_a_reference_too_low_for_its_note_moves_to_the_next_page():
    bottom = pdf_export.FRAME.y1
    notes = {"n1": ("<p>a</p>", 30.0), "n2": ("<p>b</p>", 30.0)}
    high = pymupdf.Rect(60, 100, 60, 112)
    low = pymupdf.Rect(60, bottom - 40, 60, bottom - 28)  # its note would cover it

    room = pdf_export._room_needed([(0, "n1", high), (0, "n2", low)], notes)

    # Room for note 1, and the text ends above the line with reference 2.
    assert room == {0: bottom - low.y0 + 0.5}
    assert room[0] >= pdf_export._RULE + 30


@pytest.mark.skipif(not HAS_PANDOC, reason="Pandoc not installed")
def test_docx_has_word_footnotes(make_layout_pdf, tmp_path):
    out = tmp_path / "book.docx"

    convert_pdf(_book(make_layout_pdf), out, "docx")

    with zipfile.ZipFile(out) as zf:
        notes = zf.read("word/footnotes.xml").decode()
        document = zf.read("word/document.xml").decode()
    assert "The footnote text." in notes
    assert "Chapter Two" in document
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".book.docx")]


def test_default_paths_never_overwrite_the_input(tmp_path):
    pdf = tmp_path / "book.pdf"
    assert default_output_path(pdf, "pdf").name == "book.reflowed.pdf"
    assert default_output_path(pdf, "txt").name == "book.clean.txt"
    assert default_output_path(pdf, "docx").name == "book.docx"


def test_cli_picks_format_from_extension(make_layout_pdf, tmp_path, capsys):
    pdf = _book(make_layout_pdf)

    assert main(["convert", str(pdf), "-o", str(tmp_path / "book.html")]) == 0

    assert "(html)" in capsys.readouterr().out

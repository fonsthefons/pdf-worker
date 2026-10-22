from pathlib import Path

import pymupdf
import pytest

from pdf_worker.errors import PdfOpenError
from pdf_worker.layout import _with_text, page_lines
from pdf_worker.text_extraction import (
    default_output_path,
    extract_text_to_file,
    iter_page_texts,
)


def test_word_gaps_without_a_space_character_become_spaces():
    # As in the Greek sample PDF: "καὶ" and "ἦλθεν" 4.25 pt apart, no space glyph.
    def char(c, x0, x1):
        return {"c": c, "bbox": (x0, 0, x1, 12)}

    first = {
        "size": 12.0,
        "chars": [
            char("κ", 142.38, 148.21),
            char("α", 148.21, 153.88),
            char("ὶ", 153.88, 156.95),
            char("ἦ", 161.20, 166.98),
            char("λ", 166.98, 172.5),  # kerned slightly: still one word
            char(" ", 172.5, 176.75),
            char("τ", 176.75, 182.0),
        ],
    }
    # The next word in another span (another subset of the same font).
    second = {"size": 12.0, "chars": [char("Ἰ", 186.3, 191.9), char("ο", 191.9, 196.8)]}

    spans = _with_text([first, second])

    assert [span["text"] for span in spans] == ["καὶ ἦλ τ", " Ἰο"]
    assert "chars" not in first


def test_typeset_ligatures_come_back_as_letters():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="F0", fontbuffer=pymupdf.Font("notos").buffer)
    page.insert_text((72, 72), "ﬁgura ﬂor eﬀecto", fontname="F0")

    text = "".join(span["text"] for line in page_lines(page) for span in line.spans)

    assert text == "figura flor effecto"


def test_iter_page_texts_yields_each_page_in_order(make_pdf):
    pdf = make_pdf(["first page", "second page", "third page"])

    pages = list(iter_page_texts(pdf))

    assert [p.number for p in pages] == [1, 2, 3]
    assert [p.text.strip() for p in pages] == ["first page", "second page", "third page"]


def test_extract_writes_pages_joined_by_separator(make_pdf, tmp_path):
    pdf = make_pdf(["alpha", "beta"])
    out = tmp_path / "out.txt"

    report = extract_text_to_file(pdf, out, page_separator="\n---\n")

    content = out.read_text(encoding="utf-8")
    assert [chunk.strip() for chunk in content.split("\n---\n")] == ["alpha", "beta"]
    assert report.page_count == 2
    assert report.output_path == out


def test_extract_uses_form_feed_between_pages_by_default(make_pdf, tmp_path):
    pdf = make_pdf(["one", "two", "three"])
    out = tmp_path / "out.txt"

    extract_text_to_file(pdf, out)

    assert out.read_text(encoding="utf-8").count("\f") == 2


def test_extract_preserves_non_ascii_text(make_pdf, tmp_path):
    pdf = make_pdf(["Crítica de la razón"])
    out = tmp_path / "out.txt"

    extract_text_to_file(pdf, out)

    assert "Crítica de la razón" in out.read_text(encoding="utf-8")


def test_extract_reports_pages_without_text(make_pdf, tmp_path):
    pdf = make_pdf(["has text", "", "more text", ""])

    report = extract_text_to_file(pdf, tmp_path / "out.txt")

    assert report.empty_pages == [2, 4]


def test_extract_creates_missing_output_directories(make_pdf, tmp_path):
    pdf = make_pdf(["hello"])
    out = tmp_path / "nested" / "dir" / "out.txt"

    extract_text_to_file(pdf, out)

    assert out.is_file()


def test_missing_input_raises_and_leaves_no_output(tmp_path):
    out = tmp_path / "out.txt"

    with pytest.raises(PdfOpenError, match="not found"):
        extract_text_to_file(tmp_path / "missing.pdf", out)

    assert list(tmp_path.iterdir()) == []


def test_non_pdf_input_raises(tmp_path):
    bogus = tmp_path / "bogus.pdf"
    bogus.write_text("this is not a pdf")

    with pytest.raises(PdfOpenError):
        extract_text_to_file(bogus, tmp_path / "out.txt")


def test_default_output_path_swaps_extension():
    assert default_output_path(Path("dir/book.pdf")) == Path("dir/book.txt")

from pathlib import Path

import pytest

from pdf_worker.errors import PdfOpenError
from pdf_worker.text_extraction import (
    default_output_path,
    extract_text_to_file,
    iter_page_texts,
)


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

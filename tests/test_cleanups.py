from pdf_worker.book_metadata import title_from_file
from pdf_worker.convert import convert_pdf
from pdf_worker.layout import _cluster_sizes

BODY = 11
LINE = 15
FILLER = [
    "The quick brown fox jumps over the lazy dog and keeps running far",
    "away across the green fields until the evening light finally fades",
    "into a calm and quiet night where every sound seems to have gone.",
]


def _md(make_layout_pdf, tmp_path, pages):
    out = tmp_path / "book.md"
    report = convert_pdf(make_layout_pdf(pages), out, "md")
    return out.read_text(encoding="utf-8"), report


def test_printed_contents_without_links_is_dropped(make_layout_pdf, tmp_path):
    contents = [(72, 80, "Contents", 18)]
    for i, (title, page) in enumerate(
        [("Chapter One", 1), ("Chapter Two", 9), ("Chapter Three", 17), ("Notes", 30),
         ("Index", 41), ("Bibliography", 50)]
    ):  # fmt: skip
        contents.append((72, 120 + LINE * i, f"{title} {'.' * 30} {page}", BODY))
    chapter = [(72, 80, "Chapter One", 18)]
    chapter += [(72, 120 + LINE * i, t, BODY) for i, t in enumerate(FILLER * 3)]

    text, _ = _md(make_layout_pdf, tmp_path, [contents, chapter])

    assert "Bibliography" not in text
    assert "....." not in text
    assert text.count("Chapter One") == 1  # the real heading stays
    assert "quick brown fox" in text


def test_heading_sizes_jittering_by_ocr_cluster_into_one_level():
    # One printed heading size, read by OCR as 13.8 ... 14.4; and a smaller one.
    sizes = {14.4: 30, 14.1: 120, 13.8: 40, 12.0: 80}

    assert _cluster_sizes(sizes) == [14.1, 12.0]


def test_large_print_passage_is_not_a_heading(make_layout_pdf, tmp_path):
    page = [(72, 120 + LINE * i, t, BODY) for i, t in enumerate(FILLER * 4)]
    page += [(72, 400 + 22 * i, t, 16) for i, t in enumerate(FILLER + FILLER[:2])]

    text, report = _md(make_layout_pdf, tmp_path, [page])

    assert report.stats.headings == 0
    assert "#" not in text.split("---", 2)[2]


def test_title_from_ocr_copy_drops_suffix(tmp_path):
    assert title_from_file(tmp_path / "My_Book.ocr.pdf") == "My Book"

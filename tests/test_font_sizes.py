from pdf_worker.document import open_pdf
from pdf_worker.font_sizes import misreports, same_leading_sizes
from pdf_worker.layout import Line


def _line(baseline: float, size: float, text: str = "una línea de texto") -> Line:
    span = {"text": text, "flags": 0, "origin": (60.0, baseline), "size": size}
    return Line(spans=(span,), size=size, bbox=(60.0, baseline - size, 330.0, baseline + 3))


def test_lines_set_with_one_leading_take_its_size_and_a_heading_keeps_its_own():
    lines = [
        _line(60, 13.0, "D) MATEMÁTICA"),  # alone: the next line is 40 pt down
        _line(100, 7.9),  # the same print, reported in another font's scale
        _line(114, 9.95),
        _line(128, 9.95),
    ]

    out = same_leading_sizes(lines, {14.0: 9.8})

    assert [line.size for line in out] == [13.0, 9.8, 9.8, 9.8]


def test_a_book_with_a_few_fonts_reports_its_sizes(make_pdf):
    with open_pdf(make_pdf(["una línea\notra línea", "y otra más"])) as doc:
        assert not misreports(doc)

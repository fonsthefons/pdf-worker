"""``convert`` following a book's marks (docs/marks-plan.md, Phase 2)."""

import pymupdf
import pytest
from test_endnotes import _book as _chapter_notes_book

from pdf_worker import follow_marks, marks
from pdf_worker.convert import convert_pdf
from pdf_worker.layout import page_lines
from pdf_worker.marks import Mark

BODY = 12
TEXT = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod"


def _body(y=130, lines=14):
    return [(72, y + 15 * k, TEXT, BODY) for k in range(lines)]


def _rect(box, pad=1.0):
    x0, y0, x1, y1 = box
    return [[x0 - pad, y0 - pad], [x1 + pad, y0 - pad], [x1 + pad, y1 + pad], [x0 - pad, y1 + pad]]


def _save_marks(pdf, found: list[tuple[int, str, str]], notes=None) -> None:
    """A marks file next to ``pdf``: a style mark per (page, kind, start of its line)."""
    book = marks.new_marks(pdf)
    book.settings.notes = notes
    with pymupdf.open(pdf) as doc:
        for k, (page, kind, start) in enumerate(found, start=1):
            line = next(ln for ln in page_lines(doc[page - 1]) if ln.text.startswith(start))
            book.marks.append(Mark(f"m{k}", page, kind, _rect(line.bbox), [line.text]))
    marks.save(marks.default_marks_path(pdf), book)


def _convert(pdf, tmp_path, use_marks=True, name="book.md") -> str:
    out = tmp_path / name
    convert_pdf(pdf, out, "md", title="t", author="a", cover=False, marks=use_marks)
    return out.read_text(encoding="utf-8")


def test_a_footnote_the_rules_miss_is_found_by_a_marks_style(make_layout_pdf, tmp_path):
    # Notes set nearly as big as the body: not small type, so the rules see no notes.
    note = 11.2
    notes = ["Una nota que las reglas no ven.", "Otra nota distinta.", "La tercera nota."]
    pdf = make_layout_pdf([[*_body(), (72, 720, f"1 {text}", note)] for text in notes])
    _save_marks(pdf, [(1, "footnote", "1 Una")])

    before = _convert(pdf, tmp_path, use_marks=False, name="before.md")
    after = _convert(pdf, tmp_path)

    assert "[^p2-1]" not in before and "1 Otra nota distinta." in before
    assert "[^p2-1]: Otra nota distinta." in after
    assert "[^p3-1]: La tercera nota." in after


def test_a_running_head_unlike_the_rules_ones_is_dropped(make_layout_pdf, tmp_path):
    # Bigger than the body, below the top zone, a new text on every page: the rules take
    # each for a heading.
    heads = ["LIBRO PRIMERO", "PARTE SEGUNDA", "SECCIÓN TERCERA"]
    pdf = make_layout_pdf([[(200, 100, head, 14), *_body()] for head in heads])
    _save_marks(pdf, [(1, "running-head", "LIBRO")])

    before = _convert(pdf, tmp_path, use_marks=False, name="before.md")
    after = _convert(pdf, tmp_path)

    assert "PARTE SEGUNDA" in before
    assert not any(head in after for head in heads)
    assert TEXT in after


def test_notes_printed_on_the_page_turn_off_the_chapter_notes(make_layout_pdf, tmp_path):
    pdf = _chapter_notes_book(make_layout_pdf)
    _save_marks(pdf, [], notes="page")

    before = _convert(pdf, tmp_path, use_marks=False, name="before.md")
    after = _convert(pdf, tmp_path)

    assert "[^c1-2]" in before
    assert "[^c1-" not in after and "[^c2-" not in after


def test_marks_for_another_pdf_are_an_error(make_layout_pdf, tmp_path):
    pdf = make_layout_pdf([_body()])
    other = make_layout_pdf([_body(), _body()], name="other.pdf")
    marks.save(marks.default_marks_path(pdf), marks.new_marks(other))

    with pytest.raises(marks.MarksError):
        _convert(pdf, tmp_path)
    assert TEXT in _convert(pdf, tmp_path, use_marks=False)


def test_a_scan_block_takes_the_kind_most_of_its_lines_have(make_pdf):
    pdf = make_pdf(["", ""])
    row = {
        "width": 595,  # the page's own size: boxes in points
        "height": 842,
        "blocks": [
            {"label": "header", "bbox": [200, 40, 400, 55], "text": "FILEBO"},
            {"label": "text", "bbox": [72, 100, 540, 160], "text": "uno\ndos\ntres\ncuatro"},
            {"label": "text", "bbox": [72, 700, 540, 720], "text": "1 Una nota."},
        ],
    }
    rows = [dict(row, page=0), dict(row, page=1)]
    book = marks.new_marks(pdf)
    # Shapes over the first page's head and note blocks, and over two of the four body lines.
    book.marks = [
        Mark("m1", 1, "running-head", _rect((200, 40, 400, 55))),
        Mark("m2", 1, "footnote", _rect((72, 700, 540, 720))),
        Mark("m3", 1, "ignore", _rect((72, 100, 540, 128)), scope="here"),
    ]
    with pymupdf.open(pdf) as doc:
        kinds = follow_marks.paddle_kinds(doc, rows, book)

    assert kinds[0] == {0: "running-head", 2: "footnote"}  # two of four lines: not most
    # Matched by the first page's examples: on a scan, only a kind known by its place.
    assert kinds[1] == {0: "running-head"}

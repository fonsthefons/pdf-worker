import json
import threading
import urllib.request

import pymupdf
import pytest

from pdf_worker import marking, marks, style_sheet
from pdf_worker.layout import page_lines
from pdf_worker.marking import ViewLine
from pdf_worker.marks import Mark
from pdf_worker.style_sheet import PageLines

BODY = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incid"


def _centred(text: str, size: float, font: str = "helv") -> float:
    return 306 - pymupdf.get_text_length(text, fontname=font, fontsize=size) / 2


def _book(path, headings) -> None:
    """Pages with a running head, a bold heading (``headings``: page -> (text, x) or
    None), ten body lines (the first with a note number), a footnote and a page number."""
    doc = pymupdf.open()
    for number in range(1, len(headings) + 1):
        page = doc.new_page()
        page.insert_text(
            (_centred("HISTORIA DE LA FILOSOFÍA", 9), 40), "HISTORIA DE LA FILOSOFÍA", fontsize=9
        )
        heading = headings[number - 1]
        if heading:
            text, x = heading
            page.insert_text((x, 120), text, fontsize=16, fontname="hebo")
        end = 72 + pymupdf.get_text_length(BODY, fontsize=11)
        for k in range(10):
            page.insert_text((72, 160 + 14 * k), BODY, fontsize=11)
            if not k:  # a note number glued to the first line's last word
                page.insert_text((end, 156), "1", fontsize=7)
                page.insert_text((end + 4, 160), " sigue", fontsize=11)
        page.insert_text((72, 700), "1 Una nota al pie de la página.", fontsize=8)
        page.insert_text((_centred(str(number), 9), 760), str(number), fontsize=9)
        if number == 3:
            page.insert_text((72, 60), "7", fontsize=9)  # a number at the top: no page number
            page.insert_text((72, 400), "Una cita en otro tamaño", fontsize=14)
    doc.save(path)
    doc.close()


def _rect(box, pad=1.0):
    x0, y0, x1, y1 = box
    return [(x0 - pad, y0 - pad), (x1 + pad, y0 - pad), (x1 + pad, y1 + pad), (x0 - pad, y1 + pad)]


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setenv("PDF_WORKER_PADDLE_CACHE", str(tmp_path / "paddle"))
    path = tmp_path / "book.pdf"
    title = "CAPÍTULO I"
    _book(
        path,
        [
            (title, _centred(title, 16, "hebo")),
            None,
            (title, _centred(title, 16, "hebo")),
            (title, 72),
        ],
    )
    doc = pymupdf.open(path)
    opened = marking.Book(doc, path, marks.default_marks_path(path))
    yield opened
    doc.close()


def _line(book, page, start):
    """The line whose text is ``start``, else the first that starts with it."""
    texts = [line["text"].strip() for line in book.view(page)["lines"]]
    if start in texts:
        return texts.index(start)
    return next(i for i, text in enumerate(texts) if text.startswith(start))


def _mark(book, id, page, kind, starts, level=None, scope="style"):
    lines = book.view(page)["lines"]
    boxes = [lines[_line(book, page, s)]["bbox"] for s in starts]
    box = (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )
    return Mark(id, page, kind, _rect(box), [], level, scope)


def _style_marks(book) -> marks.Marks:
    found = marks.Marks(book.info)
    found.marks = [
        _mark(book, "m1", 1, "heading", ["CAPÍTULO"], level=1),
        _mark(book, "m2", 1, "body", ["Lorem"]),
        _mark(book, "m3", 1, "footnote", ["1 Una"]),
        _mark(book, "m4", 1, "running-head", ["HISTORIA"]),
        _mark(book, "m5", 2, "page-number", ["2"]),
    ]
    end = 72 + pymupdf.get_text_length(BODY, fontsize=11)
    found.marks.append(
        Mark("m6", 1, "note-ref", [(end - 1, 148), (end + 5, 148), (end + 5, 157), (end - 1, 157)])
    )
    return found


def _labels(book, found):
    book.marks = found
    return book.classified()


def test_lines_on_unmarked_pages_take_the_kind_whose_examples_they_agree_with(book):
    result = _labels(book, _style_marks(book))
    page3 = result.labels[2]

    def label(start):
        return page3[_line(book, 3, start)]

    assert (label("CAPÍTULO").kind, label("CAPÍTULO").level, label("CAPÍTULO").sure) == (
        "heading",
        1,
        "matched",
    )
    assert (label("Lorem").kind, label("Lorem").sure) == ("body", "matched")
    assert label("1 Una").kind == "footnote" and label("HISTORIA").kind == "running-head"
    assert label("3").kind == "page-number"
    # A number at the top is not a page number marked at the foot; another size is no kind.
    assert label("7").sure == "rules" and label("Una cita").sure == "rules"
    # The marked lines are "marked"; the note number after the first line is found.
    assert result.labels[0][_line(book, 1, "CAPÍTULO")].sure == "marked"
    assert len(result.refs[2]) == 1 and result.refs[2][0][0] > 480


def test_a_heading_placed_like_no_example_is_doubtful(book):
    result = _labels(book, _style_marks(book))
    flush = result.labels[3][_line(book, 4, "CAPÍTULO")]
    assert (flush.kind, flush.sure, flush.odd) == ("heading", "matched", True)
    assert not result.labels[2][_line(book, 3, "CAPÍTULO")].odd
    assert result.doubtful(4) and not result.doubtful(3)  # pages are 1-based
    assert result.next_doubtful(1) == 4 and result.next_doubtful(4) is None


def test_two_kinds_agreeing_are_a_conflict_and_a_here_mark_teaches_nothing(book):
    found = _style_marks(book)
    found.marks.append(_mark(book, "m7", 2, "endnote", ["1 Una"]))
    found.marks.append(_mark(book, "m8", 3, "ignore", ["Lorem"], scope="here"))
    result = _labels(book, found)

    footnote = result.labels[2][_line(book, 3, "1 Una")]
    assert footnote.sure == "conflict" and set(footnote.agree) == {"footnote", "endnote"}
    assert result.labels[1][_line(book, 2, "1 Una")].kind == "endnote"  # marked
    assert result.labels[2][_line(book, 3, "Lorem")].kind == "ignore"
    assert result.labels[3][_line(book, 4, "Lorem")].kind == "body"
    assert result.next_doubtful(1) == 3


def test_features_of_a_line():
    lines = [
        ViewLine((72, 100, 540, 112), BODY),
        ViewLine((250, 60, 360, 80), "CAPÍTULO IV"),
        ViewLine((20, 200, 30, 212), "b"),
    ]
    measures = style_sheet.measure([PageLines(612, 792, lines), PageLines(612, 792, lines[:1] * 4)])
    body, heading, margin = measures.features[0]
    assert heading.numbering == "division" and heading.caps and heading.align == "centre"
    assert body.numbering == "none" and body.caps is False and body.align == "left"
    assert margin.align == "margin" and margin.caps is None and heading.font is None
    assert heading.size > 1.5 and 0.9 < body.size < 1.1
    assert 0.07 < heading.top < 0.08 and style_sheet.numbering("IV. Título") == "roman"
    assert style_sheet.numbering("a) uno") == "letter" and style_sheet.numbering("12") == "arabic"
    assert style_sheet.numbering("a).- Primer estadio") == "letter"
    assert style_sheet.numbering("I believe") == "none" and style_sheet.numbering("II") == "roman"
    assert style_sheet.numbering("1Hegel, Hist.") == "arabic"


def test_of_two_kinds_that_agree_the_nearer_takes_the_line():
    def page():
        lines = [ViewLine((72, 100 + 14 * k, 540, 112 + 14 * k), BODY) for k in range(10)]
        lines.append(ViewLine((256, 300, 356, 312), "Nota del editor"))
        lines.append(ViewLine((72, 330, 540, 342), "Capítulo uno ....................... 5"))
        return PageLines(612, 792, lines)

    pages = [page(), page()]
    found = marks.Marks(marks.PdfInfo("scan.pdf", 2, "0"))
    found.marks = [
        Mark("m1", 1, "body", _rect(pages[0].lines[0].bbox)),
        Mark("m2", 1, "contents", _rect(pages[0].lines[10].bbox)),
    ]
    labels = style_sheet.classify(pages, found).labels[1]

    assert [label.kind for label in labels[:10]] == ["body"] * 10
    assert (labels[10].kind, labels[10].sure) == ("contents", "matched")
    assert labels[11].sure == "rules"  # dot leaders: like neither example


def test_a_line_without_letters_is_never_a_matched_heading(make_layout_pdf):
    # Headings in body type (as Ratzinger's): a paragraph's last line "40,6-8)." agrees
    # with them in font, size and numbering, its capitals unknown.
    body = [(72, 130 + 15 * k, BODY, 12) for k in range(12)]
    pdf = make_layout_pdf(
        [
            [(72, 100, "1. DUDA Y FE", 12), *body],
            [(72, 100, "2. EL DILEMA", 12), *body, (72, 315, "40,6-8).", 12)],
        ]
    )
    with pymupdf.open(pdf) as doc:
        pages = [PageLines(p.rect.width, p.rect.height, page_lines(p)) for p in doc]
    found = marks.Marks(marks.PdfInfo("layout.pdf", 2, "0"))
    found.marks = [Mark("m1", 1, "heading", _rect(pages[0].lines[0].bbox), level=3)]
    labels = style_sheet.classify(pages, found).labels[1]

    assert (labels[0].kind, labels[0].level) == ("heading", 3)
    assert pages[1].lines[-1].text.startswith("40,6") and labels[-1].kind != "heading"


def test_a_scan_place_mark_taking_no_line_finds_lines_in_the_margin():
    def page(*extra):
        lines = [ViewLine((72, 100 + 14 * k, 540, 112 + 14 * k), BODY) for k in range(10)]
        return PageLines(612, 792, lines + list(extra))

    pages = [
        page(),
        page(ViewLine((20, 200, 30, 212), "b")),
        page(ViewLine((560, 300, 575, 312), "12")),
    ]
    found = marks.Marks(marks.PdfInfo("scan.pdf", 3, "0"))
    found.marks = [Mark("m1", 1, "margin-ref", _rect((20, 150, 30, 162)))]
    result = style_sheet.classify(pages, found)

    assert result.labels[1][10].kind == "margin-ref" and result.labels[2][10].kind == "margin-ref"
    assert result.labels[1][0].sure == "rules"


def test_the_marking_page_serves_the_kinds_and_the_next_doubtful_page(book):
    marks.save(book.path, _style_marks(book))
    book.marks = marks.load(book.path)
    server = marking.serve(book)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{url}/labels/3.json", timeout=10) as reply:
            labels = json.loads(reply.read())
        line = labels["lines"][_line(book, 3, "CAPÍTULO")]
        assert (line["kind"], line["level"], line["sure"]) == ("heading", 1, "matched")
        assert len(labels["refs"]) == 1
        with urllib.request.urlopen(f"{url}/doubtful.json?after=1", timeout=10) as reply:
            assert json.loads(reply.read()) == {"page": 4}
    finally:
        server.shutdown()
        server.server_close()

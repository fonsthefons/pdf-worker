"""``convert`` following a book's marks (docs/marks-plan.md, Phase 2)."""

import pymupdf
import pytest
from test_endnotes import _book as _chapter_notes_book

from pdf_worker import follow_marks, marks
from pdf_worker.convert import convert_pdf
from pdf_worker.layout import page_lines
from pdf_worker.marks import Mark
from pdf_worker.structure import Heading, Paragraph

BODY = 12
TEXT = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod"


def _body(y=130, lines=14):
    return [(72, y + 15 * k, TEXT, BODY) for k in range(lines)]


def _rect(box, pad=1.0):
    x0, y0, x1, y1 = box
    return [[x0 - pad, y0 - pad], [x1 + pad, y0 - pad], [x1 + pad, y1 + pad], [x0 - pad, y1 + pad]]


def _save_marks(pdf, found: list[tuple], notes=None) -> None:
    """A marks file next to ``pdf``: a style mark per (page, kind, start of its line[,
    heading level])."""
    book = marks.new_marks(pdf)
    book.settings.notes = notes
    with pymupdf.open(pdf) as doc:
        for k, (page, kind, start, *level) in enumerate(found, start=1):
            line = next(ln for ln in page_lines(doc[page - 1]) if ln.text.startswith(start))
            mark = Mark(f"m{k}", page, kind, _rect(line.bbox), [line.text], *level)
            book.marks.append(mark)
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


def _headings(markdown: str) -> list[str]:
    return [line for line in markdown.splitlines() if line.startswith("#")]


def test_a_heading_in_body_type_is_found_by_a_marks_style_at_its_level(make_layout_pdf, tmp_path):
    heads = ["LA CUNA DEL PENSAMIENTO", "LOS PIONEROS JONIOS"]
    pdf = make_layout_pdf([[(72, 100, head, BODY), *_body()] for head in heads])
    _save_marks(pdf, [(1, "heading", "LA CUNA", 2)])

    before = _convert(pdf, tmp_path, use_marks=False, name="before.md")
    after = _convert(pdf, tmp_path)

    assert not any("LOS PIONEROS" in h for h in _headings(before))
    assert "## LOS PIONEROS JONIOS" in _headings(after)


def test_a_line_marked_body_is_never_a_heading(make_layout_pdf, tmp_path):
    pdf = make_layout_pdf([[(72, 100, "Una cita en letra grande", 16), *_body()]])
    _save_marks(pdf, [(1, "body", "Una cita")])

    before = _convert(pdf, tmp_path, use_marks=False, name="before.md")
    after = _convert(pdf, tmp_path)

    assert any("Una cita en letra grande" in h for h in _headings(before))
    assert "Una cita en letra grande" in after and not _headings(after)


def test_levels_set_in_one_size_place_a_rules_heading_at_the_commonest():
    lines = [("heading 1", 14.0), *[("heading 3", 12.0)] * 5, ("heading 2", 12.0), ("body", 12.0)]
    place = follow_marks._placer(lines, tol=0.6)

    assert (place(12.0), place(12.2), place(16.0)) == (3, 3, 1)
    assert follow_marks._placer([("body", 12.0)], tol=0.6) is None


def test_a_rules_headings_level_is_placed_among_the_marked_levels_by_size(
    make_layout_pdf, tmp_path
):
    pdf = make_layout_pdf(
        [
            [(72, 100, "PRIMERA PARTE", 20), *_body()],
            [(72, 100, "TALES DE MILETO", 14), *_body()],
            [(72, 100, "Una sección aparte", 16), *_body()],
        ]
    )
    _save_marks(pdf, [(1, "heading", "PRIMERA", 1), (2, "heading", "TALES", 3)])

    before = _convert(pdf, tmp_path, use_marks=False, name="before.md")
    after = _convert(pdf, tmp_path)

    assert "## Una sección aparte" in _headings(before)  # sizes 20, 16, 14
    assert _headings(after) == ["# PRIMERA PARTE", "### TALES DE MILETO", "### Una sección aparte"]


def test_a_headings_number_and_title_stay_one_heading(make_layout_pdf, tmp_path):
    pages = [("CAPÍTULO II", "LA CUNA DEL PENSAMIENTO"), ("CAPÍTULO III", "LOS PIONEROS JONIOS")]
    pdf = make_layout_pdf(
        [[(72, 100, number, 14), (72, 125, title, 18), *_body(y=165)] for number, title in pages]
    )
    # Both lines one heading of level 2 (two sizes, as Copleston's are).
    _save_marks(pdf, [(1, "heading", "CAPÍTULO", 2), (1, "heading", "LA CUNA", 2)])

    before = _convert(pdf, tmp_path, use_marks=False, name="before.md")
    after = _convert(pdf, tmp_path)

    assert len(_headings(before)) == 4
    # Page 2's lines matched by page 1's examples.
    assert _headings(after) == [
        "## CAPÍTULO II LA CUNA DEL PENSAMIENTO",
        "## CAPÍTULO III LOS PIONEROS JONIOS",
    ]


def test_a_scans_heading_blocks_follow_the_marks(tmp_path):
    from test_paddle_book import INTRO, _book, _row

    rows = [
        _row(
            0,
            ("text", [144, 100, 1046, 400], INTRO),
            ("paragraph_title", [400, 500, 800, 560], "PARTE I"),
            ("paragraph_title", [300, 580, 900, 640], "LA ILUSTRACIÓN FRANCESA"),
            ("paragraph_title", [400, 660, 800, 690], "Capítulo II"),
            ("paragraph_title", [144, 700, 1046, 760], "Una línea en letra grande"),
            ("text", [144, 800, 1046, 1200], INTRO),
        )
    ]
    # One level-1 heading over two blocks; a level-2 one of its own (the person gave it
    # its own level); a body line Paddle took for a title.
    kinds = {0: {1: "heading 1", 2: "heading 1", 3: "heading 2", 4: "body"}}

    blocks = _book(tmp_path, rows, kinds=kinds)

    headings = [(b.text, b.level) for b in blocks if isinstance(b, Heading)]
    assert headings == [("PARTE I LA ILUSTRACIÓN FRANCESA", 1), ("Capítulo II", 2)]
    assert any(b.text == "Una línea en letra grande" for b in blocks if isinstance(b, Paragraph))


def test_a_scans_title_blocks_take_the_marked_levels(make_pdf):
    pdf = make_pdf(["", ""])
    body = "\n".join([TEXT] * 4)
    rows = [
        {
            "page": 0,
            "width": 595,
            "height": 842,
            "blocks": [
                {"label": "doc_title", "bbox": [250, 100, 350, 130], "text": "FILEBO"},
                {"label": "header", "bbox": [200, 140, 400, 155], "text": "SÓCRATES, PROTARCO"},
                {"label": "text", "bbox": [72, 200, 540, 260], "text": body},
            ],
        },
        {
            "page": 1,
            "width": 595,
            "height": 842,
            "blocks": [
                # Unmarked, unlike the examples (not in capitals): Paddle's level 2, but
                # sized like the marked level 1.
                {
                    "label": "paragraph_title",
                    "bbox": [200, 95, 400, 135],
                    "text": "Timeo y Critias",
                },
                {"label": "text", "bbox": [72, 200, 540, 260], "text": body},
            ],
        },
    ]
    book = marks.new_marks(pdf)
    book.marks = [
        Mark("m1", 1, "heading", _rect((250, 100, 350, 130)), level=1),
        Mark("m2", 1, "heading", _rect((200, 140, 400, 155)), level=2),
    ]
    with pymupdf.open(pdf) as doc:
        kinds = follow_marks.paddle_kinds(doc, rows, book)

    assert kinds[0] == {0: "heading 1", 1: "heading 2"}
    assert kinds[1] == {0: "level 1"}  # if today's rules keep it as a heading


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

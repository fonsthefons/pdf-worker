"""Margin references (Stephanus "22", "b", "c" ...) and running heads ("TIMEO 163")."""

import pymupdf

from pdf_worker import pdf_export
from pdf_worker.convert import convert_pdf
from pdf_worker.epub import write_epub
from pdf_worker.footnotes import BodyLine
from pdf_worker.inline import MarginRef, margin_ref, pieces, plain
from pdf_worker.layout import DocumentProfile, Line
from pdf_worker.margin_estimates import estimate_margin_refs
from pdf_worker.margin_refs import (
    PageScan,
    ScanMark,
    ScanWord,
    assign_labels,
    mark_paddle_blocks,
    next_label,
    outer_marks,
)
from pdf_worker.output import Metadata
from pdf_worker.structure import Heading, Note, Paragraph, _State
from pdf_worker.text_export import write_text

BODY = 11
FULL = [
    "The quick brown fox jumps over the lazy dog and keeps running far",
    "away across the green fields until the evening light finally fades",
    "into a calm and quiet night where every sound seems to have gone.",
]


def test_labels_follow_the_section_order_whatever_was_read():
    labels = []
    previous = None
    # As read on the sample page: "22", "b", "c", unreadable, "e", and "2" for "23".
    for reading in ["22", "b", "c", "?", "e", "2", "c", "c"]:
        previous = next_label(previous, reading)
        labels.append(previous)

    # "c" after 23a is one missed mark ("b"): believed; another "c" is a misread "d".
    assert labels == ["22a", "22b", "22c", "22d", "22e", "23a", "23c", "23d"]
    assert next_label(None, "b") == "b"  # no number yet: as printed
    assert next_label(None, "?") is None


def test_a_whole_run_of_marks_is_labelled_together():
    # Platón bad pp. 41-43: a misread "23", then a stray "e" and two pencil blots
    # among 23d and 23e; the greedy reading ran one label ahead from there on.
    pages = [41] * 3 + [42] * 5 + [43] * 4 + [44] * 2
    reads = ["22", "b", "c", "e", "d", "?", "?", "e", "24", "?", "c", "?", "e", "25"]
    labels = assign_labels(list(zip(pages, reads, strict=True)))
    assert labels[3:9] == [None, "23d", None, None, "23e", "24a"]
    assert labels[-1] == "25a" and labels[0] == "23a"
    # A heading starts a new run; one with no number read labels nothing (pencil
    # marks in an introduction).
    run = [(1, r) for r in ("66", "?", "c", "d", "e", "67", "b")]
    run += [(2, None), (3, "c"), (3, "?")]
    assert assign_labels(run) == ["66a", "66b", "66c", "66d", "66e", "67a", "67b", None, None]
    # Nor one where no page number of two digits is read where it is labelled.
    assert assign_labels([(5, "2"), (5, "?"), (5, "12"), (6, "2"), (6, "3")]) == [None] * 5
    # A long gap (an introduction) starts the next dialogue's count.
    filebo_end = [(1, r) for r in ("66", "b", "c", "d", "e", "67", "b")]
    timeo_start = [(20, r) for r in ("17", "b", "c", "d", "e", "18", "b")]
    labels = assign_labels(filebo_end + timeo_start)
    assert labels[5:9] == ["67a", "67b", "17a", "17b"]


def test_marks_on_the_spine_side_are_the_scanners_shadow():
    scan = PageScan(
        [], [ScanMark("c", 1, "left"), ScanMark("d", 5, "right"), ScanMark("a", 9, "left")]
    )
    assert [m.reading for m in outer_marks(scan, "right").marks] == ["d"]
    # No readable mark outside: nothing to go by, all stay.
    assert outer_marks(PageScan([], [ScanMark("?", 2, "right")]), "right").marks == [
        ScanMark("?", 2, "right")
    ]


def test_line_numbers_are_not_section_references():
    state = _State(DocumentProfile(body_size=BODY))
    line = Line(spans=(), size=BODY, bbox=(72, 100, 400, 111))

    numbers = state._label_margin_refs([BodyLine(margin_ref("5") + "Puer qui ridet", line)])
    sections = state._label_margin_refs([BodyLine(margin_ref("b") + "una y otra", line)])

    assert numbers[0].text == "Puer qui ridet"
    assert sections[0].text == margin_ref("b") + "una y otra"


def test_paddle_text_loses_the_marks_it_read_and_each_mark_finds_its_line():
    words = [
        *(ScanWord(w, 0, False) for w in ["honores", "y", "que,"]),
        ScanWord("22", 0, True),
        *(ScanWord(w, 1, False) for w in ["sacerdotes", "que", "muchas", "por"]),
        ScanWord("mn", 2, True),  # "c" in the margin, misread
        ScanWord("fuego", 3, False),
    ]
    scan = PageScan(words, [ScanMark("22", 0), ScanMark("c", 1)])
    # Paddle reads the "22" into the text and "c fuego" as "el fuego".
    texts = ["  honores y que, 22 sacerdotes que muchas por el fuego"]

    cleaned, marks = mark_paddle_blocks(texts, scan)

    assert cleaned == ["  honores y que, sacerdotes que muchas por fuego"]
    assert marks == [(0, 0, "22"), (0, 3, "c")]  # "honores" and "sacerdotes"


def test_a_word_past_a_column_measured_too_narrow_stays():
    # Indented lines (a list of variants) set the column's edge; prose sticks out.
    words = [
        *(ScanWord(w, 0, False) for w in ["texto", "de", "Platonis"]),
        ScanWord("Opera,", 0, True),
        ScanWord("Oxford", 1, False),
    ]
    scan = PageScan(words, [ScanMark("b", 1)])

    cleaned, _ = mark_paddle_blocks(["texto de Platonis Opera, Oxford"], scan)

    assert cleaned == ["texto de Platonis Opera, Oxford"]


def test_running_heads_leave_the_text_and_the_title_opens_the_book(make_layout_pdf, tmp_path):
    body = [(72, 120 + 14 * i, t, BODY) for i, t in enumerate(FULL * 2)]
    last = (72, 120 + 14 * len(body), "relatada, se refiere, a", BODY)
    first = (72, 120, "una desviación de los cuerpos.", BODY)
    pages = [
        [(290, 50, "TIMEO", 8), (530, 50, "163", 8), *body, last],
        [(72, 50, "164", 8), (280, 50, "DIALOGOS", 8), first, *body[1:]],
    ]
    out = tmp_path / "book.txt"

    convert_pdf(make_layout_pdf(pages), out, "txt")

    text = out.read_text(encoding="utf-8")
    assert text.count("TIMEO") == 1 and "\nTIMEO\n" in text
    assert "DIALOGOS" not in text
    assert "se refiere, a una desviación" in text  # the sentence runs on over the page


def _blocks():
    text = (
        "Solón contaba que cuando llegó allí recibió de ellos muchos "
        + margin_ref("22a")
        + "honores y que, al consultar sobre las antigüedades[^1] a los sacerdotes, "
        + " ".join(FULL * 3)
    )
    return [Heading("TIMEO", 1), Paragraph(text), Note("1", "Una nota.")]


def test_text_and_epub_show_margin_references_apart_from_footnotes(tmp_path):
    write_text(_blocks(), tmp_path / "book.txt", Metadata("Timeo"))
    stats = write_epub(_blocks(), tmp_path / "book.epub", Metadata("Timeo"))

    text = (tmp_path / "book.txt").read_text(encoding="utf-8")
    assert "muchos [22a] honores" in text and "antigüedades[1] a los" in text
    with pymupdf.open(tmp_path / "book.epub") as doc:
        html = "".join(page.get_text("html") for page in doc)
    assert stats.margin_refs == 1 and "22a" in html


def test_labels_lost_between_two_found_ones_are_estimated_evenly():
    words = [f"w{i}" for i in range(30)]
    text = margin_ref("23b") + " ".join(words[:15]) + " " + margin_ref("23e") + " ".join(words[15:])
    blocks = [
        Paragraph(margin_ref("22e") + "start"),
        Paragraph(text),
        Heading("TIMEO", 1),
        Paragraph(margin_ref("17a") + "nuevo " + margin_ref("17d") + "fin"),  # no room between
        Paragraph(margin_ref("9b") + "otro"),  # numbers going down: no anchor pair
    ]

    out = list(estimate_margin_refs(blocks))

    tokens = out[1].text.split()
    labels = [p.label for p in pieces(out[1].text) if isinstance(p, MarginRef)]
    assert labels == ["23b", "~23c", "~23d", "23e"]
    assert tokens[5].startswith(margin_ref("~23c"))  # 15 words, three shares
    assert tokens[10].startswith(margin_ref("~23d"))
    assert plain(out[1].text).split() == words
    assert out[0] == blocks[0]  # 23a: no word between 22e and 23b to put it on
    assert out[2:] == blocks[2:]


def test_estimated_labels_are_pink_in_the_reflowed_pdf(tmp_path):
    out = tmp_path / "book.pdf"
    text = margin_ref("22a") + "honores " + " ".join(FULL) + " " + margin_ref("~22b") + "fin"

    pdf_export.write_pdf([Paragraph(text)], out, Metadata("Timeo"))

    with pymupdf.open(out) as doc:
        colors = {
            span["text"]: span["color"]
            for block in doc[0].get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
        }
    assert colors["22a"] >> 16 < 0x80 < colors["~22b"] >> 16  # green, then pink


def test_reflowed_pdf_sets_margin_references_in_the_margin(tmp_path):
    out = tmp_path / "book.pdf"

    pdf_export.write_pdf(_blocks(), out, Metadata("Timeo"))

    with pymupdf.open(out) as doc:
        page = next(p for p in doc if "honores" in p.get_text())
        label = page.search_for("22a")
        word = page.search_for("honores")[0]
        lines = [plain(line) for line in page.get_text().splitlines()]
        foot = page.search_for("Una nota.")
    text_right = pdf_export.FRAME.x1 - pdf_export.FRAME.width * 0.05
    assert len(label) == 1 and label[0].x0 > text_right  # in the margin, not the text
    assert abs(label[0].y1 - word.y1) < 3  # level with its word's line
    assert not any("22a" in line and "honores" in line for line in lines)
    assert foot  # the footnote is still at the foot of the page

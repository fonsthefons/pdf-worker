"""Margin references (Stephanus "22", "b", "c" ...) and running heads ("TIMEO 163")."""

import shutil

import pymupdf
import pytest

from pdf_worker.convert import convert_pdf
from pdf_worker.epub import write_epub
from pdf_worker.footnotes import BodyLine
from pdf_worker.inline import MarginRef, margin_ref, pieces, plain
from pdf_worker.layout import DocumentProfile, Line
from pdf_worker.margin_estimates import estimate_margin_refs, recover_margin_refs
from pdf_worker.margin_refs import (
    PageScan,
    ScanMark,
    ScanWord,
    assign_labels,
    in_book,
    learn_strip,
    mark_paddle_blocks,
    next_label,
    outer_marks,
    page_column,
    scan_page,
)
from pdf_worker.ocr import tesseract_path
from pdf_worker.output import Metadata
from pdf_worker.structure import Heading, Note, Paragraph, _State
from pdf_worker.text_export import write_text
from pdf_worker.typst_export import write_pdf

BODY = 11
HAS_TESSERACT = bool(shutil.which("tesseract") or shutil.which("/opt/homebrew/bin/tesseract"))
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


def test_a_book_has_margin_references_when_they_are_on_a_fifth_of_its_pages():
    assert in_book(230, 293)  # Platón
    assert not in_book(4, 462)  # ink in the philosophy book's margins


def test_references_printed_in_the_text_become_margin_references(make_pdf, tmp_path):
    pdf = make_pdf(
        [f"{FULL[0]}\nque dios plantó [8oe] para nosotros {FULL[1]}\nnota [I7b] y (8oc] [la] otra"]
    )

    convert_pdf(pdf, tmp_path / "book.txt", "txt")

    text = (tmp_path / "book.txt").read_text(encoding="utf-8")
    # Taken as printed, even out of order: the notes cite passages ("[17b]").
    assert "plantó [80e] para" in text and "nota [17b] y [80c] [la]" in text
    assert "[80c] [la] otra" in text  # no digit: an editor's insertion, not a reference


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
    assert stats.margin_refs == 1 and "[22a]" in html  # bracketed: Kindle drops the styling


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


def test_bracketed_references_misread_between_two_found_ones_are_recovered():
    # Timeo: 18d and 19c read; 18e, 19a and 19b came out as "b8e]", "[Iga]", "[Igb]".
    blocks = [
        Paragraph(margin_ref("18d") + "y para todos. Las alianzas matrimoniales b8e] por medio"),
        Paragraph("TIM.-Nos acordamos. [Iga]"),
        Paragraph("¿lo hemos resumido [Igb] o [sic] no? Animales " + margin_ref("19c") + "fin"),
        Paragraph("por naturaleza y [˒oa] por educación " + margin_ref("20b") + "fin"),
        Paragraph(margin_ref("22a") + "Deucalión [22h] y [2 3a] dos [23bl " + margin_ref("23c")),
        Paragraph("después [Igd] nada"),  # no found label after it
    ]

    out = list(recover_margin_refs(blocks))

    labels = [p.label for b in out for p in pieces(b.text) if isinstance(p, MarginRef)]
    assert labels == [
        *("18d", "18e", "19a", "19b", "19c", "20a", "20b"),
        *("22a", "22b", "23a", "23b", "23c"),
    ]
    assert "matrimoniales " + margin_ref("18e") + "por" in out[0].text
    assert "[sic]" in out[2].text
    assert out[5] == blocks[5]


def test_margin_references_are_off_unless_asked_for():
    from pdf_worker.convert import _without_margin_refs

    blocks = [
        Heading(margin_ref("22a") + "TIMEO", 1),
        Paragraph("muchos " + margin_ref("22b") + "honores"),
    ]

    assert list(_without_margin_refs(blocks)) == [Heading("TIMEO", 1), Paragraph("muchos honores")]


def test_estimated_labels_are_pink_in_the_reflowed_pdf(tmp_path):
    out = tmp_path / "book.pdf"
    text = margin_ref("22a") + "honores " + " ".join(FULL) + " " + margin_ref("~22b") + "fin"

    write_pdf([Paragraph(text)], out, Metadata("Timeo"))

    with pymupdf.open(out) as doc:
        colors = {
            span["text"]: span["color"]
            for block in doc[0].get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
        }
    assert colors["22a"] >> 16 < 0x80 < colors["~22b"] >> 16  # green, then pink


def test_the_strip_is_learnt_from_the_marks_and_facing_pages_swap_it():
    doc = pymupdf.open()
    for _ in range(4):
        doc.new_page(width=330, height=520)
    pages = list(doc)
    column = (50.0, 280.0, 10.0)  # left, right, line height (points)
    # Two marks right of the column on a first (odd) page, one left on a second.
    strip = learn_strip(
        [
            (pages[0], (285, 100, 292, 108)),
            (pages[2], (284, 300, 296, 310)),
            (pages[1], (38, 90, 45, 98)),
        ],
        lambda page: column,
    )
    side, near, far = strip.sides[0]
    assert side == "right" and near == pytest.approx(0.15) and far == pytest.approx(1.85)
    assert strip.sides[1][0] == "left" and strip.sides[1][1:] == pytest.approx((0.25, 1.45))
    # Never closer to the text than its own ink reaches (a shape drawn into the column).
    close = learn_strip([(pages[0], (279, 100, 290, 108))], lambda page: column)
    assert close.sides[0][1] == pytest.approx(0.15)
    # Marks on one side only: the facing pages have theirs on the other side.
    one = learn_strip([(pages[0], (285, 100, 292, 108))], lambda page: column)
    assert one.sides[1] == ("left", *one.sides[0][1:])
    assert learn_strip([], lambda page: column) is None


_WORDS = [
    "la",
    "vida",
    "del",
    "alma",
    "es",
    "una",
    "cosa",
    "que",
    "nadie",
    "ignora",
    "bien",
    "pues",
    "todo",
    "lo",
]


def _scanned_book(path, pages):
    """A scan in Courier (justified by construction: 38 letters a line), each page
    ``(side, labels, ink)``: the margin labels ``[(line, label, gap in points)]`` on that
    side, and ``ink`` (a number) on the other."""
    doc = pymupdf.open()
    for index, (side, labels, ink) in enumerate(pages):
        page = doc.new_page(width=330, height=520)
        x = 60 if index % 2 == 0 else 45
        for k in range(30):
            words = (_WORDS * 3)[k % len(_WORDS) :]
            page.insert_text((x, 60 + 14 * k), " ".join(words)[:38], fontsize=10, fontname="cour")
        right = x + 6 * 38
        for k, label, gap in labels:
            lx = right + gap if side == "right" else x - gap - 5 * len(label)
            page.insert_text((lx, 60 + 14 * k), label, fontsize=9, fontname="tiro")
        ix = x - 20 if side == "right" else right + 8
        page.insert_text((ix, 60 + 14 * 14), ink, fontsize=9, fontname="tiro")
    scan = pymupdf.open()
    for page in doc:
        picture = page.get_pixmap(dpi=300)
        scan.new_page(width=330, height=520).insert_image(page.rect, pixmap=picture)
    scan.save(path)
    return path


@pytest.mark.skipif(not HAS_TESSERACT, reason="Tesseract not installed")
def test_margin_references_are_looked_for_where_the_marks_say(tmp_path):
    # The first page: 22, b, d (c is not printed) right of the text, b glued to its line
    # (Tesseract reads it into the line's first word); the second: 23, b on the left; the
    # third has its references inside, on the left. The first two have a "12" on their
    # spine side.
    pages = [
        ("right", [(3, "22", 6), (8, "b", 2), (19, "d", 6)], "12"),
        ("left", [(4, "23", 6), (12, "b", 6)], "12"),
        ("left", [(2, "c", 6), (9, "d", 6)], ""),
    ]
    path = _scanned_book(tmp_path / "scan.pdf", pages)
    tesseract = tesseract_path()
    with pymupdf.open(path) as doc:
        marked = [(doc[0], (293, 41, 302, 50)), (doc[1], (28, 102, 39, 111))]
        strip = learn_strip(marked, lambda page: page_column(page, tesseract, "spa"))
        scans = [scan_page(page, tesseract, "spa", strip) for page in doc]
        before = [scan_page(page, tesseract, "spa") for page in doc]

    # One side each, the marked one unless the page has its references on the other.
    assert [{m.side for m in s.marks} for s in scans] == [{"right"}, {"left"}, {"left"}]
    assert any(m.side == "left" for m in before[0].marks)  # the "12" was a mark before
    # Each mark beside its line, the glued "b" too (lost before).
    assert [len(s.marks) for s in scans] == [3, 2, 2]
    assert sum(m.side == "right" for m in before[0].marks) == 2
    # Labelled in order; the unprinted 22c stays missing.
    readings = [(i, m.reading) for i, s in enumerate(scans) for m in s.marks]
    assert assign_labels(readings) == ["22a", "22b", "22d", "23a", "23b", "23c", "23d"]


def test_reflowed_pdf_sets_margin_references_in_the_margin(tmp_path):
    out = tmp_path / "book.pdf"

    write_pdf(_blocks(), out, Metadata("Timeo"), notes_at="page")

    with pymupdf.open(out) as doc:
        page = next(p for p in doc if "honores" in p.get_text())
        label = page.search_for("22a")
        word = page.search_for("honores")[0]
        lines = [plain(line) for line in page.get_text().splitlines()]
        foot = page.search_for("Una nota.")
    assert len(label) == 1 and label[0].x0 > word.x1  # in the margin, not the text
    assert abs(label[0].y1 - word.y1) < 5  # level with its word's line
    assert not any("22a" in line and "honores" in line for line in lines)
    assert foot  # the footnote is still at the foot of the page
    assert not any("[22a]" in line for line in lines)  # the margin label is bare: "22a"

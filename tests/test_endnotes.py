import pymupdf

from pdf_worker import endnotes
from pdf_worker.convert import convert_pdf
from pdf_worker.drop_notes import drop_notes
from pdf_worker.inline import margin_ref
from pdf_worker.layout import NOTE_MARK_RE
from pdf_worker.structure import Heading, Note, Paragraph
from pdf_worker.text_extraction import extract_text_to_file

BODY = 11
NOTE = 9
LINE = 15
FILLER = [
    "Filler body text keeps the body font dominant on every page here.",
    "More filler text so that the analysis sees enough ordinary lines.",
]


def _with_sup(y, before, marker, after=""):
    """Body text at baseline ``y`` with a raised superscript ``marker`` after ``before``."""
    x = 72 + pymupdf.get_text_length(before, fontsize=BODY)
    items = [(72, y, before, BODY), (x + 0.5, y - 5, marker, 7)]
    if after:
        items.append((x + 1 + pymupdf.get_text_length(marker, fontsize=7), y, after, BODY))
    return items


def _chapter(title, refs):
    """A chapter page: a heading and one sentence per reference number."""
    items = [(72, 80, title, 18)]
    y = 120
    for n in refs:
        items += _with_sup(y, f"Claim number {n} of {title} is stated here.", str(n))
        y += LINE
    items += [(72, y + LINE * i, text, BODY) for i, text in enumerate(FILLER * 3)]
    return items


def _notes_page(groups):
    """A "Notes" section: per chapter a subheading and numbered notes."""
    items = [(72, 80, "Notes", 18)]
    y = 120
    for title, notes in groups:
        items.append((72, y, title, 14))
        y += LINE + 4
        for n, text in enumerate(notes, start=1):
            if isinstance(text, tuple):  # a note with a second paragraph
                items.append((72, y, f"{n}. {text[0]}", NOTE))
                y += LINE + 6
                items.append((84, y, text[1], NOTE))
            else:
                items.append((72, y, f"{n}. {text}", NOTE))
            y += LINE
        y += 10
    return items


def _book(make_layout_pdf):
    return make_layout_pdf(
        [
            _chapter("Chapter One", [1, 2]),
            _chapter("Chapter Two", [1, 2, 3]),
            _notes_page(
                [
                    (
                        "Chapter One",
                        ["First note of one.", ("Second note of one.", "Its second paragraph.")],
                    ),
                    (
                        "Chapter Two",
                        ["First note of two.", "Second note of two.", "Third note of two."],
                    ),
                ]
            ),
        ]
    )


def test_chapter_endnotes_are_linked_in_text(make_layout_pdf, tmp_path):
    out = tmp_path / "book.txt"

    report = extract_text_to_file(_book(make_layout_pdf), out)

    text = out.read_text(encoding="utf-8")
    assert "Claim number 2 of Chapter One is stated here.[^c1-2]" in text
    assert "Claim number 3 of Chapter Two is stated here.[^c2-3]" in text
    assert "[^c1-1]: First note of one." in text
    assert "[^c2-3]: Third note of two." in text
    assert report.footnote_count == 5 and report.footnote_reference_count == 5
    assert report.undefined_footnotes == report.unreferenced_footnotes == []


def test_chapter_endnotes_in_markdown(make_layout_pdf, title_rows, tmp_path):
    pdf = _book(make_layout_pdf)
    out = tmp_path / "book.md"

    report = convert_pdf(pdf, out, "md", layout_rows=title_rows(pdf))

    text = out.read_text(encoding="utf-8")
    assert report.stats.notes == 5
    # Multi-paragraph notes keep their paragraphs (Pandoc: indented continuation).
    assert "[^c1-2]: Second note of one.\n\n    Its second paragraph.\n" in text
    assert "[^c2-1]: First note of two.\n" in text
    # The per-chapter subheading inside the notes section is not a stray heading.
    assert text.count("# Chapter Two") == 1


def test_a_notes_page_the_model_boxes_as_references_keeps_its_note_paragraphs(
    make_layout_pdf, tmp_path
):
    # The layout model boxes notes sections like a bibliography (Timeo Greek p. 215 on):
    # one box over the whole notes page must not join a note's paragraphs.
    pdf = _book(make_layout_pdf)
    with pymupdf.open(pdf) as doc:
        rect = doc[2].rect
    box = {"label": "reference_content", "score": 0.9, "bbox": [0, 0, rect.width, rect.height]}
    rows = {2: {"page": 2, "width": rect.width, "height": rect.height, "blocks": [box]}}
    out = tmp_path / "book.md"

    convert_pdf(pdf, out, "md", layout_rows=rows)

    assert "[^c1-2]: Second note of one.\n\n    Its second paragraph.\n" in out.read_text(
        encoding="utf-8"
    )


def test_notes_none_drops_notes_their_chapter_and_references(make_layout_pdf, title_rows, tmp_path):
    pdf = _book(make_layout_pdf)

    for fmt in ("md", "txt"):
        out = tmp_path / f"book.{fmt}"
        report = convert_pdf(pdf, out, fmt, notes_at="none", layout_rows=title_rows(pdf))
        text = (tmp_path / f"book.{fmt}").read_text(encoding="utf-8")
        assert report.stats.notes == 0
        assert "Claim number 2 of Chapter One is stated here." in text
        assert "note of" not in text and "[^" not in text and "[2]" not in text
        assert "Notes" not in text  # the endnotes chapter's heading went with it


def test_notes_none_keeps_margin_references():
    blocks = [
        Heading("TIMEO", 1),
        Paragraph(margin_ref("22a") + "honores[^c1-1] y"),
        Note("c1-1", "n"),
    ]

    assert list(drop_notes(blocks)) == [
        Heading("TIMEO", 1),
        Paragraph(margin_ref("22a") + "honores y"),
    ]


def test_endnotes_numbered_in_brackets_are_linked(make_layout_pdf, tmp_path):
    # An ebook made into a PDF: each note "[1] Text <<" on a page of its own.
    texts = ["Bracketed note one, as printed.", "The second says something else."]
    notes = [[(72, 100, f"[{n}] {text} <<", BODY)] for n, text in enumerate(texts, start=1)]
    pdf = make_layout_pdf([_chapter("Chapter One", [1, 2]), *notes])
    out = tmp_path / "book.txt"

    report = extract_text_to_file(pdf, out)

    text = out.read_text(encoding="utf-8")
    assert "Claim number 2 of Chapter One is stated here.[^c1-2]" in text
    assert "[^c1-1]: Bracketed note one, as printed." in text
    assert "[1]" not in text
    assert report.footnote_count == 2


def test_numbered_list_without_references_is_not_notes(make_layout_pdf, tmp_path):
    page = [
        *[(72, 100 + LINE * i, text, BODY) for i, text in enumerate(FILLER * 2)],
        (72, 200, "1. Apples are listed first.", BODY),
        (72, 215, "2. Pears are listed second.", BODY),
        (72, 230, "3. Plums are listed third.", BODY),
    ]
    out = tmp_path / "list.txt"

    report = extract_text_to_file(make_layout_pdf([page]), out)

    assert report.footnote_count == 0
    assert "1. Apples are listed first." in out.read_text(encoding="utf-8")


def test_sequences_resume_after_a_list_inside_a_note():
    defs = [(n, (0, n)) for n in (1, 2, 3)]
    defs += [(n, (1, n)) for n in (1, 2)]  # "1." and "2." inside note 3
    defs += [(n, (2, n)) for n in (4, 5)]

    groups = endnotes.sequences(defs)

    assert [[n for n, _ in g.items] for g in groups] == [[1, 2, 3, 4, 5]]


def test_runs_pair_with_groups_by_count_and_order():
    refs = [(n, (0, n, 0)) for n in range(1, 11)] + [(n, (5, n, 0)) for n in range(1, 4)]
    defs = [(n, (9, n)) for n in range(1, 11)] + [(n, (10, n)) for n in range(1, 4)]

    notes = endnotes.match_chapter_notes(refs, defs)

    assert notes.refs[(0, 10)] == {0: "c1-10"}
    assert notes.refs[(5, 3)] == {0: "c2-3"}
    assert notes.defs[(10, 1)] == "c2-1"
    assert notes.last_in_group == {"c1-10", "c2-3"}


def test_a_misread_number_starting_a_notes_line_is_a_mark():
    assert NOTE_MARK_RE.match("3.¡. Así pues, Timeo y Hermócrates se alojan")
    assert not NOTE_MARK_RE.match("12 , 1274a 2 2 , Locro recibía sus leyes")  # a citation
    assert not NOTE_MARK_RE.match("Así pues, Timeo")


def test_lossy_notes_pair_from_any_number_and_misread_ones_fill_gaps():
    # The Timeo: note 1 lost, references 2-12 (and a stray "8" before), notes 2-15
    # whose 5 and 11 were misread beyond reading ("n"), but hang beside their lines.
    refs = [(8, (0, 1, 0))] + [(n, (1, n, 0)) for n in range(2, 13)]
    defs = [(n, (9, 2 * n)) for n in range(2, 16) if n not in (5, 11)]
    marks = [(9, 2 * n) for n in range(2, 16)]

    notes = endnotes.match_chapter_notes(refs, defs, lossy=True, least=4, marks=marks)

    assert notes.refs[(1, 2)] == {0: "c1-2"} and notes.refs[(1, 12)] == {0: "c1-12"}
    assert notes.defs[(9, 10)] == "c1-5" and notes.defs[(9, 22)] == "c1-11"
    assert (0, 1) not in notes.refs


def test_misread_note_numbers_fill_by_their_last_digits_then_by_count():
    # Timeo notes 447-460: 448-451, 453, 455, 456 read; 447 "H7", 452 "45⛨", 454
    # "4-54-", 457 ".i,57", 458 ".i,58", 459 "-1,59", 460 "4-60"; 446 and 461 read.
    read = {446, 448, 449, 450, 451, 453, 455, 456, 461}
    misread = {447: "H7", 452: "45⛨", 454: "4-54-", 457: ".i,57", 458: ".i,58"}
    misread |= {459: "-1,59", 460: "4-60"}
    defs = [(n, (9, n)) for n in sorted(read)]
    marks = [(9, n) for n in misread]
    readings = {(9, n): reading for n, reading in misread.items()}
    defined = dict(defs)

    endnotes._fill_gaps(defined, marks, readings)

    assert defined == {n: (9, n) for n in range(446, 462)}
    # "H7" with both 447 and 457 missing could be either: left to the count.
    defined = {446: (9, 446), 458: (9, 458)}
    endnotes._fill_gaps(defined, [(9, 447)], {(9, 447): "H7"})
    assert set(defined) == {446, 458}


def test_a_stray_superscript_among_the_notes_does_not_end_the_references_there():
    # Timeo 3: references 2-101, then "111" read on the second page of notes 2-116.
    refs = [(n, (1, n, 0)) for n in range(2, 102)] + [(111, (31, 3, 0))]
    defs = [(n, (30 + n // 40, n % 40)) for n in range(2, 117)]

    notes = endnotes.match_chapter_notes(refs, defs, lossy=True, least=4)

    assert notes.defs[(30, 2)] == "c1-2" and notes.refs[(1, 2)] == {0: "c1-2"}
    assert len(notes.defs) == 115
    assert (31, 3) not in notes.refs

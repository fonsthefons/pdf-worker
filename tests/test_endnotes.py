import pymupdf

from pdf_worker import endnotes
from pdf_worker.convert import convert_pdf
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


def test_chapter_endnotes_in_markdown(make_layout_pdf, tmp_path):
    out = tmp_path / "book.md"

    report = convert_pdf(_book(make_layout_pdf), out, "md")

    text = out.read_text(encoding="utf-8")
    assert report.stats.notes == 5
    # Multi-paragraph notes keep their paragraphs (Pandoc: indented continuation).
    assert "[^c1-2]: Second note of one.\n\n    Its second paragraph.\n" in text
    assert "[^c2-1]: First note of two.\n" in text
    # The per-chapter subheading inside the notes section is not a stray heading.
    assert text.count("# Chapter Two") == 1


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

    groups = endnotes._sequences(defs)

    assert [[n for n, _ in g.items] for g in groups] == [[1, 2, 3, 4, 5]]


def test_runs_pair_with_groups_by_count_and_order():
    refs = [(n, (0, n, 0)) for n in range(1, 11)] + [(n, (5, n, 0)) for n in range(1, 4)]
    defs = [(n, (9, n)) for n in range(1, 11)] + [(n, (10, n)) for n in range(1, 4)]

    notes = endnotes.match_chapter_notes(refs, defs)

    assert notes.refs[(0, 10)] == {0: "c1-10"}
    assert notes.refs[(5, 3)] == {0: "c2-3"}
    assert notes.defs[(10, 1)] == "c2-1"
    assert notes.last_in_group == {"c1-10", "c2-3"}

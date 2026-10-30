import pymupdf

from pdf_worker.cli import main
from pdf_worker.text_extraction import extract_text_to_file, iter_page_texts

BODY = 11
NOTE = 8
# Real pages have far more body text than notes; the body font size is detected from
# the most common size, so every test page carries some filler body text.
FILLER = [
    (72, 300 + 14 * i, "Filler body text keeps the body font dominant here.", BODY)
    for i in range(6)
]


def _body(y, text):
    return (72, y, text, BODY)


def _note(y, text):
    return (72, y, text, NOTE)


def _with_sup(y, before, marker, after=""):
    """Body text at baseline ``y`` with a raised superscript ``marker`` after ``before``."""
    x = 72 + pymupdf.get_text_length(before, fontsize=BODY)
    items = [_body(y, before), (x + 0.5, y - 5, marker, 7)]
    if after:
        items.append((x + 1 + pymupdf.get_text_length(marker, fontsize=7), y, after, BODY))
    return items


def _page_with_footnote():
    return [
        *_with_sup(100, "Body text with a note", "1", " and more text."),
        _body(114, "Second body line."),
        *FILLER,
        _note(760, "1 The footnote text itself."),
        _note(770, "continues here."),
        (300, 800, "7", 9),
    ]


def _texts(pdf):
    return [page.text for page in iter_page_texts(pdf)]


def test_page_footnote_is_linked_and_moved_to_page_end(make_layout_pdf):
    pdf = make_layout_pdf([_page_with_footnote()])

    (text,) = _texts(pdf)

    assert "Body text with a note[^p1-1] and more text." in text
    assert "[^p1-1]: The footnote text itself.\ncontinues here.\n" in text
    assert text.endswith("[^p1-1]: The footnote text itself.\ncontinues here.\n")
    # The page number below the notes is page furniture: in neither the notes nor the body.
    assert "7" not in text
    assert "1 The footnote" not in text


def test_multiple_footnotes_with_numbers_and_symbols(make_layout_pdf):
    pdf = make_layout_pdf(
        [
            [
                *_with_sup(100, "First claim", "*"),
                *_with_sup(114, "Second claim", "2"),
                *FILLER,
                _note(740, "* A starred note."),
                _note(752, "2 A numbered note."),
            ]
        ]
    )

    (text,) = _texts(pdf)

    assert "First claim[^p1-*]" in text
    assert "Second claim[^p1-2]" in text
    assert "[^p1-*]: A starred note.\n[^p1-2]: A numbered note.\n" in text


def test_superscript_marker_in_note_line(make_layout_pdf):
    pdf = make_layout_pdf(
        [
            [
                *_with_sup(100, "Claim", "3"),
                *FILLER,
                (72, 755, "3", 6),
                (78, 760, "Note with a raised marker.", NOTE),
            ]
        ]
    )

    (text,) = _texts(pdf)

    assert "Claim[^p1-3]" in text
    assert "[^p1-3]: Note with a raised marker." in text


def test_footnote_continued_on_next_page(make_layout_pdf):
    pdf = make_layout_pdf(
        [
            _page_with_footnote(),
            [_body(100, "Next page body."), *FILLER, _note(760, "rest of the long footnote.")],
        ]
    )

    first, second = _texts(pdf)

    assert "[^p1-1]: The footnote" in first
    assert "[^p1-1]: (continued) rest of the long footnote." in second
    assert second.startswith("Next page body.")


def test_parenthesized_markers_in_the_text_and_the_notes(make_layout_pdf):
    pdf = make_layout_pdf(
        [
            [
                _body(100, "A claim made in plain text (1). More."),
                _body(114, "Another claim (2) here."),
                *FILLER,
                _note(740, "(1) The first note."),
                _note(752, "(2) The second note."),
            ]
        ]
    )

    (text,) = _texts(pdf)

    assert "A claim made in plain text[^p1-1]. More." in text
    assert "Another claim[^p1-2] here." in text
    assert "[^p1-1]: The first note.\n[^p1-2]: The second note.\n" in text


def test_parenthesized_notes_at_a_chapter_end_are_found(make_layout_pdf):
    # Notes gathered at the foot of the chapter's last page, their "(n)" pages before.
    pdf = make_layout_pdf(
        [
            [_body(100, "A claim made early (1). More."), _body(114, "Another (2) here."), *FILLER],
            [
                _body(100, "The chapter ends on this page."),
                *FILLER,
                _note(740, "(1) The first note."),
                _note(752, "(2) The second note."),
            ],
        ]
    )

    _, end = _texts(pdf)

    assert "(1) The first note" not in end
    assert "The first note." in end and "The second note." in end
    assert "[^p2-1]: The first note." in end


def test_parenthesized_lines_are_notes_only_where_the_text_marks_them(make_layout_pdf):
    pdf = make_layout_pdf(
        [[_body(100, "No markers in this text."), *FILLER, _note(740, "(1) A small line.")]]
    )

    (text,) = _texts(pdf)

    assert "[^" not in text
    assert "(1) A small line." in text


def test_the_next_note_number_is_a_note_without_a_matching_marker(make_layout_pdf):
    pdf = make_layout_pdf(
        [
            [
                *_with_sup(100, "First claim", "1"),
                _body(114, "A second claim, glued individual2 here."),
                *FILLER,
                _note(740, "1 The first note."),
                _note(752, "2 The second note."),
            ]
        ]
    )

    (text,) = _texts(pdf)

    assert "[^p1-1]: The first note.\n[^p1-2]: The second note.\n" in text
    assert "2 The second note" not in text


def test_an_exponent_is_left_alone(make_layout_pdf):
    pdf = make_layout_pdf([[*_with_sup(100, "Area in m", "2"), _body(114, "More."), *FILLER]])

    (text,) = _texts(pdf)

    assert "[^" not in text


def test_a_reference_without_its_note_gets_one_saying_so(make_layout_pdf):
    pdf = make_layout_pdf([[*_with_sup(100, "As the guests", "3"), _body(114, "More."), *FILLER]])

    (text,) = _texts(pdf)

    assert "As the guests[^o1-3]" in text
    assert "[^o1-3]: no footnote content found" in text


def test_small_margin_notes_beside_body_are_not_footnotes(make_layout_pdf):
    body = [_body(400 + 14 * i, f"{i} body line that runs down the page.") for i in range(25)]
    margin = [(460, 500 + 12 * i, f"{i + 1} margin gloss", NOTE) for i in range(5)]
    pdf = make_layout_pdf([body + margin])

    (text,) = _texts(pdf)

    assert "[^" not in text
    assert "1 margin gloss" in text


def test_bracketed_endnotes_are_linked_across_pages(make_layout_pdf):
    pdf = make_layout_pdf(
        [
            [_body(100, "A sentence with a note.[1] Another one, [2] here.")],
            [_body(100, "Notes"), _body(120, "[1] First endnote."), _body(134, "[2] Second.")],
        ]
    )

    body, notes = _texts(pdf)

    assert "A sentence with a note.[^1] Another one,[^2] here." in body
    assert "[^1]: First endnote.\n[^2]: Second.\n" in notes


def test_numbered_list_items_are_not_endnotes(make_layout_pdf):
    items = [_body(100 + 14 * i, f"[{i % 3 + 1}] exercise item {i}") for i in range(12)]
    pdf = make_layout_pdf([items])

    (text,) = _texts(pdf)

    assert "[^" not in text
    assert "[1] exercise item 0" in text


def test_footnotes_can_be_disabled(make_layout_pdf):
    pdf = make_layout_pdf([_page_with_footnote()])

    (page,) = iter_page_texts(pdf, footnotes=False)

    assert "[^" not in page.text
    assert "1 The footnote text itself." in page.text


def test_report_counts_and_flags_unreferenced_notes(make_layout_pdf, tmp_path):
    pdf = make_layout_pdf(
        [
            _page_with_footnote(),
            # No superscript references here: notes accepted by their numbering only.
            [_body(100, "Body without markers."), *FILLER, _note(760, "4 Orphan note.")],
        ]
    )

    report = extract_text_to_file(pdf, tmp_path / "out.txt")

    assert report.footnote_count == 2
    assert report.footnote_reference_count == 1
    assert report.unreferenced_footnotes == ["p2-4"]
    assert report.undefined_footnotes == []


def test_cli_reports_footnotes_and_supports_opt_out(make_layout_pdf, tmp_path, capsys):
    pdf = make_layout_pdf([_page_with_footnote()])
    out = tmp_path / "out.txt"

    main(["extract-text", str(pdf), "-o", str(out)])
    assert "Marked 1 footnote(s) and 1 reference(s)" in capsys.readouterr().out
    assert "[^p1-1]" in out.read_text(encoding="utf-8")

    main(["extract-text", str(pdf), "-o", str(out), "--no-footnotes"])
    assert "Marked" not in capsys.readouterr().out
    assert "[^" not in out.read_text(encoding="utf-8")

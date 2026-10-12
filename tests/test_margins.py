import zipfile

from pdf_worker.convert import convert_pdf

BODY = 11
LINE = 16
FULL = [
    "The quick brown fox jumps over the lazy dog and keeps running far",
    "away across the green fields until the evening light finally fades",
    "into a calm and quiet night where every sound seems to have gone",
    "and the old farmer walks slowly home along the winding river path",
]


def _md(make_layout_pdf, tmp_path, pages):
    pdf = make_layout_pdf(pages)
    out = tmp_path / "book.md"
    report = convert_pdf(pdf, out, "md")
    return out.read_text(encoding="utf-8"), report


def _textbook_page():
    """A body column, glosses in the right margin and line numbers in the left gutter."""
    return [
        (72, 100, FULL[0], BODY),
        (72, 100 + LINE, FULL[1], BODY),
        (40, 100 + 2 * LINE, "5  " + FULL[2], BODY),  # number merged into the line
        (72, 100 + 3 * LINE, FULL[3], BODY),
        (72, 100 + 4 * LINE, "and that is the end.", BODY),
        (460, 100, "fox = vulpes", 8),
        (460, 100 + LINE, "fields = agri", 8),
        (460, 100 + 3 * LINE, "farmer = agricola", 8),
        (40, 100 + 4 * LINE, "10", 8),
    ]


def test_glosses_are_separated_from_the_body(make_layout_pdf, tmp_path):
    text, report = _md(make_layout_pdf, tmp_path, [_textbook_page()])

    body = " ".join(FULL) + " and that is the end."
    assert f"\n{body}\n" in text  # one clean paragraph, line number removed
    assert "> fox = vulpes\\\n> fields = agri\\\n> farmer = agricola\n" in text
    assert text.index(body) < text.index("> fox")
    assert "10" not in text
    assert report.stats.glosses == 1 and report.stats.paragraphs == 1


def test_glosses_follow_a_paragraph_that_continues_on_the_next_page(make_layout_pdf, tmp_path):
    first = [item for item in _textbook_page() if item[2] != "and that is the end."]
    second = [(72, 100, "and that is the end.", BODY)]

    text, _ = _md(make_layout_pdf, tmp_path, [first, second])

    assert text.index("the end.") < text.index("> fox")


def test_glosses_become_an_aside_box_in_epub(make_layout_pdf, tmp_path):
    pdf = make_layout_pdf([_textbook_page()])
    out = tmp_path / "book.epub"

    convert_pdf(pdf, out, "epub")

    with zipfile.ZipFile(out) as zf:
        chapter = zf.read("OEBPS/c001.xhtml").decode()
    assert '<div class="gloss"><p>fox = vulpes<br/>fields = agri<br/>' in chapter


def test_table_rows_are_joined(make_layout_pdf, tmp_path):
    rows = [("Nominative", "Accusative", "Verb"), ("Marcus", "Iuliam", "pulsat.")]
    page = [*[(72, 100 + LINE * i, line, BODY) for i, line in enumerate(FULL)]]
    for r, cells in enumerate(rows):
        for c, cell in enumerate(cells):
            page.append((72 + 130 * c, 200 + 2 * LINE * r, cell, BODY))

    text, _ = _md(make_layout_pdf, tmp_path, [page])

    assert "\nNominative Accusative Verb\n" in text
    assert "\nMarcus Iuliam pulsat.\n" in text


def test_two_equal_columns_are_not_glosses(make_layout_pdf, tmp_path):
    left = [
        "The quick brown fox jumps over",
        "the lazy dog and keeps running",
        "far away to the end.",
    ]
    right = [
        "Across the green fields until",
        "the evening light finally fades",
        "into the night.",
    ]
    page = [(50, 100 + LINE * i, t, BODY) for i, t in enumerate(left)]
    page += [(310, 100 + LINE * i, t, BODY) for i, t in enumerate(right)]

    text, report = _md(make_layout_pdf, tmp_path, [page])

    assert report.stats.glosses == 0
    assert "Across the green fields" in text and ">" not in text.split("---", 2)[2]


def test_picture_noise_is_dropped_but_section_breaks_stay(make_layout_pdf, tmp_path):
    page = [
        *[(72, 100 + LINE * i, t, BODY) for i, t in enumerate(FULL[:2])],
        (72, 100 + 2 * LINE, "and a short end.", BODY),
        (200, 180, "' , !", BODY),
        (200, 220, "* * *", BODY),
        (72, 260, "A new section begins here.", BODY),
    ]

    text, _ = _md(make_layout_pdf, tmp_path, [page])

    assert "' , !" not in text and "!" not in text.split("---", 2)[2]
    assert "\\* \\* \\*" in text

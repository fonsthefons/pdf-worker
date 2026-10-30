import shutil
import subprocess
import zipfile

import pymupdf
import pytest

from pdf_worker.cli import main
from pdf_worker.convert import (
    UnsupportedFormatError,
    _referenced_notes,
    convert_pdf,
    guess_language,
)
from pdf_worker.layout import page_lines, running_key
from pdf_worker.structure import Note, Paragraph, join_lines

BODY = 11
LINE = 14
EPUBCHECK = shutil.which("epubcheck") or (
    "/opt/homebrew/bin/epubcheck" if shutil.which("/opt/homebrew/bin/epubcheck") else None
)

# Lines of about the same width, so they all reach the right margin.
FULL = [
    "The quick brown fox jumps over the lazy dog and keeps running far",
    "away across the green fields until the evening light finally fades",
    "into a calm and quiet night where every sound seems to have gone",
]


def _body(y, text):
    return (72, y, text, BODY)


def _paragraph(top, lines, last):
    """A paragraph: full-width ``lines`` then a short ``last`` line."""
    items = [_body(top + LINE * i, text) for i, text in enumerate(lines)]
    items.append(_body(top + LINE * len(lines), last))
    return items


def _md(make_layout_pdf, tmp_path, pages, **kwargs):
    pdf = make_layout_pdf(pages)
    out = tmp_path / "book.md"
    report = convert_pdf(pdf, out, "md", **kwargs)
    return out.read_text(encoding="utf-8"), report


def test_notes_of_the_notes_section_no_reference_points_to_are_left_out():
    blocks = [
        Paragraph("el cuarto[^c1-3]."),
        Note("p1-1", "A page footnote is kept."),
        Note("c1-3", "Hermócrates."),
        Note("c1-40", "For a page the excerpt left out."),
        Note("o168-1", "no footnote content found"),  # a page number's "1", dropped
    ]

    assert list(_referenced_notes(blocks)) == blocks[:3]


def test_join_lines_undoes_hyphenation_and_joins_refs():
    assert join_lines(["a hyphen-", "ated word"]) == "a hyphenated word"
    assert join_lines(["Well-", "Known"]) == "Well- Known"
    assert join_lines(["a claim.", "[^1]", "Next"]) == "a claim.[^1] Next"


def test_headings_paragraphs_and_hyphenation(make_layout_pdf, title_rows, tmp_path):
    page = [
        (72, 80, "Chapter One", 18),
        *_paragraph(120, FULL[:2], "and a short hyphen-"),
        _body(120 + LINE * 3, "ated ending."),
        *_paragraph(200, FULL[1:], "Second paragraph ends here."),
    ]
    pdf = make_layout_pdf([page])
    out = tmp_path / "book.md"
    report = convert_pdf(pdf, out, "md", title="Test Book", layout_rows=title_rows(pdf))
    text = out.read_text(encoding="utf-8")

    assert text.startswith('---\ntitle: "Test Book"\nlang: en\n---\n')
    assert "\n# Chapter One\n" in text
    assert f"{FULL[0]} {FULL[1]} and a short hyphenated ending.\n\n" in text
    assert f"{FULL[1]} {FULL[2]} Second paragraph ends here.\n" in text
    assert report.stats.headings == 1
    assert report.stats.paragraphs == 2


def test_paragraph_continues_across_pages(make_layout_pdf, tmp_path):
    pages = [
        [*_paragraph(100, FULL[:2], FULL[2])],  # last line is full width: no ending
        [_body(100, "and it ends on the next page."), *_paragraph(200, FULL[:1], "Done.")],
    ]
    text, _ = _md(make_layout_pdf, tmp_path, pages)

    assert f"{FULL[2]} and it ends on the next page.\n\n" in text


def test_a_line_lowered_for_its_note_number_stays_in_the_paragraph(make_layout_pdf, tmp_path):
    # A web page printed by a browser: the line with "[2]" is set lower by the number's rise.
    rise = 6
    second = 100 + LINE + rise
    x = 72 + pymupdf.get_text_length(FULL[1], fontsize=BODY)
    after = x + pymupdf.get_text_length("[2]", fontsize=BODY)
    page = [
        _body(100, FULL[0]),
        _body(second, FULL[1]),
        (x, second - rise, "[2]", BODY),
        (after, second, " and", BODY),
        _body(second + LINE, "the end of it."),
        *_paragraph(second + LINE * 3, FULL[:1], "Next paragraph."),
    ]
    text, report = _md(make_layout_pdf, tmp_path, [page])

    assert FULL[0] + " " + FULL[1] in text
    assert report.stats.paragraphs == 2


def test_a_printed_web_page_loses_the_browser_header_and_footer(make_layout_pdf, tmp_path):
    # Two pages only (too few to repeat), the header also the title in large type.
    pages = [
        [
            (40, 12, "MY BOOK", 9),
            *([(72, 60, "MY BOOK", 24)] if n == 1 else []),
            *_paragraph(120, FULL[:2], "It ends here."),
            (40, 835, f"http://example.org/book/cover.htm ({n} de 2)04/12/2006 23:18:49", 9),
        ]
        for n in (1, 2)
    ]
    text, _ = _md(make_layout_pdf, tmp_path, pages)

    assert "example.org" not in text
    assert text.count("MY BOOK") == 1


def test_bold_chapter_lines_near_the_top_are_not_running_heads(tmp_path):
    # "CHAPTER II", "CHAPTER III"... read alike ("chapter #") in the top margin of 5 of
    # 30 pages: fewer than a running head's share of the pages, more than a small one's.
    pdf = tmp_path / "chapters.pdf"
    doc = pymupdf.open()
    for n in range(30):
        page = doc.new_page()
        if n % 6 == 0:
            numeral = ("II", "III", "IV", "V", "VI")[n // 6]
            page.insert_text((250, 60), f"CHAPTER {numeral}", fontsize=BODY, fontname="hebo")
        word = chr(97 + n // 26) + chr(97 + n % 26)  # each page its own text, or a watermark
        for i, text in enumerate(FULL):
            page.insert_text((72, 150 + LINE * i), f"{word} {text}", fontsize=BODY)
    doc.save(pdf)
    out = tmp_path / "chapters.md"

    convert_pdf(pdf, out, "md")

    assert out.read_text(encoding="utf-8").count("CHAPTER") == 5


def test_a_block_set_in_from_the_margin_is_one_paragraph(make_layout_pdf, tmp_path):
    # A quotation set in as a whole: every line starts in from the margin, the first more.
    inset = ["The quick brown fox jumps over the lazy dog and", "keeps running far away across"]
    page = [
        *_paragraph(100, FULL[:1], "Its first paragraph ends."),
        (110, 100 + LINE * 2, inset[0], BODY),
        (95, 100 + LINE * 3, inset[1], BODY),
        (95, 100 + LINE * 4, "the green fields.", BODY),
        (90, 100 + LINE * 5, "Then the text goes on with a new paragraph of its own.", BODY),
    ]
    text, report = _md(make_layout_pdf, tmp_path, [page])

    assert f"{inset[0]} {inset[1]} the green fields.\n" in text
    assert report.stats.paragraphs == 3


def test_hanging_indents_start_paragraphs_at_the_margin(make_layout_pdf, tmp_path):
    # Dialogue set like the Abada Timeo: a turn starts at the margin, its other lines indented.
    page = [
        item
        for n, top in enumerate((100, 160, 220))
        for item in (
            _body(top, FULL[0]),
            (90, top + LINE, FULL[1], BODY),
            (90, top + LINE * 2, f"Turn {n} ends here.", BODY),
        )
    ]
    text, report = _md(make_layout_pdf, tmp_path, [page])

    assert f"{FULL[0]} {FULL[1]} Turn 1 ends here.\n" in text
    assert report.stats.paragraphs == 3


BIBLIOGRAPHY = [
    "GRABMANN, M.: Der göttliche Grund der menschlichen Wahrheits-",
    "erkenntnis nach Augustinus und Thomas,",
    "Aschendorff, Münster 1924.",  # a short line, then a capital: today a new paragraph
    "GILSON, E.: El ser y los filósofos, Pamplona 1979.",
]


def _reference_boxes(pdf, entries, label="reference_content"):
    """A layout row (pixels of an image twice the page's size) with one ``label`` box
    around each entry: a list of line indexes."""
    with pymupdf.open(pdf) as doc:
        page = doc[0]
        bboxes = [line.bbox for line in page_lines(page)]
        width, height = page.rect.width, page.rect.height

    def box(lines):
        x0, y0, x1, y1 = zip(*(bboxes[i] for i in lines), strict=True)
        return {
            "label": label,
            "score": 0.9,
            "bbox": [2 * min(x0), 2 * min(y0), 2 * max(x1), 2 * max(y1)],
        }

    return {
        0: {
            "page": 0,
            "width": 2 * width,
            "height": 2 * height,
            "blocks": [box(e) for e in entries],
        }
    }


@pytest.mark.parametrize("model", [False, True])
def test_a_bibliography_entry_is_the_layout_models_box(make_layout_pdf, tmp_path, model):
    pdf = make_layout_pdf([[_body(100 + LINE * i, text) for i, text in enumerate(BIBLIOGRAPHY)]])
    rows = _reference_boxes(pdf, [[0, 1, 2], [3]]) if model else None
    out = tmp_path / "book.md"

    report = convert_pdf(pdf, out, "md", layout_rows=rows)

    text = out.read_text(encoding="utf-8")
    assert ("Thomas, Aschendorff, Münster 1924.\n" in text) == model
    assert report.stats.paragraphs == (2 if model else 3)


@pytest.mark.parametrize("model", [False, True])
def test_no_new_paragraph_inside_one_text_box(make_layout_pdf, tmp_path, model):
    lines = [
        FULL[0],  # a box of its own: at its edge today's rule joins the next line
        "and a short line,",
        "Paris in the spring, where it ends.",  # a short line, then a capital: today a start
    ]
    page = [_body(100 + LINE * i, text) for i, text in enumerate(lines)]
    page.append(_body(100 + LINE * 5, "A second paragraph after a gap."))
    pdf = make_layout_pdf([page])
    rows = _reference_boxes(pdf, [[0], [1, 2], [3]], label="text") if model else None
    out = tmp_path / "book.md"

    report = convert_pdf(pdf, out, "md", layout_rows=rows)

    text = out.read_text(encoding="utf-8")
    assert (f"{FULL[0]} and a short line, Paris in the spring" in text) == model
    assert report.stats.paragraphs == (2 if model else 3)


@pytest.mark.parametrize(
    "item",
    [
        "-Sólo sé que son tíos.",  # a dialogue line (Niebla p. 31; no "—" in this font)
        "1.2. Estructura de los elementos.",  # a numbered item (Diálogos p. 86)
        "1º.",
        "J. GARCÍA BACCA, Platón. «Critias», Caracas, 1980.",  # an entry (Diálogos p. 159)
        "PRIMER CAPÍTULO",  # a chapter heading (Kant p. 87)
    ],
)
def test_a_line_that_starts_an_item_keeps_todays_split_inside_a_text_box(
    make_layout_pdf, tmp_path, item
):
    lines = [FULL[0], "and a short line ends.", item]
    pdf = make_layout_pdf([[_body(100 + LINE * i, text) for i, text in enumerate(lines)]])
    rows = _reference_boxes(pdf, [[0, 1, 2]], label="text")
    out = tmp_path / "book.md"

    report = convert_pdf(pdf, out, "md", layout_rows=rows)

    assert report.stats.paragraphs + report.stats.headings == 2


def test_a_line_after_a_section_mark_keeps_todays_split_inside_a_text_box(
    make_layout_pdf, tmp_path
):
    # Kant p. 38: "- § 7 -" and its title "Explicación" in one box.
    lines = [FULL[0], "and it ends.", "- § 7 -", "Explicación"]
    pdf = make_layout_pdf([[_body(100 + LINE * i, text) for i, text in enumerate(lines)]])
    rows = _reference_boxes(pdf, [[0, 1, 2, 3]], label="text")
    out = tmp_path / "book.md"

    report = convert_pdf(pdf, out, "md", layout_rows=rows)

    assert report.stats.paragraphs + report.stats.headings == 3


def _boxes(pdf, *labelled):
    """A layout row with ``(label, line indexes)`` boxes."""
    rows = _reference_boxes(pdf, [lines for _, lines in labelled])
    for block, (label, _) in zip(rows[0]["blocks"], labelled, strict=True):
        block["label"] = label
    return rows


@pytest.mark.parametrize("model", [False, True])
def test_a_line_in_a_title_box_is_a_heading_its_level_from_its_size(
    make_layout_pdf, tmp_path, model
):
    # Kant p. 195 "Tesis", Metafísica p. 98: a title in body type, under a larger one.
    page = [
        (72, 80, "Chapter One", 18),
        *_paragraph(120, FULL[:1], "It ends."),
        _body(120 + LINE * 3, "Tesis"),
        *_paragraph(120 + LINE * 5, FULL[:1], "It ends too."),
    ]
    pdf = make_layout_pdf([page])
    title, text = ("paragraph_title", "text")
    rows = _boxes(pdf, ("doc_title", [0]), (text, [1, 2]), (title, [3]), (text, [4, 5]))
    out = tmp_path / "book.md"

    report = convert_pdf(pdf, out, "md", layout_rows=rows if model else None)

    md = out.read_text(encoding="utf-8")
    assert "\n# Chapter One\n" in md  # without the model, by its size
    assert ("\n## Tesis\n" in md) == model
    assert report.stats.headings == (2 if model else 1)


def test_large_type_below_a_larger_title_box_is_not_a_heading(make_layout_pdf, tmp_path):
    # Niebla p. 28 (OCR specks in large type), Kant p. 59 (table rows): the model says text.
    page = [
        (72, 80, "Chapter One", 20),
        (72, 110, "A row in large type", 14),
        *_paragraph(140, FULL[:1], "It ends."),
    ]
    pdf = make_layout_pdf([page])
    rows = _boxes(pdf, ("paragraph_title", [0]), ("text", [1]), ("text", [2, 3]))
    out = tmp_path / "book.md"

    report = convert_pdf(pdf, out, "md", layout_rows=rows)

    assert report.stats.headings == 1


def test_headings_beside_the_title_boxes(make_layout_pdf, tmp_path):
    # tools/headings_test.py: Metafísica's 17.5 pt divider boxed as text, larger than any
    # title box on its page, is a heading; Kant's all-caps "PRIMER CAPÍTULO" in body type
    # is not; Dilexit's "V." boxed apart from its title joins it.
    page = [
        (72, 80, "Chapter One", 18),
        *_paragraph(120, FULL[:1], "It ends."),
        _body(120 + LINE * 3, "CAPITULO PRIMERO"),
        *_paragraph(120 + LINE * 5, FULL[:1], "It ends too."),
        _body(120 + LINE * 8, "V."),
        _body(120 + LINE * 9, "Este es el corazón"),
        *_paragraph(120 + LINE * 11, FULL[:1], "It ends here."),
    ]
    pdf = make_layout_pdf([page])
    text = "text"
    rows = _boxes(
        pdf,
        (text, [0]),
        (text, [1, 2]),
        (text, [3]),
        (text, [4, 5]),
        ("paragraph_title", [6]),
        (text, [7]),
        (text, [8, 9]),
    )
    out = tmp_path / "book.md"

    convert_pdf(pdf, out, "md", layout_rows=rows)

    md = out.read_text(encoding="utf-8").splitlines()
    headings = [line.lstrip("# ") for line in md if line.startswith("#")]
    assert headings == ["Chapter One", "V. Este es el corazón"]


def test_a_bare_number_does_not_take_the_first_line_of_a_running_paragraph(
    make_layout_pdf, tmp_path
):
    # Niebla's dotless chapter numerals ("III"), each a title box over the chapter's text.
    page = [_body(80, "III"), *_paragraph(120, FULL[:2], "It ends.")]
    pdf = make_layout_pdf([page])
    rows = _boxes(pdf, ("paragraph_title", [0]), ("text", [1, 2, 3]))
    out = tmp_path / "book.md"

    convert_pdf(pdf, out, "md", layout_rows=rows)

    md = out.read_text(encoding="utf-8")
    assert [line for line in md.splitlines() if line.startswith("#")] == ["# III"]
    assert f"\n\n{FULL[0]} {FULL[1]} It ends.\n" in md


def test_a_line_left_of_the_margin_starts_a_turn(make_layout_pdf, tmp_path):
    # A Timeo page of long speeches: few turns, so the margin is the indent (x 90), and
    # "CRITIAS.-" sticks out after a full line ending "propósito36•".
    page = [
        (90, 100, FULL[0], BODY),
        *[(90, 100 + LINE * i, FULL[1], BODY) for i in range(1, 6)],
        (90, 100 + LINE * 6, FULL[1] + "•", BODY),
        (72, 100 + LINE * 7, "CRITIAS.-Es preciso hacerlo, si también a nuestro", BODY),
        (90, 100 + LINE * 8, FULL[1], BODY),
        (72, 100 + LINE * 9, "tercer compañero le parece bien and so it goes", BODY),
        (90, 100 + LINE * 10, "and ends.", BODY),
    ]
    text, report = _md(make_layout_pdf, tmp_path, [page])

    assert "\nCRITIAS.-Es preciso" in text
    assert f"{FULL[1]} tercer compañero" in text  # lowercase: the sentence goes on
    assert report.stats.paragraphs == 2


def test_a_numbered_notes_next_line_stays_in_it_after_a_short_line(make_layout_pdf, tmp_path):
    # Dilexit nos: "[5] Homilía ... (14 octubre 2016):" ends short; its next line is
    # capitalised, which would start a paragraph in the text.
    pages = [
        [*_paragraph(100, FULL[:2], "A claim with a note.[1] And another.[2]")],
        [
            _body(100, "[1] Homily, Domus Sanctae Marthae (14 October 2016):"),
            _body(114, "L'Osservatore Romano, weekly edition, p. 9."),
            _body(128, "[2] Second note."),
        ],
    ]
    text, report = _md(make_layout_pdf, tmp_path, pages)

    assert "[^1]: Homily, Domus Sanctae Marthae (14 October 2016): L’Osservatore" in text
    assert report.stats.paragraphs == 1


def test_running_headers_and_page_numbers_are_dropped(make_layout_pdf, tmp_path):
    pages = [
        [
            (72, 30, "My Running Header", 9),
            *_paragraph(100, FULL, f"Page {n} text."),
            (290, 815, str(n), 9),
        ]
        for n in range(1, 5)
    ]
    text, _ = _md(make_layout_pdf, tmp_path, pages)

    assert "My Running Header" not in text
    assert "Page 3 text." in text
    assert "\n3\n" not in text


ENDINGS = ("Ends one.", "Ends two.", "Ends three.", "Ends four.")  # unlike each other


def test_a_running_head_just_below_the_top_tenth_is_dropped(make_layout_pdf, tmp_path):
    # Metafísica: heads in 8 pt with their top at about 10.9% of the page.
    head = (200, 100, "La causalidad", 8)
    pages = [
        [head, *_paragraph(130, FULL[:1], ENDINGS[0]), *_paragraph(200, FULL[:2], FULL[2])],
        [head, _body(130, "and it ends on the next page."), *_paragraph(200, FULL, ENDINGS[1])],
        *([head, *_paragraph(130, FULL[:2], ENDINGS[n])] for n in (2, 3)),
    ]
    text, _ = _md(make_layout_pdf, tmp_path, pages)

    assert "causalidad" not in text
    assert f"{FULL[2]} and it ends on the next page." in text


def test_a_running_head_bigger_than_the_body_on_many_pages_is_dropped(make_layout_pdf, tmp_path):
    # Niebla: heads in 9.9 pt over a 9.2 pt body, past the size limit of rule 2.
    pages = [
        [(200, 60, "MIGUEL DE UNAMUNO", 12), *_paragraph(100, FULL[:2], ENDINGS[n])]
        for n in range(4)
    ]
    text, _ = _md(make_layout_pdf, tmp_path, pages)

    assert "UNAMUNO" not in text


def test_a_body_size_heading_at_the_top_of_one_page_is_kept(make_layout_pdf, tmp_path):
    pages = [
        [
            *([(200, 60, "The Second Part", BODY)] if n == 1 else []),
            *_paragraph(100, FULL[:2], ENDINGS[n]),
        ]
        for n in range(4)
    ]
    text, _ = _md(make_layout_pdf, tmp_path, pages)

    assert "The Second Part" in text


def test_section_marks_at_the_top_of_pages_are_kept(make_layout_pdf, tmp_path):
    pages = [
        [(280, 60, f"- § {n + 4} -", BODY), *_paragraph(100, FULL[:2], ENDINGS[n])]
        for n in range(2)
    ]
    text, _ = _md(make_layout_pdf, tmp_path, pages)

    assert "§ 4" in text and "§ 5" in text


def test_page_numbers_spaced_by_ocr_are_dropped(make_layout_pdf, tmp_path):
    pages = [
        [*_paragraph(100, FULL[:2], ENDINGS[n]), (290, 815, f"1 5 {n + 6}", 9)] for n in range(2)
    ]
    text, _ = _md(make_layout_pdf, tmp_path, pages)

    assert "1 5" not in text


def test_running_key_reads_ocr_variants_alike():
    assert running_key("L O S TRASCENDENTALES") == running_key("Los trascendentales")
    assert running_key("METAFÍSICA") == running_key("METAFISICA")
    assert running_key("LA CAUSALIDAD’") == running_key("LA CAUSALIDAD")
    assert running_key("ΤΙΜΑΙΟΣ")


def test_a_divider_page_keeps_the_title_its_running_heads_repeat(make_layout_pdf, tmp_path):
    pages = [
        [(200, 400, "INTRODUCCION", 18)],
        *([(250, 50, "INTRODUCCION", 8), *_paragraph(100, FULL[:2], ENDINGS[n])] for n in range(3)),
    ]
    text, _ = _md(make_layout_pdf, tmp_path, pages)

    assert text.count("INTRODUCCION") == 1


def test_footnotes_become_markdown_notes(make_layout_pdf, tmp_path):
    marker_x = 72 + pymupdf.get_text_length("A claim", fontsize=BODY)
    page = [
        _body(100, "A claim"),
        (marker_x + 0.5, 95, "1", 7),
        *_paragraph(130, FULL, "Filler paragraph."),
        *_paragraph(200, FULL, "More filler."),
        (72, 760, "1 The footnote text.", 8),
    ]
    text, report = _md(make_layout_pdf, tmp_path, [page])

    assert "A claim[^p1-1]\n" in text
    assert text.endswith("[^p1-1]: The footnote text.\n\n")
    assert report.stats.notes == 1


def test_markdown_escapes_syntax(make_layout_pdf, tmp_path):
    page = [
        *_paragraph(100, FULL, "Ends with *stars* here."),
        _body(200, "# Not a heading."),
        _body(240, "12. Numbered."),
    ]
    text, _ = _md(make_layout_pdf, tmp_path, [page])

    assert r"Ends with \*stars\* here." in text
    assert "\n\\# Not a heading.\n" in text
    assert "\n12\\. Numbered.\n" in text


def _epub(make_layout_pdf, title_rows, tmp_path):
    marker_x = 72 + pymupdf.get_text_length("A claim", fontsize=BODY)
    pages = [
        [
            (72, 80, "Chapter One", 18),
            _body(120, "A claim"),
            (marker_x + 0.5, 115, "1", 7),
            *_paragraph(150, FULL, "Filler & <markup> paragraph."),
            (72, 760, "1 The footnote text.", 8),
        ],
        [(72, 80, "Chapter Two", 18), *_paragraph(120, FULL, "Second chapter.")],
    ]
    pdf = make_layout_pdf(pages)
    out = tmp_path / "book.epub"
    report = convert_pdf(
        pdf,
        out,
        "epub",
        title="Test Book",
        author="A. Writer",
        language="en",
        layout_rows=title_rows(pdf),
    )
    return out, report


def test_epub_layout_metadata_and_linked_notes(make_layout_pdf, title_rows, tmp_path):
    out, report = _epub(make_layout_pdf, title_rows, tmp_path)

    with zipfile.ZipFile(out) as zf:
        first = zf.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"
        opf = zf.read("OEBPS/content.opf").decode()
        chapter = zf.read("OEBPS/c001.xhtml").decode()
        notes = zf.read("OEBPS/notes.xhtml").decode()
        nav = zf.read("OEBPS/nav.xhtml").decode()

    assert "<dc:title>Test Book</dc:title>" in opf
    assert "<dc:creator>A. Writer</dc:creator>" in opf
    assert "<dc:language>en</dc:language>" in opf
    assert 'href="notes.xhtml#n1" epub:type="noteref"' in chapter
    assert 'id="r1"' in chapter
    assert "Filler &amp; &lt;markup&gt; paragraph." in chapter
    assert 'epub:type="footnote"' in notes
    assert 'href="c001.xhtml#r1" role="doc-backlink"' in notes
    assert "The footnote text." in notes
    assert 'text. <a class="back" href="c001.xhtml#r1" role="doc-backlink">↩</a></p>' in notes
    assert "Chapter One" in nav and "Chapter Two" in nav
    assert report.stats.notes == 1


@pytest.mark.skipif(EPUBCHECK is None, reason="epubcheck not installed")
def test_epub_passes_epubcheck(make_layout_pdf, title_rows, tmp_path):
    out, _ = _epub(make_layout_pdf, title_rows, tmp_path)

    result = subprocess.run([EPUBCHECK, str(out)], capture_output=True, text=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No errors or warnings detected" in result.stdout


def test_guess_language():
    assert guess_language("El perro de la casa que está en el jardín con los niños") == "es"
    assert guess_language("The dog of the house is in the garden with the children") == "en"
    assert guess_language("Puer et puella in horto sunt, sed non est ad villam") == "la"
    assert guess_language("") == "en"


def test_unsupported_format_is_rejected(make_layout_pdf, tmp_path):
    pdf = make_layout_pdf([[_body(100, "text")]])

    with pytest.raises(UnsupportedFormatError):
        convert_pdf(pdf, tmp_path / "out.odt", "odt")
    with pytest.raises(UnsupportedFormatError, match="overwrite the input"):
        convert_pdf(pdf, pdf, "pdf")


def test_cli_convert_picks_format_from_extension(make_layout_pdf, tmp_path, capsys):
    pdf = make_layout_pdf([[*_paragraph(100, FULL, "End.")]], name="book.pdf")

    assert main(["convert", str(pdf), "-o", str(tmp_path / "out.md")]) == 0
    assert (tmp_path / "out.md").read_text(encoding="utf-8").startswith("---")
    assert "(md)" in capsys.readouterr().out

    assert main(["convert", str(pdf)]) == 0
    assert zipfile.is_zipfile(pdf.with_suffix(".epub"))

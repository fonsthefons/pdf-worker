"""Sections from the marks, and the printed contents as links (docs/marks-plan.md, Phase 5)."""

import re
import zipfile

import pymupdf
from test_endnotes import _book as _chapter_notes_book
from test_follow_marks import BODY, TEXT, _body, _convert, _rect

from pdf_worker import follow_marks, marks
from pdf_worker.convert import convert_pdf
from pdf_worker.epub import write_epub
from pdf_worker.inline import is_contents_entry, page_mark, plain
from pdf_worker.layout import page_lines
from pdf_worker.marks import Mark, Section
from pdf_worker.output import Metadata
from pdf_worker.structure import Heading, Note, Paragraph, SectionStart


def _save(pdf, found=(), sections=(), notes=None) -> None:
    """A marks file next to ``pdf``: a style mark per (page, kind, start of its line), and
    the sections as (page, kind[, keep])."""
    book = marks.new_marks(pdf)
    book.settings.notes = notes
    book.sections = [Section(*s) for s in sections]
    with pymupdf.open(pdf) as doc:
        for k, (page, kind, start) in enumerate(found, start=1):
            line = next(ln for ln in page_lines(doc[page - 1]) if ln.text.startswith(start))
            book.marks.append(Mark(f"m{k}", page, kind, _rect(line.bbox), [line.text]))
    marks.save(marks.default_marks_path(pdf), book)


def _epub(pdf, tmp_path) -> dict[str, str]:
    out = tmp_path / "book.epub"
    convert_pdf(pdf, out, "epub", title="t", author="a", cover=False)
    with zipfile.ZipFile(out) as z:
        return {n: z.read(n).decode() for n in z.namelist() if n.endswith(".xhtml")}


def test_a_section_marker_goes_before_its_first_block():
    book = marks.Marks(marks.PdfInfo("b.pdf", 4, ""))
    book.sections = [Section(1, "front"), Section(3, "bibliography"), Section(4, "index")]
    blocks = [
        Heading("Uno", 1, page=0),
        Paragraph("texto", page=0),
        Note("p1-1", "una nota"),
        # A scan's blocks: no page, their page start in the text.
        Heading("Dos", 1),
        Paragraph(page_mark(2, "3") + "Autor, Libro."),
        Paragraph("Otro autor."),
        Paragraph(page_mark(3, "4") + "abad, 3"),
    ]

    out = list(follow_marks.sections(iter(blocks), book))

    kinds = [b.kind if isinstance(b, SectionStart) else type(b).__name__ for b in out]
    assert kinds == [
        "front",
        "Heading",
        "Paragraph",
        "Note",
        "Heading",
        "bibliography",
        "Paragraph",
        "Paragraph",
        "index",
        "Paragraph",
    ]


def test_each_section_is_a_chapter_named_by_its_first_heading_or_its_kind(tmp_path):
    blocks = [
        SectionStart("introduction"),
        Heading("Prólogo del editor", 1, page=0),
        Paragraph("Un texto corto.", page=0),
        SectionStart("bibliography"),
        Paragraph("Autor, Un libro, Madrid 1990.", page=1),
    ]
    out = tmp_path / "b.epub"

    stats = write_epub(iter(blocks), out, Metadata("t", language="es"))

    with zipfile.ZipFile(out) as z:
        c1, c2 = z.read("OEBPS/c001.xhtml").decode(), z.read("OEBPS/c002.xhtml").decode()
        nav = z.read("OEBPS/nav.xhtml").decode()
    assert stats.chapters == 2
    assert "<title>Prólogo del editor</title>" in c1
    assert "<title>Bibliografía</title>" in c2 and "Madrid 1990" in c2
    assert 'href="c002.xhtml">Bibliografía</a>' in nav


def test_a_section_not_kept_is_left_out(make_layout_pdf, tmp_path):
    words = ["Alfa", "Beta", "Gamma"]
    pdf = make_layout_pdf(
        [[(72, 130 + 15 * k, f"{w} {TEXT}", BODY) for k in range(10)] for w in words]
    )
    _save(pdf, sections=[(1, "main"), (2, "introduction", False), (3, "main")])

    before = _convert(pdf, tmp_path, use_marks=False, name="before.md")
    after = _convert(pdf, tmp_path)

    assert "Beta" in before
    assert "Alfa" in after and "Gamma" in after and "Beta" not in after


def _contents_book(make_layout_pdf):
    entries = [
        "Índice sin destino",
        "1. Capítulo uno ........ 2",
        "Otra parte ........ 3",
        "3. Capítulo tres ........ 4",
        "Apéndice primero ........ 5",
        "Apéndice segundo ........ 6",
        "a).- Una subsección del apéndice",
        "que sigue en la línea siguiente",
    ]
    contents = [(72, 100 + 20 * k, entry, BODY) for k, entry in enumerate(entries)]
    heads = ["CAPÍTULO UNO", "Parte segunda del libro", "Capítulo Tres"]
    # Long enough chapters that each heading starts a chapter file of the EPUB.
    pages = [[(72, 90, head, 20), *_body(lines=30)] for head in heads]
    return make_layout_pdf([contents, *pages])


def test_contents_lines_link_to_the_headings_they_name(make_layout_pdf, tmp_path):
    pdf = _contents_book(make_layout_pdf)
    starts = ("Índice", "1. Cap", "Otra", "3. Cap", "Apéndice p", "Apéndice s", "a).", "que")
    found = [(1, "contents", s) for s in starts]
    _save(pdf, found, sections=[(1, "contents"), (2, "main")])

    files = _epub(pdf, tmp_path)

    text = files["OEBPS/c001.xhtml"]
    links = re.findall(r'<a href="([^"]+)">([^<]+)</a>', text)
    # By text (numbers, page numbers, accents and case left out), then by order.
    assert links == [
        ("c002.xhtml#h1", "1. Capítulo uno"),
        ("c003.xhtml#h2", "Otra parte"),
        ("c004.xhtml#h3", "3. Capítulo tres"),
    ]
    # Naming no heading: plain text.
    assert "Índice sin destino</li>" in text and '">Apéndice primero</li>' in text
    # A lettered item is an entry of its own; a line in lowercase goes on with its entry.
    assert '">a).- Una subsección del apéndice que sigue en la línea siguiente</li>' in text
    assert '<ol class="contents">' in text
    # Body lines in the contents' type, outside the contents section: no entries.
    assert not any("<li id" in files[f"OEBPS/c00{n}.xhtml"] for n in (2, 3, 4))
    assert "Capítulo tres</a></li>" in text and "........" not in text


def test_without_marks_a_printed_contents_is_dropped_as_before(make_layout_pdf, tmp_path):
    pdf = _contents_book(make_layout_pdf)

    md = _convert(pdf, tmp_path)

    assert "Otra parte" not in md and "Capítulo uno" not in md


def test_a_scans_contents_and_bibliography_follow_the_sections(tmp_path):
    from test_paddle_book import INTRO, _book, _row

    contents = "I. LA ILUSTRACIÓN FRANCESA ..... 1\nObservaciones introductorias.\n15"
    rows = [
        _row(0, ("text", [144, 100, 1046, 400], INTRO)),
        _row(1, ("content", [144, 100, 1046, 400], contents)),
        _row(
            2,
            ("text", [144, 100, 1046, 400], INTRO),
            ("text", [144, 500, 500, 520], "AUTOR UNO, Un libro, Madrid 1990"),
        ),
        _row(3, ("text", [144, 100, 500, 120], "AUTOR DOS, Otro libro, Roma 1980")),
    ]
    sections = {2: "bibliography", 3: "bibliography"}

    before = _book(tmp_path, rows)
    after = _book(tmp_path, rows, kinds={1: {0: "contents"}}, sections=sections)

    texts = [plain(b.text) for b in before if isinstance(b, Paragraph)]
    assert not any("ILUSTRACIÓN" in t for t in texts)  # a contents page: dropped
    assert any("Madrid 1990 AUTOR DOS" in t for t in texts)
    entries = [
        plain(b.text) for b in after if isinstance(b, Paragraph) and is_contents_entry(b.text)
    ]
    assert entries == ["I. LA ILUSTRACIÓN FRANCESA", "Observaciones introductorias."]
    texts = [plain(b.text).strip() for b in after if isinstance(b, Paragraph)]
    assert (
        "AUTOR UNO, Un libro, Madrid 1990" in texts and "AUTOR DOS, Otro libro, Roma 1980" in texts
    )


def _bibliography_page():
    entries = [
        "AUTOR UNO, Un libro de historia, Madrid 1990",
        f"AUTOR DOS, {TEXT}",
        "Buenos Aires 1950",
        "- Otra obra del mismo autor, Roma 1980",  # a dash for the same author
        "de AUTOR TRES, Un libro más, Lima 1970",
    ]
    return [(72, 300 + 15 * k, entry, BODY) for k, entry in enumerate(entries)]


def test_bibliography_entries_are_one_paragraph_each(make_layout_pdf, tmp_path):
    pdf = make_layout_pdf([_body(), [*_body(y=100, lines=8), *_bibliography_page()]])
    _save(pdf, sections=[(1, "main"), (2, "bibliography")])

    before = _convert(pdf, tmp_path, use_marks=False, name="before.md")
    after = _convert(pdf, tmp_path)

    # The rules end an entry at a short line only before a capital or a number.
    assert "Buenos Aires 1950 - Otra obra" in before and "Roma 1980 de AUTOR" in before
    paragraphs = [p.strip() for p in after.split("\n\n")]
    assert "AUTOR UNO, Un libro de historia, Madrid 1990" in paragraphs
    assert f"AUTOR DOS, {TEXT} Buenos Aires 1950" in paragraphs
    assert "\\- Otra obra del mismo autor, Roma 1980" in paragraphs  # Markdown's escape
    assert "de AUTOR TRES, Un libro más, Lima 1970" in paragraphs


def test_a_notes_section_holds_the_books_endnotes(make_layout_pdf, tmp_path):
    pdf = _chapter_notes_book(make_layout_pdf)
    # The setting says footnotes; the person marked the last page as the notes section.
    _save(pdf, notes="page")
    before = _convert(pdf, tmp_path, name="before.md")
    _save(pdf, sections=[(1, "main"), (3, "notes")], notes="page")

    after = _convert(pdf, tmp_path)

    assert "[^c1-2]" not in before
    assert "[^c1-2]" in after and "[^c2-3]: Third note of two." in after

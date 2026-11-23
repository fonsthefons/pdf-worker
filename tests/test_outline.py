import pymupdf

from pdf_worker import outline
from pdf_worker.blocks_file import read_blocks
from pdf_worker.convert import convert_pdf
from pdf_worker.inline import plain
from pdf_worker.structure import Heading, Note, Paragraph


def _levels(blocks, bookmarks=(), marked=False):
    levels = outline.collect(blocks, list(bookmarks), marked)
    return [b.level for b in outline.apply(blocks, levels) if isinstance(b, Heading)]


def _bookmarks(make_pdf, toc):
    path = make_pdf(["uno", "dos", "tres"])
    with pymupdf.open(path) as doc:
        doc.set_toc(toc)
        doc.saveIncr()
    with pymupdf.open(path) as doc:
        return doc.get_toc()


def test_bookmarks_set_the_levels(make_pdf):
    toc = _bookmarks(make_pdf, [[1, "1. Capítulo I - Jonia", 1], [2, "1. Tales", 2]])
    blocks = [
        Heading("CAPÍTULO I JONIA", 2, 0),
        Paragraph("texto"),
        Heading("1. Tales", 2, 1),
        Heading("2. Anaximandro", 2, 2),  # no bookmark: the level of "1. Tales", same size
        Heading("Textos", 3, 2),  # one size smaller: one level below
    ]
    assert _levels(blocks, toc) == [1, 2, 2, 3]


def test_unmatched_headings_follow_the_matched_one_before_them(make_pdf):
    # The dialogos book: bookmarks for the dialogues and their introductions only.
    toc = _bookmarks(
        make_pdf,
        [[1, "Filebo", 1], [2, "Introducción", 1], [2, "Filebo", 2], [2, "Bibliografía", 3]],
    )
    blocks = [
        Heading("DIÁLOGOS VI", 1, 0),  # before any matched heading: unchanged
        Heading("FILEBO", 2, 0),
        Heading("INTRODUCCIÓN", 2, 0),
        Heading("NOTA AL TEXTO", 3, 0),
        Heading("Estructura y finalidad del diálogo", 3, 0),
        Heading("FILEBO", 2, 1),
        Heading("BIBLIOGRAFÍA", 2, 2),
        Heading("2) Comentarios:", 4, 2),
    ]
    assert _levels(blocks, toc) == [1, 1, 2, 3, 3, 2, 2, 4]


def test_a_bookmark_names_a_heading_on_its_page_or_later(make_pdf):
    toc = _bookmarks(make_pdf, [[1, "Jonia", 2], [2, "Tales", 2]])
    # A contents page's copy of "JONIA" (page 0) is not the bookmark's heading (page 1).
    blocks = [Heading("JONIA", 3, 0), Heading("JONIA", 1, 1), Heading("1. Tales", 2, 1)]
    assert _levels(blocks, toc) == [3, 1, 2]


def test_bookmarks_that_say_no_hierarchy_are_ignored(make_pdf):
    nested = [Heading("Capítulo 1", 1, 0), Heading("1. Uno", 2, 0), Heading("Capítulo 2", 1, 1)]
    one_level = _bookmarks(make_pdf, [[1, "Capítulo 1", 1], [1, "Uno", 1], [1, "Capítulo 2", 2]])
    assert _levels(nested, one_level) == [1, 2, 1]  # not all level 1
    flat = [Heading("I. Uno", 3, 0), Heading("1. Dos", 3, 0), Heading("II. Tres", 3, 1)]
    unnamed = _bookmarks(make_pdf, [[1, "Otra cosa", 1], [2, "Nada", 1]])
    assert _levels(flat, unnamed) == [1, 2, 1]  # ranked as without bookmarks


def test_flat_numbered_headings_are_ranked_by_their_numbering():
    # The Filosofía book: every heading in one type size, level 3.
    blocks = [
        Heading("Prólogo", 3),  # front matter: the top level
        Heading("I. Los presocráticos", 3),
        Heading("1. Tales", 3),
        Heading("a) Vida", 3),
        Heading("b) Obra", 3),
        Heading("2. Anaximandro", 3),
        Heading("II. Sócrates", 3),
    ]
    assert _levels(blocks) == [1, 1, 2, 3, 3, 2, 1]


def test_unnumbered_headings_among_flat_numbered_ones_go_to_the_top():
    # The Filosofía book: a contents page set as headings, then the chapters; an
    # unnumbered capitals kind (BIBLIOGRAFÍA) once ranked between I. and 1.
    blocks = [
        Heading("UNIVERSIDAD SAN DÁMASO", 1, source="tags"),  # a tagged cover: still ranked
        Heading("Prof. Dr. Enrique González", 2),  # the cover: front matter, to the top
        Heading("INTRODUCCIÓN A LA FILOSOFÍA", 1),
        Heading("I. ¿QUÉ ES FILOSOFÍA?", 3),
        Heading("II. HUMANISMO Y FILOSOFÍA", 3),
        Heading("BIBLIOGRAFÍA", 3),
        Heading("I. ¿QUÉ ES FILOSOFÍA?", 3),
        Heading("2. La Sabiduría divina", 3),
        Heading("¿Contiene algún razonamiento experimental acerca de", 3),
        Heading("III. ALGUNOS TEMAS FILOSÓFICOS", 3),
        Heading("1. La verdad", 3),
        Heading("a) La verdad como adecuación", 3),
        Heading("g) Conclusión", 3),
        Heading("2. El hombre como alma y cuerpo", 3),
    ]
    assert _levels(blocks) == [1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 2, 3, 3, 2]


def test_sizes_that_already_nest_are_left_alone():
    blocks = [Heading("Capítulo 1", 1), Heading("1. Uno", 2), Heading("a) Uno", 2)]
    assert outline.collect(blocks, []) == {}
    assert _levels(blocks) == [1, 2, 2]
    # The dialogos book: unnumbered headings in two sizes, a few numbered ones in one.
    dialogos = [
        Heading("FILEBO", 2),
        Heading("NOTA AL TEXTO", 3),
        Heading("1) Ediciones:", 4),
        Heading("Estructura y finalidad del diálogo", 3),
        Heading("BIBLIOGRAFÍA", 2),
        Heading("2) Comentarios:", 4),
    ]
    assert outline.collect(dialogos, []) == {}


def test_marks_and_tags_headings_keep_their_level(make_pdf):
    blocks = [
        Heading("I. Uno", 4, 0, source="tags"),
        Heading("1. Uno", 3, 0),
        Heading("a) Uno", 5, 0, source="marks"),
        Heading("II. Dos", 5, 0),
    ]
    # Marks or tags headings in the book: no ranking by numbering.
    assert _levels(blocks) == _levels(blocks, marked=True) == [4, 3, 5, 5]
    toc = _bookmarks(make_pdf, [[1, "I. Uno", 1], [2, "Uno", 1], [3, "a) Uno", 1]])
    # "II. Dos" follows the marks heading before it at that heading's own level, 5.
    assert _levels(blocks, toc, marked=True) == [4, 2, 5, 5]


def test_other_blocks_come_out_identical():
    blocks = [Paragraph("texto"), Heading("I. Uno", 2), Note("1", "nota"), Heading("1. a", 2)]
    out = list(outline.apply(blocks, outline.collect(blocks, [])))
    assert [b for b in out if not isinstance(b, Heading)] == [blocks[0], blocks[2]]
    assert out[0] is blocks[0] and out[2] is blocks[2]


def _book(make_layout_pdf, title_rows, tmp_path, scan):
    body = "The quick brown fox jumps over the lazy dog and keeps running far."
    pdf = make_layout_pdf(
        [
            [
                (72, 80, "Chapter One", 18),
                (72, 120, body, 11),
                (72, 250, "Section A", 18),
                (72, 290, body, 11),
            ]
        ]
    )
    with pymupdf.open(pdf) as doc:
        doc.set_toc([[1, "Chapter One", 1], [2, "Section A", 1]])
        if scan:  # a full-page image under the text: a scan with its text layer
            pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 8, 8), False)
            doc[0].insert_image(doc[0].rect, pixmap=pix, keep_proportion=False, overlay=False)
        doc.saveIncr()
    blocks = tmp_path / "book.blocks.jsonl"
    convert_pdf(pdf, tmp_path / "book.md", "md", layout_rows=title_rows(pdf), blocks_path=blocks)
    return [(plain(b.text), b.level) for b in read_blocks(blocks) if isinstance(b, Heading)]


def test_bookmarks_reach_the_book_but_not_a_scan(make_layout_pdf, title_rows, tmp_path):
    assert _book(make_layout_pdf, title_rows, tmp_path, scan=False) == [
        ("Chapter One", 1),
        ("Section A", 2),
    ]
    assert _book(make_layout_pdf, title_rows, tmp_path, scan=True) == [
        ("Chapter One", 1),
        ("Section A", 1),
    ]

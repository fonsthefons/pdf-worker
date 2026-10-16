"""Books built straight from PaddleOCR-VL blocks (no Paddle needed: rows are given)."""

import json
import sys
from collections import Counter

import pymupdf
import pytest

from pdf_worker import paddle_ocr
from pdf_worker.convert import convert_pdf
from pdf_worker.inline import margin_ref, page_mark, plain
from pdf_worker.paddle_book import (
    _Book,
    iter_paddle_blocks,
    restore_question_marks,
    spanish_letters,
)
from pdf_worker.structure import Gloss, Heading, Note, Paragraph

pytest.importorskip("pymupdf_fonts")

INTRO = "La primera nota llamativa en el Filebo es su indeterminación dramática. " * 8


def _row(page: int, *blocks: tuple[str, list, str]) -> dict:
    return {
        "page": page,
        "width": 1190,
        "height": 1684,
        "blocks": [{"label": a, "bbox": b, "text": t} for a, b, t in blocks],
    }


ROWS = [
    _row(
        0, ("doc_title", [300, 600, 900, 700], "DIÁLOGOS"), ("text", [400, 900, 800, 950], "GREDOS")
    ),
    _row(
        1,
        ("paragraph_title", [400, 200, 800, 260], "INTRODUCCIÓN"),
        ("text", [144, 300, 1046, 1200], INTRO + "el cambio de $ ^{1} $ inter-\nlocutor y de"),
        ("footnote", [144, 1400, 1046, 1440], "Estos cambios ocurren."),
    ),
    _row(
        2,
        ("header", [500, 60, 700, 90], "DIÁLOGOS"),
        ("number", [144, 60, 180, 90], "10"),
        ("text", [144, 120, 1046, 400], "tiempo. " + INTRO),
        ("paragraph_title", [400, 500, 800, 560], "FILEBO"),
        ("header", [400, 600, 800, 640], "SÓCRATES, PROTARCO"),
        ("text", [144, 700, 1046, 900], "Sóc.—Considera, pues, Protarco, esta tesis $ ^{1} $."),
        ("text", [200, 910, 600, 940], "PRO. — De acuerdo."),
        ("footnote", [144, 1400, 1046, 1440], "$ ^{1} $ El objeto de la discusión."),
    ),
]


@pytest.fixture
def scan_pdf(tmp_path):
    path = tmp_path / "scan.pdf"
    with pymupdf.open() as doc:
        for _ in ROWS:
            doc.new_page()
        doc.save(path)
    return path


def test_blocks_follow_paddles_labels(scan_pdf):
    with pymupdf.open(scan_pdf) as doc:
        blocks = list(iter_paddle_blocks(doc, ROWS, images=False))

    headings = [b.text for b in blocks if isinstance(b, Heading)]
    paragraphs = [b for b in blocks if isinstance(b, Paragraph)]
    notes = [b for b in blocks if isinstance(b, Note)]
    assert headings == ["INTRODUCCIÓN", "FILEBO"]  # the title page is front matter
    # One paragraph across the page break; the running head and page number are gone.
    intro = plain(paragraphs[0].text)
    assert "interlocutor y de tiempo." in intro and "DIÁLOGOS" not in intro
    assert "[^c0-1]" in intro
    assert paragraphs[1].small and paragraphs[1].text == "SÓCRATES, PROTARCO"
    assert paragraphs[2].text.startswith("SÓC. — Considera") and "[^c1-1]" in paragraphs[2].text
    assert paragraphs[3].text == "PRO. — De acuerdo."
    # The dialogue's notes count from 1 again: a new part.
    assert [(n.label, n.text) for n in notes] == [
        ("c0-1", "Estos cambios ocurren."),
        ("c1-1", "El objeto de la discusión."),
    ]


def test_convert_from_paddle_rows_with_notes_at_the_end(scan_pdf, tmp_path):
    out = tmp_path / "book.pdf"
    convert_pdf(scan_pdf, out, "pdf", paddle_rows=ROWS, notes_at="end")
    with pymupdf.open(out) as doc:
        text = "".join(page.get_text() for page in doc)
    # All notes in the notes section after the text, not at the foot of their pages.
    assert text.index("De acuerdo") < text.index("Estos cambios") < text.index("El objeto")


def test_worker_progress_reaches_the_caller_and_errors_keep_their_tail(tmp_path, monkeypatch):
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import sys\n"
        "for n in (1, 2):\n"
        "    print(f'paddle: page {n}/2', file=sys.stderr)\n"
        "print('boom', file=sys.stderr)\n"
        "sys.exit(1)\n"
    )
    monkeypatch.setattr(paddle_ocr, "_WORKER", worker)
    seen = []
    with pytest.raises(paddle_ocr.OcrError, match="boom"):
        paddle_ocr._run_worker(
            sys.executable, "x.pdf", [0, 1], tmp_path / "o", tmp_path, "s", False, seen.append
        )
    assert seen == [1, 2]


def test_pages_missing_from_the_scan_take_their_notes_with_them(tmp_path):
    # Printed pages 279 -> 282: notes 7-12 were on 280-281; "¹" is a misread "¹³".
    rows = [
        _row(
            0,
            ("number", [144, 60, 180, 90], "279"),
            ("text", [144, 120, 1046, 400], INTRO + "el orden $ ^{6} $."),
            ("footnote", [144, 1400, 1046, 1440], "6 Tal como lo muestra."),
        ),
        _row(
            1,
            ("number", [144, 60, 180, 90], "282"),
            ("text", [144, 120, 1046, 400], "Inundaciones en nueve mil años $ ^{13} $. " + INTRO),
            ("footnote", [144, 1400, 1046, 1440], "$ ^{1} $ Como se ve Critias."),
        ),
    ]
    path = tmp_path / "gap.pdf"
    with pymupdf.open() as doc:
        for _ in rows:
            doc.new_page()
        doc.save(path)
    with pymupdf.open(path) as doc:
        notes = [b for b in iter_paddle_blocks(doc, rows, images=False) if isinstance(b, Note)]
    assert [n.label for n in notes] == ["c0-6", "c0-13"]


def test_two_notes_read_as_one_block_are_split(tmp_path):
    rows = [
        _row(
            0,
            ("text", [144, 300, 1046, 900], INTRO + " J 28 $ ^{10} $ y J 31 $ ^{11} $."),
            ("footnote", [144, 1400, 1046, 1440], "10. J 28.\n11. J 31."),
        )
    ]
    path = tmp_path / "two.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(path)
    with pymupdf.open(path) as doc:
        notes = [b for b in iter_paddle_blocks(doc, rows, images=False) if isinstance(b, Note)]
    assert [(n.label, n.text) for n in notes] == [("c0-10", "J 28."), ("c0-11", "J 31.")]


def test_a_readers_tick_in_the_margin_is_no_gloss(tmp_path):
    rows = [
        _row(
            0,
            ("text", [144, 300, 1046, 900], INTRO),
            ("aside_text", [1060, 400, 1090, 430], "！"),
            ("aside_text", [1060, 500, 1150, 560], "-a -ā:\nItalia"),
        )
    ]
    path = tmp_path / "tick.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(path)
    with pymupdf.open(path) as doc:
        blocks = list(iter_paddle_blocks(doc, rows, images=False))
    assert [b.lines for b in blocks if isinstance(b, Gloss)] == [("-a -ā:", "Italia")]


def test_a_printed_table_of_contents_is_dropped(tmp_path):
    rows = [
        _row(
            0,
            ("paragraph_title", [400, 200, 800, 260], "PRÓLOGO"),
            ("text", [144, 300, 1046, 900], INTRO),
        ),
        _row(
            1,
            ("paragraph_title", [400, 200, 800, 260], "ÍNDICE"),
            ("content", [144, 300, 1046, 900], "III. ROUSSEAU.—I ..... 6\nVida y escritos."),
            ("paragraph_title", [400, 950, 800, 990], "PARTE IV"),
            ("text", [144, 1000, 1046, 1300], INTRO),
        ),
    ]
    path = tmp_path / "toc.pdf"
    with pymupdf.open() as doc:
        for _ in rows:
            doc.new_page()
        doc.save(path)
    with pymupdf.open(path) as doc:
        blocks = list(iter_paddle_blocks(doc, rows, images=False))
    assert [b.text for b in blocks if isinstance(b, Heading)] == ["PRÓLOGO"]
    assert "ROUSSEAU" not in " ".join(plain(b.text) for b in blocks if isinstance(b, Paragraph))


def test_a_margin_mark_read_into_the_text_goes():
    book = _Book(lambda reading: "17b")
    assert plain(book._body_text("de niño. b PRO.— ¡Cómo?", [(3, "b")])) == (
        "de niño. PRO.— ¡Cómo?"
    )
    book = _Book(lambda reading: "26a")
    text = book._body_text("26 PRO.— Totalmente.", [(0, "26")])
    assert text.startswith(margin_ref("26a")) and plain(text) == "PRO. — Totalmente."
    # A vowel is a word: "e" stays.
    book = _Book(lambda reading: "40b")
    assert plain(book._body_text("e iba", [(1, "?")])) == "e iba"
    # On a word broken at the line end, the reference goes before the whole word.
    book = _Book(lambda reading: "108d")
    assert (
        book._body_text("e invo- car, junto", [(2, "d")])
        == "e " + margin_ref("108d") + "invocar, junto"
    )


def test_a_word_broken_across_pages_keeps_the_page_mark_before_it():
    book = _Book(lambda reading: None)
    list(book.add_page(None, {}, [("text", None, "además, some-")], {}, False))
    book.marks.append(page_mark(140, "145"))
    list(book.add_page(None, {}, [("text", None, "tieron a crítica")], {}, False))
    assert book.para == "además, " + page_mark(140, "145") + "sometieron a crítica"


def test_a_question_mark_read_as_a_letter_is_put_back():
    counts = Counter({"por": 40, "idea": 5, "dea": 0, "qué": 30})
    assert restore_question_marks("PRO. — iY bien? lPor qué no? 2El qué?", counts) == (
        "PRO. — ¿Y bien? ¿Por qué no? ¿El qué?"
    )
    assert restore_question_marks("Y ipor qué?", counts) == "Y ¿por qué?"
    assert restore_question_marks("PRO. — L Cómo no?", counts) == "PRO. — ¿Cómo no?"
    assert restore_question_marks("de l por qué?", counts) == "de l por qué?"
    assert spanish_letters("Sốc. — Sị; aún así, ñandú") == "Sóc. — Si; aún así, ñandú"
    # A real word stays, and so does anything outside a question.
    assert restore_question_marks("¿Tienes idea? Isla grande. iY bien!", counts) == (
        "¿Tienes idea? Isla grande. iY bien!"
    )


def test_book_pages_are_counted(scan_pdf):
    seen = []
    with pymupdf.open(scan_pdf) as doc:
        list(iter_paddle_blocks(doc, ROWS, images=False, on_page=lambda d, t: seen.append((d, t))))
    assert seen[0] == (0, len(ROWS)) and seen[-1] == (len(ROWS), len(ROWS))


def test_cached_pages_need_no_paddle(tmp_path, monkeypatch, make_pdf):
    monkeypatch.setenv("PDF_WORKER_PADDLE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("PDF_WORKER_PADDLE_PYTHON", str(tmp_path / "nope" / "python"))
    pdf = make_pdf(["x", "y"])
    cache = paddle_ocr._pages_cache(pdf)
    cache.parent.mkdir(parents=True)
    rows = [_row(1, ("text", [0, 0, 10, 10], "uno")), _row(0, ("text", [0, 0, 10, 10], "cero"))]
    cache.write_text("".join(json.dumps(r) + "\n" for r in rows) + '{"page": 2, "blo')

    assert [r["page"] for r in paddle_ocr.paddle_pages(pdf, [0, 1])] == [0, 1]
    with pytest.raises(paddle_ocr.OcrEngineMissingError):
        paddle_ocr.paddle_pages(pdf, [0, 1, 2])  # page 2 (cut short) must be read again

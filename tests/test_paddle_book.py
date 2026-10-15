"""Books built straight from PaddleOCR-VL blocks (no Paddle needed: rows are given)."""

import json

import pymupdf
import pytest

from pdf_worker import paddle_ocr
from pdf_worker.convert import convert_pdf
from pdf_worker.inline import plain
from pdf_worker.paddle_book import iter_paddle_blocks
from pdf_worker.structure import Heading, Note, Paragraph

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

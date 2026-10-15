"""Poor scans with their own OCR layer (ABBYY FineReader): underlines, page boxes that
don't start at (0, 0), odd space sizes, margin marks, soft hyphens, dialogue."""

import pymupdf
import pytest

from pdf_worker.footnotes import BodyLine
from pdf_worker.inline import margin_ref
from pdf_worker.layout import Line, ink_bbox
from pdf_worker.margins import _trim_edge_marks
from pdf_worker.ocr_check import assess_text_layer
from pdf_worker.structure import _page_margins, join_lines

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

TEXT = [
    "The quick brown fox jumps over the lazy dog and keeps running far",
    "away across the green fields until the evening light finally fades",
    "into a calm and quiet night where every sound seems to have gone.",
]


def _span(text, x0, x1, size=10.0, top=0.0):
    return {"text": text, "bbox": (x0, top, x1, top + size), "size": size, "flags": 0}


def _line(*spans, size=10.0):
    return Line(spans=spans, size=size, bbox=ink_bbox(spans, (0, 0, 0, 0)))


def test_underline_dots_are_erased_but_letters_stops_and_dashes_stay():
    from pdf_worker.underlines import erase_underlines

    page = np.full((200, 600), 255, dtype=np.uint8)
    for x in range(50, 550, 30):
        page[60:85, x : x + 20] = 0  # "letters"
    page[95:98, 50:550:8] = 0  # a dotted pencil underline under them
    page[95:98, 51:550:8] = 0
    page[150:154, 100:104] = 0  # a full stop
    page[140:143, 200:245] = 0  # an em dash

    cleaned, broken = erase_underlines(page, 300)

    assert broken == 1
    assert (cleaned[95:98] == 255).all()
    assert (cleaned[60:85, 50:70] == 0).all()
    assert (cleaned[150:154, 100:104] == 0).all() and (cleaned[140:143, 200:245] == 0).all()


def _underlined_scan(tmp_path):
    source = pymupdf.open()
    page = source.new_page()
    for i, text in enumerate(TEXT * 3):
        page.insert_text((72, 100 + 18 * i), text, fontsize=14)
        if i < 4:  # a reader's dotted pencil line under the first four lines
            page.draw_line((72, 104 + 18 * i), (450, 104 + 18 * i), width=1, dashes="[2 3] 0")
    picture = page.get_pixmap(dpi=200)
    path = tmp_path / "underlined.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        target = doc.new_page()
        target.insert_image(target.rect, pixmap=picture)
        for i, text in enumerate(TEXT * 3):
            target.insert_text((72, 100 + 18 * i), text, fontsize=14, render_mode=3)
    doc.save(path)
    return path


def test_underlined_pages_of_a_scan_are_redone(tmp_path):
    with pymupdf.open(_underlined_scan(tmp_path)) as doc:
        report = assess_text_layer(doc)

    assert report.mode == "redo"
    assert report.pages == (1, 2, 3)
    assert "underlines" in report.reason


def test_page_boxes_are_moved_to_the_origin_for_ocr(tmp_path):
    from pdf_worker.ocr import _zero_origin_copy

    source = tmp_path / "spread.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=660, height=500)
    page.insert_text((400, 100), "right-hand page", fontsize=12)
    page.set_mediabox(pymupdf.Rect(330, 0, 660, 500))
    doc.save(source)
    target = tmp_path / "moved.pdf"

    assert _zero_origin_copy(source, target)
    with pymupdf.open(source) as before, pymupdf.open(target) as after:
        old = before[0].search_for("right-hand")[0]
        new = after[0].search_for("right-hand")[0]
        assert tuple(after[0].mediabox) == (0, 0, 330, 500)
        assert new == old  # same place on the visible page
    assert not _zero_origin_copy(target, tmp_path / "unused.pdf")


def test_space_sizes_do_not_move_the_line():
    line = _line(
        _span("razón.", 88, 114, top=274),
        _span(" ", 114, 262, size=35, top=258),
        _span("Y", 262, 270, top=274),
    )

    assert line.top == 274


def test_margin_marks_glued_onto_a_line_become_margin_references():
    tail = _line(_span("una y otra.", 36, 260), _span(" ", 260, 293), _span("b", 294, 298))
    head = _line(_span("d", 20, 24), _span(" ", 24, 50), _span("Pro. — En efecto.", 50, 200))
    misread = _line(_span("Niobe y", 36, 260), _span(" ", 260, 293), _span("h", 294, 298))
    reference = _line(_span("cuantos son capaces de ellos,³", 36, 291))

    trimmed_tail = _trim_edge_marks(BodyLine("una y otra. b", tail), 36, 290, 10)
    trimmed_head = _trim_edge_marks(BodyLine("d Pro. — En efecto.", head), 36, 290, 10)
    trimmed_misread = _trim_edge_marks(BodyLine("Niobe y h", misread), 36, 290, 10)

    # Out of the text, kept as a reference that opens the line.
    assert trimmed_tail.text.strip() == margin_ref("b") + "una y otra."
    assert trimmed_tail.line.x1 == 260
    assert trimmed_head.text == margin_ref("d") + "Pro. — En efecto." and trimmed_head.line.x0 == 50
    assert trimmed_misread.text.strip() == margin_ref("?") + "Niobe y"  # named by the sequence
    assert _trim_edge_marks(BodyLine(reference.text, reference), 36, 290, 10).text == reference.text


def test_scanner_edges_are_not_pictures():
    from pdf_worker.images import _blank_scan_edges

    width, height = 40, 50
    pixels = bytearray([255]) * (width * height)
    for row in range(height):
        pixels[row * width : row * width + 3] = bytes(3)  # black bar down the left edge
    for row in range(10, 20):
        pixels[row * width + 15 : row * width + 25] = bytes(10)  # a picture

    _blank_scan_edges(pixels, width, height, dark=128)

    assert all(pixels[row * width] == 255 for row in range(height))
    assert pixels[15 * width + 20] == 0


def test_soft_hyphens_join_words():
    assert join_lines(["La refuta­", "ción por parte"]) == "La refutación por parte"


def test_dialogue_indents_are_seen_although_most_lines_are_indented():
    speakers = [_line(_span("PRO. — Así es.", 82, 150, top=20 * i)) for i in range(6)]
    wrapped = [_line(_span("de manifiesto un estado", 66, 320, top=200 + 20 * i)) for i in range(4)]

    margins = _page_margins([BodyLine(ln.text, ln) for ln in speakers + wrapped], 10.0)

    assert margins.left == 66

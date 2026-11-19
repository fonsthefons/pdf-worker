import json

import pymupdf
import pytest

from pdf_worker import spreads
from pdf_worker.document import open_pdf

SIDES = [
    [f"{side} line {k} " + " ".join(f"{side[0]}{k}w{j}" for j in range(6)) for k in range(12)]
    for side in ("left", "right")
]


def _spread_page(doc, xs=(60, 460), width=800):
    page = doc.new_page(width=width, height=560)
    for x, lines in zip(xs, SIDES, strict=True):
        for k, line in enumerate(lines):
            page.insert_text((x, 80 + 14 * k), line, fontsize=9)
    return page


def _save(doc, path):
    doc.save(path)
    doc.close()
    return path


def _judged(path):
    with open_pdf(path) as doc:
        return spreads.judge_book(doc)


def test_a_landscape_sheet_of_two_blocks_is_cut_at_its_gutter(tmp_path):
    doc = pymupdf.open()
    _spread_page(doc)
    src = _save(doc, tmp_path / "spread.pdf")

    sheets = _judged(src)
    assert [s.cut for s in sheets] == [True] and 330 < sheets[0].gutter < 460
    pages = spreads.split(src, tmp_path / "cut.pdf", sheets)

    assert [(p["page"], p["sheet"], p["side"]) for p in pages] == [(1, 1, "left"), (2, 1, "right")]
    assert json.loads((tmp_path / "cut.pages.json").read_text()) == pages
    with open_pdf(tmp_path / "cut.pdf") as doc:
        got = [[row[3] for row in spreads._rows(page)] for page in doc]
    assert got == SIDES


@pytest.mark.parametrize("kind", ["rotate90", "rotate270", "cropped"])
def test_a_rotated_or_cropped_spread_is_cut_into_its_halves(tmp_path, kind):
    """A /Rotate sheet (its page_lines unrotated) and a CropBox inside the MediaBox."""
    spread = pymupdf.open()
    _spread_page(spread)
    doc = pymupdf.open()
    if kind == "cropped":
        page = doc.new_page(width=900, height=660)
        page.show_pdf_page(pymupdf.Rect(50, 50, 850, 610), spread, 0)
        page.insert_text((60, 30), "a crop mark outside the crop box " * 3, fontsize=9)
        page.set_cropbox(pymupdf.Rect(50, 50, 850, 610))
    else:  # an upright MediaBox shown sideways: the spread is upright on screen
        turn = int(kind.removeprefix("rotate"))
        page = doc.new_page(width=560, height=800)
        page.show_pdf_page(page.rect, spread, 0, rotate=turn)
        page.set_rotation(turn)
    src = _save(doc, tmp_path / "sheet.pdf")

    sheets = _judged(src)
    assert [s.cut for s in sheets] == [True]
    spreads.split(src, tmp_path / "cut.pdf", sheets)
    with open_pdf(tmp_path / "cut.pdf") as doc:
        assert [[row[3] for row in spreads._rows(page)] for page in doc] == SIDES
        assert all(page.rect.height == 560 and page.rect.width < 450 for page in doc)


def test_a_scanned_spread_with_a_gutter_shadow_is_cut_by_its_picture(tmp_path):
    doc = pymupdf.open()
    page = _spread_page(doc)
    for k in range(20):  # a smooth dark shadow down the gutter
        grey = 0.4 + 0.6 * abs(k - 10) / 10
        page.draw_rect(pymupdf.Rect(390 + k, 0, 391 + k, 560), color=None, fill=(grey,) * 3)
    picture = page.get_pixmap(dpi=100)
    scan = pymupdf.open()
    scan.new_page(width=800, height=560).insert_image(scan[0].rect, pixmap=picture)
    src = _save(scan, tmp_path / "scan.pdf")

    [sheet] = _judged(src)

    assert sheet.cut and (sheet.left, sheet.right, sheet.crossing) == (1, 1, 0)
    assert 360 < sheet.gutter < 440
    # A picture that fills the sheet is not cut.
    plate = pymupdf.open()
    page = plate.new_page(width=800, height=560)
    for k in range(40):
        page.insert_text((40, 20 + 13 * k), "a picture crossing the middle " * 4, fontsize=8)
    scan = pymupdf.open()
    scan.new_page(width=800, height=560).insert_image(
        scan[0].rect, pixmap=plate[0].get_pixmap(dpi=100)
    )
    assert not any(s.cut for s in _judged(_save(scan, tmp_path / "plate.pdf")))


def test_one_block_and_two_column_upright_pages_are_not_cut(make_pdf, tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=560)
    for k in range(20):
        page.insert_text((60, 80 + 14 * k), "one block of text that runs across the middle " * 2)
    _spread_page(doc, xs=(60, 310), width=560)  # upright, two columns
    assert not any(s.cut for s in _judged(_save(doc, tmp_path / "pages.pdf")))
    assert not any(s.cut for s in _judged(make_pdf(["\n".join(SIDES[0])])))


def test_a_landscape_table_is_not_cut(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=560)
    for k in range(20):  # four columns of cells, none across the middle
        for j, x in enumerate((60, 230, 430, 600)):
            page.insert_text((x, 80 + 20 * k), f"cell {k}.{j} value", fontsize=9)
    [sheet] = _judged(_save(doc, tmp_path / "table.pdf"))
    assert sheet.rule and not sheet.cut

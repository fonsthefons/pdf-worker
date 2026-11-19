import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check  # noqa: E402


def _row(page: int, *labels: str) -> dict:
    return {"page": page, "width": 100, "height": 100, "blocks": [{"label": x} for x in labels]}


def test_pick_takes_first_window_and_richest_windows_and_all_of_a_small_book():
    assert check.pick_pages({}, 5) == [0, 1, 2, 3, 4]
    rows = {p: _row(p, "paragraph_title", "footnote") for p in (30, 31, 60, 61, 62, 90)}
    pages = check.pick_pages(rows, 100)
    assert pages[:8] == list(range(8))
    assert len(pages) == check.WINDOWS * check.WIDTH == len(set(pages))
    assert {30, 31, 60, 61, 62, 90} <= set(pages)


def test_remap_numbers_rows_as_in_the_cut_and_cut_keeps_those_pages(make_pdf):
    pdf = make_pdf([f"page {i}" for i in range(10)])
    rows = {p: _row(p, "text") for p in (2, 5, 7)}
    mapped = check.remap(rows, [2, 3, 7])
    assert sorted(mapped) == [0, 2] and mapped[2]["page"] == 2 and rows[7]["page"] == 7
    sub = check.cut(pdf, [2, 3, 7], "unit-test")
    try:
        with pymupdf.open(sub) as doc:
            assert [p.get_text().strip() for p in doc] == ["page 2", "page 3", "page 7"]
    finally:
        sub.unlink()

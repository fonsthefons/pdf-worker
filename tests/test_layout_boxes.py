import os

import pymupdf
import pytest
from conftest import REPO_ROOT

from pdf_worker import paddle_ocr
from pdf_worker.layout import box_labels, page_lines


def test_each_line_gets_the_label_of_the_box_covering_most_of_it(make_layout_pdf):
    pdf = make_layout_pdf(
        [[(72, 100, "A running head", 9), (72, 300, "Body text here", 11), (72, 700, "Note", 8)]]
    )
    with pymupdf.open(pdf) as doc:
        page = doc[0]
        lines = page_lines(page)
        heads, body, note = (line.bbox for line in lines)
        # The row is in pixels of an image twice the page's size.
        row = {
            "page": 0,
            "width": page.rect.width * 2,
            "height": page.rect.height * 2,
            "blocks": [
                {"label": "header", "score": 0.9, "bbox": [2 * c for c in (60, 80, 400, 110)]},
                # Covers only the left third of the body line.
                {
                    "label": "text",
                    "score": 0.9,
                    "bbox": [2 * c for c in (60, body[1], (body[0] + body[2]) / 3, body[3])],
                },
            ],
        }

        assert box_labels(page, row, lines) == ["header", "", ""]


@pytest.mark.integration
@pytest.mark.skipif(
    not paddle_ocr._DEFAULT_PYTHON.is_file() and "PDF_WORKER_PADDLE_PYTHON" not in os.environ,
    reason="PaddleOCR environment not installed",
)
def test_layout_model_boxes_a_page(tmp_path, monkeypatch, make_layout_pdf):
    local_cache = REPO_ROOT / "scratch" / "paddle-home"  # the model files, if downloaded
    if local_cache.is_dir():
        monkeypatch.setenv("PDF_WORKER_PADDLE_CACHE", str(local_cache))
    pdf = make_layout_pdf(
        [[(72, 100 + 14 * i, "A line of plain body text in the book.", 11) for i in range(20)]]
    )
    calls = []

    rows = paddle_ocr.layout_pages(pdf, on_page=lambda done, total: calls.append((done, total)))

    assert list(rows) == [0]
    assert rows[0]["width"] > 0 and rows[0]["height"] > 0
    assert any(block["label"] == "text" for block in rows[0]["blocks"])
    assert calls[-1] == (1, 1)
    assert paddle_ocr.layout_pages(pdf) == rows  # cached

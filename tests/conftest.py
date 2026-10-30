from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_PDFS_DIR = REPO_ROOT / "test_pdfs"


def pytest_configure(config: pytest.Config) -> None:
    # Keep tmp_path inside the repo (not the system temp dir); see CLAUDE.md.
    if config.option.basetemp is None:
        config.option.basetemp = REPO_ROOT / "scratch" / "pytest"


@pytest.fixture(autouse=True)
def _tesseract_cache_per_test(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Each test reads with Tesseract afresh, and nothing is written outside the repo.
    monkeypatch.setenv("PDF_WORKER_TESSERACT_CACHE", str(tmp_path / "tesseract-cache"))


@pytest.fixture(autouse=True)
def _decisions_per_test(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests start with no word decisions and never write ai-client's own file.
    from ai_client import check

    monkeypatch.setattr(check.config, "DECISIONS_FILE", tmp_path / "decisions.tsv")


@pytest.fixture
def make_pdf(tmp_path: Path) -> Callable[..., Path]:
    """Build a small PDF where each entry in ``pages`` is that page's text.

    An empty string produces a page with no text layer (like a scanned image).
    """

    def _make(pages: list[str], name: str = "sample.pdf") -> Path:
        path = tmp_path / name
        doc = pymupdf.open()
        for text in pages:
            page = doc.new_page()
            if text:
                page.insert_text((72, 72), text)
        doc.save(path)
        doc.close()
        return path

    return _make


@pytest.fixture
def make_layout_pdf(tmp_path: Path) -> Callable[..., Path]:
    """Build a PDF from explicitly placed text: one list of items per page.

    Each item is ``(x, y, text, fontsize)``; ``y`` is the baseline. Use a smaller font
    and a raised ``y`` for superscript markers.
    """

    def _make(pages: list[list[tuple[float, float, str, float]]], name: str = "layout.pdf") -> Path:
        path = tmp_path / name
        doc = pymupdf.open()
        for items in pages:
            page = doc.new_page()
            for x, y, text, size in items:
                page.insert_text((x, y), text, fontsize=size)
        doc.save(path)
        doc.close()
        return path

    return _make


@pytest.fixture
def title_rows() -> Callable[..., dict[int, dict]]:
    """Layout rows (``paddle_ocr.layout_pages``) that box each line of ``min_size`` or
    more as a ``paragraph_title``: the layout model's say on a test book's headings."""
    from pdf_worker.layout import page_lines

    def _rows(pdf: Path, min_size: float = 12) -> dict[int, dict]:
        rows = {}
        with pymupdf.open(pdf) as doc:
            for index, page in enumerate(doc):
                blocks = [
                    {"label": "paragraph_title", "score": 0.9, "bbox": list(line.bbox)}
                    for line in page_lines(page)
                    if line.size >= min_size
                ]
                rect = page.rect
                rows[index] = {
                    "page": index,
                    "width": rect.width,
                    "height": rect.height,
                    "blocks": blocks,
                }
        return rows

    return _rows

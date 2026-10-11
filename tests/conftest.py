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

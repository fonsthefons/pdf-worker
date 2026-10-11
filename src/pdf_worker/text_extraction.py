"""Extract the text layer of a PDF into plain text.

Pages are processed one at a time and streamed to the output, so memory use
stays flat regardless of document length.
"""

import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from pdf_worker.document import open_pdf

# Form feed is the conventional page break in plain text (also used by pdftotext).
DEFAULT_PAGE_SEPARATOR = "\f"


@dataclass(frozen=True)
class PageText:
    number: int  # 1-based, as shown in PDF viewers
    text: str

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass
class ExtractionReport:
    output_path: Path
    page_count: int = 0
    char_count: int = 0
    empty_pages: list[int] = field(default_factory=list)


def iter_page_texts(pdf_path: str | Path) -> Iterator[PageText]:
    """Yield the text of each page in order, loading one page at a time."""
    with open_pdf(pdf_path) as doc:
        for index in range(doc.page_count):
            page = doc.load_page(index)
            yield PageText(number=index + 1, text=page.get_text("text"))


def extract_text_to_file(
    pdf_path: str | Path,
    output_path: str | Path,
    page_separator: str = DEFAULT_PAGE_SEPARATOR,
) -> ExtractionReport:
    """Write the text of every page of ``pdf_path`` to ``output_path`` (UTF-8).

    The output is written to a temporary file and moved into place only on
    success, so a failed run never leaves a truncated ``.txt`` behind.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = ExtractionReport(output_path=output_path)

    fd, tmp_name = tempfile.mkstemp(
        dir=output_path.parent, prefix=f".{output_path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            for page in iter_page_texts(pdf_path):
                if page.number > 1:
                    out.write(page_separator)
                out.write(page.text)
                report.page_count += 1
                report.char_count += len(page.text)
                if page.is_empty:
                    report.empty_pages.append(page.number)
        os.replace(tmp_name, output_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return report


def default_output_path(pdf_path: str | Path) -> Path:
    """``book.pdf`` -> ``book.txt`` alongside the input."""
    return Path(pdf_path).with_suffix(".txt")

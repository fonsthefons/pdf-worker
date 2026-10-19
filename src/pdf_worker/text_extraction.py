"""Extract the text layer of a PDF into plain text.

Pages are processed one at a time and streamed to the output, so memory use
stays flat regardless of document length. Footnotes and endnotes are marked
explicitly by default (see ``pdf_worker.footnotes``).
"""

import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from pdf_worker.document import open_pdf
from pdf_worker.footnotes import render_page
from pdf_worker.inline import STYLE_RE
from pdf_worker.layout import analyze_document, page_lines

# Form feed is the conventional page break in plain text (also used by pdftotext).
DEFAULT_PAGE_SEPARATOR = "\f"


@dataclass(frozen=True)
class PageText:
    number: int  # 1-based, as shown in PDF viewers
    text: str
    footnote_definitions: tuple[str, ...] = ()  # labels of notes defined on this page
    footnote_references: tuple[str, ...] = ()  # labels referenced from this page

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass
class ExtractionReport:
    output_path: Path
    page_count: int = 0
    char_count: int = 0
    empty_pages: list[int] = field(default_factory=list)
    footnote_count: int = 0
    footnote_reference_count: int = 0
    # Labels referenced in the text but never defined, and defined but never referenced.
    undefined_footnotes: list[str] = field(default_factory=list)
    unreferenced_footnotes: list[str] = field(default_factory=list)


def iter_page_texts(pdf_path: str | Path, footnotes: bool = True) -> Iterator[PageText]:
    """Yield the text of each page in order, loading one page at a time.

    With ``footnotes`` (the default) a quick analysis pass runs first, then each
    page's footnote references and definitions are marked in Markdown syntax.
    """
    with open_pdf(pdf_path) as doc:
        if not footnotes:
            for index in range(doc.page_count):
                lines = page_lines(doc.load_page(index))
                yield PageText(number=index + 1, text="".join(f"{line.text}\n" for line in lines))
            return
        profile = analyze_document(doc)
        previous_label = None
        for index in range(doc.page_count):
            rendered = render_page(doc.load_page(index), index, profile, previous_label)
            previous_label = rendered.trailing_label
            yield PageText(
                number=index + 1,
                text=STYLE_RE.sub("", rendered.text),  # plain text: no italics
                footnote_definitions=rendered.definitions,
                footnote_references=rendered.references,
            )


def extract_text_to_file(
    pdf_path: str | Path,
    output_path: str | Path,
    page_separator: str = DEFAULT_PAGE_SEPARATOR,
    footnotes: bool = True,
) -> ExtractionReport:
    """Write the text of every page of ``pdf_path`` to ``output_path`` (UTF-8).

    The output is written to a temporary file and moved into place only on
    success, so a failed run never leaves a truncated ``.txt`` behind.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = ExtractionReport(output_path=output_path)
    defined: set[str] = set()
    referenced: set[str] = set()

    fd, tmp_name = tempfile.mkstemp(
        dir=output_path.parent, prefix=f".{output_path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            for page in iter_page_texts(pdf_path, footnotes=footnotes):
                if page.number > 1:
                    out.write(page_separator)
                out.write(page.text)
                report.page_count += 1
                report.char_count += len(page.text)
                if page.is_empty:
                    report.empty_pages.append(page.number)
                report.footnote_count += len(page.footnote_definitions)
                report.footnote_reference_count += len(page.footnote_references)
                defined.update(page.footnote_definitions)
                referenced.update(page.footnote_references)
        report.undefined_footnotes = sorted(referenced - defined, key=_label_sort_key)
        report.unreferenced_footnotes = sorted(defined - referenced, key=_label_sort_key)
        os.replace(tmp_name, output_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return report


def _label_sort_key(label: str) -> tuple:
    """Sort labels like ``p2-1`` / ``p10-3`` / ``12`` in document order."""
    parts = label.lstrip("p").split("-")
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in parts)


def default_output_path(pdf_path: str | Path) -> Path:
    """``book.pdf`` -> ``book.txt`` alongside the input."""
    return Path(pdf_path).with_suffix(".txt")

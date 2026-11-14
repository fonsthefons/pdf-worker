"""Write the book as a tagged PDF typeset by Typst (A5 pages, like an e-book).

The book is written as Markdown first (``pdf_worker.markdown_export``, margin references
as raw Typst), turned into Typst source by Pandoc, given the rules of ``typst/book.typ``
(page, fonts, margin references, notes at the end) and compiled by the ``typst`` package.
"""

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import pymupdf
import typst

from pdf_worker.cover import cover_jpeg
from pdf_worker.docx_export import pandoc_path
from pdf_worker.epub import _notes_title
from pdf_worker.errors import PdfWorkerError
from pdf_worker.markdown_export import write_markdown
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import Block, Note, Paragraph

TEMPLATE = Path(__file__).parent / "typst" / "book.typ"
_CONF = "#show: doc => conf("
_REF = re.compile(r"\[\^([^\]]+)\]")


def write_pdf(
    blocks: Iterable[Block],
    output_path: Path,
    meta: Metadata,
    notes_at: str = "end",
    cover: bool = False,
    on_pass: Callable[[int, int], None] | None = None,
) -> WriteStats:
    """Typeset the book as an A5 PDF. ``notes_at``: "page" sets each footnote at the foot
    of its page, "end" gathers them in a notes section after the book. ``cover`` adds a
    text cover (``pdf_worker.cover``) as page 1, unnumbered. ``on_pass(done, 1)``: one
    pass."""
    pandoc = pandoc_path()
    if on_pass:
        on_pass(0, 1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=output_path.parent, prefix=f".{output_path.name}.w."))
    try:
        stats = write_markdown(_keep_unreferenced(blocks), work / "book.md", meta, typst=True)
        # No title block: the cover shows the title; the template sets the PDF's own.
        blank = ["-V", "title=", "-V", "author=", "-V", "date="]
        result = subprocess.run(
            [pandoc, "book.md", "-f", "markdown", "-t", "typst", "-s", "-o", "book.typ"]
            + ["--resource-path", ".", *blank],
            cwd=work,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise PdfWorkerError(f"Pandoc failed: {result.stderr.strip()[-500:]}")
        source_path = work / "book.typ"
        source = source_path.read_text(encoding="utf-8")
        # Pandoc's conf() sets letter paper and its own margins: our rules go after its call.
        try:
            at = source.index("\n)\n", source.index(_CONF)) + 3
        except ValueError:
            raise PdfWorkerError(
                "Pandoc's Typst template has no conf() call (a custom default.typst?)"
            ) from None
        rules = TEMPLATE.read_text(encoding="utf-8")
        source_path.write_text(source[:at] + rules + source[at:], encoding="utf-8")
        if cover:
            (work / "cover.jpg").write_bytes(cover_jpeg(meta))
        inputs = {
            "title": meta.title,
            "author": meta.author,
            "lang": meta.language.split("-")[0],
            "notes": notes_at,
            "notes-title": _notes_title(meta.language),
            "cover": "cover.jpg" if cover else "",
        }
        target = work / "book.pdf"
        try:
            typst.compile(str(source_path), output=str(target), sys_inputs=inputs)
        except typst.TypstError as error:
            raise PdfWorkerError(f"Typst failed: {str(error)[-500:]}") from error
        with pymupdf.open(target) as doc:
            stats.chapters = doc.page_count  # pages, for the summary
        os.replace(target, output_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if on_pass:
        on_pass(1, 1)
    return stats


def _keep_unreferenced(blocks: Iterable[Block]) -> Iterator[Block]:
    """Pandoc drops a footnote nothing refers to (OCR lost its number): keep such a note
    as a small paragraph where it stands. Notes follow their page's text, so a reference
    is always seen before its note."""
    seen: set[str] = set()
    for block in blocks:
        if isinstance(block, Note) and block.label not in seen:
            yield Paragraph(f"{block.label}. {block.text}")
            continue
        text = getattr(block, "text", None)
        if isinstance(text, str) and not isinstance(block, Note):
            seen.update(_REF.findall(text))
        for line in getattr(block, "lines", None) or []:
            seen.update(_REF.findall(line))
        for row in getattr(block, "rows", None) or []:
            for cell in row:
                seen.update(_REF.findall(cell))
        yield block

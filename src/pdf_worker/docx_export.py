"""Write the book as a Word document (.docx) with real Word footnotes.

The book is written as Markdown first (``pdf_worker.markdown_export``: Pandoc footnote
syntax, tables, pictures), then converted by Pandoc, which turns ``[^n]`` notes into
Word footnotes and the YAML front matter into document properties.
"""

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path
from xml.sax.saxutils import escape

from pdf_worker.cover import translated_by
from pdf_worker.errors import PdfWorkerError
from pdf_worker.markdown_export import write_markdown
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import Block


class PandocMissingError(PdfWorkerError):
    """Pandoc is needed for .docx output."""


def pandoc_path() -> str:
    path = shutil.which("pandoc") or shutil.which("/opt/homebrew/bin/pandoc")
    if not path:
        raise PandocMissingError("Word output needs Pandoc; install it with: brew install pandoc")
    return path


def write_docx(
    blocks: Iterable[Block], output_path: Path, meta: Metadata, cover: bool = False
) -> WriteStats:
    """``cover``: the title block (Pandoc's, from the metadata) and translator make page 1."""
    pandoc = pandoc_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=output_path.parent, prefix=f".{output_path.name}.w."))
    try:
        markdown = work / "book.md"
        stats = write_markdown(blocks, markdown, meta)
        sources = ["book.md"]
        if cover:
            # Pandoc reads book.md's metadata after this, but sets the title block first.
            (work / "cover.md").write_text(_cover_markdown(meta), encoding="utf-8")
            sources.insert(0, "cover.md")
        target = work / "book.docx"
        result = subprocess.run(
            [pandoc, *sources, "-f", "markdown", "-o", "book.docx", "--resource-path", "."],
            cwd=work,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise PdfWorkerError(f"Pandoc failed: {result.stderr.strip()[-500:]}")
        os.replace(target, output_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return stats


def _cover_markdown(meta: Metadata) -> str:
    xml = ""
    if meta.translator:
        xml += (
            '<w:p><w:pPr><w:pStyle w:val="Author"/></w:pPr>'
            f"<w:r><w:t>{escape(translated_by(meta))}</w:t></w:r></w:p>"
        )
    xml += '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    return f"```{{=openxml}}\n{xml}\n```\n"

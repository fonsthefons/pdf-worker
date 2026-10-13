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


def write_docx(blocks: Iterable[Block], output_path: Path, meta: Metadata) -> WriteStats:
    pandoc = pandoc_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=output_path.parent, prefix=f".{output_path.name}.w."))
    try:
        markdown = work / "book.md"
        stats = write_markdown(blocks, markdown, meta)
        target = work / "book.docx"
        result = subprocess.run(
            [pandoc, "book.md", "-f", "markdown", "-o", "book.docx", "--resource-path", "."],
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

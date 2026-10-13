"""Write the book as a freshly typeset, reflowed PDF (A5 pages, like an e-book).

The book is rendered to HTML (``pdf_worker.html_export``) and laid out by MuPDF's
Story engine onto new pages, with working links for contents and footnotes.
"""

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

import pymupdf

from pdf_worker.html_export import write_html
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import Block

PAGE = pymupdf.paper_rect("a5")
MARGIN = 42  # points
_CSS = """\
body { font-family: serif; font-size: 11pt; line-height: 1.35; }
h1, h2, h3, h4, h5, h6 { font-family: sans-serif; }
p { margin: 0 0 0.3em 0; text-align: justify; }
img { max-width: 100%; }
"""


def write_pdf(blocks: Iterable[Block], output_path: Path, meta: Metadata) -> WriteStats:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=output_path.parent, prefix=f".{output_path.name}.w."))
    fd, tmp_name = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.")
    os.close(fd)
    try:
        page_html = work / "book.html"
        stats = write_html(blocks, page_html, meta, images_dir=work / "images", css=_CSS)
        story = pymupdf.Story(
            html=page_html.read_text(encoding="utf-8"),
            archive=pymupdf.Archive(str(work)),
        )
        frame = PAGE + (MARGIN, MARGIN, -MARGIN, -MARGIN)

        def rect_fn(rect_num, filled):
            return PAGE, frame, None

        # Lays the story out page by page and returns the PDF with links resolved.
        with story.write_with_links(rect_fn) as doc:
            doc.set_metadata({"title": meta.title, "author": meta.author, "producer": "pdf-worker"})
            doc.save(tmp_name, garbage=3, deflate=True)
            stats.chapters = doc.page_count  # pages, for the summary
        os.replace(tmp_name, output_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    finally:
        for path in sorted(work.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        work.rmdir()
    return stats

"""Write the book as one self-contained HTML page (and the basis of reflowed PDFs).

The EPUB writer already resolves footnotes, links, page anchors, tables and pictures,
so the book is built as an EPUB in a work folder and its parts are joined into one page:
chapter bodies in order, then the notes. Links between EPUB files become links within
the page; pictures are embedded (``data:`` URIs) or written to a folder.
"""

import base64
import os
import re
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path

from pdf_worker.epub import _CSS, write_epub
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import Block

_BODY_RE = re.compile(r"<body[^>]*>(.*)</body>", re.DOTALL)
_HREF_RE = re.compile(r'href="(c\d{3}|notes)\.xhtml(#[^"]*)?"')
_SRC_RE = re.compile(r'src="images/([^"]+)"')
_NAV_RE = re.compile(r'<nav epub:type="toc".*?</nav>', re.DOTALL)
_PAGE_LIST_RE = re.compile(r'<nav epub:type="page-list".*?</nav>', re.DOTALL)
_EPUB_ATTR_RE = re.compile(r'\s(?:epub:type|role)="[^"]*"')

PAGE_CSS = """\
body { max-width: 40em; margin: 2em auto; padding: 0 1em; line-height: 1.5;
  font-family: Georgia, serif; }
nav.contents ol { list-style: none; padding-left: 1.2em; }
section.notes { border-top: 1px solid #999; margin-top: 3em; }
"""


def write_html(
    blocks: Iterable[Block],
    output_path: Path,
    meta: Metadata,
    images_dir: Path | None = None,
    css: str = PAGE_CSS,
) -> WriteStats:
    """Write ``output_path``. Pictures are embedded, or saved in ``images_dir``."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=output_path.parent, prefix=f".{output_path.name}.w."))
    fd, tmp_name = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.")
    try:
        epub = work / "book.epub"
        stats = write_epub(blocks, epub, meta)
        with (
            zipfile.ZipFile(epub) as zf,
            os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out,
        ):
            _write_page(zf, out, meta, images_dir, css)
        os.replace(tmp_name, output_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    finally:
        for path in sorted(work.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        work.rmdir()
    return stats


def _write_page(zf: zipfile.ZipFile, out, meta: Metadata, images_dir, css: str) -> None:
    names = set(zf.namelist())
    chapters = sorted(n for n in names if re.fullmatch(r"OEBPS/c\d{3}\.xhtml", n))
    if images_dir is not None:
        images_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            if name.startswith("OEBPS/images/") and not name.endswith("/"):
                (images_dir / Path(name).name).write_bytes(zf.read(name))

    def image_src(match: re.Match) -> str:
        if images_dir is not None:
            return f'src="{images_dir.name}/{match.group(1)}"'
        data = base64.b64encode(zf.read(f"OEBPS/images/{match.group(1)}")).decode()
        return f'src="data:image/jpeg;base64,{data}"'

    def body_of(name: str) -> str:
        html = zf.read(name).decode("utf-8")
        match = _BODY_RE.search(html)
        body = match.group(1) if match else ""
        body = _HREF_RE.sub(_local_href, body)
        body = _SRC_RE.sub(image_src, body)
        return _EPUB_ATTR_RE.sub("", body)

    language = meta.language
    out.write(
        "<!DOCTYPE html>\n"
        f'<html lang="{language}">\n<head>\n<meta charset="utf-8"/>\n'
        f"<title>{_escape(meta.title)}</title>\n<style>\n{_CSS}{css}</style>\n</head>\n"
        '<body id="top">\n'
    )
    nav = zf.read("OEBPS/nav.xhtml").decode("utf-8")
    toc = _NAV_RE.search(_PAGE_LIST_RE.sub("", nav))
    if toc:
        contents = _HREF_RE.sub(_local_href, toc.group(0))
        contents = _EPUB_ATTR_RE.sub("", contents).replace("<nav", '<nav class="contents"', 1)
        out.write(contents + "\n")
    for name in chapters:
        out.write(f'<section id="{Path(name).stem}">\n{body_of(name)}</section>\n')
    if "OEBPS/notes.xhtml" in names:
        notes = body_of("OEBPS/notes.xhtml")
        out.write(f'<section id="notes" class="notes">\n{notes}</section>\n')
    out.write("</body>\n</html>\n")


def _local_href(match: re.Match) -> str:
    """``c003.xhtml#h7`` -> ``#h7``; a whole file -> its section (``#c003``)."""
    return f'href="{match.group(2) or "#" + match.group(1)}"'


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

"""Rebuild an EPUB the way a converted PDF comes out: read its documents into structure
blocks and write them with ``pdf_worker.epub.write_epub``. Notes become pop-ups, the
publisher's front matter (cover, title, copyright and contents pages) is left out, and
the book gets the text cover instead.

Two passes over the spine. The first finds the note references (links whose text is a
marker such as "[12]" or "*", or marked ``epub:type="noteref"``) and the elements they
point to; the second turns each document into blocks, those elements into ``Note``s.
"""

import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from pathlib import Path
from posixpath import dirname, join, normpath
from urllib.parse import unquote, urlsplit

import pymupdf

from pdf_worker import book_metadata
from pdf_worker.cover import cover_jpeg, find_translator
from pdf_worker.ebook_to_pdf import A5, quiet_mupdf
from pdf_worker.epub import _LINK_SLACK, write_epub
from pdf_worker.errors import PdfWorkerError
from pdf_worker.inline import (
    BOLD,
    END_BOLD,
    END_ITALIC,
    ITALIC,
    LINE_BREAK,
    PAGE_MARK_RE,
    link,
    page_mark,
    page_target,
    plain,
    uri_target,
)
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import Block, Heading, Image, Note, Paragraph, Table

_BLOCKS = {
    "p", "div", "li", "ul", "ol", "dl", "dd", "dt", "blockquote", "pre", "table", "tr",
    "td", "th", "section", "article", "aside", "header", "footer", "figure", "figcaption",
    "body", "hr", "center", "address", "h1", "h2", "h3", "h4", "h5", "h6",
}  # fmt: skip
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_VOID = {"br", "img", "hr", "meta", "link", "input", "col", "wbr", "source", "area", "base"}
_HIDDEN = {"head", "script", "style", "title", "nav", "template", "noscript"}
_BOILERPLATE = "pg-boilerplate"  # Project Gutenberg's class for its header and licence
_ITALIC, _BOLD = {"i", "em", "cite", "var", "dfn"}, {"b", "strong"}
_INDENTED = {"blockquote", "li", "dd"}  # set apart from the text: written as small
_CELLS = {"td", "th"}
_MAX_HEADING_CHARS = 160  # a contents entry's target longer than this is text
# A place in a document as one number (line * this + column), for links into the book.
_LINE = 10_000_000
# The visible text of a note reference: "12", "[12]", "[32a]", "(a)", "*", "iv".
_MARKER_RE = re.compile(r"^[\[(]?(?:\d{1,4}[a-z]?|[a-z]|[ivxlc]{1,6}|[*†‡§]{1,3})[\])]?\.?$")
_SPACES_RE = re.compile(r"\s+")
# Front matter: the leading documents before the first one this long, at most this many.
_FRONT_MAX_CHARS = 3_000
_FRONT_MAX_DOCS = 12
_BLANK_CHARS = 50  # a cover or a picture page
_TITLE_PAGE_CHARS = 600  # a title page names the title and the author, and little else
_TOC_LINK_SHARE = 0.6  # a contents page: most of its text is links
_TOC_MIN_LINKS = 5
_FRONT_RE = re.compile(
    r"ISBN|©|\bcopyright\b|todos los derechos|all rights reserved|t[ií]tulo original|"
    r"original title|editor digital|\bepub\s+(?:base\s+)?r\d|project gutenberg|"
    r"exportado de wikisource|dep[oó]sito legal",
    re.IGNORECASE,
)
# An ebook tool's imprint page: never text, so dropped anywhere (books joined into one
# repeat their front matter mid-book). ISBN and © are not: a bibliography prints them.
_IMPRINT_RE = re.compile(
    r"editor digital|\bepub\s+(?:base\s+)?r\d|project gutenberg|exportado de wikisource",
    re.IGNORECASE,
)
_GUIDE_FRONT = {"cover", "title-page", "copyright-page", "toc"}
_GUIDE_START = {"text", "start", "bodymatter"}
_AUTHOR_PREFIX_RE = re.compile(r"^(?:autor|author|auteur)\s*:\s*", re.IGNORECASE)
_MIN_IMAGE_SIDE = 16  # smaller pictures are bullets and rules
_JPEG_QUALITY = 85
# More note references leading nowhere than this means the notes weren't understood.
_MAX_UNLINKED, _MAX_UNLINKED_SHARE = 2, 0.01


class EpubReadError(PdfWorkerError):
    """The EPUB could not be read confidently enough to rebuild it."""


@dataclass
class RebuildReport:
    output_path: Path
    metadata: Metadata
    stats: WriteStats
    dropped: list[str] = field(default_factory=list)  # front matter left out
    unlinked: int = 0  # note references whose note wasn't found


def default_output_path(epub_path: str | Path) -> Path:
    return Path(epub_path).with_suffix(".rebuilt.epub")


def rebuild_epub(
    epub_path: str | Path, output_path: str | Path, cover: bool = True
) -> RebuildReport:
    """Rebuild ``epub_path`` at ``output_path`` (atomically). Raises ``EpubReadError``
    when its notes can't be linked up or it has no text, so the caller can keep it as
    it is."""
    epub_path, output_path = Path(epub_path), Path(output_path)
    if output_path.resolve() == epub_path.resolve():
        raise EpubReadError(f"The output would overwrite the input: {output_path}")
    try:
        zf = zipfile.ZipFile(epub_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise EpubReadError(f"Could not open {epub_path} as an EPUB: {exc}") from exc
    with zf:
        book = _read_package(zf, epub_path)
        scans = [_scan(zf, name) for name in book.spine]
        start = _content_start(book, scans)
        kept = [s for s in scans[start:] if not (_is_contents_page(s) or _is_imprint(s))]
        notes, backrefs, markers, unlinked = _find_notes(kept, {s.name: s for s in scans})
        if unlinked > max(_MAX_UNLINKED, _MAX_UNLINKED_SHARE * len(notes)):
            raise EpubReadError(f"{unlinked} note reference(s) lead nowhere")
        meta = _title_page_metadata(epub_path, book.meta)
        if not meta.translator:
            front = [line for s in scans[:start] for line in s.text.splitlines()]
            meta = replace(meta, translator=find_translator(front))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.")
        os.close(fd)
        try:
            by_name = {s.name: s for s in scans}
            index = {s.name: i for i, s in enumerate(scans)}
            context = _Book(zf, notes, backrefs, markers, book.toc, by_name, index)
            blocks = _without_notes_titles(b for s in kept for b in _blocks(context, s.name))
            stats = write_epub(blocks, Path(tmp), meta, cover=cover_jpeg(meta) if cover else None)
            if not stats.paragraphs:
                raise EpubReadError(f"No text found in {epub_path}")
            os.replace(tmp, output_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    dropped = [s.name for s in scans if s not in kept]
    return RebuildReport(output_path, meta, stats, dropped, unlinked)


# -- the package --------------------------------------------------------------------
@dataclass
class _Package:
    spine: list[str]  # zip names, in reading order
    meta: Metadata
    start: str | None  # where the text starts, by the guide or the landmarks
    front: set[str]  # cover, title, copyright and contents pages, by the guide
    # The NCX contents: (zip name, id) -> (level, title); id "" for a document's start.
    toc: dict[tuple[str, str], tuple[int, str]] = field(default_factory=dict)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(element: ET.Element, name: str) -> str:
    return next((v for k, v in element.attrib.items() if _local(k) == name), "")


def _zip_name(base: str, href: str) -> str:
    return normpath(join(dirname(base), unquote(urlsplit(href).path)))


def _read_package(zf: zipfile.ZipFile, epub_path: Path) -> _Package:
    try:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        opf_name = next(
            _attr(e, "full-path") for e in container.iter() if _local(e.tag) == "rootfile"
        )
        opf = ET.fromstring(zf.read(opf_name))
    except (KeyError, StopIteration, ET.ParseError) as exc:
        raise EpubReadError(f"{epub_path} has no readable package document: {exc}") from exc
    items, spine, dc, start, front, nav, ncx = {}, [], {}, None, set(), None, None
    for e in opf.iter():
        tag = _local(e.tag)
        if tag == "item":
            items[_attr(e, "id")] = _zip_name(opf_name, _attr(e, "href"))
            if "nav" in _attr(e, "properties").split():
                nav = items[_attr(e, "id")]
            if _attr(e, "media-type") == "application/x-dtbncx+xml":
                ncx = ncx or items[_attr(e, "id")]
        elif tag == "spine" and _attr(e, "toc") in items:
            ncx = items[_attr(e, "toc")]
        elif tag == "itemref" and _attr(e, "idref") in items:
            spine.append(items[_attr(e, "idref")])
        elif tag == "reference":
            name = _zip_name(opf_name, _attr(e, "href"))
            kind = _attr(e, "type").lower()
            if kind in _GUIDE_START:
                start = start or name
            elif kind in _GUIDE_FRONT:
                front.add(name)
        elif tag in ("title", "creator", "contributor", "language", "publisher", "date"):
            role = _attr(e, "role") or ("aut" if tag == "creator" else "")
            dc.setdefault((tag, role), (e.text or "").strip())
    if nav and not start:
        start = _nav_bodymatter(zf, nav)
    names = set(zf.namelist())
    spine = [name for name in spine if name in names]
    author = dc.get(("creator", "aut")) or dc.get(("contributor", "aut"), "")
    # Calibre writes "0101-01-01" for no date.
    year = re.search(r"1[5-9]\d\d|20\d\d", dc.get(("date", ""), ""))
    meta = Metadata(
        title=dc.get(("title", "")),
        author=_AUTHOR_PREFIX_RE.sub("", author),
        language=(dc.get(("language", "")) or "en").split("-")[0].lower(),
        translator=dc.get(("creator", "trl")) or dc.get(("contributor", "trl"), ""),
        publisher=dc.get(("publisher", ""), ""),
        year=year[0] if year else "",
    )
    return _Package(spine, meta, start, front, _read_ncx(zf, ncx) if ncx else {})


def _read_ncx(zf: zipfile.ZipFile, ncx: str) -> dict[tuple[str, str], tuple[int, str]]:
    # shortcut: the NCX only (every sample has one); read the EPUB 3 nav's toc list if
    # a book without one turns up.
    try:
        root = ET.fromstring(zf.read(ncx))
    except (KeyError, ET.ParseError):
        return {}
    toc: dict[tuple[str, str], tuple[int, str]] = {}

    def walk(parent: ET.Element, level: int) -> None:
        for point in (e for e in parent if _local(e.tag) == "navPoint"):
            labels = (e for e in point if _local(e.tag) == "navLabel")
            title = " ".join("".join(t for e in labels for t in e.itertext()).split())
            src = next((_attr(e, "src") for e in point if _local(e.tag) == "content"), "")
            target = _target(ncx, src)
            if target and title:
                toc.setdefault(target, (level, title))
            walk(point, level + 1)

    for nav_map in (e for e in root.iter() if _local(e.tag) == "navMap"):
        walk(nav_map, 1)
    return toc


def _title_page_metadata(epub_path: Path, meta: Metadata) -> Metadata:
    """Fields the package left empty, found on the title page as for a PDF
    (``book_metadata``), the file name last. Only when the title or the author is
    missing: laying out a big book takes seconds, and the package's fields are better
    (the title page of a complete works names its first volume)."""
    if meta.title and meta.author:
        return meta
    try:
        with quiet_mupdf(), pymupdf.open(epub_path) as doc:
            doc.layout(width=A5[0], height=A5[1], fontsize=11)
            pages = range(min(book_metadata.PAGES, doc.page_count))
            texts = [b[4] for n in pages for b in doc.load_page(n).get_text("blocks")]
            found, _ = book_metadata.find_metadata(doc, texts, {}, epub_path, meta.language)
    except (pymupdf.FileDataError, RuntimeError):
        return replace(meta, title=meta.title or book_metadata.title_from_file(epub_path))
    fields = ("title", "author", "translator", "publisher", "year")
    return replace(meta, **{f: getattr(meta, f) or getattr(found, f) for f in fields})


def _nav_bodymatter(zf: zipfile.ZipFile, nav: str) -> str | None:
    """The EPUB 3 landmark where the text starts."""
    try:
        text = zf.read(nav).decode("utf-8", "replace")
    except KeyError:
        return None
    for tag in re.findall(r"<a\b[^>]*>", text):
        href = re.search(r'\bhref="([^"]+)"', tag)
        if href and re.search(r'epub:type="[^"]*\bbodymatter\b', tag):
            return _zip_name(nav, href[1])
    return None


# -- first pass: what each document holds -------------------------------------------
@dataclass
class _Link:
    target: tuple[str, str] | None  # (zip name, id) for a link into the book
    noteref: bool  # marked as a note reference
    own_ids: list[str]  # its id and those of the inline elements around it
    text: str = ""


@dataclass(eq=False)
class _Scan:
    name: str
    ids: dict[str, str] = field(default_factory=dict)  # id -> tag
    places: dict[str, int] = field(default_factory=dict)  # id -> _place of its tag
    with_heading: set[str] = field(default_factory=set)  # ids of elements holding one
    links: list[_Link] = field(default_factory=list)
    chars: int = 0
    link_chars: int = 0
    images: int = 0
    headings: int = 0
    text: str = ""  # the first _FRONT_MAX_CHARS characters, a line per block


class _Scanner(HTMLParser):
    def __init__(self, scan: _Scan) -> None:
        super().__init__(convert_charrefs=True)
        self.scan = scan
        self.stack: list[tuple[str, str, bool]] = []  # (tag, id, hides its content)
        self.hidden = 0
        self.link: _Link | None = None
        self.texts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        element_id = a.get("id") or (a.get("name", "") if tag == "a" else "")
        if element_id:
            self.scan.ids.setdefault(element_id, tag)
            self.scan.places.setdefault(element_id, _place(self))
        if tag in _HEADINGS and not self.hidden:
            self.scan.headings += 1
            self.scan.with_heading.update(i for _, i, _ in self.stack if i)
        if tag in ("img", "image") and not self.hidden:
            self.scan.images += 1
        if tag == "a" and a.get("href") and not self.hidden:
            types = (a.get("epub:type", "") + " " + a.get("role", "")).split()
            inline = [i for t, i, _ in reversed(self.stack) if t not in _BLOCKS and i]
            self.link = _Link(
                _target(self.scan.name, a["href"]),
                "noteref" in types or "doc-noteref" in types,
                [element_id, *inline] if element_id else inline,
            )
            self.scan.links.append(self.link)
        if tag in _BLOCKS or tag == "br":
            self.texts.append("\n")
        if tag not in _VOID:
            hides = _hides(tag, a)
            self.stack.append((tag, element_id, hides))
            self.hidden += hides

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.link = None
        if tag in _BLOCKS:
            self.texts.append("\n")
        while any(t == tag for t, _, _ in self.stack):
            popped, _, hides = self.stack.pop()
            self.hidden -= hides
            if popped == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.hidden:
            return
        text = _SPACES_RE.sub(" ", data)
        size = len(text.strip())
        self.scan.chars += size
        if self.link is not None:
            self.link.text += text
            self.scan.link_chars += size
        if sum(map(len, self.texts)) < _FRONT_MAX_CHARS:
            self.texts.append(text)


def _hides(tag: str, attrs: dict) -> bool:
    """Not text of the book: the head, scripts, navigation, Project Gutenberg's licence
    and header (``pg-boilerplate``)."""
    return tag in _HIDDEN or _BOILERPLATE in (attrs.get("class") or "").split()


def _place(parser: HTMLParser) -> int:
    line, column = parser.getpos()
    return line * _LINE + column


def _target(base: str, href: str) -> tuple[str, str] | None:
    """(zip name, id) of a link into the book, id "" for a document's start."""
    parts = urlsplit(href)
    if parts.scheme or parts.netloc or not (parts.path or parts.fragment):
        return None
    return (_zip_name(base, href) if parts.path else base), unquote(parts.fragment)


def _read_text(zf: zipfile.ZipFile, name: str) -> str:
    # shortcut: documents are taken as UTF-8 (all EPUB 3 and nearly all EPUB 2 are);
    # read the XML declaration's encoding if a Latin-1 book ever turns up.
    return zf.read(name).decode("utf-8", "replace")


def _scan(zf: zipfile.ZipFile, name: str) -> _Scan:
    scan = _Scan(name)
    scanner = _Scanner(scan)
    scanner.feed(_read_text(zf, name))
    scanner.close()
    lines = (" ".join(line.split()) for line in "".join(scanner.texts).split("\n"))
    scan.text = "\n".join(line for line in lines if line)
    return scan


def _is_contents_page(scan: _Scan) -> bool:
    links = sum(link.target is not None for link in scan.links)
    return links >= _TOC_MIN_LINKS and scan.link_chars >= _TOC_LINK_SHARE * scan.chars


def _is_imprint(scan: _Scan) -> bool:
    return scan.chars < _FRONT_MAX_CHARS and bool(_IMPRINT_RE.search(scan.text))


def _content_start(book: _Package, scans: list[_Scan]) -> int:
    """Index of the first spine document of the text: after the last front-matter page
    (cover, synopsis, title, copyright, contents) before the first long one. Blank pages
    count only before the first page with a heading: after it, one is part of the text."""
    names = [s.name for s in scans]
    if book.start in names:
        return names.index(book.start)
    key = _key(book.meta.title)
    author = _key(book.meta.author)
    start, headed = 0, False
    for index, scan in enumerate(scans[:_FRONT_MAX_DOCS]):
        if scan.chars >= _FRONT_MAX_CHARS:
            break
        text = _key(scan.text)
        blank = not scan.chars or (scan.chars < _BLANK_CHARS and not scan.headings)
        front = (
            (blank and not headed)
            or scan.name in book.front
            or _is_contents_page(scan)
            or bool(_FRONT_RE.search(scan.text))
            or (
                scan.chars < _TITLE_PAGE_CHARS
                and len(key) >= 4
                and key in text
                and (not author or author in text)
            )
        )
        if front:
            start = index + 1
        headed = headed or (scan.headings > 0 and not front)
    return start


def _key(text: str) -> str:
    return "".join(c for c in text.casefold() if c.isalnum())


def _find_notes(
    kept: list[_Scan], scans: dict[str, _Scan]
) -> tuple[dict[tuple[str, str], str], set[tuple[str, str]], dict[str, str], int]:
    """The note elements the kept documents refer to (-> label, in order of first
    reference), the elements holding the references (for back links), each label's
    marker as printed, and the count of references whose note doesn't exist."""
    notes: dict[tuple[str, str], str] = {}
    backrefs: set[tuple[str, str]] = set()
    markers: dict[str, str] = {}
    unlinked = 0
    for scan in kept:
        for ref in scan.links:
            marker = ref.text.strip()
            if ref.target is None or not (ref.noteref or _MARKER_RE.match(marker.lower())):
                continue
            if not ref.target[1]:
                continue  # a link to a whole document: a chapter
            if ref.target in backrefs:
                continue  # a note's link back to its reference, which came first
            target_scan = scans.get(ref.target[0])
            tag = target_scan.ids.get(ref.target[1]) if target_scan else None
            if tag is None:
                unlinked += 1
                continue
            if tag in _HEADINGS or tag == "body" or ref.target[1] in target_scan.with_heading:
                continue  # a link to a chapter, not a note
            if ref.target not in notes:
                notes[ref.target] = label = f"e{len(notes) + 1}"
                markers[label] = marker
            backrefs.update((scan.name, i) for i in ref.own_ids)
    return notes, backrefs, markers, unlinked


# -- second pass: blocks --------------------------------------------------------------
@dataclass
class _Book:
    zf: zipfile.ZipFile
    notes: dict[tuple[str, str], str]
    backrefs: set[tuple[str, str]]
    markers: dict[str, str]
    toc: dict[tuple[str, str], tuple[int, str]]
    scans: dict[str, _Scan]
    index: dict[str, int]  # spine position of each document: its blocks' "page"
    pages: int = 0  # page breaks marked so far


class _Reader(HTMLParser):
    """One document's blocks. A note is the element a reference points to, or, when
    that is an inline anchor, the block around it.

    Blocks carry the document's spine position as their page and the place where they
    end as their top, so the writer resolves a link to (document, place of the target's
    tag) to the block holding the target (``_link``)."""

    def __init__(self, book: _Book, name: str) -> None:
        super().__init__(convert_charrefs=True)
        self.book, self.name = book, name
        self.page = book.index[name]
        self.blocks: list[Block] = []
        self.stack: list[str] = []
        self.hidden = 0  # depth where hidden content started, 0 if none
        self.buffer: list[str] = []
        self.heading = 0  # level of the heading being read
        self.pending = ""  # page marks waiting for the next block's text
        self.note: str | None = None  # label of the note being read
        self.note_depth = 0  # it ends when the stack is shorter than this
        self.links: list[tuple[int, str]] = []  # (buffer position, target) of open links
        self.small = False  # the block being read is a quote or a list item
        self.mark = ""  # a list item's bullet or number, for its text
        self.lists: list[int | None] = []  # items so far of each open <ol>, None for <ul>
        self.table: list[list[str]] | None = None  # rows of the table being read
        self.table_depth = 0
        # The contents entry of the next block: a document's start counts only when it
        # has no heading of its own.
        start = book.toc.get((name, ""))
        self.toc_entry = start if start and not book.scans[name].headings else None

    # -- tags ---------------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        if self.hidden:
            if tag not in _VOID:
                self.stack.append(tag)
            return
        element_id = a.get("id") or (a.get("name", "") if tag == "a" else "")
        label = self.book.notes.get((self.name, element_id)) if element_id else None
        if tag in _BLOCKS:
            self._boundary(tag)
            self.small = self.small or tag in _INDENTED
        if tag not in _VOID and _hides(tag, a):
            self.stack.append(tag)
            self.hidden = len(self.stack)
            return
        if label:
            self._start_note(label, tag)
            self.toc_entry = None
        elif element_id and self.note is None and (self.name, element_id) in self.book.toc:
            self.toc_entry = self.book.toc[(self.name, element_id)]
        self._structure(tag)
        if tag in _HEADINGS and self.note is None and self.table is None:
            self.heading = int(tag[1])
        elif tag in _ITALIC:
            self.buffer.append(ITALIC)
        elif tag in _BOLD:
            self.buffer.append(BOLD)
        elif tag in ("img", "image"):
            self._image(a.get("src") or a.get("xlink:href") or a.get("href", ""))
        elif tag == "br":
            self.buffer.append(LINE_BREAK)
        if tag in _VOID:
            return
        self.stack.append(tag)
        types = (a.get("epub:type", "") + " " + a.get("role", "")).split()
        if "pagebreak" in types or "doc-pagebreak" in types:
            page_label = a.get("aria-label") or a.get("title") or str(self.book.pages + 1)
            self.buffer.append(page_mark(self.book.pages, page_label))
            self.book.pages += 1
            self.hidden = len(self.stack)  # its text is the page number
        elif tag == "a" and a.get("href"):
            self._link(a["href"])

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.stack:
            return
        while self.stack:
            popped = self.stack.pop()
            depth = len(self.stack)
            if self.hidden and depth < self.hidden:
                self.hidden = 0
            elif not self.hidden:
                self._close(popped, depth)
            if popped == tag:
                break

    def _structure(self, tag: str) -> None:
        """Lists and tables starting. A table inside a table or a note is text."""
        if tag in ("ul", "ol"):
            self.lists.append(0 if tag == "ol" else None)
        elif tag == "li":
            count = self.lists[-1] if self.lists else None
            if count is not None:
                self.lists[-1] = count = count + 1
            self.mark = f"{count}. " if count is not None else "• "
        elif self.table is not None:
            if tag == "tr":
                self.table.append([])
            elif tag in _CELLS:
                self.buffer = []  # the space between cells
        elif tag == "table" and self.note is None:
            self.table, self.table_depth = [], len(self.stack) + 1

    def _close(self, tag: str, depth: int) -> None:
        if self.table is not None and tag in _CELLS:
            cell = _text(self.buffer).replace(LINE_BREAK, " ")
            self.buffer = []
            if not self.table:
                self.table.append([])
            self.table[-1].append(cell)
        elif self.table is not None and tag == "table" and depth < self.table_depth:
            self._end_table()
        elif tag in ("ul", "ol") and self.lists:
            self.lists.pop()
        if tag in _ITALIC:
            self.buffer.append(END_ITALIC)
        elif tag in _BOLD:
            self.buffer.append(END_BOLD)
        elif tag == "a" and self.links and self.links[-1][0] >= 0:
            position, target = self.links.pop()
            text = "".join(self.buffer[position:])
            del self.buffer[position:]
            self.buffer.append(link(target, text) if plain(text).strip() else text)
        elif tag == "a" and self.links:
            self.links.pop()
        if tag in _BLOCKS:
            self._boundary(tag)
            self.small = any(t in _INDENTED for t in self.stack)
        if self.note is not None and depth < self.note_depth:
            self._end_note()

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.buffer.append(data)

    def close(self) -> None:
        super().close()
        if self.note is not None:
            self._end_note()
        if self.table is not None:
            self._end_table()
        self._flush()

    # -- pieces -------------------------------------------------------------------
    def _link(self, href: str) -> None:
        target = _target(self.name, href)
        label = self.book.notes.get(target) if target else None
        if label:
            self.buffer.append(f"[^{label}]")
        if label or target in self.book.backrefs:
            self.hidden = len(self.stack)  # the marker, or the back link's "<<"
        elif urlsplit(href).scheme in ("http", "https"):
            self.links.append((len(self.buffer), uri_target(href)))
        elif target and target[0] in self.book.index:
            # The writer goes to the first block ending past the target's tag.
            place = self.book.scans[target[0]].places.get(target[1], 0) if target[1] else 0
            page = self.book.index[target[0]]
            self.links.append((len(self.buffer), page_target(page, place + _LINK_SLACK + 1)))
        else:
            self.links.append((-1, ""))  # outside the spine: kept as plain text

    def _image(self, src: str) -> None:
        if self.note is not None or not src:
            return
        try:
            image = _jpeg(self.book.zf.read(_zip_name(self.name, src)))
        except KeyError:
            return
        if image:
            if self.table is None:
                self._flush()
            self.blocks.append(image)

    def _boundary(self, tag: str) -> None:
        if self.note is not None:
            self.buffer.append("\n\n")
        elif self.table is not None:
            self.buffer.append(" ")
        else:
            self._flush()
            if tag in _HEADINGS:
                self.heading = 0

    def _flush(self) -> None:
        text = self.pending + _text(self.buffer)
        self.buffer = []
        mark, self.mark = self.mark, ""
        if not plain(text).strip():
            self.pending = "".join(m[0] for m in PAGE_MARK_RE.finditer(text))
            return
        self.pending = ""
        place = _place(self)
        entry, self.toc_entry = self.toc_entry, None
        if self.heading:
            self.blocks.append(Heading(_one_line(text), self.heading, self.page, place))
            return
        if entry:
            level, title = entry
            target, start = _key(title), _key(plain(text))
            # A styled paragraph as the heading; else the entry's title before the text.
            short = len(plain(text)) <= _MAX_HEADING_CHARS and LINE_BREAK not in text
            if short and start and (target.startswith(start) or start.startswith(target)):
                self.blocks.append(Heading(_one_line(text), level, self.page, place))
                return
            self.blocks.append(Heading(title, level, self.page, place))
        self.blocks.append(Paragraph(mark + text, self.small, self.page, place))

    def _end_table(self) -> None:
        """A table of two columns or more; a one-column one (layout) as paragraphs."""
        rows = [r for r in self.table or () if any(plain(c).strip() for c in r)]
        self.table, self.buffer, self.mark = None, [], ""
        place = _place(self)
        if any(len(r) > 1 for r in rows):
            width = max(map(len, rows))
            self.blocks.append(Table(tuple((*r, *[""] * (width - len(r))) for r in rows)))
        else:
            self.blocks.extend(Paragraph(r[0], False, self.page, place) for r in rows)

    def _start_note(self, label: str, tag: str) -> None:
        if self.note is not None:
            self._end_note()
        if tag in _BLOCKS:
            self._flush()
            self.note_depth = len(self.stack) + 1
        else:  # an anchor inside the note's block: the note is that block
            blocks = [i for i, t in enumerate(self.stack) if t in _BLOCKS]
            self.note_depth = blocks[-1] + 1 if blocks else 1
        self.note = label

    def _end_note(self) -> None:
        label, self.note = self.note, None
        paragraphs = [_one_line(_text([p])) for p in "".join(self.buffer).split("\n\n")]
        self.buffer = []
        text = "\n\n".join(p for p in paragraphs if plain(p).strip())
        text = _without_marker(text, self.book.markers.get(label, ""))
        self.blocks.append(Note(label, text or "(note text not found)"))


def _text(pieces: list[str]) -> str:
    """Spaces collapsed, line breaks kept (only inside the text)."""
    lines = "".join(pieces).split(LINE_BREAK)
    return LINE_BREAK.join(_SPACES_RE.sub(" ", line).strip() for line in lines).strip()


def _one_line(text: str) -> str:
    return text.replace(LINE_BREAK, " ")


def _without_printed_lines(blocks: list[Block]) -> list[Block]:
    """Line breaks are kept for verse and addresses, but a document of prose broken at
    every printed line (Project Gutenberg's) is joined up again: most of its broken
    paragraphs have most lines starting in lower case.
    shortcut: verse in lower case is taken for prose too; look at line lengths if a
    book of modern verse comes out joined."""
    broken = [b for b in blocks if isinstance(b, Paragraph) and LINE_BREAK in b.text]
    if not broken or 2 * sum(map(_prose_lines, broken)) < len(broken):
        return blocks
    return [replace(b, text=_one_line(b.text)) if isinstance(b, Paragraph) else b for b in blocks]


def _prose_lines(paragraph: Paragraph) -> bool:
    lines = paragraph.text.split(LINE_BREAK)[1:]
    starts = [plain(line).lstrip(" «“\"'¿¡(—-")[:1] for line in lines]
    return 2 * sum(s.islower() for s in starts) >= len(starts)


def _without_marker(text: str, marker: str) -> str:
    """The note's text without its printed number: "[12] Hegel" -> "Hegel"."""
    core = marker.strip("[]().* ")
    if core:
        text = re.sub(rf"^[\[(]?{re.escape(core)}[\])]?(?=\W)", "", text)
    return re.sub(r"^[\s.:)\]]+", "", text)


def _blocks(book: _Book, name: str) -> list[Block]:
    reader = _Reader(book, name)
    reader.feed(_read_text(book.zf, name))
    reader.close()
    return _with_continued_notes(_without_printed_lines(reader.blocks))


def _without_notes_titles(blocks: Iterator[Block]) -> Iterator[Block]:
    """Leave out the headings right before a note: a notes page's own title ("Notas",
    "Notas al capítulo 3"), often in a file of its own. The rebuilt book has its notes
    section; in the text itself a note never follows a heading."""
    held: list[Heading] = []
    for block in blocks:
        if isinstance(block, Heading):
            held.append(block)
            continue
        if not isinstance(block, Note):
            yield from held
        held = []
        yield block
    yield from held


def _with_continued_notes(blocks: list[Block]) -> list[Block]:
    """On a notes page (its first block after the headings is a note), a paragraph after
    a note is that note's next paragraph: only the first carries the id. Elsewhere (a
    chapter with notes in it) it's text."""
    first = next((i for i, b in enumerate(blocks) if not isinstance(b, Heading)), None)
    if first is None or not isinstance(blocks[first], Note):
        return blocks
    rest = blocks[first:]
    merged = blocks[:first]
    for block in rest:
        if isinstance(block, Paragraph) and isinstance(merged[-1], Note):
            note = merged[-1]
            merged[-1] = Note(note.label, f"{note.text}\n\n{block.text}")
        else:
            merged.append(block)
    return merged


def _jpeg(data: bytes) -> Image | None:
    """The picture as a JPEG; None for tiny ones and ones MuPDF can't read."""
    try:
        with quiet_mupdf():
            pix = pymupdf.Pixmap(data)
    except (RuntimeError, ValueError):
        return _svg_jpeg(data) if b"<svg" in data[:4096] else None
    width, height = pix.width, pix.height
    if min(width, height) < _MIN_IMAGE_SIDE:
        return None
    if data[:3] != b"\xff\xd8\xff":
        # Drawn on a white page, so transparent parts come out white, not black.
        with quiet_mupdf(), pymupdf.open() as doc:
            page = doc.new_page(width=width, height=height)
            page.insert_image(page.rect, stream=data)
            data = page.get_pixmap().tobytes("jpg", jpg_quality=_JPEG_QUALITY)
    return Image(data, width, height)


def _svg_jpeg(data: bytes) -> Image | None:
    # shortcut: SVG files referenced by <img> only; drawings inline in the XHTML (<svg>
    # with shapes) are dropped. Render those too if a book needs them.
    try:
        with quiet_mupdf(), pymupdf.open(stream=data, filetype="svg") as doc:
            pix = doc.load_page(0).get_pixmap(dpi=150)
    except (RuntimeError, ValueError):
        return None
    if min(pix.width, pix.height) < _MIN_IMAGE_SIDE:
        return None
    return Image(pix.tobytes("jpg", jpg_quality=_JPEG_QUALITY), pix.width, pix.height)

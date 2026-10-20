"""Write structure blocks as an EPUB 3 book that works well with Send to Kindle.

* Chapters are written to the zip as they fill up, so only one chapter is in memory.
* Footnotes and endnotes go to ``notes.xhtml`` as ``epub:type="footnote"`` asides with
  links in both directions (reference -> note -> back), which Kindle shows as pop-ups.
  Notes are streamed to a temporary file and added to the zip at the end.
* Both an EPUB 3 navigation document and an EPUB 2 NCX are included for older readers.
"""

import bisect
import html
import os
import re
import shutil
import tempfile
import uuid
import zipfile
import zlib
from array import array
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pdf_worker.index_links import parse_word_target, word_keys
from pdf_worker.inline import (
    ESTIMATED,
    LinkClose,
    LinkOpen,
    MarginRef,
    PageMark,
    Style,
    parse_page_target,
    pieces,
    plain,
)
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import (
    REF_RE,
    Block,
    Gloss,
    Heading,
    Image,
    Note,
    Paragraph,
    Table,
)

# Start a new chapter file at a heading once the current one has this much text, and
# force one at a paragraph boundary when it grows past the hard limit (Kindle prefers
# content files well under 300 KB).
_MIN_CHAPTER_CHARS = 2_000
_MAX_CHAPTER_CHARS = 150_000
_NOTES_FILE = "notes.xhtml"
_NOTE_NUMBER_RE = re.compile(r'<aside class="note" id="n(\d+)"')
_COVER_PAGE = "cover.xhtml"
_COVER_IMAGE = "OEBPS/images/cover.jpg"
# Link targets are written as placeholders and resolved at the end (see _EpubBuilder).
_LINK_START, _LINK_END = "", ""
_PLACEHOLDER_RE = re.compile("([^]*)")
# A link to a page resolves to the first heading at most this far above its target
# position, else the page start; pages without anchors pass it on to the next ones.
_LINK_SLACK = 30.0
_LINK_LOOKAHEAD_PAGES = 4
# Link text vs. block start: compare this many letters/digits, and at least this many.
_KEY_SEP = ""
_KEY_CHARS = 40
_MIN_KEY = 6
_TRAILING_PAGE_RE = re.compile(r"(?<=\S)[\s.·…]+(?:\d{1,4}|[ivxlcdm]{1,7})\s*$", re.I)
# Characters that are not allowed in XML 1.0 documents.
_XML_INVALID_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

_CSS = """\
body { margin: 0 5%; }
h1, h2, h3, h4, h5, h6 { text-align: center; font-weight: bold; margin: 1.5em 0 0.8em; }
h1 { font-size: 1.6em; }
h2 { font-size: 1.35em; }
h3 { font-size: 1.15em; }
h4, h5, h6 { font-size: 1em; }
p { margin: 0; text-indent: 1.2em; text-align: justify; }
h1 + p, h2 + p, h3 + p, h4 + p, h5 + p, h6 + p { text-indent: 0; }
p.small { font-size: 0.85em; text-indent: 0; margin: 0.4em 0; }
a.noteref { text-decoration: none; }
span.mref { color: #2e7d32; font-weight: bold; font-size: 0.8em; padding: 0 0.2em; }
span.mref.est { color: #d81b60; }
sup { font-size: 0.75em; line-height: 0; }
aside.note p { text-indent: 0; margin: 0 0 0.6em; text-align: left; }
div.gloss { font-size: 0.8em; margin: 0.4em 0 0.8em 1em; padding-left: 0.6em;
  border-left: 2px solid #999; }
div.gloss p { text-indent: 0; text-align: left; }
table.data { border-collapse: collapse; margin: 0.6em 0; }
table.data td { padding: 0.1em 0.6em 0.1em 0; vertical-align: top; text-align: left; }
div.figure { text-align: center; margin: 0.8em 0; }
div.figure img { max-width: 100%; height: auto; }
div.cover { text-align: center; margin: 0; }
div.cover img { max-width: 100%; max-height: 100%; }
"""


def _match_key(text: str) -> str:
    """Letters and digits only, lower case: "CAPÍTULO 1 –" and "Capítulo 1" compare equal."""
    return "".join(c for c in text.casefold() if c.isalnum())[:_KEY_CHARS]


def _link_text(items: list, position: int) -> str:
    """The text of the link opened at ``items[position]``."""
    texts = []
    for piece in items[position + 1 :]:
        if isinstance(piece, LinkClose | LinkOpen):
            break
        if isinstance(piece, str):
            texts.append(piece)
    # Contents entries end with their page number ("Preface xv"): not part of the title.
    return _TRAILING_PAGE_RE.sub("", REF_RE.sub("", "".join(texts)))


def _has(keys: array, key: int) -> bool:
    i = bisect.bisect_left(keys, key)
    return i < len(keys) and keys[i] == key


def _clean(text: str) -> str:
    return _XML_INVALID_RE.sub("", text)


def _esc(text: str) -> str:
    return html.escape(_clean(text), quote=False)


def _attr(text: str) -> str:
    return html.escape(_clean(text), quote=True)


def _xhtml_page(title: str, language: str, body: str, epub_type: str = "") -> str:
    type_attr = f' epub:type="{epub_type}"' if epub_type else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{_attr(language)}" lang="{_attr(language)}">\n'
        f'<head>\n<meta charset="utf-8"/>\n<title>{_esc(title)}</title>\n'
        '<link rel="stylesheet" type="text/css" href="style.css"/>\n</head>\n'
        f"<body{type_attr}>\n{body}</body>\n</html>\n"
    )


@dataclass
class _TocEntry:
    level: int
    text: str
    href: str


class _EpubBuilder:
    """Assembles chapters, notes, the TOC and the page list.

    Chapter files go to ``work_dir`` first: a link may point forward (a contents entry to
    a later chapter), so link targets are written as placeholders and resolved once the
    whole book has been seen (``resolve``).
    """

    def __init__(self, work_dir: Path, notes_file, meta: Metadata) -> None:
        self.work_dir = work_dir
        self.notes = notes_file
        self.meta = meta
        self.stats = WriteStats()
        self.chapter_files: list[str] = []
        self.toc: list[_TocEntry] = []
        self.parts: list[str] = []
        self.chars = 0
        self.chapter_title = ""
        self.note_ids: dict[str, str] = {}  # label -> "n7"
        self.first_ref: dict[str, str] = {}  # label -> "c003.xhtml#r7"
        self.ref_counts: dict[str, int] = {}
        self.defined: set[str] = set()
        self.unreferenced: dict[str, str] = {}  # label -> note XHTML, no reference seen yet
        self.open_note: Note | None = None
        # PDF page index -> [(top, href, match key)] of the page start and its blocks.
        self.anchors: dict[int, list[tuple[float, str, str]]] = {}
        # PDF page index -> [(href, word keys)] of each paragraph's text on it, for index
        # links; keys as sorted crc32s to keep memory small.
        self.words: dict[int, list[tuple[str, array]]] = {}
        self.page_list: list[tuple[int, str, str]] = []  # (page index, label, href)
        self.image_files: list[str] = []  # "images/img3.jpg", in work_dir
        (work_dir / "images").mkdir(exist_ok=True)

    # -- chapters ---------------------------------------------------------------------
    @property
    def current_file(self) -> str:
        return f"c{len(self.chapter_files) + 1:03d}.xhtml"

    def _close_chapter(self) -> None:
        if not self.parts:
            return
        name = self.current_file
        title = self.chapter_title or f"{self.meta.title} ({len(self.chapter_files) + 1})"
        page = _xhtml_page(title, self.meta.language, "".join(self.parts))
        (self.work_dir / name).write_text(page, encoding="utf-8")
        self.chapter_files.append(name)
        if not any(entry.href.startswith(name) for entry in self.toc):
            self.toc.append(_TocEntry(1, title, name))
        self.parts, self.chars, self.chapter_title = [], 0, ""

    def add(self, block: Block) -> None:
        if isinstance(block, Heading):
            if self.chars >= _MIN_CHAPTER_CHARS:
                self._close_chapter()
            self.stats.headings += 1
            anchor = f"h{self.stats.headings}"
            tag = f"h{min(block.level, 6)}"
            text = self._inline(block.text)
            self.parts.append(f'<{tag} id="{anchor}">{text}</{tag}>\n')
            title = REF_RE.sub("", plain(block.text)).strip()
            self.toc.append(_TocEntry(block.level, title, f"{self.current_file}#{anchor}"))
            if block.page >= 0:
                self.anchors.setdefault(block.page, []).append(
                    (block.top, f"{self.current_file}#{anchor}", _match_key(title))
                )
            if not self.chapter_title:
                self.chapter_title = title
            self.chars += len(block.text)
        elif isinstance(block, Paragraph):
            self.stats.paragraphs += 1
            css = ' class="small"' if block.small else ""
            # Every paragraph is a possible link target ("b12"): links from a contents
            # page land on the exact block, even when its heading looked like body text.
            anchor = f"b{self.stats.paragraphs}"
            text = self._inline(block.text)
            if block.page >= 0:
                key = _match_key(REF_RE.sub("", plain(block.text)))
                self.anchors.setdefault(block.page, []).append(
                    (block.top, f"{self.current_file}#{anchor}", key)
                )
                self._add_words(block.text, block.page, f"{self.current_file}#{anchor}")
            self.parts.append(f'<p id="{anchor}"{css}>{text}</p>\n')
            self.chars += len(block.text)
            if self.chars >= _MAX_CHAPTER_CHARS:
                self._close_chapter()
        elif isinstance(block, Gloss):
            self.stats.glosses += 1
            lines = "<br/>".join(_esc(plain(line)) for line in block.lines)
            self.parts.append(f'<div class="gloss"><p>{lines}</p></div>\n')
            self.chars += sum(len(line) for line in block.lines)
        elif isinstance(block, Table):
            self.stats.tables += 1
            rows = "".join(
                "<tr>" + "".join(f"<td>{self._inline(cell)}</td>" for cell in row) + "</tr>"
                for row in block.rows
            )
            self.parts.append(f'<table class="data"><tbody>{rows}</tbody></table>\n')
            self.chars += sum(len(cell) for row in block.rows for cell in row)
        elif isinstance(block, Image):
            self.stats.images += 1
            name = f"images/img{self.stats.images}.jpg"
            (self.work_dir / name).write_bytes(block.data)
            self.image_files.append(name)
            self.parts.append(
                f'<div class="figure"><img src="{name}" alt="" '
                f'width="{block.width}" height="{block.height}"/></div>\n'
            )
            self.chars += 200  # pictures weigh on chapter size too
        elif isinstance(block, Note):
            self._add_note(block)

    def _add_words(self, text: str, page: int, href: str) -> None:
        """Each page's part of a paragraph: from its start, then from each page start."""
        texts: list[str] = []
        for piece in [*pieces(text), PageMark(-1, "")]:
            if isinstance(piece, str):
                texts.append(piece)
            elif isinstance(piece, PageMark):
                keys = array("I", sorted(zlib.crc32(k.encode()) for k in word_keys("".join(texts))))
                if keys:
                    self.words.setdefault(page, []).append((href, keys))
                texts, page = [], piece.index
                href = f"{self.current_file}#pg{piece.index}"

    # -- notes ------------------------------------------------------------------------
    def _note_id(self, label: str) -> str:
        if label not in self.note_ids:
            self.note_ids[label] = f"n{len(self.note_ids) + 1}"
        return self.note_ids[label]

    def _number(self, label: str) -> str:
        # Notes numbered 1-N through the book, not as printed (often 1 again on each page).
        return self._note_id(label)[1:]

    def _inline(self, text: str, file: str | None = None, notes: bool = False) -> str:
        """Block text as XHTML: footnote references, page starts and links.

        In notes (``notes=True``) references become plain markers.
        """
        file = file or self.current_file
        out = []
        open_links = 0
        styles = {True: False, False: False}  # italic, bold: on at this point
        items = list(pieces(text))
        for position, piece in enumerate(items):
            if isinstance(piece, PageMark):
                page_id = f"pg{piece.index}"
                self.anchors.setdefault(piece.index, []).insert(0, (-1.0, f"{file}#{page_id}", ""))
                self.page_list.append((piece.index, piece.label, f"{file}#{page_id}"))
                out.append(
                    f'<span epub:type="pagebreak" role="doc-pagebreak" id="{page_id}" '
                    f'aria-label="{_attr(piece.label)}"></span>'
                )
            elif isinstance(piece, LinkOpen):
                if open_links:
                    out.append("</a>")  # links can't nest: close the outer one first
                # The placeholder carries the link's text too, to match it with the start
                # of the target block (a contents entry and its heading).
                key = _match_key(_link_text(items, position))
                out.append(f'<a href="{_LINK_START}{piece.target}{_KEY_SEP}{key}{_LINK_END}">')
                open_links = 1
            elif isinstance(piece, LinkClose):
                if open_links:
                    out.append("</a>")
                    open_links = 0
            elif isinstance(piece, MarginRef):
                self.stats.margin_refs += 1
                kind = "mref est" if piece.label.startswith(ESTIMATED) else "mref"
                mark_id = f"m{self.stats.margin_refs}"
                out.append(f'<span class="{kind}" id="{mark_id}">{_esc(piece.label)}</span>')
            elif isinstance(piece, Style):
                styles[piece.italic] = piece.on
            else:
                part = []
                last = 0
                for match in REF_RE.finditer(piece):
                    part.append(_esc(piece[last : match.start()]))
                    if notes or open_links:
                        # No links inside links: a reference in linked text is plain.
                        part.append(f"<sup>{self._number(match.group(1))}</sup>")
                    else:
                        part.append(self._noteref(match.group(1)))
                    last = match.end()
                part.append(_esc(piece[last:]))
                part = "".join(part)
                if styles[True] and part.strip():
                    part = f"<i>{part}</i>"
                if styles[False] and part.strip():
                    part = f"<b>{part}</b>"
                out.append(part)
        out.append("</a>" * open_links)
        return "".join(out)

    def resolve(self, text: str) -> str:
        """Replace link placeholders with real hrefs, now that every page is placed."""

        def _href(match: re.Match) -> str:
            target, _, key = match.group(1).partition(_KEY_SEP)
            return _attr(self._target_href(target, key))

        return _PLACEHOLDER_RE.sub(_href, text)

    def _target_href(self, target: str, key: str = "") -> str:
        if target.startswith("u:"):
            return target[2:]
        word = parse_word_target(target)
        if word:
            page, word_key = word
            wanted = zlib.crc32(word_key.encode())
            hrefs = [href for href, keys in self.words.get(page, ()) if _has(keys, wanted)]
            return hrefs[0] if hrefs else self._target_href(f"p:{page}:0")
        place = parse_page_target(target)
        first = self.chapter_files[0] if self.chapter_files else "c001.xhtml"
        if place is None:
            return first
        page, y = place
        # Best: a block on (or next to) the target page that starts with the link text.
        if len(key) >= _MIN_KEY:
            for index in (page, page - 1, page + 1):
                for _, href, block_key in self.anchors.get(index, ()):
                    same_start = block_key[: len(key)] == key[: len(block_key)]
                    if len(block_key) >= _MIN_KEY and same_start:
                        return href
        for index in range(page, page + _LINK_LOOKAHEAD_PAGES):
            anchors = self.anchors.get(index)
            if not anchors:
                continue
            if index == page:
                # The first block at or just below the target, else the page start.
                below = [a for a in anchors if a[0] >= y - _LINK_SLACK]
                return min(below)[1] if below else anchors[0][1]
            return anchors[0][1]
        return first

    def _noteref(self, label: str) -> str:
        note_id = self._note_id(label)
        count = self.ref_counts.get(label, 0) + 1
        self.ref_counts[label] = count
        ref_id = f"r{note_id[1:]}" + (f"-{count}" if count > 1 else "")
        self.first_ref.setdefault(label, f"{self.current_file}#{ref_id}")
        return (
            f'<a class="noteref" id="{ref_id}" href="{_NOTES_FILE}#{note_id}" '
            f'epub:type="noteref" role="doc-noteref"><sup>{self._number(label)}</sup></a>'
        )

    def _add_note(self, note: Note) -> None:
        if note.continued and self.open_note and self.open_note.label == note.label:
            self.open_note = Note(note.label, f"{self.open_note.text} {note.text}")
            return
        self._flush_note()
        self.open_note = note

    def _flush_note(self) -> None:
        note, self.open_note = self.open_note, None
        if note is None or note.label in self.defined:
            return
        self.defined.add(note.label)
        self.stats.notes += 1
        if note.label in self.note_ids:
            self._write_note(note.label, self._inline_note(note.text))
        else:  # numbered by its reference, which may come later
            self.unreferenced[note.label] = self._inline_note(note.text)

    def _inline_note(self, text: str) -> str:
        # References inside notes are rare; render them as plain markers. Paragraphs
        # after the first become their own <p>.
        return "</p><p>".join(
            self._inline(p, file=_NOTES_FILE, notes=True)
            for p in text.split("\n\n")
            if plain(p).strip()
        )

    def _write_note(self, label: str, body: str) -> None:
        note_id = self._note_id(label)
        marker = self._number(label)
        back = self.first_ref.get(label)
        link = f'<a href="{_attr(back)}" role="doc-backlink">{marker}</a>' if back else marker
        arrow = f' <a class="back" href="{_attr(back)}" role="doc-backlink">↩</a>' if back else ""
        self.notes.write(
            f'<aside class="note" id="{note_id}" epub:type="footnote" role="doc-footnote">'
            f"<p>{link}. {body}{arrow}</p></aside>\n"
        )

    def finish(self) -> None:
        self._flush_note()
        # After the referenced ones: notes whose reference was never found.
        for label, body in self.unreferenced.items():
            self._write_note(label, body)
        # Every reference needs a target, or the EPUB is invalid.
        for label in self.first_ref:
            if label not in self.defined:
                self.defined.add(label)
                self._write_note(label, "(note text not found)")
        self._close_chapter()
        if not self.chapter_files:
            self.parts.append(f"<p>{_esc(self.meta.title)}</p>\n")
            self._close_chapter()
        self.stats.chapters = len(self.chapter_files)


def write_epub(
    blocks: Iterable[Block], output_path: Path, meta: Metadata, cover: bytes | None = None
) -> WriteStats:
    """Write an EPUB 3 book; ``cover`` is a JPEG for the cover image and page."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.")
    os.close(fd)
    work_dir = Path(tempfile.mkdtemp(dir=output_path.parent, prefix=f".{output_path.name}.w."))
    notes_path = work_dir / "notes.part"
    try:
        with notes_path.open("w", encoding="utf-8", newline="\n") as notes:
            builder = _EpubBuilder(work_dir, notes, meta)
            for block in blocks:
                builder.add(block)
            builder.finish()
        with zipfile.ZipFile(tmp_name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # The mimetype entry must come first and be stored uncompressed.
            zf.writestr(
                zipfile.ZipInfo("mimetype"),
                "application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
            zf.writestr("META-INF/container.xml", _CONTAINER)
            zf.writestr("OEBPS/style.css", _CSS)
            if cover:
                zf.writestr(_COVER_IMAGE, cover, compress_type=zipfile.ZIP_STORED)
                zf.writestr(f"OEBPS/{_COVER_PAGE}", _cover_page(meta))
            for name in builder.image_files:
                # JPEGs are compressed already.
                zf.write(work_dir / name, f"OEBPS/{name}", compress_type=zipfile.ZIP_STORED)
            for name in builder.chapter_files:
                chapter = (work_dir / name).read_text(encoding="utf-8")
                zf.writestr(f"OEBPS/{name}", builder.resolve(chapter))
                (work_dir / name).unlink()
            has_notes = bool(builder.defined)
            if has_notes:
                _write_notes_file(zf, notes_path, meta, builder.resolve)
            pages = sorted(builder.page_list)
            zf.writestr("OEBPS/nav.xhtml", _nav(builder.toc, meta, has_notes, pages))
            zf.writestr("OEBPS/toc.ncx", _ncx(builder.toc, meta, has_notes))
            zf.writestr(
                "OEBPS/content.opf",
                _opf(
                    builder.chapter_files,
                    meta,
                    has_notes,
                    bool(pages),
                    images=builder.image_files,
                    cover=bool(cover),
                ),
            )
        os.replace(tmp_name, output_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return builder.stats


def _write_notes_file(
    zf: zipfile.ZipFile, notes_path: Path, meta: Metadata, resolve: Callable[[str], str]
) -> None:
    title = _notes_title(meta.language)
    head, tail = _xhtml_page(title, meta.language, "\0", epub_type="backmatter").split("\0")
    with zf.open(f"OEBPS/{_NOTES_FILE}", "w") as out:
        out.write(head.encode("utf-8"))
        out.write(
            f'<section epub:type="endnotes" role="doc-endnotes">\n<h2>{_esc(title)}</h2>\n'.encode()
        )
        # One note per line, so links can be resolved line by line; in number order (a
        # note can come before its reference on the page).
        with notes_path.open(encoding="utf-8") as notes:
            lines = sorted(notes, key=lambda note: int(_NOTE_NUMBER_RE.search(note)[1]))
        for note in lines:
            out.write(resolve(note).encode("utf-8"))
        out.write(b"</section>\n")
        out.write(tail.encode("utf-8"))


def _notes_title(language: str) -> str:
    return {
        "es": "Notas",
        "fr": "Notes",
        "it": "Note",
        "de": "Anmerkungen",
        "pt": "Notas",
        "la": "Notae",
    }.get(language.split("-")[0], "Notes")


def _book_id(meta: Metadata) -> str:
    return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'pdf-worker:{meta.title}:{meta.author}')}"


_CONTAINER = """\
<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _cover_page(meta: Metadata) -> str:
    body = f'<div class="cover"><img src="images/cover.jpg" alt="{_attr(meta.title)}"/></div>\n'
    return _xhtml_page(meta.title, meta.language, body, epub_type="cover")


def _opf(
    chapters: list[str],
    meta: Metadata,
    has_notes: bool,
    has_pages: bool = False,
    images: list[str] = (),
    cover: bool = False,
) -> str:
    modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
    ]
    spine = []
    if cover:
        items.append(
            '<item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" '
            'properties="cover-image"/>'
        )
        items.append(f'<item id="cover" href="{_COVER_PAGE}" media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="cover"/>')
    for index, name in enumerate(images, start=1):
        items.append(f'<item id="img{index}" href="{name}" media-type="image/jpeg"/>')
    for index, name in enumerate(chapters, start=1):
        items.append(f'<item id="c{index}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{index}"/>')
    if has_notes:
        items.append(f'<item id="notes" href="{_NOTES_FILE}" media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="notes"/>')
    creator = f"<dc:creator>{_esc(meta.author)}</dc:creator>\n    " if meta.author else ""
    if meta.translator:
        creator += (
            f'<dc:contributor id="trl">{_esc(meta.translator)}</dc:contributor>\n    '
            '<meta refines="#trl" property="role" scheme="marc:relators">trl</meta>\n    '
        )
    if meta.publisher:
        creator += f"<dc:publisher>{_esc(meta.publisher)}</dc:publisher>\n    "
    if meta.year:
        creator += f"<dc:date>{_esc(meta.year)}</dc:date>\n    "
    if has_pages:
        creator += '<meta property="schema:accessibilityFeature">printPageNumbers</meta>\n    '
    if cover:
        # EPUB 2 style cover hint: older Kindle conversions look for it.
        creator += '<meta name="cover" content="cover-image"/>\n    '
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        f'unique-identifier="bookid" xml:lang="{_attr(meta.language)}">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="bookid">{_book_id(meta)}</dc:identifier>\n'
        f"    <dc:title>{_esc(meta.title)}</dc:title>\n"
        f"    {creator}<dc:language>{_esc(meta.language)}</dc:language>\n"
        f'    <meta property="dcterms:modified">{modified}</meta>\n'
        "  </metadata>\n  <manifest>\n    "
        + "\n    ".join(items)
        + '\n  </manifest>\n  <spine toc="ncx">\n    '
        + "\n    ".join(spine)
        + "\n  </spine>\n</package>\n"
    )


def _toc_entries(toc: list[_TocEntry], meta: Metadata, has_notes: bool) -> list[_TocEntry]:
    entries = [entry for entry in toc if entry.text] or [_TocEntry(1, meta.title, "c001.xhtml")]
    if has_notes:
        entries.append(
            _TocEntry(min(e.level for e in entries), _notes_title(meta.language), _NOTES_FILE)
        )
    return entries


def _page_list(pages: list[tuple[int, str, str]]) -> str:
    """EPUB 3 page list: printed page numbers that readers (Kindle) show as real pages.

    Each entry points into the text, so the numbers stay right at any font size.
    """
    seen: set[int] = set()
    items = []
    for index, label, href in pages:
        if index in seen:
            continue
        seen.add(index)
        items.append(f'<li><a href="{_attr(href)}">{_esc(label)}</a></li>')
    return (
        '<nav epub:type="page-list" id="page-list" role="doc-pagelist" hidden="hidden">\n'
        "<h2>Pages</h2>\n<ol>" + "".join(items) + "</ol>\n</nav>\n"
    )


def _nav(
    toc: list[_TocEntry],
    meta: Metadata,
    has_notes: bool,
    pages: list[tuple[int, str, str]] | None = None,
) -> str:
    entries = _toc_entries(toc, meta, has_notes)
    out = []
    depth = 0
    for entry, entry_depth in zip(entries, _depths(entries), strict=True):
        if entry_depth > depth:
            out.append("<ol>")
        else:
            out.append("</li>")
            while depth > entry_depth:
                out.append("</ol></li>")
                depth -= 1
        depth = entry_depth
        out.append(f'<li><a href="{_attr(entry.href)}">{_esc(entry.text)}</a>')
    while depth:
        out.append("</li></ol>")
        depth -= 1
    body = f'<nav epub:type="toc" id="toc" role="doc-toc">\n<h1>{_esc(meta.title)}</h1>\n'
    body += "\n".join(out) + "\n</nav>\n"
    if pages:
        body += _page_list(pages)
    return _xhtml_page(meta.title, meta.language, body)


def _depths(entries: list[_TocEntry]) -> list[int]:
    """Nesting depth (1 = top) of each entry: under the closest earlier, higher heading.

    Depth grows by at most one per entry, so the nav always forms a valid tree.
    """
    depths = []
    open_levels: list[int] = []
    for entry in entries:
        while open_levels and open_levels[-1] >= entry.level:
            open_levels.pop()
        open_levels.append(entry.level)
        depths.append(len(open_levels))
    return depths


def _ncx(toc: list[_TocEntry], meta: Metadata, has_notes: bool) -> str:
    points = []
    for order, entry in enumerate(_toc_entries(toc, meta, has_notes), start=1):
        points.append(
            f'<navPoint id="p{order}" playOrder="{order}"><navLabel><text>{_esc(entry.text)}'
            f'</text></navLabel><content src="{_attr(entry.href)}"/></navPoint>'
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        f'<head><meta name="dtb:uid" content="{_book_id(meta)}"/></head>\n'
        f"<docTitle><text>{_esc(meta.title)}</text></docTitle>\n<navMap>\n"
        + "\n".join(points)
        + "\n</navMap>\n</ncx>\n"
    )

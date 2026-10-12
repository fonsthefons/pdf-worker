"""Write structure blocks as an EPUB 3 book that works well with Send to Kindle.

* Chapters are written to the zip as they fill up, so only one chapter is in memory.
* Footnotes and endnotes go to ``notes.xhtml`` as ``epub:type="footnote"`` asides with
  links in both directions (reference -> note -> back), which Kindle shows as pop-ups.
  Notes are streamed to a temporary file and added to the zip at the end.
* Both an EPUB 3 navigation document and an EPUB 2 NCX are included for older readers.
"""

import html
import os
import re
import tempfile
import uuid
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pdf_worker.footnotes import display_marker
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import REF_RE, Block, Gloss, Heading, Note, Paragraph

# Start a new chapter file at a heading once the current one has this much text, and
# force one at a paragraph boundary when it grows past the hard limit (Kindle prefers
# content files well under 300 KB).
_MIN_CHAPTER_CHARS = 2_000
_MAX_CHAPTER_CHARS = 150_000
_NOTES_FILE = "notes.xhtml"
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
sup { font-size: 0.75em; line-height: 0; }
aside.note p { text-indent: 0; margin: 0 0 0.6em; text-align: left; }
div.gloss { font-size: 0.8em; margin: 0.4em 0 0.8em 1em; padding-left: 0.6em;
  border-left: 2px solid #999; }
div.gloss p { text-indent: 0; text-align: left; }
"""


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
    def __init__(self, zf: zipfile.ZipFile, notes_file, meta: Metadata) -> None:
        self.zf = zf
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
        self.open_note: Note | None = None

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
        self.zf.writestr(f"OEBPS/{name}", page)
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
            self.toc.append(
                _TocEntry(
                    block.level, REF_RE.sub("", block.text).strip(), f"{self.current_file}#{anchor}"
                )
            )
            if not self.chapter_title:
                self.chapter_title = REF_RE.sub("", block.text).strip()
            self.chars += len(block.text)
        elif isinstance(block, Paragraph):
            self.stats.paragraphs += 1
            css = ' class="small"' if block.small else ""
            self.parts.append(f"<p{css}>{self._inline(block.text)}</p>\n")
            self.chars += len(block.text)
            if self.chars >= _MAX_CHAPTER_CHARS:
                self._close_chapter()
        elif isinstance(block, Gloss):
            self.stats.glosses += 1
            lines = "<br/>".join(_esc(line) for line in block.lines)
            self.parts.append(f'<div class="gloss"><p>{lines}</p></div>\n')
            self.chars += sum(len(line) for line in block.lines)
        elif isinstance(block, Note):
            self._add_note(block)

    # -- notes ------------------------------------------------------------------------
    def _note_id(self, label: str) -> str:
        if label not in self.note_ids:
            self.note_ids[label] = f"n{len(self.note_ids) + 1}"
        return self.note_ids[label]

    def _inline(self, text: str) -> str:
        out = []
        last = 0
        for match in REF_RE.finditer(text):
            out.append(_esc(text[last : match.start()]))
            out.append(self._noteref(match.group(1)))
            last = match.end()
        out.append(_esc(text[last:]))
        return "".join(out)

    def _noteref(self, label: str) -> str:
        note_id = self._note_id(label)
        count = self.ref_counts.get(label, 0) + 1
        self.ref_counts[label] = count
        ref_id = f"r{note_id[1:]}" + (f"-{count}" if count > 1 else "")
        self.first_ref.setdefault(label, f"{self.current_file}#{ref_id}")
        return (
            f'<a class="noteref" id="{ref_id}" href="{_NOTES_FILE}#{note_id}" '
            f'epub:type="noteref" role="doc-noteref"><sup>{_esc(display_marker(label))}</sup></a>'
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
        self._write_note(note.label, self._inline_note(note.text))

    def _inline_note(self, text: str) -> str:
        # References inside notes are rare; render them as plain markers.
        return _esc(REF_RE.sub(lambda m: display_marker(m.group(1)), text))

    def _write_note(self, label: str, body: str) -> None:
        note_id = self._note_id(label)
        marker = _esc(display_marker(label))
        back = self.first_ref.get(label)
        link = f'<a href="{_attr(back)}" role="doc-backlink">{marker}</a>' if back else marker
        self.notes.write(
            f'<aside class="note" id="{note_id}" epub:type="footnote" role="doc-footnote">'
            f"<p>{link}. {body}</p></aside>\n"
        )

    def finish(self) -> None:
        self._flush_note()
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


def write_epub(blocks: Iterable[Block], output_path: Path, meta: Metadata) -> WriteStats:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.")
    os.close(fd)
    nfd, notes_name = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.n.")
    try:
        with (
            zipfile.ZipFile(tmp_name, "w", compression=zipfile.ZIP_DEFLATED) as zf,
            os.fdopen(nfd, "w", encoding="utf-8", newline="\n") as notes,
        ):
            # The mimetype entry must come first and be stored uncompressed.
            zf.writestr(
                zipfile.ZipInfo("mimetype"),
                "application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
            zf.writestr("META-INF/container.xml", _CONTAINER)
            zf.writestr("OEBPS/style.css", _CSS)
            builder = _EpubBuilder(zf, notes, meta)
            for block in blocks:
                builder.add(block)
            builder.finish()
            notes.close()
            has_notes = bool(builder.defined)
            if has_notes:
                _write_notes_file(zf, Path(notes_name), meta)
            zf.writestr("OEBPS/nav.xhtml", _nav(builder.toc, meta, has_notes))
            zf.writestr("OEBPS/toc.ncx", _ncx(builder.toc, meta, has_notes))
            zf.writestr("OEBPS/content.opf", _opf(builder.chapter_files, meta, has_notes))
        os.replace(tmp_name, output_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    finally:
        Path(notes_name).unlink(missing_ok=True)
    return builder.stats


def _write_notes_file(zf: zipfile.ZipFile, notes_path: Path, meta: Metadata) -> None:
    title = _notes_title(meta.language)
    head, tail = _xhtml_page(title, meta.language, "\0", epub_type="backmatter").split("\0")
    with zf.open(f"OEBPS/{_NOTES_FILE}", "w") as out:
        out.write(head.encode("utf-8"))
        out.write(
            f'<section epub:type="endnotes" role="doc-endnotes">\n<h2>{_esc(title)}</h2>\n'.encode()
        )
        with open(notes_path, "rb") as notes:
            for chunk in iter(lambda: notes.read(1 << 16), b""):
                out.write(chunk)
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


def _opf(chapters: list[str], meta: Metadata, has_notes: bool) -> str:
    modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
    ]
    spine = []
    for index, name in enumerate(chapters, start=1):
        items.append(f'<item id="c{index}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{index}"/>')
    if has_notes:
        items.append(f'<item id="notes" href="{_NOTES_FILE}" media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="notes"/>')
    creator = f"<dc:creator>{_esc(meta.author)}</dc:creator>\n    " if meta.author else ""
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


def _nav(toc: list[_TocEntry], meta: Metadata, has_notes: bool) -> str:
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

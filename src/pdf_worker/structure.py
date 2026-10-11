"""Rebuild document structure (headings, paragraphs, notes) from page layouts.

Blocks are yielded as a stream: paragraphs may span pages, but only the current
paragraph is held in memory. Footnote references in block text use the
``[^label]`` markup produced by ``pdf_worker.footnotes``.
"""

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

import pymupdf

from pdf_worker.footnotes import (
    CONTINUED,
    SEPARATOR_RE,
    BodyLine,
    PageLayout,
    is_small,
    layout_page,
)
from pdf_worker.layout import HEADING_RATIO, DocumentProfile, Line

# Gap between line tops, relative to normal line spacing, that starts a new paragraph.
_PARAGRAPH_GAP = 1.3
# A previous line ending this far (in ems) before the right margin is a paragraph end.
_SHORT_LINE_EMS = 2.5
_SENTENCE_END = tuple('.!?»"”’)]')
# A footnote reference in block text: ``[^label]``.
REF_RE = re.compile(r"\[\^([^\]\s]+)\]")
_REF_ONLY_RE = re.compile(r"^(?:\[\^[^\]\s]+\])+$")


@dataclass(frozen=True)
class Heading:
    text: str
    level: int


@dataclass(frozen=True)
class Paragraph:
    text: str
    small: bool = False  # smaller type than the body: glosses, captions, asides


@dataclass(frozen=True)
class Note:
    label: str
    text: str
    continued: bool = False  # continues the previous note with the same label


Block = Heading | Paragraph | Note


@dataclass
class _Margins:
    left: float
    right: float


@dataclass
class _Builder:
    """The block currently being assembled."""

    kind: str = ""  # "", "para", "small", "note", "heading"
    label: str = ""
    level: int = 0
    parts: list[str] = field(default_factory=list)
    lines: int = 0
    bold: bool = True

    def add(self, text: str, bold: bool) -> None:
        self.parts.append(text)
        self.lines += 1
        self.bold = self.bold and bold

    def text(self) -> str:
        return join_lines(self.parts)


def join_lines(parts: list[str]) -> str:
    """Join wrapped lines, undoing end-of-line hyphenation (``Pu-`` + ``ella``)."""
    out = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not out:
            out = part
        elif len(out) > 1 and out[-1] == "-" and out[-2].isalpha() and part[0].islower():
            out = out[:-1] + part
        elif _REF_ONLY_RE.match(part):
            out += part  # a reference that wrapped onto its own line
        else:
            out += " " + part
    return out


def iter_blocks(doc: pymupdf.Document, profile: DocumentProfile) -> Iterator[Block]:
    """Yield the document's blocks in reading order, one page loaded at a time."""
    state = _State(profile)
    previous_label = None
    for index in range(doc.page_count):
        page = doc.load_page(index)
        layout = layout_page(page, index, profile, previous_label)
        previous_label = layout.trailing_label
        yield from state.add_page(layout, page.rect.height)
    yield from state.finish()


class _State:
    def __init__(self, profile: DocumentProfile) -> None:
        self.profile = profile
        self.current = _Builder()
        self.pending_notes: list[Note] = []
        self.prev: Line | None = None
        self.prev_text = ""
        self.prev_margins: _Margins | None = None
        self.break_next = False  # a blank line was seen

    # -- page handling ----------------------------------------------------------------
    def add_page(self, layout: PageLayout, page_height: float) -> Iterator[Block]:
        profile = self.profile
        lines = [
            bl
            for bl in layout.lines
            if not profile.is_running(bl.line, page_height) and not SEPARATOR_RE.match(bl.text)
        ]
        margins = _page_margins(lines, profile.body_size)
        new_page = True
        # Blank lines only separate paragraphs between two lines of the same page; blanks
        # at the top or bottom of a page are layout padding.
        self.break_next = False
        for body_line in lines:
            if not body_line.text.strip():
                self.break_next = not new_page
                continue
            yield from self._add_line(body_line, margins, new_page)
            new_page = False
        for label, texts in layout.notes:
            continued = bool(texts) and texts[0].startswith(CONTINUED)
            parts = [texts[0][len(CONTINUED) :] if continued else texts[0], *texts[1:]]
            self.pending_notes.append(Note(label, join_lines(parts), continued))
        if self.current.kind == "":
            yield from self._flush_notes()
        self.prev_margins = margins

    def finish(self) -> Iterator[Block]:
        yield from self._flush()

    # -- line handling ----------------------------------------------------------------
    def _add_line(self, body_line: BodyLine, margins: _Margins, new_page: bool) -> Iterator[Block]:
        line, text = body_line.line, body_line.text
        profile = self.profile
        level = None
        if line.size >= profile.body_size * HEADING_RATIO:
            level = profile.heading_level(line.size)

        if body_line.endnote_label:
            yield from self._flush()
            self.current = _Builder(kind="note", label=body_line.endnote_label)
        elif level:
            same_heading = (
                self.current.kind == "heading"
                and self.current.level == level
                and not self._starts_paragraph(line, text, margins, new_page)
            )
            if not same_heading:
                yield from self._flush()
                self.current = _Builder(kind="heading", level=level)
        else:
            kind = "small" if is_small(line, profile.body_size) else "para"
            starts = self._starts_paragraph(line, text, margins, new_page)
            if self.current.kind == "note" and not starts:
                kind = "note"  # endnote text wrapping onto further lines
            if starts or self.current.kind != kind:
                yield from self._flush()
                self.current = _Builder(kind=kind)
        self.current.add(text, line.bold)
        self.prev, self.prev_text = line, text
        self.break_next = False

    def _starts_paragraph(self, line: Line, text: str, margins: _Margins, new_page: bool) -> bool:
        prev = self.prev
        if prev is None or self.break_next:
            return True
        if abs(line.size - prev.size) > 0.6:
            return True
        stripped = self.prev_text.rstrip()
        # A trailing footnote reference doesn't hide the punctuation before it.
        stripped = REF_RE.sub("", stripped).rstrip()
        ends_sentence = stripped.endswith(_SENTENCE_END)
        if len(text) - len(text.lstrip(" ")) >= 2:
            return True  # typed indentation (leading spaces)
        size = line.size or self.profile.body_size
        indented = margins.left + 0.8 * size < line.x0 < margins.left + 6 * size
        if not new_page:
            spacing = self.profile.line_spacing * (size / (self.profile.body_size or size))
            gap = line.top - prev.top
            if gap > spacing * _PARAGRAPH_GAP:
                return True
            if gap < -spacing * 0.5:
                return ends_sentence  # jumped up to a new column
        if indented:
            return True
        right = (self.prev_margins if new_page and self.prev_margins else margins).right
        short = prev.x1 < right - _SHORT_LINE_EMS * (prev.size or size)
        # A short line ends its paragraph when the sentence ended, or when the next line
        # starts like a new item (contents entries, lists, verse).
        first = text.lstrip()[:1]
        return short and (ends_sentence or first.isupper() or first.isdigit())

    # -- output -----------------------------------------------------------------------
    def _flush(self) -> Iterator[Block]:
        current, self.current = self.current, _Builder()
        if current.kind == "":
            pass
        elif current.kind == "heading":
            yield Heading(current.text(), current.level)
        elif current.kind == "note":
            yield Note(current.label, current.text())
        else:
            text = current.text()
            if text:
                level = self._implicit_heading_level(current, text)
                if level:
                    yield Heading(text, level)
                else:
                    yield Paragraph(text, small=current.kind == "small")
        yield from self._flush_notes()

    def _flush_notes(self) -> Iterator[Block]:
        notes, self.pending_notes = self.pending_notes, []
        yield from notes

    def _implicit_heading_level(self, block: _Builder, text: str) -> int | None:
        """A short, isolated, all-caps or bold line (or two) in body type reads as a heading."""
        if block.kind != "para" or block.lines > 2 or len(text) > 120:
            return None
        if text.endswith((".", ",", ";", ":")) or "[^" in text:
            return None
        letters = [c for c in text if c.isalpha()]
        if len(letters) < 3:
            return None
        if all(c.isupper() for c in letters) or block.bold:
            return len(self.profile.heading_sizes) + 1
        return None


def _page_margins(lines: list[BodyLine], body_size: float) -> _Margins:
    """Typical left edge and right edge of body text on this page."""
    lefts: Counter[int] = Counter()
    rights: list[float] = []
    for body_line in lines:
        line = body_line.line
        if body_line.text.strip() and abs(line.size - body_size) < 0.6:
            lefts[round(line.x0)] += 1
            rights.append(line.x1)
    if not lefts:
        return _Margins(left=0.0, right=0.0)
    rights.sort()
    return _Margins(left=float(lefts.most_common(1)[0][0]), right=rights[int(len(rights) * 0.8)])

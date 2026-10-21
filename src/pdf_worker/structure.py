"""Rebuild document structure (headings, paragraphs, notes) from page layouts.

Blocks are yielded as a stream: paragraphs may span pages, but only the current
paragraph is held in memory. Footnote references in block text use the
``[^label]`` markup produced by ``pdf_worker.footnotes``.
"""

import re
from collections import Counter
from collections.abc import Callable, Collection, Iterator
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
from pdf_worker.images import PageImage, labels_inside, page_images
from pdf_worker.inline import (
    CELL,
    LEADING_PAGE_MARKS_RE,
    MARGIN_REF_RE,
    STYLE_RE,
    link,
    margin_ref,
    page_mark,
    page_target,
    plain,
    uri_target,
)
from pdf_worker.layout import HEADING_RATIO, PAGE_NUMBER_RE, DocumentProfile, Line, page_lines
from pdf_worker.margin_refs import bracketed, has_letter, next_label
from pdf_worker.margins import split_columns

# Gap between line tops, relative to normal line spacing, that starts a new paragraph.
_PARAGRAPH_GAP = 1.3
# A previous line ending this far (in ems) before the right margin is a paragraph end.
_SHORT_LINE_EMS = 2.5
_SENTENCE_END = tuple('.!?»"”’)]')
# Font size change (share of the block's size) that starts a new block. OCR'd text layers
# size each line from its height, so sizes wobble by a few percent.
_SIZE_JITTER = 0.08
# A "heading" longer than this is large print, not a heading.
_MAX_HEADING_LINES = 3
_MAX_HEADING_CHARS = 160
# A contents entry: a title, then dot leaders or spaces, then a page number.
# (The page number may sit in a column of its own: then the entry ends in leaders.)
_CONTENTS_ENTRY_RE = re.compile(
    r"^\s*\S.*?(?:[.·…_ ]*[.·…_]{3,}\s*(?:\d{1,4}|[ivxlcdm]{1,7})?"
    r"|\s+(?:\d{1,4}|[ivxlcdm]{1,7}))\s*$",
    re.IGNORECASE,
)
_MIN_CONTENTS_ENTRIES = 5
# Chapter numbers are short headings too: "3", "IV", "II.".
_NUMBERING_RE = re.compile(r"^\s*(?:\d{1,3}|[IVXLC]{1,6})\.?\s*$")
# A footnote reference in block text: ``[^label]``.
REF_RE = re.compile(r"\[\^([^\]\s]+)\]")
_REF_ONLY_RE = re.compile(r"^(?:\[\^[^\]\s]+\])+$")
_LEADING_REFS_RE = re.compile(f"^((?:{MARGIN_REF_RE.pattern}\\s*)+)")
# Running heads sit in this top share of the page; some share a line with the page
# number: "TIMEO 163", "164 DIÁLOGOS".
_HEAD_ZONE = 0.1
_HEAD_WITH_NUMBER_RE = re.compile(r"^(?:(\d{1,4})\s+(\D.*)|(\D.*?)\s+(\d{1,4}))$")
SOFT_HYPHEN = "­"
# Marks a paragraph break inside a block's lines (multi-paragraph notes).
PARAGRAPH_BREAK = " "


@dataclass(frozen=True)
class Heading:
    text: str
    level: int
    page: int = -1  # PDF page index and position of the heading, for resolving links
    top: float = 0.0


@dataclass(frozen=True)
class Paragraph:
    text: str
    small: bool = False  # smaller type than the body: glosses, captions, asides
    page: int = -1  # where it starts, for resolving links (see Heading)
    top: float = 0.0


@dataclass(frozen=True)
class Note:
    label: str
    text: str
    continued: bool = False  # continues the previous note with the same label


@dataclass(frozen=True)
class Gloss:
    """Notes printed in the page margin beside the text, one entry per line."""

    lines: tuple[str, ...]


@dataclass(frozen=True)
class Image:
    """A picture (JPEG), placed after the paragraph it follows on the page."""

    data: bytes
    width: int
    height: int


@dataclass(frozen=True)
class Table:
    """Rows of cells: text that sat side by side on two or more consecutive rows."""

    rows: tuple[tuple[str, ...], ...]


Block = Heading | Paragraph | Note | Gloss | Image | Table


@dataclass
class _Margins:
    left: float
    right: float


@dataclass
class _Builder:
    """The block currently being assembled."""

    kind: str = ""  # "", "para", "small", "note", "heading", "table"
    label: str = ""
    level: int = 0
    parts: list[str] = field(default_factory=list)
    lines: int = 0
    bold: bool = True
    size_total: float = 0.0
    page: int = -1  # where the block starts: PDF page index and top of its first line
    top: float = 0.0
    rows: list[list[str]] = field(default_factory=list)  # kind "table"

    def add(self, text: str, line: Line, page: int, emphasized: bool = False) -> None:
        if not self.lines:
            self.page, self.top = page, line.top
        self.parts.append(text)
        self.lines += 1
        self.bold = self.bold and (line.bold or emphasized)
        self.size_total += line.size

    @property
    def size(self) -> float:
        """Mean font size of the block's lines (OCR'd text jitters line by line)."""
        return self.size_total / self.lines if self.lines else 0.0

    def text(self) -> str:
        return join_lines(self.parts)


def join_lines(parts: list[str]) -> str:
    """Join wrapped lines, undoing end-of-line hyphenation (``Pu-`` + ``ella``).

    A ``PARAGRAPH_BREAK`` part becomes a blank line (``\\n\\n``) between paragraphs.
    """
    out = ""
    for part in parts:
        if part == PARAGRAPH_BREAK:
            if out and not out.endswith("\n\n"):
                out += "\n\n"
            continue
        part = part.strip()
        # Page-start markers lead a page's first line; join on the text after them.
        lead = ""
        marks = LEADING_PAGE_MARKS_RE.match(part)
        if marks:
            lead, part = marks.group(1), marks.group(2).strip()
        # Margin references open their line; one on a word broken across lines goes
        # before the whole word ("des-" + "pués").
        found = _LEADING_REFS_RE.match(part)
        refs = (
            "".join(margin_ref(label) for label in MARGIN_REF_RE.findall(found.group(1)))
            if found
            else ""
        )
        if found:
            lead, part = lead + refs, part[found.end() :].strip()
        if not part:
            out += lead
            continue
        if not out or out.endswith("\n\n") or not plain(out):
            out += lead + part
        elif (
            len(out) > 1
            and out[-1] == "-"
            and STYLE_RE.sub("", out[:-1])[-1:].isalpha()
            and STYLE_RE.sub("", part)[:1].islower()
        ) or (
            out[-1] == SOFT_HYPHEN  # the layer marks the break as hyphenation
        ):
            if refs:
                cut = max(out.rfind(" "), out.rfind("\n")) + 1
                out = out[:cut] + refs + out[cut:]
                lead = lead[: -len(refs)]
            out = out[:-1] + lead + part
        elif _REF_ONLY_RE.match(part):
            out += lead + part  # a reference that wrapped onto its own line
        else:
            out += " " + lead + part
    return out


def iter_blocks(
    doc: pymupdf.Document,
    profile: DocumentProfile,
    images: bool = False,
    skip: Collection[int] = (),
    on_page: Callable[[int, int], None] | None = None,
) -> Iterator[Block]:
    """Yield the document's blocks in reading order, one page loaded at a time.

    With ``images``, pictures on each page become ``Image`` blocks. ``skip`` pages
    (indexes) are left out. ``on_page(done, total)`` follows the pages.
    """
    state = _State(profile)
    previous_label = None
    for index in range(doc.page_count):
        if on_page:
            on_page(index, doc.page_count)
        if index in skip:
            continue
        page = doc.load_page(index)
        layout = layout_page(page, index, profile, previous_label)
        previous_label = layout.trailing_label
        label = profile.page_labels[index] if index < len(profile.page_labels) else ""
        pictures = []
        if images:
            # All of the page's text (footnotes too) must be masked out of scans.
            pictures = page_images(page, page_lines(page), profile.repeated_images)
        yield from state.add_page(
            layout,
            page.rect.width,
            page.rect.height,
            page_index=index,
            page_label=label or str(index + 1),
            links=_page_links(page, doc.page_count),
            images=pictures,
        )
    yield from state.finish()
    if on_page:
        on_page(doc.page_count, doc.page_count)


def _is_contents_page(lines: list[BodyLine]) -> bool:
    """Most lines are contents entries: text ending in a page number."""
    texts = [plain(bl.text).strip() for bl in lines if bl.text.strip()]
    entries = sum(1 for text in texts if _CONTENTS_ENTRY_RE.match(text))
    return entries >= _MIN_CONTENTS_ENTRIES and entries >= 0.5 * len(texts)


def _running_heads(
    lines: list[BodyLine], page_width: float, page_height: float, body_size: float
) -> tuple[set[int], str]:
    """Running heads: small lines at the top of the page on one row with the page number
    ("TIMEO ... 163"). Found on every page, however short the book.

    Returns their indexes and, on a right-hand page (number on the right), the head:
    by convention there the work's title, on left-hand pages the book's.
    """
    heads, title = set(), ""
    top = [
        (i, bl)
        for i, bl in enumerate(lines)
        if plain(bl.text).strip() and bl.line.top < page_height * _HEAD_ZONE
    ]
    numbers = [bl.line for _, bl in top if PAGE_NUMBER_RE.match(plain(bl.text))]
    for i, bl in top:
        text = plain(bl.text).strip()
        if PAGE_NUMBER_RE.match(text) or bl.line.size > body_size * 1.05:
            continue
        merged = _HEAD_WITH_NUMBER_RE.match(text)
        if merged:
            head = (merged.group(2) or merged.group(3)).strip()
            right_hand = merged.group(4) is not None
        else:
            height = bl.line.bbox[3] - bl.line.top
            row = [n for n in numbers if abs(n.top - bl.line.top) < height]
            if not row:
                continue
            head, right_hand = text, row[0].x0 > page_width / 2
        if any(c.isalpha() for c in head):
            heads.add(i)
            title = head if right_hand else title
    return heads, title


def _page_links(page: pymupdf.Page, page_count: int) -> list[tuple[pymupdf.Rect, str]]:
    """Links on a page as (area, inline target): web addresses and places in the book."""
    out = []
    for item in page.get_links():
        rect = pymupdf.Rect(item["from"])
        if item.get("uri") and item["kind"] == pymupdf.LINK_URI:
            out.append((rect, uri_target(item["uri"])))
        elif item["kind"] in (pymupdf.LINK_GOTO, pymupdf.LINK_NAMED):
            target_page = item.get("page", -1)
            if 0 <= target_page < page_count:
                to = item.get("to")
                out.append((rect, page_target(target_page, to.y if to else 0.0)))
    return out


def _link_line(body_line: BodyLine, links: list[tuple[pymupdf.Rect, str]]) -> BodyLine:
    """Wrap the parts of a line that were links in the PDF with link markers."""
    line, text = body_line.line, body_line.text
    height = line.bbox[3] - line.bbox[1]
    found = False
    for rect, target in sorted(links, key=lambda item: item[0].x0):
        overlap = min(rect.y1, line.bbox[3]) - max(rect.y0, line.bbox[1])
        if overlap < 0.5 * height or rect.x1 <= line.x0 or rect.x0 >= line.x1:
            continue
        inside = [
            span["text"]
            for span in line.spans
            if rect.x0 - 1 <= (span["bbox"][0] + span["bbox"][2]) / 2 <= rect.x1 + 1
        ]
        linked = "".join(inside).strip()
        if not linked:
            continue
        if linked == plain(text).strip():
            stripped = text.strip()
            text = text.replace(stripped, link(target, stripped), 1)
        elif linked in text:
            text = text.replace(linked, link(target, linked), 1)
        else:
            continue
        found = True
    return BodyLine(text, line, body_line.endnote_label) if found else body_line


class _State:
    def __init__(self, profile: DocumentProfile) -> None:
        self.profile = profile
        self.current = _Builder()
        # Glosses and notes wait until the paragraph in progress ends.
        self.pending: list[Note | Gloss | Image] = []
        self.prev: Line | None = None
        self.prev_text = ""
        self.prev_margins: _Margins | None = None
        self.break_next = False  # a blank line was seen
        self.in_notes = False  # inside a chapter-endnotes area (see pdf_worker.endnotes)
        self.page_index = 0
        self.pending_marks: list[str] = []  # page starts not yet attached to a line
        self.margin_label: str | None = None  # the last margin reference ("22b")
        self.has_heading = False  # a heading was yielded (or a running head made one)

    # -- page handling ----------------------------------------------------------------
    def add_page(
        self,
        layout: PageLayout,
        page_width: float,
        page_height: float,
        page_index: int = 0,
        page_label: str = "",
        links: list[tuple[pymupdf.Rect, str]] | None = None,
        images: list[PageImage] | None = None,
    ) -> Iterator[Block]:
        profile = self.profile
        self.page_index = page_index
        # The page's start is marked on its first line (pages without text pass it on).
        self.pending_marks.append(page_mark(page_index, page_label or str(page_index + 1)))
        pictures = sorted(images or [], key=lambda image: image.top)
        # Labels printed inside a picture ("insula", "fluvius") stay in the picture.
        labels = labels_inside([bl.line for bl in layout.lines], pictures)
        heads, title = _running_heads(layout.lines, page_width, page_height, profile.body_size)
        if title and not self.has_heading:
            # A book without headings opens with its running title ("TIMEO"), once.
            self.has_heading = True
            self.pending.append(Heading(title, 1, page_index, 0.0))
        columns = split_columns(
            [
                bl
                for i, bl in enumerate(layout.lines)
                if i not in labels
                and i not in heads
                and not profile.is_running(bl.line, page_height)
                and not SEPARATOR_RE.match(bl.text)
            ],
            page_width,
            profile.body_size,
        )
        lines = list(columns.body)
        glosses = columns.glosses
        if _is_contents_page(lines) and not links:
            # A printed table of contents without links: the EPUB has its own, so the
            # entries ("Chapter One ...... 42") and a column of page numbers are dropped.
            lines = [bl for bl in lines if not _CONTENTS_ENTRY_RE.match(plain(bl.text))]
            glosses = ()
        lines = self._label_margin_refs(lines)
        # Printed in the text, so taken as read: notes cite them out of order ("[38e]").
        lines = [BodyLine(bracketed(bl.text), bl.line, bl.endnote_label) for bl in lines]
        margins = _page_margins(lines, profile.body_size)
        new_page = True
        # Blank lines only separate paragraphs between two lines of the same page; blanks
        # at the top or bottom of a page are layout padding.
        self.break_next = False
        for body_line in lines:
            if not body_line.text.strip():
                self.break_next = not new_page
                continue
            while pictures and pictures[0].top < body_line.line.top:
                # A picture above this line follows the paragraph in progress.
                picture = pictures.pop(0)
                self.pending.append(Image(picture.data, picture.width, picture.height))
            if links:
                body_line = _link_line(body_line, links)
            if self.pending_marks:
                marks, self.pending_marks = "".join(self.pending_marks), []
                body_line = BodyLine(
                    marks + body_line.text, body_line.line, body_line.endnote_label
                )
            yield from self._add_line(body_line, margins, new_page)
            new_page = False
        for picture in pictures:  # pictures below the page's last line
            self.pending.append(Image(picture.data, picture.width, picture.height))
        if glosses:
            # Like footnotes, the page's glosses follow the paragraph in progress.
            self.pending.append(Gloss(glosses))
        for label, texts in layout.notes:
            continued = bool(texts) and texts[0].startswith(CONTINUED)
            parts = [texts[0][len(CONTINUED) :] if continued else texts[0], *texts[1:]]
            self.pending.append(Note(label, join_lines(parts), continued))
        if self.current.kind == "":
            yield from self._flush_notes()
        self.prev_margins = margins

    def finish(self) -> Iterator[Block]:
        yield from self._flush()

    def _label_margin_refs(self, lines: list[BodyLine]) -> list[BodyLine]:
        """Give the page's margin references their full labels ("b" -> "22b"), in order.

        Bare numbers on a page without section letters, outside a running sequence, are
        line numbers ("5", "10"): dropped."""
        readings = [r for bl in lines for r in MARGIN_REF_RE.findall(bl.text)]
        if not readings:
            return lines
        if self.profile.bracketed_refs:  # printed in the text: line-end marks are page numbers
            return [
                BodyLine(MARGIN_REF_RE.sub("", bl.text), bl.line, bl.endnote_label) for bl in lines
            ]
        running = bool(self.margin_label and self.margin_label[:-1].isdigit())
        keep = running or any(has_letter(r) for r in readings)

        def label(match: re.Match) -> str:
            new = next_label(self.margin_label, match.group(1)) if keep else None
            if new is None:
                return ""
            self.margin_label = new
            return margin_ref(new)

        return [
            BodyLine(MARGIN_REF_RE.sub(label, bl.text), bl.line, bl.endnote_label) for bl in lines
        ]

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
            self.in_notes = body_line.endnote_label.startswith("c")
        elif self.in_notes and self.current.kind == "note":
            notes = profile.chapter_notes
            last = (
                self.current.label in notes.last_in_group
                and self.current.label not in notes.section_continues
            )
            starts = self._starts_paragraph(line, text, margins, new_page)
            if level and not last:
                # A group heading inside the notes area ("2 The Foundation ..."): drop it,
                # but keep any page-start marker it carried for the next line.
                marks = LEADING_PAGE_MARKS_RE.match(text.strip())
                if marks:
                    self.pending_marks.append(marks.group(1))
                return
            other_type = abs(line.size - self.current.size) > _SIZE_JITTER * self.current.size
            if last and (level or (starts and other_type)):
                # The notes area ends after a group's last note, at a heading or where
                # the type changes back from note size.
                self.in_notes = False
                yield from self._add_line(body_line, margins, new_page)
                return
            if starts:
                self.current.parts.append(PARAGRAPH_BREAK)  # a note with paragraphs
            self.current.add(text, line, self.page_index)
            self.prev, self.prev_text = line, text
            self.break_next = False
            return
        elif CELL in text and not level:
            # A row of side-by-side cells: start or extend a table.
            cells = [cell.strip() for cell in text.split(CELL)]
            current = self.current
            if current.kind != "table" or abs(len(cells) - len(current.rows[0])) > 1:
                yield from self._flush()
                self.current = current = _Builder(kind="table")
                current.page, current.top = self.page_index, line.top
            current.rows.append(cells)
            current.lines += 1
            self.prev, self.prev_text = line, text
            self.break_next = False
            return
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
            if not starts and self.current.kind in ("note", "para", "small"):
                # Wrapped lines keep the block's kind: endnote text, and OCR'd lines whose
                # size straddles the small-type threshold.
                kind = self.current.kind
            if starts or self.current.kind != kind:
                yield from self._flush()
                self.current = _Builder(kind=kind)
        self.current.add(text, line, self.page_index, profile.emphasized(line))
        self.prev, self.prev_text = line, text
        self.break_next = False

    def _starts_paragraph(self, line: Line, text: str, margins: _Margins, new_page: bool) -> bool:
        prev = self.prev
        if prev is None or self.break_next:
            return True
        reference = self.current.size or prev.size
        if abs(line.size - reference) > max(0.6, _SIZE_JITTER * reference):
            return True
        if self.profile.emphasized(prev) and not self.profile.emphasized(line):
            return True  # a bold heading line, then the paragraph
        stripped = plain(self.prev_text).rstrip()
        # A trailing footnote reference doesn't hide the punctuation before it.
        stripped = REF_RE.sub("", stripped).rstrip()
        ends_sentence = stripped.endswith(_SENTENCE_END)
        text = plain(text)
        if len(text) - len(text.lstrip(" ")) >= 2:
            return True  # typed indentation (leading spaces)
        size = line.size or self.profile.body_size
        indented = margins.left + 0.8 * size < line.x0 < margins.left + 6 * size
        if not new_page:
            spacing = self.profile.line_spacing * (size / (self.profile.body_size or size))
            gap = line.baseline - prev.baseline
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
            text = current.text()
            letters = sum(c.isalnum() for c in plain(text))
            if letters < 3 and not _NUMBERING_RE.match(plain(text)):
                pass  # a speck of OCR noise in large type ("y", "HN")
            elif current.lines > _MAX_HEADING_LINES or len(plain(text)) > _MAX_HEADING_CHARS:
                # Several lines of large type: a passage in big print, not a heading.
                yield Paragraph(text, False, current.page, current.top)
            else:
                self.has_heading = True
                yield Heading(text, current.level, current.page, current.top)
        elif current.kind == "note":
            yield Note(current.label, current.text())
        elif current.kind == "table":
            if len(current.rows) >= 2:
                width = max(len(row) for row in current.rows)
                yield Table(tuple(tuple(row + [""] * (width - len(row))) for row in current.rows))
            else:
                # One row is no table: text with a wide gap, such as "Name      Date".
                text = " ".join(current.rows[0])
                yield Paragraph(text, False, current.page, current.top)
        else:
            text = current.text()
            if text:
                level = self._implicit_heading_level(current, plain(text))
                if level:
                    self.has_heading = True
                    yield Heading(text, level, current.page, current.top)
                else:
                    yield Paragraph(text, current.kind == "small", current.page, current.top)
        yield from self._flush_notes()

    def _flush_notes(self) -> Iterator[Block]:
        pending, self.pending = self.pending, []
        yield from pending

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
    """Typical left edge and right edge of body text on this page. Where no line is in
    the book's body size, the page's own size stands in: the Timeo's dialogue is set
    larger than its long notes, and without margins every line counted as indented."""
    texts = [bl for bl in lines if bl.text.strip()]
    if texts and not any(abs(bl.line.size - body_size) < 0.6 for bl in texts):
        body_size = Counter(bl.line.size for bl in texts).most_common(1)[0][0]
    lefts: Counter[int] = Counter()
    rights: list[float] = []
    for body_line in lines:
        line = body_line.line
        if body_line.text.strip() and abs(line.size - body_size) < 0.6:
            lefts[round(line.x0 / 3) * 3] += 1
            rights.append(line.x1)
    if not lefts:
        return _Margins(left=0.0, right=0.0)
    rights.sort()
    # The leftmost edge shared by a fair share of lines: in dialogue most lines are
    # indented speaker turns, so the most common edge would be the indent.
    shared = [x for x, n in lefts.items() if n >= max(2, 0.2 * len(rights))]
    left = min(shared) if shared else lefts.most_common(1)[0][0]
    return _Margins(left=float(left), right=rights[int(len(rights) * 0.8)])

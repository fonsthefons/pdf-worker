"""Detect footnotes and endnotes and mark them explicitly in extracted text.

Markup follows Markdown/Pandoc footnote syntax so later converters can rebuild them:

* Page footnotes (small text at the bottom of a page, referenced by superscript markers)
  get page-scoped labels: ``body text[^p12-1]`` ... ``[^p12-1]: The note.``
  A note that runs onto the next page is emitted again with the same label and the
  prefix ``(continued)``.
* Bracketed endnotes (``[31]`` in the body, and a later line starting with ``[31]``)
  keep their number: ``body text[^31]`` ... ``[^31]: The note.``

References are only rewritten when a matching definition was found, so exponents and
other stray superscripts or bracketed numbers are left untouched.

Detection needs the document profile from ``pdf_worker.layout.analyze_document`` (one
cheap pass) before pages are processed; both passes hold a single page at a time.
"""

import re
from dataclasses import dataclass

import pymupdf

from pdf_worker.layout import (
    LOOSE_NOTE_MARK_RE,
    NOTE_MARK_RE,
    PAGE_NUMBER_RE,
    SMALL_RATIO,
    SUPERSCRIPT,
    DocumentProfile,
    Line,
    boxes,
    page_lines,
    plain_note_start,
)
from pdf_worker.styles import span_text

# Footnote regions must start in the lower part of the page.
_REGION_MIN_TOP = 0.4
CONTINUED = "(continued) "
NO_NOTE_TEXT = "no footnote content found"  # the note of a reference whose note wasn't found
# Highest note number trusted when the marker looks like ordinary text.
_MAX_PLAIN_MARKER = 30

_MARKER = r"\d{1,3}|[*†‡§¶]{1,3}"
_MARKER_RE = re.compile(rf"^(?:{_MARKER})$")
_MARKER_LIST_RE = re.compile(rf"^(?:{_MARKER})(?:\s*,\s*(?:{_MARKER}))*$")
_DEF_START_RE = re.compile(rf"^\s*({_MARKER})(?:[.)]\s*|\s+)(?=\S)")
# OCR often garbles a superscript marker into stray symbols: "*8 It is", "‘3 See".
_OCR_DEF_START_RE = re.compile(r"^\s*[*'‘’\"“”^°]{1,2}(\d{1,3})\s+(?=\S)")
_BRACKET_REF_RE = re.compile(r"[ \t ]*\[(\d{1,4})\]")
_BRACKET_DEF_RE = re.compile(r"^\s*\[(\d{1,4})\][\s ]*")
SEPARATOR_RE = re.compile(r"^\s*[_\-—–]{3,}\s*$")
# A printer's signature mark at the foot of a page: "P 2", "B", "Q 3".
_SIGNATURE_RE = re.compile(r"^[A-Z]{1,2}(?:\s*\d)?$")


@dataclass(frozen=True)
class BodyLine:
    """A body text line with footnote references already rewritten to ``[^label]``."""

    text: str
    line: Line
    # Set when this line starts an endnote definition; ``text`` is then the note text.
    endnote_label: str | None = None
    # The layout model's say on a paragraph starting here: between two lines of
    # bibliography (``reference_content`` boxes), True at a new box, False inside one;
    # None leaves it to ``structure``'s rules.
    starts: bool | None = None


@dataclass(frozen=True)
class PageLayout:
    lines: tuple[BodyLine, ...]
    # Page footnotes found at the bottom of the page: (label, text lines).
    notes: tuple[tuple[str, tuple[str, ...]], ...]
    definitions: tuple[str, ...]  # labels defined on this page (continuations excluded)
    references: tuple[str, ...]  # labels referenced on this page, in order
    trailing_label: str | None  # last page footnote on the page (may continue)
    # Running heads and feet, page numbers, watermarks (``DocumentProfile.furniture``).
    furniture: tuple[Line, ...]


@dataclass(frozen=True)
class RenderedPage:
    text: str
    definitions: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    trailing_label: str | None = None


def display_marker(label: str) -> str:
    """The marker a reader sees: ``p12-1`` / ``c3-1`` / ``o12-1`` (a reference whose
    note wasn't found) -> ``1``; endnote ``31`` -> ``31``."""
    if label[:1] in ("p", "c", "o") and "-" in label:
        return label.split("-", 1)[1]
    return label


def layout_page(
    page: pymupdf.Page,
    page_index: int,
    profile: DocumentProfile,
    previous_label: str | None = None,
) -> PageLayout:
    """Split a page into body lines (references marked) and its footnotes."""
    lines = page_lines(page)
    furniture = profile.furniture(page_index, lines, page.rect.height)
    chapter_notes = profile.chapter_notes
    region = None
    if page_index not in chapter_notes.note_pages:
        region = _find_region(lines, profile.body_size, page.rect.height, furniture)
    notes: list[tuple[str, list[str]]] = []
    marker_labels: dict[str, str] = {}
    consumed: set[int] = set()
    if region is not None:
        notes, marker_labels, consumed = _collect_footnotes(
            lines, region, page_index + 1, previous_label
        )

    # One bibliography entry per ``reference_content`` box; not on a page of chapter
    # notes, which the model boxes alike (one box per note, or across two).
    row = None if page_index in chapter_notes.note_pages else profile.layout.get(page_index)
    entries = [
        i if i is not None and row["blocks"][i]["label"] == "reference_content" else None
        for i in (boxes(page, row, lines) if row else [None] * len(lines))
    ]
    entry = None  # the box of the body line before

    references: list[str] = []
    # A note continued from the previous page reuses that page's label; count it once.
    definitions = [label for label, _ in notes if label != previous_label]
    body: list[BodyLine] = []
    for line_index, line in enumerate(lines):
        if line_index in consumed or line_index in furniture:
            continue
        before, entry = entry, entries[line_index]
        starts = None if before is None or entry is None else entry != before
        if page_index in chapter_notes.note_pages:
            hung = plain_note_start(lines, line_index)
            if hung and hung[1] != line_index and (page_index, hung[1]) in chapter_notes.defs:
                continue  # a note's number hung beside its first line, which takes it
        chapter_refs = chapter_notes.refs.get((page_index, line_index), {})
        # Outside the notes pages, a reference without its note still gets one.
        prefix = None if page_index in chapter_notes.note_pages else f"o{page_index + 1}-"
        text = _render_line(line, marker_labels, references, chapter_refs, prefix)
        chapter_def = chapter_notes.defs.get((page_index, line_index))
        if chapter_def:
            definitions.append(chapter_def)
            number = rf"^\s*{display_marker(chapter_def)}\.?\s*"
            # Its number, or the misread mark taken for it ("3.¡." for 34, ".i,57").
            mark = NOTE_MARK_RE if NOTE_MARK_RE.match(text) else LOOSE_NOTE_MARK_RE
            text = (
                re.sub(number, "", text, count=1)
                if re.match(number, text)
                else mark.sub("", text, count=1)
            )
            body.append(
                BodyLine(
                    text=text,
                    line=line,
                    endnote_label=chapter_def,
                    starts=starts,
                )
            )
            continue
        endnote, text = _split_endnote(text, page_index, line_index, profile)
        if endnote:
            definitions.append(endnote)
        text = _render_brackets(text, profile, references)
        body.append(BodyLine(text=text, line=line, endnote_label=endnote, starts=starts))
    trailing = notes[-1][0] if notes else None
    found = {label for label, _ in notes}
    for label in dict.fromkeys(marker_labels.values()):
        if label not in found and label in references:
            notes.append((label, [NO_NOTE_TEXT]))
            definitions.append(label)
    return PageLayout(
        lines=tuple(body),
        notes=tuple((label, tuple(texts)) for label, texts in notes),
        definitions=tuple(definitions),
        references=tuple(references),
        trailing_label=trailing,
        furniture=tuple(lines[i] for i in sorted(furniture)),
    )


def render_page(
    page: pymupdf.Page,
    page_index: int,
    profile: DocumentProfile,
    previous_label: str | None = None,
) -> RenderedPage:
    """Render one page's text with footnote references and definitions marked."""
    layout = layout_page(page, page_index, profile, previous_label)
    out = []
    for body_line in layout.lines:
        prefix = f"[^{body_line.endnote_label}]: " if body_line.endnote_label else ""
        out.append(prefix + body_line.text + "\n")
    if layout.notes:
        out.append("\n")
        for label, note_lines in layout.notes:
            out.append(f"[^{label}]: " + "\n".join(note_lines) + "\n")
    return RenderedPage(
        text="".join(out),
        definitions=layout.definitions,
        references=layout.references,
        trailing_label=layout.trailing_label,
    )


def is_small(line: Line, body_size: float) -> bool:
    return 0 < line.size < body_size * SMALL_RATIO


def _definition_marker(line: Line) -> tuple[str, str, bool] | None:
    """If ``line`` starts a footnote, return (marker, text after it, distinct).

    ``distinct`` is True when the marker is typeset apart from the text (superscript or
    smaller type), which makes it trustworthy even without matching references.
    """
    spans = [span for span in line.spans if span["text"].strip()]
    if not spans:
        return None
    first = spans[0]
    if first["flags"] & SUPERSCRIPT and _MARKER_RE.match(first["text"].strip()):
        rest = line.text.split(first["text"], 1)[1]
        return first["text"].strip(), rest.lstrip(), True
    match = _DEF_START_RE.match(line.text)
    if match:
        distinct = (
            len(spans) > 1
            and first["text"].strip() == match.group(1)
            and first["size"] < spans[1]["size"] * 0.85
        )
        return match.group(1), line.text[match.end() :], distinct
    match = _OCR_DEF_START_RE.match(line.text)
    if match:
        return match.group(1), line.text[match.end() :], False
    return None


def _superscript_markers(lines: list[Line]) -> list[str]:
    markers = []
    for line in lines:
        for span in line.spans:
            text = span["text"].strip()
            if span["flags"] & SUPERSCRIPT and _MARKER_LIST_RE.match(text):
                markers.extend(m.strip() for m in text.split(","))
    return markers


def _find_region(
    lines: list[Line], body_size: float, page_height: float, skip: set[int] = frozenset()
) -> list[int] | None:
    """Indices (top to bottom) of the bottom-of-page footnote region's lines, if any.

    Lines are taken in vertical order, not MuPDF's reading order, so a stray text box
    emitted last doesn't hide the notes; ``skip`` lines (page furniture) are ignored.
    """
    order = sorted(
        (i for i in range(len(lines)) if i not in skip),
        key=lambda i: (lines[i].top, lines[i].x0),
    )
    end = len(order)
    while end and _is_page_furniture(lines[order[end - 1]].text):
        end -= 1
    start = end
    while start:
        line = lines[order[start - 1]]
        # OCR jitter: one line a little too big (or a stray fragment like "2S") between
        # two small ones still belongs to the notes.
        jitter = (
            start >= 2
            and start < end
            and (line.size < body_size or len(line.text.strip()) <= 4)
            and is_small(lines[order[start - 2]], body_size)
            and is_small(lines[order[start]], body_size)
        )
        if not (is_small(line, body_size) or not line.text.strip() or jitter):
            break
        start -= 1
    while start < end and not lines[order[start]].text.strip():
        start += 1
    if start == end:
        return None
    region = order[start:end]
    region_top = min(lines[i].top for i in region if lines[i].text.strip())
    if region_top < page_height * _REGION_MIN_TOP:
        return None
    for i in order[:start]:
        if lines[i].text.strip() and lines[i].top >= region_top:
            return None  # body text beside or below it: margin notes, not footnotes
    above = [lines[i] for i in order[:start]]
    if not _under_body_column(above, [lines[i] for i in region], body_size):
        return None
    return region


def _under_body_column(above: list[Line], region: list[Line], body_size: float) -> bool:
    """Footnotes sit under a column of body text; glosses and line numbers sit beside it,
    and pages set entirely in small type (indexes, notes sections) have no footnotes."""
    body = [ln for ln in above if ln.text.strip() and abs(ln.size - body_size) < 0.1 * body_size]
    if len(body) < 3:
        return False
    left, right = _column_edges(body)
    middle = left + 0.5 * (right - left)
    # Tiny fragments ("ae", "2S") are OCR specks, often in the gutter; ignore them.
    region = [line for line in region if len(line.text.strip()) > 3]
    # Notes may be set in two columns (and OCR splits lines into fragments), but a fair
    # share of their text starts in the left half; glosses sit wholly to one side.
    chars = sum(len(line.text.strip()) for line in region)
    left_chars = sum(len(line.text.strip()) for line in region if line.x0 < middle)
    return left_chars >= 0.35 * chars and all(line.x1 > left and line.x0 < right for line in region)


def _column_edges(lines: list[Line]) -> tuple[float, float]:
    lefts = sorted(line.x0 for line in lines)
    rights = sorted(line.x1 for line in lines)
    return lefts[len(lefts) // 5], rights[len(rights) * 4 // 5]


def _is_page_furniture(text: str) -> bool:
    """Blank lines, page numbers, and printers' signature marks ("P 2") at the foot."""
    stripped = text.strip()
    return not stripped or bool(PAGE_NUMBER_RE.match(text)) or bool(_SIGNATURE_RE.match(stripped))


def _collect_footnotes(
    lines: list[Line], region: list[int], page_number: int, previous_label: str | None
) -> tuple[list[tuple[str, list[str]]], dict[str, str], set[int]]:
    """Split the footnote region into (label, text lines) notes.

    Returns the notes, a marker -> label map for rewriting references, and the indices
    of the lines that were moved into notes (all other lines stay in the body).
    """
    in_region = set(region)
    body_refs = _superscript_markers([ln for i, ln in enumerate(lines) if i not in in_region])
    footnotes: list[tuple[str, list[str]]] = []
    marker_labels: dict[str, str] = {}
    consumed: set[int] = set()
    leading: list[int] = []  # region lines before the first note marker
    last_number = 0
    region = _column_order(lines, region)
    # A note's first line is usually indented against its wrapped lines.
    region_left = min((lines[i].x0 for i in region if lines[i].text.strip()), default=0.0)
    for index in region:
        line = lines[index]
        text = line.text
        if not text.strip() or PAGE_NUMBER_RE.match(text):
            continue
        if SEPARATOR_RE.match(text):
            consumed.add(index)
            continue
        found = _definition_marker(line)
        if found:
            indented = line.x0 > region_left + 0.3 * (line.size or 1.0)
            found = (found[0], found[1], found[2] or indented)
        if found and _accept_marker(found[0], found[2], body_refs, marker_labels, last_number):
            marker, rest, _ = found
            label = f"p{page_number}-{marker}"
            marker_labels[marker] = label
            footnotes.append((label, [rest]))
            if marker.isdigit():
                last_number = int(marker)
            consumed.add(index)
        elif footnotes:
            footnotes[-1][1].append(text)
            consumed.add(index)
        else:
            leading.append(index)

    if leading and previous_label:
        # Small text above this page's first marker continues the previous page's note.
        texts = [lines[i].text for i in leading]
        footnotes.insert(0, (previous_label, [CONTINUED + texts[0], *texts[1:]]))
        consumed.update(leading)
    if not footnotes:
        return [], {}, set()
    return footnotes, marker_labels, consumed


def _column_order(lines: list[Line], region: list[int]) -> list[int]:
    """Notes set in two columns are read left column first, then right."""
    texts = [i for i in region if lines[i].text.strip()]
    if not texts:
        return region
    middle = (min(lines[i].x0 for i in texts) + max(lines[i].x1 for i in texts)) / 2
    right = [i for i in texts if lines[i].x0 >= middle]
    if not right or len(right) == len(texts):
        return region
    return sorted(region, key=lambda i: (lines[i].x0 >= middle, lines[i].top, lines[i].x0))


def _accept_marker(
    marker: str, distinct: bool, body_refs: list[str], seen: dict[str, str], last_number: int
) -> bool:
    if marker in seen:
        return False
    if body_refs:
        return marker in body_refs
    # No superscript references to confirm against: require an increasing sequence, and
    # a marker set apart from the text or a small number (not "341 F. 2d 1003").
    if not marker.isdigit():
        return True
    number = int(marker)
    return number > last_number and (distinct or number <= _MAX_PLAIN_MARKER)


def _render_line(
    line: Line,
    marker_labels: dict[str, str],
    references: list[str],
    chapter_refs: dict[int, str] | None = None,
    orphan_prefix: str | None = None,
) -> str:
    """A line's text with its note references marked. With ``orphan_prefix``, a
    superscript marker matching no note is marked too, labelled with the prefix, and
    added to ``marker_labels``."""
    if not marker_labels and not chapter_refs and orphan_prefix is None:
        return "".join(span_text(span) for span in line.spans)
    parts: list[str] = []
    for span_index, span in enumerate(line.spans):
        text = span["text"]
        stripped = text.strip()
        if chapter_refs and span_index in chapter_refs and stripped not in marker_labels:
            while parts and not parts[-1].strip():
                parts.pop()
            if parts:
                parts[-1] = parts[-1].rstrip()
            parts.append(f"[^{chapter_refs[span_index]}]")
            references.append(chapter_refs[span_index])
            if text != text.rstrip():
                parts.append(" ")
            continue
        if span["flags"] & SUPERSCRIPT and _MARKER_LIST_RE.match(stripped):
            markers = [m.strip() for m in stripped.split(",")]
            before = "".join(parts).split()[-1:]
            # An exponent ("m²", "x³") follows a word of a letter or two; a reference doesn't.
            exponent = bool(before) and before[0].isalpha() and len(before[0]) <= 2
            if orphan_prefix is not None and not exponent:
                for marker in markers:
                    marker_labels.setdefault(marker, f"{orphan_prefix}{marker}")
            if all(m in marker_labels for m in markers):
                while parts and not parts[-1].strip():
                    parts.pop()
                if parts:
                    parts[-1] = parts[-1].rstrip()
                for marker in markers:
                    parts.append(f"[^{marker_labels[marker]}]")
                    references.append(marker_labels[marker])
                continue
        parts.append(span_text(span))
    return "".join(parts)


def _split_endnote(
    text: str, page_index: int, line_index: int, profile: DocumentProfile
) -> tuple[str | None, str]:
    """If this line defines a bracketed endnote, return (label, text after the marker)."""
    if not profile.endnote_defs or "[" not in text:
        return None, text
    match = _BRACKET_DEF_RE.match(text)
    if match and profile.endnote_defs.get(int(match.group(1))) == (page_index, line_index):
        return str(int(match.group(1))), text[match.end() :]
    return None, text


def _render_brackets(text: str, profile: DocumentProfile, references: list[str]) -> str:
    if not profile.endnote_defs or "[" not in text:
        return text

    def _ref(found: re.Match) -> str:
        number = int(found.group(1))
        if number not in profile.endnote_defs:
            return found.group(0)
        references.append(str(number))
        return f"[^{number}]"

    return _BRACKET_REF_RE.sub(_ref, text)

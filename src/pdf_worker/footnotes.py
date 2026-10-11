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

from pdf_worker.layout import PAGE_NUMBER_RE, SUPERSCRIPT, DocumentProfile, Line, page_lines

# Lines this much smaller than the body font count as footnote-sized.
SMALL_RATIO = 0.92
# Footnote regions must start in the lower part of the page.
_REGION_MIN_TOP = 0.4
CONTINUED = "(continued) "

_MARKER = r"\d{1,3}|[*†‡§¶]{1,3}"
_MARKER_RE = re.compile(rf"^(?:{_MARKER})$")
_MARKER_LIST_RE = re.compile(rf"^(?:{_MARKER})(?:\s*,\s*(?:{_MARKER}))*$")
_DEF_START_RE = re.compile(rf"^\s*({_MARKER})(?:[.)]\s*|\s+)(?=\S)")
_BRACKET_REF_RE = re.compile(r"[ \t ]*\[(\d{1,4})\]")
_BRACKET_DEF_RE = re.compile(r"^\s*\[(\d{1,4})\][\s ]*")
SEPARATOR_RE = re.compile(r"^\s*[_\-—–]{3,}\s*$")


@dataclass(frozen=True)
class BodyLine:
    """A body text line with footnote references already rewritten to ``[^label]``."""

    text: str
    line: Line
    # Set when this line starts an endnote definition; ``text`` is then the note text.
    endnote_label: str | None = None


@dataclass(frozen=True)
class PageLayout:
    lines: tuple[BodyLine, ...]
    # Page footnotes found at the bottom of the page: (label, text lines).
    notes: tuple[tuple[str, tuple[str, ...]], ...]
    definitions: tuple[str, ...]  # labels defined on this page (continuations excluded)
    references: tuple[str, ...]  # labels referenced on this page, in order
    trailing_label: str | None  # last page footnote on the page (may continue)


@dataclass(frozen=True)
class RenderedPage:
    text: str
    definitions: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    trailing_label: str | None = None


def display_marker(label: str) -> str:
    """The marker a reader sees: ``p12-1`` -> ``1``; endnote ``31`` -> ``31``."""
    if label.startswith("p") and "-" in label:
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
    region_start = _find_region(lines, profile.body_size, page.rect.height)
    notes: list[tuple[str, list[str]]] = []
    marker_labels: dict[str, str] = {}
    consumed: set[int] = set()
    if region_start is not None:
        notes, marker_labels, consumed = _collect_footnotes(
            lines, region_start, page_index + 1, previous_label
        )

    references: list[str] = []
    # A note continued from the previous page reuses that page's label; count it once.
    definitions = [label for label, _ in notes if label != previous_label]
    body: list[BodyLine] = []
    for line_index, line in enumerate(lines):
        if line_index in consumed:
            continue
        text = _render_line(line, marker_labels, references)
        endnote, text = _split_endnote(text, page_index, line_index, profile)
        if endnote:
            definitions.append(endnote)
        text = _render_brackets(text, profile, references)
        body.append(BodyLine(text=text, line=line, endnote_label=endnote))
    return PageLayout(
        lines=tuple(body),
        notes=tuple((label, tuple(texts)) for label, texts in notes),
        definitions=tuple(definitions),
        references=tuple(references),
        trailing_label=notes[-1][0] if notes else None,
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


def _definition_marker(line: Line) -> tuple[str, str] | None:
    """If ``line`` starts a footnote, return (marker, text after the marker)."""
    spans = [span for span in line.spans if span["text"].strip()]
    if not spans:
        return None
    first = spans[0]
    if first["flags"] & SUPERSCRIPT and _MARKER_RE.match(first["text"].strip()):
        rest = line.text.split(first["text"], 1)[1]
        return first["text"].strip(), rest.lstrip()
    match = _DEF_START_RE.match(line.text)
    if match:
        return match.group(1), line.text[match.end() :]
    return None


def _superscript_markers(lines: list[Line]) -> list[str]:
    markers = []
    for line in lines:
        for span in line.spans:
            text = span["text"].strip()
            if span["flags"] & SUPERSCRIPT and _MARKER_LIST_RE.match(text):
                markers.extend(m.strip() for m in text.split(","))
    return markers


def _find_region(lines: list[Line], body_size: float, page_height: float) -> int | None:
    """Index of the first line of the bottom-of-page footnote region, if any."""
    end = len(lines)
    while end and (not lines[end - 1].text.strip() or PAGE_NUMBER_RE.match(lines[end - 1].text)):
        end -= 1
    start = end
    while start and (is_small(lines[start - 1], body_size) or not lines[start - 1].text.strip()):
        start -= 1
    while start < end and not lines[start].text.strip():
        start += 1
    if start == end:
        return None
    region_top = min(line.top for line in lines[start:end] if line.text.strip())
    if region_top < page_height * _REGION_MIN_TOP:
        return None
    for line in lines[:start]:
        if line.text.strip() and line.top >= region_top:
            return None  # body text beside or below it: margin notes, not footnotes
    return start


def _collect_footnotes(
    lines: list[Line], region_start: int, page_number: int, previous_label: str | None
) -> tuple[list[tuple[str, list[str]]], dict[str, str], set[int]]:
    """Split the footnote region into (label, text lines) notes.

    Returns the notes, a marker -> label map for rewriting references, and the indices
    of the lines that were moved into notes (all other lines stay in the body).
    """
    body_refs = _superscript_markers(lines[:region_start])
    footnotes: list[tuple[str, list[str]]] = []
    marker_labels: dict[str, str] = {}
    consumed: set[int] = set()
    leading: list[int] = []  # region lines before the first note marker
    last_number = 0
    for index in range(region_start, len(lines)):
        line = lines[index]
        text = line.text
        if not text.strip() or PAGE_NUMBER_RE.match(text):
            continue
        if SEPARATOR_RE.match(text):
            consumed.add(index)
            continue
        found = _definition_marker(line)
        if found and _accept_marker(found[0], body_refs, marker_labels, last_number):
            marker, rest = found
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


def _accept_marker(
    marker: str, body_refs: list[str], seen: dict[str, str], last_number: int
) -> bool:
    if marker in seen:
        return False
    if body_refs:
        return marker in body_refs
    # No superscript references to confirm against: require an increasing sequence.
    return not marker.isdigit() or int(marker) > last_number


def _render_line(line: Line, marker_labels: dict[str, str], references: list[str]) -> str:
    if not marker_labels:
        return line.text
    parts: list[str] = []
    for span in line.spans:
        text = span["text"]
        stripped = text.strip()
        if span["flags"] & SUPERSCRIPT and _MARKER_LIST_RE.match(stripped):
            markers = [m.strip() for m in stripped.split(",")]
            if all(m in marker_labels for m in markers):
                while parts and not parts[-1].strip():
                    parts.pop()
                if parts:
                    parts[-1] = parts[-1].rstrip()
                for marker in markers:
                    parts.append(f"[^{marker_labels[marker]}]")
                    references.append(marker_labels[marker])
                continue
        parts.append(text)
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

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

Detection needs one cheap analysis pass over the document (font sizes and bracket
numbers only) before pages are rendered; both passes hold a single page at a time.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

# Text-only extraction flags: never decode images (scanned books would bloat memory).
_TEXT_FLAGS = pymupdf.TEXTFLAGS_TEXT
_SUPERSCRIPT = 1  # MuPDF span flag bit

# Lines this much smaller than the body font count as footnote-sized.
_SMALL_RATIO = 0.92
# Footnote regions must start in the lower part of the page.
_REGION_MIN_TOP = 0.4
# A bracketed number seen more often than this is not an endnote.
_MAX_ENDNOTE_OCCURRENCES = 3

_MARKER = r"\d{1,3}|[*†‡§¶]{1,3}"
_MARKER_RE = re.compile(rf"^(?:{_MARKER})$")
_MARKER_LIST_RE = re.compile(rf"^(?:{_MARKER})(?:\s*,\s*(?:{_MARKER}))*$")
_DEF_START_RE = re.compile(rf"^\s*({_MARKER})(?:[.)]\s*|\s+)(?=\S)")
_BRACKET_RE = re.compile(r"\[(\d{1,4})\]")
_BRACKET_REF_RE = re.compile(r"[ \t ]*\[(\d{1,4})\]")
_BRACKET_DEF_RE = re.compile(r"^\s*\[(\d{1,4})\][\s ]*")
_PAGE_NUMBER_RE = re.compile(r"^\s*(?:page\s*)?\d{1,4}(?:\s*/\s*\d{1,4})?\s*$", re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"^\s*[_\-—–]{3,}\s*$")


@dataclass(frozen=True)
class _Line:
    spans: tuple[dict, ...]
    size: float
    top: float

    @property
    def text(self) -> str:
        return "".join(span["text"] for span in self.spans)


@dataclass
class DocumentProfile:
    """What the analysis pass learned about the whole document."""

    body_size: float = 0.0
    # Endnote number -> (page index, line index) of the line that defines it.
    endnote_defs: dict[int, tuple[int, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderedPage:
    text: str
    definitions: tuple[str, ...] = ()  # labels defined on this page
    references: tuple[str, ...] = ()  # labels referenced on this page (in order)
    # Label of a page footnote still open at the bottom of this page (may continue).
    trailing_label: str | None = None


def _page_lines(page: pymupdf.Page) -> list[_Line]:
    lines = []
    for block in page.get_text("dict", flags=_TEXT_FLAGS)["blocks"]:
        for line in block.get("lines", ()):
            spans = tuple(line["spans"])
            sizes = Counter()
            for span in spans:
                sizes[round(span["size"], 1)] += len(span["text"].strip())
            size = sizes.most_common(1)[0][0] if sizes else 0.0
            lines.append(_Line(spans=spans, size=size, top=line["bbox"][1]))
    return lines


def analyze_document(doc: pymupdf.Document) -> DocumentProfile:
    """Find the body font size and which lines define bracketed endnotes."""
    sizes: Counter[float] = Counter()
    occurrences: Counter[int] = Counter()
    line_starts: dict[int, tuple[int, int]] = {}
    referenced_mid_line: set[int] = set()
    for page_index in range(doc.page_count):
        for line_index, line in enumerate(_page_lines(doc.load_page(page_index))):
            for span in line.spans:
                sizes[round(span["size"], 1)] += len(span["text"].strip())
            text = line.text
            for match in _BRACKET_RE.finditer(text):
                number = int(match.group(1))
                at_line_start = match.start() == len(text) - len(text.lstrip())
                if not occurrences[number] and not at_line_start:
                    referenced_mid_line.add(number)
                elif occurrences[number] and at_line_start:
                    # A later occurrence at the start of a line: the note itself.
                    line_starts[number] = (page_index, line_index)
                occurrences[number] += 1
    sizes.pop(0.0, None)
    body_size = sizes.most_common(1)[0][0] if sizes else 0.0
    # An endnote number appears about twice (reference + note); numbers that recur
    # more often are list items or exercise numbers, not notes.
    candidates = {
        number: position
        for number, position in line_starts.items()
        if occurrences[number] <= _MAX_ENDNOTE_OCCURRENCES
    }
    # Real references sit mostly mid-sentence; numbered lists put every one at a line
    # start. Only trust the pattern when most candidates were referenced mid-line.
    if len(candidates.keys() & referenced_mid_line) * 2 <= len(candidates):
        candidates = {}
    return DocumentProfile(body_size=body_size, endnote_defs=candidates)


def _is_small(line: _Line, body_size: float) -> bool:
    return 0 < line.size < body_size * _SMALL_RATIO


def _definition_marker(line: _Line) -> tuple[str, str] | None:
    """If ``line`` starts a footnote, return (marker, text after the marker)."""
    spans = [span for span in line.spans if span["text"].strip()]
    if not spans:
        return None
    first = spans[0]
    if first["flags"] & _SUPERSCRIPT and _MARKER_RE.match(first["text"].strip()):
        rest = line.text.split(first["text"], 1)[1]
        return first["text"].strip(), rest.lstrip()
    match = _DEF_START_RE.match(line.text)
    if match:
        return match.group(1), line.text[match.end() :]
    return None


def _superscript_markers(lines: list[_Line]) -> list[str]:
    markers = []
    for line in lines:
        for span in line.spans:
            text = span["text"].strip()
            if span["flags"] & _SUPERSCRIPT and _MARKER_LIST_RE.match(text):
                markers.extend(m.strip() for m in text.split(","))
    return markers


def _find_region(lines: list[_Line], body_size: float, page_height: float) -> int | None:
    """Index of the first line of the bottom-of-page footnote region, if any."""
    end = len(lines)
    while end and (not lines[end - 1].text.strip() or _PAGE_NUMBER_RE.match(lines[end - 1].text)):
        end -= 1
    start = end
    while start and (_is_small(lines[start - 1], body_size) or not lines[start - 1].text.strip()):
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


def render_page(
    page: pymupdf.Page,
    page_index: int,
    profile: DocumentProfile,
    previous_label: str | None = None,
) -> RenderedPage:
    """Render one page's text with footnote references and definitions marked."""
    lines = _page_lines(page)
    region_start = _find_region(lines, profile.body_size, page.rect.height)
    footnotes: list[tuple[str, list[str]]] = []
    marker_labels: dict[str, str] = {}
    consumed: set[int] = set()
    if region_start is not None:
        footnotes, marker_labels, consumed = _collect_footnotes(
            lines, region_start, page_index + 1, previous_label
        )

    references: list[str] = []
    # A note continued from the previous page reuses that page's label; count it once.
    definitions = [label for label, _ in footnotes if label != previous_label]
    out: list[str] = []
    for line_index, line in enumerate(lines):
        if line_index in consumed:
            continue
        text = _render_line(line, marker_labels, references)
        text = _render_brackets(text, page_index, line_index, profile, references, definitions)
        out.append(text + "\n")

    if footnotes:
        out.append("\n")
        for label, note_lines in footnotes:
            out.append(f"[^{label}]: " + "\n".join(note_lines) + "\n")
    return RenderedPage(
        text="".join(out),
        definitions=tuple(definitions),
        references=tuple(references),
        trailing_label=footnotes[-1][0] if footnotes else None,
    )


def _collect_footnotes(
    lines: list[_Line], region_start: int, page_number: int, previous_label: str | None
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
        if not text.strip() or _PAGE_NUMBER_RE.match(text):
            continue
        if _SEPARATOR_RE.match(text):
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
        footnotes.insert(0, (previous_label, ["(continued) " + texts[0], *texts[1:]]))
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


def _render_line(line: _Line, marker_labels: dict[str, str], references: list[str]) -> str:
    if not marker_labels:
        return line.text
    parts: list[str] = []
    for span in line.spans:
        text = span["text"]
        stripped = text.strip()
        if span["flags"] & _SUPERSCRIPT and _MARKER_LIST_RE.match(stripped):
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


def _render_brackets(
    text: str,
    page_index: int,
    line_index: int,
    profile: DocumentProfile,
    references: list[str],
    definitions: list[str],
) -> str:
    if not profile.endnote_defs or "[" not in text:
        return text
    prefix = ""
    match = _BRACKET_DEF_RE.match(text)
    if match and profile.endnote_defs.get(int(match.group(1))) == (page_index, line_index):
        label = str(int(match.group(1)))
        definitions.append(label)
        prefix = f"[^{label}]: "
        text = text[match.end() :]

    def _ref(found: re.Match) -> str:
        number = int(found.group(1))
        if number not in profile.endnote_defs:
            return found.group(0)
        references.append(str(number))
        return f"[^{number}]"

    return prefix + _BRACKET_REF_RE.sub(_ref, text)

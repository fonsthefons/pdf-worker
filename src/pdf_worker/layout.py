"""Page lines with geometry, and a one-pass analysis of the whole document's layout.

The analysis pass keeps only small aggregates (counters, a few labels and a text
sample), never the document text, so it is safe on huge PDFs.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from pdf_worker.consensus import apply_fixes, page_fixes
from pdf_worker.endnotes import ChapterNotes, match_chapter_notes
from pdf_worker.margin_refs import apply_marks, page_marks

# Text-only extraction flags: never decode images (scanned books would bloat memory).
_TEXT_FLAGS = pymupdf.TEXTFLAGS_TEXT
SUPERSCRIPT = 1  # MuPDF span flag bits
BOLD = 16
# A gap between two letters wider than this share of the font size is a word space
# (a normal space is ~0.25 em; letters sit much closer, kerned or not).
_WORD_GAP = 0.15
_SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_FROM_SUPERSCRIPT = str.maketrans(_SUPERSCRIPT_DIGITS, "0123456789")

# Lines whose font is this much bigger than the body font are headings.
HEADING_RATIO = 1.15
# Sizes within this share of a heading size belong to it (OCR jitter).
_HEADING_BAND = 0.05
_MAX_HEADING_LEVELS = 4
_BODY_FONT_SHARE = 0.85
# Running headers/footers live in this fraction of the page at the top and bottom.
_MARGIN_ZONE = 0.1
# A margin line repeated on at least this share of pages (and 3 pages) is running text.
_RUNNING_SHARE = 0.2
_MIN_SMALL_RUNNING = 4
# The printed page numbers must agree on this share of all pages.
_MIN_PRINTED_SHARE = 0.25
_REPEATED_IMAGE_SHARE = 0.3
_PRINTED_NUMBER_RE = re.compile(r"^\s*(\d{1,4})\s*$")
# A mid-page line on at least this share of pages (and 5 pages) is a watermark.
_WATERMARK_SHARE = 0.5
_MIN_WATERMARK_CHARS = 12
# A bracketed number seen more often than this is not an endnote.
_MAX_ENDNOTE_OCCURRENCES = 3
# Characters of body text kept for language detection.
_SAMPLE_CHARS = 20_000

_BRACKET_RE = re.compile(r"\[(\d{1,4})\]")
# A line starting a numbered note: "12. Text" (or "12.Text"; not a decimal like "3.14").
NUMBERED_NOTE_RE = re.compile(r"^\s*(\d{1,4})\.\s*(?=[^\d\s])")
_DIGITS_RE = re.compile(r"\d+")
# Upper-case Roman numerals of two or more letters (a lone "I" or "V" may be a word).
_ROMAN_RE = re.compile(r"\b[IVXLC]{2,}\b|\b[VXLC]\b")
PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:page\s*|p\.\s*|-\s*)?\d{1,4}(?:\s*/\s*\d{1,4}|\s*-)?\s*$", re.IGNORECASE
)


@dataclass(frozen=True)
class Line:
    spans: tuple[dict, ...]
    size: float  # dominant font size (by characters)
    bbox: tuple[float, float, float, float]

    @property
    def text(self) -> str:
        return "".join(span["text"] for span in self.spans)

    @property
    def top(self) -> float:
        return self.bbox[1]

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    @property
    def bold(self) -> bool:
        spans = [span for span in self.spans if span["text"].strip()]
        return bool(spans) and all(span["flags"] & BOLD for span in spans)


def page_lines(page: pymupdf.Page) -> list[Line]:
    """All text lines of a page in MuPDF reading order, with OCR fixes from
    ``pdf_worker.consensus`` and stored margin references (``pdf_worker.margin_refs``)
    applied."""
    fixes = page_fixes(page)
    marks = page_marks(page)
    lines = []
    for block in page.get_text("rawdict", flags=_TEXT_FLAGS)["blocks"]:
        for line in block.get("lines", ()):
            if fixes:
                apply_fixes([char for span in line["spans"] for char in span["chars"]], fixes)
            if marks:  # after the fixes, which look for letters only
                apply_marks([char for span in line["spans"] for char in span["chars"]], marks)
            spans = _with_text(line["spans"])
            sizes: Counter[float] = Counter()
            for span in spans:
                sizes[round(span["size"], 1)] += len(span["text"].strip())
            size = sizes.most_common(1)[0][0] if sizes else 0.0
            lines.append(Line(spans=spans, size=size, bbox=ink_bbox(spans, line["bbox"])))
    return lines


def ink_bbox(spans: tuple[dict, ...], fallback) -> tuple[float, float, float, float]:
    """The box around a line's visible text. Spaces don't count: OCR layers (ABBYY) give
    word-gap spaces odd sizes and heights, which would shift the line's top."""
    boxes = [span["bbox"] for span in spans if span["text"].strip()]
    if not boxes:
        return tuple(fallback)
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _with_text(spans: list[dict]) -> tuple[dict, ...]:
    """A line's ``rawdict`` spans as ``dict`` spans: chars joined into ``text``, with a
    space wherever the PDF leaves a word gap but no space character. MuPDF misses some
    of these, e.g. after accented Greek vowels in XeTeX books ("καὶἦλθεν").

    Unicode superscript digits ("criados²", as OCR layers write note references)
    become spans of their own with plain digits and the superscript flag."""
    prev = None
    out_spans = []
    for span in spans:
        pieces: list[tuple[bool, list[str], list]] = []  # (superscript, chars, boxes)
        for char in span.pop("chars"):
            sup = char["c"] in _SUPERSCRIPT_DIGITS
            if (
                prev is not None
                and not prev["c"].isspace()
                and not char["c"].isspace()
                and char["bbox"][0] - prev["bbox"][2] > _WORD_GAP * span["size"]
            ):
                if not pieces:
                    pieces.append((False, [], []))
                pieces[-1][1].append(" ")
            if not pieces or pieces[-1][0] != sup:
                pieces.append((sup, [], []))
            pieces[-1][1].append(char["c"].translate(_FROM_SUPERSCRIPT))
            pieces[-1][2].append(char["bbox"])
            prev = char
        if len(pieces) <= 1 and not (pieces and pieces[0][0]):
            span["text"] = "".join(pieces[0][1]) if pieces else ""
            out_spans.append(span)
            continue
        for sup, chars, boxes in pieces:
            bbox = span["bbox"]  # a piece that is only a word-gap space has no boxes
            if boxes:
                x0s, y0s, x1s, y1s = zip(*boxes, strict=True)
                bbox = (min(x0s), min(y0s), max(x1s), max(y1s))
            flags = span["flags"] | SUPERSCRIPT if sup else span["flags"]
            out_spans.append(dict(span, text="".join(chars), bbox=bbox, flags=flags))
    return tuple(out_spans)


def is_superscript_number(span: dict, line: Line) -> bool:
    """A note reference: digits set as superscript, or in small raised type."""
    text = span["text"].strip()
    if not text.isdigit() or len(text) > 4:
        return False
    if span["flags"] & SUPERSCRIPT:
        return True
    raised = span["bbox"][3] < line.bbox[3] - 0.15 * line.size
    return span["size"] < line.size * 0.8 and raised


def running_key(text: str) -> str:
    """Normalise a header/footer line so ``3/49`` and ``4/49`` (or ``CAP. III`` and
    ``CAP. IV``) compare equal."""
    text = _ROMAN_RE.sub("#", text.strip())
    return _DIGITS_RE.sub("#", text.lower())


@dataclass
class DocumentProfile:
    """What the analysis pass learned about the whole document."""

    body_size: float = 0.0
    # Typical distance between the tops of consecutive body lines.
    line_spacing: float = 0.0
    # Heading font sizes, largest first; index + 1 is the heading level.
    heading_sizes: list[float] = field(default_factory=list)
    # Normalised texts of running headers/footers (see ``running_key``).
    running_texts: set[str] = field(default_factory=set)
    # Lines repeated mid-page on most pages ("Page Proof Pending Publication").
    watermarks: set[str] = field(default_factory=set)
    # Endnote number -> (page index, line index) of the line that defines it.
    endnote_defs: dict[int, tuple[int, int]] = field(default_factory=dict)
    # Superscript-referenced endnotes collected per chapter (see ``pdf_worker.endnotes``).
    chapter_notes: ChapterNotes = field(default_factory=ChapterNotes)
    # Printed page number of each page ("23", front matter "xii"), for EPUB page lists.
    page_labels: list[str] = field(default_factory=list)
    # Images placed on many pages (logos, rules): not figures.
    repeated_images: set[int] = field(default_factory=set)
    # Fonts that set most of the text. A line set wholly in other fonts is emphasised
    # (bold or a display face), even when the PDF has no bold flag (Type3 fonts).
    body_fonts: set[str] = field(default_factory=set)

    def emphasized(self, line: Line) -> bool:
        if line.bold:
            return True
        names = {span.get("font", "") for span in line.spans if span["text"].strip()}
        return bool(names) and bool(self.body_fonts) and not names & self.body_fonts

    text_sample: str = ""
    page_count: int = 0

    def heading_level(self, size: float) -> int | None:
        """Level of the nearest heading size, if ``size`` is within its jitter band."""
        best = None
        for level, heading_size in enumerate(self.heading_sizes, start=1):
            distance = abs(size - heading_size)
            if distance <= max(0.3, heading_size * 2 * _HEADING_BAND) and (
                best is None or distance < best[0]
            ):
                best = (distance, level)
        return best[1] if best else None

    def is_running(self, line: Line, page_height: float) -> bool:
        """True for running headers/footers and bare page numbers in the margins, and
        for watermarks repeated on most pages wherever they sit."""
        text = line.text
        if page_height * _MARGIN_ZONE < line.top < page_height * (1 - _MARGIN_ZONE):
            return running_key(text) in self.watermarks
        return bool(PAGE_NUMBER_RE.match(text)) or running_key(text) in self.running_texts


def analyze_document(doc: pymupdf.Document) -> DocumentProfile:
    """One pass over every page collecting font, spacing, margin and endnote statistics."""
    sizes: Counter[float] = Counter()
    gaps: Counter[float] = Counter()
    margin_texts: Counter[str] = Counter()
    margin_sizes: dict[str, float] = {}
    offsets: Counter[int] = Counter()  # printed page number minus page index
    image_pages: Counter[int] = Counter()  # image xref -> pages it is placed on
    fonts: Counter[str] = Counter()  # font name -> characters set in it
    inner_texts: Counter[str] = Counter()
    occurrences: Counter[int] = Counter()
    line_starts: dict[int, tuple[int, int]] = {}
    referenced_mid_line: set[int] = set()
    sup_refs: list[tuple[int, tuple[int, int, int]]] = []
    note_lines: list[tuple[int, tuple[int, int]]] = []
    sample: list[str] = []
    sample_len = 0
    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        height = page.rect.height
        lines = page_lines(page)
        page_margin_texts = set()
        page_inner_texts = set()
        page_offsets: set[int] = set()
        image_pages.update({info[0] for info in page.get_images(full=False)})
        for line_index, line in enumerate(lines):
            text = line.text
            for span in line.spans:
                sizes[round(span["size"], 1)] += len(span["text"].strip())
                fonts[span.get("font", "")] += len(span["text"].strip())
            if text.strip() and not height * _MARGIN_ZONE < line.top < height * (1 - _MARGIN_ZONE):
                key = running_key(text)
                page_margin_texts.add(key)
                margin_sizes[key] = max(margin_sizes.get(key, 0.0), line.size)
                printed = _PRINTED_NUMBER_RE.match(text)
                if printed:
                    page_offsets.add(int(printed.group(1)) - page_index)
            elif len(text.strip()) >= _MIN_WATERMARK_CHARS:
                page_inner_texts.add(running_key(text))
            if line_index and lines[line_index - 1].size == line.size:
                gap = round(line.top - lines[line_index - 1].top, 1)
                if 0 < gap < 3 * line.size:
                    gaps[(line.size, gap)] += 1
            if sample_len < _SAMPLE_CHARS and text.strip():
                sample.append(text)
                sample_len += len(text)
            for span_index, span in enumerate(line.spans):
                if is_superscript_number(span, line):
                    number = int(span["text"].strip())
                    sup_refs.append((number, (page_index, line_index, span_index)))
            numbered = NUMBERED_NOTE_RE.match(text)
            if numbered:
                note_lines.append((int(numbered.group(1)), (page_index, line_index)))
            for match in _BRACKET_RE.finditer(text):
                number = int(match.group(1))
                at_line_start = match.start() == len(text) - len(text.lstrip())
                if not occurrences[number] and not at_line_start:
                    referenced_mid_line.add(number)
                elif occurrences[number] and at_line_start:
                    # A later occurrence at the start of a line: the note itself.
                    line_starts[number] = (page_index, line_index)
                occurrences[number] += 1
        margin_texts.update(page_margin_texts)
        inner_texts.update(page_inner_texts)
        offsets.update(page_offsets)

    sizes.pop(0.0, None)
    body_size = sizes.most_common(1)[0][0] if sizes else 0.0
    body_gaps = Counter({gap: n for (size, gap), n in gaps.items() if size == body_size})
    line_spacing = body_gaps.most_common(1)[0][0] if body_gaps else body_size * 1.2
    heading_sizes = _cluster_sizes(
        {s: n for s, n in sizes.items() if s >= body_size * HEADING_RATIO and n >= 3}
    )
    threshold = max(3, doc.page_count * _RUNNING_SHARE)
    # Per-chapter running heads ("NOTES TO CHAPTER 1") repeat on fewer pages; small
    # type in the margin repeated on a few pages is running text too. Large type is
    # left alone: it may be a chapter title at the top of every chapter.
    running = {
        text
        for text, n in margin_texts.items()
        if n >= threshold
        or (
            n >= _MIN_SMALL_RUNNING
            and margin_sizes.get(text, 0.0) <= body_size * 1.05
            and sum(c.isalpha() for c in text) >= 6
        )
    }
    watermark_threshold = max(5, doc.page_count * _WATERMARK_SHARE)
    watermarks = {text for text, n in inner_texts.items() if n >= watermark_threshold}
    return DocumentProfile(
        watermarks=watermarks,
        body_size=body_size,
        line_spacing=line_spacing,
        heading_sizes=heading_sizes,
        running_texts=running,
        endnote_defs=_endnote_candidates(occurrences, line_starts, referenced_mid_line),
        chapter_notes=match_chapter_notes(sup_refs, note_lines),
        page_labels=_page_labels(doc, offsets),
        body_fonts=_body_fonts(fonts),
        repeated_images={
            xref
            for xref, n in image_pages.items()
            if n >= max(3, doc.page_count * _REPEATED_IMAGE_SHARE)
        },
        text_sample=" ".join(sample),
        page_count=doc.page_count,
    )


def _body_fonts(fonts: Counter[str]) -> set[str]:
    """The most used fonts, together setting ``_BODY_FONT_SHARE`` of all characters."""
    total = sum(fonts.values())
    body: set[str] = set()
    covered = 0
    for name, count in fonts.most_common():
        if covered >= total * _BODY_FONT_SHARE:
            break
        body.add(name)
        covered += count
    return body


def _cluster_sizes(sizes: dict[float, int]) -> list[float]:
    """Heading sizes, largest first, with sizes a few percent apart merged into one.

    OCR'd text layers size each line from its height, so one printed heading size shows
    up as many slightly different sizes; each cluster is one heading level, at the
    size used most within it. At most ``_MAX_HEADING_LEVELS`` levels are kept.
    """
    clusters: list[dict[float, int]] = []
    for size in sorted(sizes, reverse=True):
        if clusters and size >= max(clusters[-1]) * (1 - 2 * _HEADING_BAND):
            clusters[-1][size] = sizes[size]
        else:
            clusters.append({size: sizes[size]})
    levels = [max(cluster, key=cluster.get) for cluster in clusters]
    return levels[:_MAX_HEADING_LEVELS]


def _page_labels(doc: pymupdf.Document, offsets: Counter[int]) -> list[str]:
    """Printed page numbers: the PDF's own page labels, else the numbers printed in the
    margins (one consistent offset from the page index), else the page index + 1.

    Pages before printed page 1 (front matter) get lower-case Roman numerals.
    """
    if doc.get_page_labels():
        return [doc.load_page(i).get_label() or str(i + 1) for i in range(doc.page_count)]
    offset = 0
    if offsets:
        best, count = offsets.most_common(1)[0]
        if count >= max(3, doc.page_count * _MIN_PRINTED_SHARE):
            offset = best
    return [
        str(i + offset) if i + offset >= 1 else _roman(i + 1).lower() for i in range(doc.page_count)
    ]


def _roman(number: int) -> str:
    out = []
    for value, letters in (
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
        (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ):  # fmt: skip
        while number >= value:
            out.append(letters)
            number -= value
    return "".join(out)


def _endnote_candidates(
    occurrences: Counter[int],
    line_starts: dict[int, tuple[int, int]],
    referenced_mid_line: set[int],
) -> dict[int, tuple[int, int]]:
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
        return {}
    return candidates

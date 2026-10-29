"""Page lines with geometry, and a one-pass analysis of the whole document's layout.

The analysis pass keeps only small aggregates (counters, a few labels and a text
sample), never the document text, so it is safe on huge PDFs.
"""

import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

import pymupdf

from pdf_worker.bilingual import apply_words, page_words
from pdf_worker.consensus import apply_fixes, page_fixes
from pdf_worker.document import TEXT_FLAGS
from pdf_worker.endnotes import ChapterNotes, lossy_min_run, match_chapter_notes
from pdf_worker.font_sizes import same_leading_sizes, sizes_by_leading
from pdf_worker.glued_refs import apply_refs, page_refs
from pdf_worker.margin_refs import OCR_DIGITS, apply_marks, has_bracketed, in_book, page_marks
from pdf_worker.note_numbers import FROM_SUP, SUP_DIGITS

SUPERSCRIPT = 1  # MuPDF span flag bits
BOLD = 16
# A gap between two letters wider than this share of the font size is a word space
# (a normal space is ~0.25 em; letters sit much closer, kerned or not).
_WORD_GAP = 0.15

# Lines whose font is this much bigger than the body font are headings.
HEADING_RATIO = 1.15
# Sizes within this share of a heading size belong to it (OCR jitter).
_HEADING_BAND = 0.05
_MAX_HEADING_LEVELS = 4
_BODY_FONT_SHARE = 0.85
# A line in a page's top or bottom row repeated in that row this many pages away (or
# fewer) is a running head or foot, if no bigger than this share of the body size.
_RUNNING_PAGES = 2
_RUNNING_SIZE = 1.05
# The old rule, kept beside it (user, 2026-10-28): in this fraction of the page at the
# top and bottom, a bare page number, or a line of any size whose key is there on at
# least this share of pages (and 3 pages), is furniture. It catches heads bigger than
# the body and, on skewed scans, heads and numbers outside the top and bottom rows.
_MARGIN_ZONE = 0.1
_RUNNING_SHARE = 0.2
# Lines this much smaller than the body font are small type (notes, heads); bigger
# lines are body text.
SMALL_RATIO = 0.92
# The printed page numbers must agree on this share of all pages.
_MIN_PRINTED_SHARE = 0.25
_REPEATED_IMAGE_SHARE = 0.3
# Digits OCR may space out: "1 5 6", "22 0".
_PRINTED_NUMBER_RE = re.compile(r"^\s*(\d(?: ?\d){0,3})\s*$")
# A mid-page line on at least this share of pages (and 5 pages) is a watermark.
_WATERMARK_SHARE = 0.5
_MIN_WATERMARK_CHARS = 12
_MIN_SPACING_LINES = 20  # gaps between lines of a size, to know its own spacing
# A bracketed number seen more often than this is not an endnote.
_MAX_ENDNOTE_OCCURRENCES = 3
# Characters of body text kept for language detection.
_SAMPLE_CHARS = 20_000

_BRACKET_RE = re.compile(r"\[(\d{1,4})\]")
# A line starting a numbered note: "12. Text" (or "12.Text"; not a decimal like "3.14").
NUMBERED_NOTE_RE = re.compile(r"^\s*(\d{1,4})\.\s*(?=[^\d\s])")
# ... or with no period: "235 Trato de ..." (footnotes look the same, see below).
_PLAIN_NOTE_RE = re.compile(r"^\s*(\d{1,4})\s+(?=[^\d\s])")
_SAME_BASELINE = 0.3  # in sizes: a hung note number sits this close to its line's
_MAX_MARK_SIGNS = 4  # a hung note number, misread ("2 +"): this many signs at most
# A misread note number starting its line: up to 4 signs, a digit among them and no
# letters ("3.¡." for 34), then the note's first word.
NOTE_MARK_RE = re.compile(r"^\s*(?=\S*\d)[^\sA-Za-zÀ-ÿ]{1,4}\s+(?=[^\W\d_])")
# ... or misread worse, letters and all (".i,57", "H7", "4-54-"), where the line starts
# at the notes' numbers (``_at_numbers``).
LOOSE_NOTE_MARK_RE = re.compile(r"^\s*(?=\S*\d)\S{1,6}\s+(?=[«“\"(]?[^\W\d_])")
_MAX_LOOSE_SIGNS = 6
_MIN_COLUMN_LINES = 5
_DIGITS_RE = re.compile(r"\d+")
PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:page\s*|p\.\s*|-\s*)?\d(?: ?\d){0,3}(?:\s*/\s*\d(?: ?\d){0,3}|\s*-)?\s*$",
    re.IGNORECASE,
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
    def baseline(self) -> float:
        """Where most of the line's letters sit (``top`` if unknown). Unlike the top, it
        doesn't move with the fonts a line happens to use, so line gaps are measured on
        it: fonts drawn from a scan's letter shapes (ClearScan-style) can claim an
        ascender of 2.4 em, which lifted lines' tops by 11 pt and broke paragraphs."""
        sitting: Counter[float] = Counter()
        for span in self.spans:
            if span["text"].strip() and "origin" in span and not span["flags"] & SUPERSCRIPT:
                sitting[round(span["origin"][1], 1)] += len(span["text"].strip())
        return sitting.most_common(1)[0][0] if sitting else self.top

    @property
    def superscript_rise(self) -> float:
        """How far the line's highest superscript sits above its baseline (0 if none). A
        browser printing a web page lowers a line with a note number ("PLATÓN[2]") by
        about this much, which looked like a paragraph's extra space."""
        rises = [
            self.baseline - span["origin"][1]
            for span in self.spans
            if span["text"].strip() and "origin" in span and span["flags"] & SUPERSCRIPT
        ]
        return max([0.0, *rises])

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
    ``pdf_worker.consensus``, re-read words (``pdf_worker.bilingual``), stored margin
    references (``pdf_worker.margin_refs``) and note references
    (``pdf_worker.glued_refs``) applied, and sizes evened out by leading
    where the fonts misreport them (``pdf_worker.font_sizes``)."""
    fixes = page_fixes(page)
    marks = page_marks(page)
    words = page_words(page)
    glued = page_refs(page)
    lines = []
    for block in page.get_text("rawdict", flags=TEXT_FLAGS)["blocks"]:
        for line in block.get("lines", ()):
            if words:
                apply_words([char for span in line["spans"] for char in span["chars"]], words)
            if fixes:
                apply_fixes([char for span in line["spans"] for char in span["chars"]], fixes)
            if marks:  # after the fixes, which look for letters only
                apply_marks([char for span in line["spans"] for char in span["chars"]], marks)
            if glued:
                apply_refs([char for span in line["spans"] for char in span["chars"]], glued)
            spans = _with_text(line["spans"])
            sizes: Counter[float] = Counter()
            for span in spans:
                sizes[round(span["size"], 1)] += len(span["text"].strip())
            size = sizes.most_common(1)[0][0] if sizes else 0.0
            lines.append(Line(spans=spans, size=size, bbox=ink_bbox(spans, line["bbox"])))
    table = sizes_by_leading(page.parent)
    return same_leading_sizes(lines, table) if table else lines


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
            sup = char["c"] != "" and char["c"] in SUP_DIGITS  # "": a dropped char
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
            pieces[-1][1].append(char["c"].translate(FROM_SUP))
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
            text = "".join(chars)
            last = out_spans[-1] if out_spans else None
            if sup and last and last["flags"] & SUPERSCRIPT and last["text"].isdigit():
                # One number set in two fonts ("⁷" "⁴" in the Timeo's redraw)
                box = last["bbox"]
                bbox = (
                    min(box[0], bbox[0]),
                    min(box[1], bbox[1]),
                    max(box[2], bbox[2]),
                    max(box[3], bbox[3]),
                )
                out_spans[-1] = dict(last, text=last["text"] + text, bbox=bbox)
                continue
            out_spans.append(dict(span, text=text, bbox=bbox, flags=flags))
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
    """Normalise a header/footer line so OCR variants ("L O S TRASCENDENTALES",
    "METAFÍSICA") and ``3/49``, ``4/49`` compare equal: case folded, accents dropped,
    only letters and digits kept, each run of digits as ``#``."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    return _DIGITS_RE.sub("#", "".join(c for c in folded if c.isalnum()))


def edge_rows(lines: list[Line]) -> dict[int, str]:
    """The page's top and bottom rows: line index -> ``"top"`` / ``"bottom"``. The top
    row is the line with the smallest baseline that has a letter or digit, and every
    line whose baseline is within half its font size of it; the bottom row likewise
    from the largest baseline. A page with one row has only a top row."""
    inked = [i for i, line in enumerate(lines) if any(c.isalnum() for c in line.text)]
    if not inked:
        return {}

    def row(anchor: int) -> list[int]:
        base = lines[anchor].baseline
        return [i for i in inked if abs(lines[i].baseline - base) <= 0.5 * lines[i].size]

    rows = dict.fromkeys(row(max(inked, key=lambda i: lines[i].baseline)), "bottom")
    rows.update(dict.fromkeys(row(min(inked, key=lambda i: lines[i].baseline)), "top"))
    return rows


def box_labels(page: pymupdf.Page, row: dict, lines: list[Line]) -> list[str]:
    """For each line, the label of the layout model's box (a row of
    ``paddle_ocr.layout_pages``, in image pixels) that covers more than half of it, else
    ``""``."""
    scale = page.rect.width / row["width"]
    boxes = [(block["label"], [c * scale for c in block["bbox"]]) for block in row["blocks"]]
    labels = []
    for line in lines:
        x0, y0, x1, y1 = line.bbox
        area = (x1 - x0) * (y1 - y0)
        best, label = area / 2, ""
        for name, (bx0, by0, bx1, by1) in boxes:
            covered = max(0, min(x1, bx1) - max(x0, bx0)) * max(0, min(y1, by1) - max(y0, by0))
            if covered > best:
                best, label = covered, name
        labels.append(label)
    return labels


@dataclass
class DocumentProfile:
    """What the analysis pass learned about the whole document."""

    body_size: float = 0.0
    # Typical distance between the tops of consecutive body lines.
    line_spacing: float = 0.0
    # The same for other sizes seen often (notes): an OCR layer's sizes need not scale
    # with their leading (the Timeo's notes read 5.8 pt, 9.3 apart; body 10.1, 12.1).
    size_spacing: dict[float, float] = field(default_factory=dict)
    # Heading font sizes, largest first; index + 1 is the heading level.
    heading_sizes: list[float] = field(default_factory=list)
    # (edge, ``running_key``) of each line in a page's top or bottom row (``edge_rows``)
    # -> the pages it is on.
    edge_pages: dict[tuple[str, str], set[int]] = field(default_factory=dict)
    # Keys of lines in the ``_MARGIN_ZONE`` of ``_RUNNING_SHARE`` of the pages.
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
    # The book prints its margin references in the text, in brackets ("[22b]").
    bracketed_refs: bool = False
    # Page index -> the layout model's boxes (``paddle_ocr.layout_pages``); not used yet.
    layout: dict[int, dict] = field(default_factory=dict)

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

    def furniture(self, page_index: int, lines: list[Line], page_height: float) -> set[int]:
        """Indexes of the page's furniture: in its top or bottom row, a bare page number,
        or a line no bigger than the body (2+ letters) that shares its row with a page
        number standing alone ("TIMEO ... 163"; not a line number beside body text) or
        is in the same row of a page at most ``_RUNNING_PAGES`` away; in the
        ``_MARGIN_ZONE``, a bare page number or a ``running_texts`` line; anywhere, a
        watermark."""
        rows = edge_rows(lines)
        numbers = {i for i in rows if PAGE_NUMBER_RE.match(lines[i].text)}
        body_rows = {
            rows[i] for i in rows.keys() - numbers if lines[i].size >= self.body_size * SMALL_RATIO
        }
        numbered = {rows[i] for i in numbers} - body_rows
        found = set()
        for i, line in enumerate(lines):
            key = running_key(line.text)
            edge = rows.get(i)
            repeated = edge and (
                line.size <= self.body_size * _RUNNING_SIZE
                and sum(c.isalpha() for c in key) >= 2
                and (
                    edge in numbered
                    or any(
                        0 < abs(page - page_index) <= _RUNNING_PAGES
                        for page in self.edge_pages.get((edge, key), ())
                    )
                )
            )
            in_zone = not _MARGIN_ZONE * page_height < line.top < (1 - _MARGIN_ZONE) * page_height
            zoned = in_zone and (PAGE_NUMBER_RE.match(line.text) or key in self.running_texts)
            if i in numbers or repeated or zoned or key in self.watermarks:
                found.add(i)
        return found


def analyze_document(
    doc: pymupdf.Document, on_page: Callable[[int, int], None] | None = None
) -> DocumentProfile:
    """One pass over every page collecting font, spacing, margin and endnote statistics.
    ``on_page(done, total)`` follows the pages."""
    sizes: Counter[float] = Counter()
    gaps: Counter[float] = Counter()
    edge_pages: defaultdict[tuple[str, str], set[int]] = defaultdict(set)
    margin_texts: Counter[str] = Counter()  # keys of lines in the margin zone -> pages
    offsets: Counter[int] = Counter()  # printed page number minus page index
    image_pages: Counter[int] = Counter()  # image xref -> pages it is placed on
    fonts: Counter[str] = Counter()  # font name -> characters set in it
    inner_texts: Counter[str] = Counter()
    occurrences: Counter[int] = Counter()
    line_starts: dict[int, tuple[int, int]] = {}
    referenced_mid_line: set[int] = set()
    sup_refs: list[tuple[int, tuple[int, int, int]]] = []
    note_lines: list[tuple[int, tuple[int, int]]] = []
    plain_note_lines: list[tuple[int, tuple[int, int]]] = []
    note_marks: list[tuple[int, int]] = []  # first lines of notes with a hung mark
    mark_readings: dict[tuple[int, int], str] = {}  # ... and what the mark was read as
    sample: list[str] = []
    sample_len = 0
    bracketed_pages = 0
    for page_index in range(doc.page_count):
        if on_page:
            on_page(page_index, doc.page_count)
        page = doc.load_page(page_index)
        lines = page_lines(page)
        rows = edge_rows(lines)
        height = page.rect.height
        margin_texts.update(
            {
                running_key(line.text)
                for line in lines
                if line.text.strip()
                and not _MARGIN_ZONE * height < line.top < (1 - _MARGIN_ZONE) * height
            }
        )
        page_inner_texts = set()
        page_offsets: set[int] = set()
        image_pages.update({info[0] for info in page.get_images(full=False)})
        bracketed_pages += any(has_bracketed(line.text) for line in lines)
        for line_index, line in enumerate(lines):
            text = line.text
            for span in line.spans:
                sizes[round(span["size"], 1)] += len(span["text"].strip())
                fonts[span.get("font", "")] += len(span["text"].strip())
            if line_index in rows:
                edge_pages[(rows[line_index], running_key(text))].add(page_index)
                printed = _PRINTED_NUMBER_RE.match(text)
                if printed:
                    page_offsets.add(int(printed.group(1).replace(" ", "")) - page_index)
            elif len(text.strip()) >= _MIN_WATERMARK_CHARS and running_key(text):
                page_inner_texts.add(running_key(text))
            if line_index and lines[line_index - 1].size == line.size:
                gap = round(line.baseline - lines[line_index - 1].baseline, 1)
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
            plain = plain_note_start(lines, line_index)
            if plain:
                plain_note_lines.append((plain[0], (page_index, plain[1])))
            mark = hung_mark(lines, line_index)
            if mark is not None:
                note_marks.append((page_index, mark))
                signs = text.split()[0] if mark == line_index else "".join(text.split())
                mark_readings[(page_index, mark)] = signs
            for match in _BRACKET_RE.finditer(text):
                number = int(match.group(1))
                at_line_start = match.start() == len(text) - len(text.lstrip())
                if not occurrences[number] and not at_line_start:
                    referenced_mid_line.add(number)
                elif occurrences[number] and at_line_start:
                    # A later occurrence at the start of a line: the note itself.
                    line_starts[number] = (page_index, line_index)
                occurrences[number] += 1
        inner_texts.update(page_inner_texts)
        offsets.update(page_offsets)

    sizes.pop(0.0, None)
    body_size = sizes.most_common(1)[0][0] if sizes else 0.0
    body_gaps = Counter({gap: n for (size, gap), n in gaps.items() if size == body_size})
    line_spacing = body_gaps.most_common(1)[0][0] if body_gaps else body_size * 1.2
    by_size: dict[float, list[float]] = {}
    for (size, gap), n in gaps.items():
        by_size.setdefault(size, []).extend([gap] * n)
    size_spacing = {
        size: statistics.median(found)
        for size, found in by_size.items()
        if len(found) >= _MIN_SPACING_LINES
    }
    heading_sizes = _cluster_sizes(
        {s: n for s, n in sizes.items() if s >= body_size * HEADING_RATIO and n >= 3}
    )
    if on_page:
        on_page(doc.page_count, doc.page_count)
    watermark_threshold = max(5, doc.page_count * _WATERMARK_SHARE)
    watermarks = {text for text, n in inner_texts.items() if n >= watermark_threshold}
    # Notes numbered "235 Text" (OCR'd: numbers lost and garbled), if they link more
    # references; only as a block after all of their references, as a page's footnotes
    # ("17 Text" at its foot) look the same.
    chapter_notes = max(
        match_chapter_notes(sup_refs, note_lines),
        match_chapter_notes(
            sup_refs,
            plain_note_lines,
            lossy=True,
            least=lossy_min_run(doc.page_count),
            marks=note_marks,
            readings=mark_readings,
        ),
        key=lambda notes: sum(len(refs) for refs in notes.refs.values()),
    )
    return DocumentProfile(
        watermarks=watermarks,
        body_size=body_size,
        line_spacing=line_spacing,
        size_spacing=size_spacing,
        heading_sizes=heading_sizes,
        edge_pages=dict(edge_pages),
        running_texts={
            key
            for key, n in margin_texts.items()
            if key and n >= max(3, doc.page_count * _RUNNING_SHARE)
        },
        endnote_defs=_endnote_candidates(occurrences, line_starts, referenced_mid_line),
        chapter_notes=chapter_notes,
        page_labels=_page_labels(doc, offsets),
        body_fonts=_body_fonts(fonts),
        repeated_images={
            xref
            for xref, n in image_pages.items()
            if n >= max(3, doc.page_count * _REPEATED_IMAGE_SHARE)
        },
        text_sample=" ".join(sample),
        page_count=doc.page_count,
        bracketed_refs=in_book(bracketed_pages, doc.page_count),
    )


def plain_note_start(lines: list[Line], index: int) -> tuple[int, int] | None:
    """A note numbered with no period: "235 Trato de ...", or "235" hung in the margin
    as a line of its own beside the note's first line. Returns (number, index of the
    note's first line)."""
    line = lines[index]
    plain = _PLAIN_NOTE_RE.match(line.text)
    if plain:
        return int(plain.group(1)), index
    # shortcut: OCR misreads of old-style figures seen in the Timeo (".¡." for 4, "o"
    # for 0, "I" for 1); add others as books show them.
    digits = "".join(line.text.split()).replace(".¡.", "4").translate(OCR_DIGITS)
    if not digits.isdigit() or len(digits) > 4:
        return None
    beside = _beside(lines, index)
    return (int(digits), beside) if beside is not None else None


def hung_mark(lines: list[Line], index: int) -> int | None:
    """A note number however misread: a few signs alone on a line, hung beside another
    ("n" for 11, "1+" for 14), or starting the note's line ("3.¡. Así pues" for 34).
    Returns the index of the note's first line."""
    if NOTE_MARK_RE.match(lines[index].text):
        return index
    if LOOSE_NOTE_MARK_RE.match(lines[index].text) and _at_numbers(lines, index):
        return index  # ".i,57 Entre los", "H7 Como": at the column of the notes' numbers
    signs = "".join(lines[index].text.split())
    # Longer at the notes' numbers: "lllll" for 122.
    most = _MAX_LOOSE_SIGNS if _at_numbers(lines, index) else _MAX_MARK_SIGNS
    if not 0 < len(signs) <= most:
        return None
    return _beside(lines, index)


def _at_numbers(lines: list[Line], index: int) -> bool:
    """Whether a line starts at the page's left edge, its notes' numbers hung out of a
    text column most lines start further in (the Timeo's notes: 54 against 69)."""
    line = lines[index]
    xs = sorted(o.x0 for o in lines if o.text.strip() and abs(o.size - line.size) < 0.6)
    if len(xs) < _MIN_COLUMN_LINES:
        return False
    return line.x0 - xs[0] < 0.5 * line.size and xs[len(xs) // 2] - line.x0 > 1.5 * line.size


def _beside(lines: list[Line], index: int) -> int | None:
    """The first of the lines on ``lines[index]``'s baseline, to its right."""
    line = lines[index]
    beside = [
        i
        for i, other in enumerate(lines)
        if abs(other.baseline - line.baseline) <= _SAME_BASELINE * other.size
        and other.x0 > line.x1
        and other.text.strip()
    ]
    return min(beside, key=lambda i: lines[i].x0) if beside else None


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

"""A marked book's style sheet (docs/marks-plan.md, Phase 1): the features of the lines a
person marked as examples, and every line's kind by them.

A line takes a kind when its features agree with one of that kind's examples: the same
font family, bold, italic, capitals, numbering class and dot leaders where both are
known, a size within a round tolerance, and for a running head or page number the same
place at the page's edge. Scans have no fonts: size, place, capitals and numbering only.
When two kinds agree, the one with the nearest example (alignment, length, place, gaps)
takes the line. How sure: ``marked`` (a mark covers the line), ``matched`` (one kind
agrees, or is clearly nearest), ``conflict`` (two kinds about as near: today's rules
decide) or ``rules`` (none agrees). A matched line placed or sized like no agreeing
example is ``odd``: the review view lists its page as doubtful.

A mark that takes no line teaches only for kinds printed outside the text column
(``PLACE_KINDS``), by its place. Note numbers (``note-ref``) are matched on a text layer
only, by their size and rise against their line and whether they are glued to a word.

Sizes are against the book's body size, gaps in its body line spacings, places in shares
of the page: all from the book itself.
"""

import math
import re
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from pdf_worker.heading_levels import _division
from pdf_worker.layout import BOLD, SUPERSCRIPT
from pdf_worker.marks import Marks, inside

ITALIC = 2  # MuPDF span flag bit
EDGE_KINDS = ("running-head", "page-number")
# Kinds printed outside the text column: a mark of theirs that takes no line (a scan's
# OCR merges margin letters into the text) still says where they sit.
PLACE_KINDS = ("margin-ref", "gloss", "line-number")
# Round tolerances, chosen before looking at the results. Sizes in body sizes: a text
# layer's sizes are exact; a scan's are estimated from a block's area per letter.
SIZE_TOL = 0.05
SCAN_SIZE_TOL = 0.15
EDGE_SPACINGS = 1.5  # a running head or page number: this near the example's place
REF_TOL = 0.1  # a note number's size and rise, in its line's sizes
# Two kinds agree: the one with the nearest example (``_distance``) takes the line, unless
# another's is within half a feature of it (a conflict). The plan's literal rule (any two
# agreeing: a conflict) left most lines in conflict: a heading's or a contents entry's
# second line looks like body text.
CLEAR = 0.5
_MIN_COLUMN_LINES = 3  # body lines a page needs to measure its own column
_MIN_COLUMN_CHARS = 20


@dataclass
class PageLines:
    """A page's size and lines: ``layout.Line`` (a text layer, with spans) or anything
    with a ``bbox`` and a ``text`` (a scan's lines, from its Paddle rows)."""

    width: float
    height: float
    lines: list


@dataclass(frozen=True)
class Features:
    size: float | None  # against the body size; None: a shape taking no line
    font: str | None  # family; None on scans
    bold: bool | None
    italic: bool | None
    caps: bool | None  # None: fewer than two letters
    align: str  # left, centre, indent, right, margin (in its page's text column)
    top: float  # share of the page height above it
    bottom: float  # ... and below it
    above: float | None  # gap to the line above, in body line spacings
    below: float | None
    numbering: str | None  # division, roman, arabic, letter, none
    length: int
    leaders: bool | None = None  # dot leaders ("....", ". . ."): a contents line's


@dataclass(frozen=True)
class RefFeatures:
    """A note number in the text: its size and rise against its line, and whether it is
    glued to the word before it."""

    size: float
    rise: float
    glued: bool


@dataclass(frozen=True)
class Label:
    kind: str | None = None
    level: int | None = None
    sure: str = "rules"  # marked, matched, conflict, rules
    odd: bool = False  # matched, but placed or sized like no example that agrees
    agree: tuple[str, ...] = ()  # the kinds that agree (``key``: "heading 2", "body")


@dataclass
class Measures:
    """A book's lines' features, and what they are measured against."""

    body: float  # body size (points; a scan's: its own estimate)
    spacing: float  # body line spacing, top to top (points)
    scan: bool
    columns: list[tuple[float, float]]  # each page's text column, left and right
    features: list[list[Features]]
    size_tol: float
    edge_tol: float  # EDGE_SPACINGS in shares of the page height


@dataclass
class StyleSheet:
    examples: dict[str, list[Features]] = field(default_factory=dict)
    refs: list[RefFeatures] = field(default_factory=list)


@dataclass
class Classification:
    labels: list[list[Label]]  # per page (index 0 = page 1), per line
    refs: list[list[tuple[float, float, float, float]]]  # note numbers found (text layer)
    sheet: StyleSheet

    def doubtful(self, page: int) -> bool:
        """Whether page ``page`` (1-based) has a conflict or an odd line."""
        return any(label.sure == "conflict" or label.odd for label in self.labels[page - 1])

    def next_doubtful(self, after: int) -> int | None:
        return next(
            (page for page in range(after + 1, len(self.labels) + 1) if self.doubtful(page)),
            None,
        )


def key(kind: str, level: int | None = None) -> str:
    return f"{kind} {level}" if level else kind


def numbering(text: str) -> str:
    """The numbering ``text`` starts with: division (a division word, "Capítulo"), roman,
    arabic, letter or none."""
    text = text.strip().lstrip("¿¡«“\"'([—-– ")
    if _division(text):
        return "division"
    if re.match(r"\d", text):  # "4", "4.2", "1Hegel" (a footnote's glued number)
        return "arabic"
    # A roman number or a letter is followed by a sign ("IV.", "a).-") or is the whole line
    # ("II"): "I believe", "Y por ello" are words.
    if re.fullmatch(r"[IVXLCDM]+", text) or re.match(r"[IVXLCDM]+[.)\-–—:]", text):
        return "roman"
    if re.match(r"[^\W\d_][.)]", text):
        return "letter"
    return "none"


_LEADERS_RE = re.compile(r"\.{4,}|(?:\. ){3,}|…{2,}|_{4,}")


def _family(font: str) -> str:
    """ "ABCDEF+TimesNewRomanPS-BoldMT" -> "TimesNewRoman"."""
    name = re.sub(r"^[A-Z]{6}\+", "", font)
    return re.sub(r"(?:PS)?MT$|PS$", "", re.split(r"[-,]", name)[0])


def _raw(line, scan: bool) -> tuple:
    """(size in points, font family, bold, italic, capitals) of a line."""
    text = line.text.strip()
    letters = [c for c in text if c.isalpha()]
    caps = all(c.isupper() for c in letters) if len(letters) >= 2 else None
    if scan:
        x0, y0, x1, y1 = line.bbox
        # shortcut: a scan's "line" is often a whole block; its type size is estimated
        # from its area per letter, in units of its own (compared only with the book's
        # body). Upgrade if the Paddle rows ever give each printed line's box.
        size = math.sqrt(max(x1 - x0, 0) * max(y1 - y0, 0) / max(len(text), 1))
        return size, None, None, None, caps
    spans = [s for s in line.spans if s["text"].strip()]
    spans = [s for s in spans if not s["flags"] & SUPERSCRIPT] or spans  # a note number
    fonts: Counter[str] = Counter()
    for span in spans:
        fonts[_family(span.get("font", ""))] += len(span["text"].strip())
    names = [span.get("font", "").lower() for span in spans]
    bold = bool(spans) and all(
        s["flags"] & BOLD or "bold" in n for s, n in zip(spans, names, strict=True)
    )
    italic = bool(spans) and all(
        s["flags"] & ITALIC or "italic" in n or "oblique" in n
        for s, n in zip(spans, names, strict=True)
    )
    return line.size, fonts.most_common(1)[0][0] if fonts else None, bold, italic, caps


def _weighted_median(pairs: list[tuple[float, int]]) -> float:
    pairs = sorted(pairs)
    half, seen = sum(n for _, n in pairs) / 2, 0
    for value, n in pairs:
        seen += n
        if seen >= half:
            return value
    return 0.0


def _align(box, column: tuple[float, float], tol: float) -> str:
    left, right = column
    middle = (box[0] + box[2]) / 2
    if middle < left - tol or middle > right + tol:
        return "margin"
    if abs(box[0] - left) <= tol:
        return "left"
    if abs(middle - (left + right) / 2) <= tol:
        return "centre"
    if abs(box[2] - right) <= tol:
        return "right"
    return "indent"


def measure(pages: Sequence[PageLines]) -> Measures:
    """Every line's features, against the book's body size, line spacing and columns."""
    scan = not any(hasattr(line, "spans") for page in pages for line in page.lines)
    raws = [[_raw(line, scan) for line in page.lines] for page in pages]
    body = _weighted_median(
        [
            (raw[0], len(line.text.strip()))
            for page, page_raws in zip(pages, raws, strict=True)
            for line, raw in zip(page.lines, page_raws, strict=True)
            if raw[0] > 0 and line.text.strip()
        ]
    )
    size_tol = SCAN_SIZE_TOL if scan else SIZE_TOL

    def bodied(raw) -> bool:
        return body > 0 and abs(raw[0] / body - 1) <= size_tol

    gaps, columns = [], []
    for page, page_raws in zip(pages, raws, strict=True):
        pairs = list(zip(page.lines, page_raws, strict=True))
        for (a, ra), (b, rb) in zip(pairs, pairs[1:], strict=False):
            gap = b.bbox[1] - a.bbox[1]
            if bodied(ra) and bodied(rb) and 0.5 * body < gap < 3 * body:
                gaps.append(gap)
        long = [
            line.bbox
            for line, raw in pairs
            if bodied(raw) and len(line.text.strip()) >= _MIN_COLUMN_CHARS
        ]
        columns.append(
            (statistics.median(b[0] for b in long), statistics.median(b[2] for b in long))
            if len(long) >= _MIN_COLUMN_LINES
            else None
        )
    # The median top-to-top gap of body lines: most follow one another in a paragraph.
    spacing = statistics.median(gaps) if len(gaps) >= 20 else body * 1.2
    measured = [(k, c) for k, c in enumerate(columns) if c]
    for index, column in enumerate(columns):
        if column is None:  # a page of few lines: the column of the pages on its side
            same = [c for k, c in measured if k % 2 == index % 2]
            found = same or [c for _, c in measured]
            columns[index] = (
                (statistics.median(c[0] for c in found), statistics.median(c[1] for c in found))
                if found
                else (0.0, pages[index].width)
            )
    features = [
        _page_features(page, page_raws, column, body, spacing)
        for page, page_raws, column in zip(pages, raws, columns, strict=True)
    ]
    heights = [page.height for page in pages] or [1.0]
    edge_tol = EDGE_SPACINGS * spacing / statistics.median(heights)
    return Measures(body, spacing, scan, columns, features, size_tol, edge_tol)


def _page_features(page: PageLines, raws, column, body: float, spacing: float):
    lines = page.lines
    order = sorted(range(len(lines)), key=lambda i: lines[i].bbox[1] + lines[i].bbox[3])
    above: dict[int, float] = {}
    below: dict[int, float] = {}
    for at, i in enumerate(order):
        box = lines[i].bbox
        for j in reversed(order[:at]):  # the nearest line above that overlaps it
            other = lines[j].bbox
            if other[0] < box[2] and box[0] < other[2]:
                gap = max(box[1] - other[3], 0.0) / spacing
                above[i], below[j] = gap, min(below.get(j, gap), gap)
                break
    found = []
    for i, (line, raw) in enumerate(zip(lines, raws, strict=True)):
        size, font, bold, italic, caps = raw
        text = line.text.strip()
        found.append(
            Features(
                size=size / body if body else None,
                font=font,
                bold=bold,
                italic=italic,
                caps=caps,
                align=_align(line.bbox, column, body),
                top=line.bbox[1] / page.height,
                bottom=(page.height - line.bbox[3]) / page.height,
                above=above.get(i),
                below=below.get(i),
                numbering=numbering(text),
                length=len(text),
                leaders=bool(_LEADERS_RE.search(text)),
            )
        )
    return found


def _shape_features(shape, page: PageLines, column, body: float) -> Features:
    """A shape that takes no line: only its place."""
    box = (
        min(p[0] for p in shape),
        min(p[1] for p in shape),
        max(p[0] for p in shape),
        max(p[1] for p in shape),
    )
    return Features(
        size=None,
        font=None,
        bold=None,
        italic=None,
        caps=None,
        align=_align(box, column, body),
        top=box[1] / page.height,
        bottom=(page.height - box[3]) / page.height,
        above=None,
        below=None,
        numbering=None,
        length=0,
    )


def _middle(box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _ref_candidates(line):
    """(span, its RefFeatures) for each number of 1-3 digits after a line's first span."""
    before = ""
    for index, span in enumerate(line.spans):
        text = span["text"]
        if index and re.fullmatch(r"\s*\d{1,3}\s*", text) and line.size and "origin" in span:
            yield (
                span,
                RefFeatures(
                    size=round(span["size"] / line.size, 3),
                    rise=round((line.baseline - span["origin"][1]) / line.size, 3),
                    glued=bool(before) and not before[-1].isspace() and not text[0].isspace(),
                ),
            )
        before += text


def build(pages: Sequence[PageLines], measures: Measures, marks: Marks) -> StyleSheet:
    """The style sheet of ``marks``' examples (``scope: style``)."""
    sheet = StyleSheet()
    for mark in marks.marks:
        if mark.scope != "style" or mark.page > len(pages):
            continue
        page = pages[mark.page - 1]
        if mark.kind == "note-ref":
            if not measures.scan:  # shortcut: a scan's words are placed by share only
                sheet.refs += [
                    ref
                    for line in page.lines
                    for span, ref in _ref_candidates(line)
                    if inside(_middle(span["bbox"]), mark.shape)
                ]
            continue
        taken = [
            measures.features[mark.page - 1][i]
            for i, line in enumerate(page.lines)
            if line.text.strip() and inside(_middle(line.bbox), mark.shape)
        ]
        if not taken and mark.kind in PLACE_KINDS:
            column = measures.columns[mark.page - 1]
            place = _shape_features(mark.shape, page, column, measures.body)
            # Inside the column it marks part of a line (OCR merged it): no line follows it.
            taken = [place] if place.align == "margin" else []
        sheet.examples.setdefault(key(mark.kind, mark.level), []).extend(taken)
    return sheet


def _agrees(example: Features, line: Features, kind: str, measures: Measures) -> bool:
    if example.size is None:  # a place only
        return line.align == example.align
    for a, b in (
        (example.font, line.font),
        (example.bold, line.bold),
        (example.italic, line.italic),
        (example.caps, line.caps),
        (example.numbering, line.numbering),
        (example.leaders, line.leaders),
    ):
        if a is not None and b is not None and a != b:
            return False
    if line.size is None or abs(line.size - example.size) > measures.size_tol:
        return False
    if kind in EDGE_KINDS:
        if example.top <= example.bottom:
            return abs(line.top - example.top) <= measures.edge_tol
        return abs(line.bottom - example.bottom) <= measures.edge_tol
    return True


def _distance(example: Features, line: Features, measures: Measures) -> float:
    """How unlike ``example`` an agreeing ``line`` is: size (in tolerances), alignment,
    length, place on the page and the gaps above and below, each counting up to 1."""
    if example.size is None:  # a place only, which agrees
        return 0.0
    found = abs(example.size - line.size) / measures.size_tol + (example.align != line.align)
    found += abs(example.length - line.length) / max(example.length, line.length, 1)
    found += abs(example.top - line.top)  # the place on the page, in page heights
    for a, b in ((example.above, line.above), (example.below, line.below)):
        if a is not None and b is not None:
            found += min(abs(a - b), 2.0) / 2
        elif a is not None or b is not None:
            found += 0.5
    return found


def _odd(examples: list[Features], line: Features, measures: Measures) -> bool:
    """Placed (aligned) or sized like none of the ``examples`` that agree with ``line``."""
    if not any(example.align == line.align for example in examples):
        return True
    sized = [example.size for example in examples if example.size is not None]
    return bool(sized) and not any(abs(size - line.size) <= measures.size_tol / 2 for size in sized)


def classify(
    pages: Sequence[PageLines], marks: Marks, measures: Measures | None = None
) -> Classification:
    """Every line's kind, level and how sure, by ``marks`` (a mark wins over the style
    sheet). ``measures``: ``measure(pages)``, if already made (it doesn't depend on the
    marks)."""
    measures = measures or measure(pages)
    sheet = build(pages, measures, marks)
    kinds = {k: k.rsplit(" ", 1)[0] if k[-1].isdigit() else k for k in sheet.examples}
    covering: list[dict[int, object]] = [{} for _ in pages]
    # A "here" mark (a correction) wins over an example; a later mark over an earlier.
    for mark in sorted(marks.marks, key=lambda m: m.scope == "here"):
        if mark.kind == "note-ref" or mark.page > len(pages):
            continue
        for i, line in enumerate(pages[mark.page - 1].lines):
            if inside(_middle(line.bbox), mark.shape):
                covering[mark.page - 1][i] = mark
    labels = []
    for page, page_features, covered in zip(pages, measures.features, covering, strict=True):
        page_labels = []
        for i, (line, features) in enumerate(zip(page.lines, page_features, strict=True)):
            if i in covered:
                mark = covered[i]
                page_labels.append(Label(mark.kind, mark.level, "marked"))
                continue
            if not line.text.strip():
                page_labels.append(Label())
                continue
            agreeing = {
                k: found
                for k, examples in sheet.examples.items()
                if (found := [e for e in examples if _agrees(e, features, kinds[k], measures)])
            }
            nearest = sorted(
                (min(_distance(e, features, measures) for e in found), k)
                for k, found in agreeing.items()
            )
            near = tuple(k for d, k in nearest if d - nearest[0][0] <= CLEAR) if nearest else ()
            if len(near) == 1:
                name = near[0]
                level = int(name.rsplit(" ", 1)[1]) if name != kinds[name] else None
                odd = _odd(agreeing[name], features, measures)
                page_labels.append(Label(kinds[name], level, "matched", odd, near))
            elif near:
                page_labels.append(Label(sure="conflict", agree=near))
            else:
                page_labels.append(Label())
        labels.append(page_labels)
    refs = [_refs(page, sheet) for page in pages]
    return Classification(labels, refs, sheet)


def _refs(page: PageLines, sheet: StyleSheet) -> list:
    if not sheet.refs:
        return []
    return [
        tuple(span["bbox"])
        for line in page.lines
        if hasattr(line, "spans")
        for span, ref in _ref_candidates(line)
        if any(
            abs(ref.size - ex.size) <= REF_TOL
            and abs(ref.rise - ex.rise) <= REF_TOL
            and ref.glued == ex.glued
            for ex in sheet.refs
        )
    ]

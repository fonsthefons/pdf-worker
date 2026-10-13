"""Separate a page's body column from its margins: glosses, line numbers, OCR junk.

Textbooks and editions often print notes in a narrow column beside the text (glosses)
and line numbers in the gutter. Read in MuPDF order these interleave with the body and
shatter its paragraphs. This module finds the body column of each page and sorts every
line into body text, a margin gloss, or something to drop.
"""

import re
import statistics
from collections import Counter
from dataclasses import dataclass

from pdf_worker.footnotes import BodyLine
from pdf_worker.inline import CELL
from pdf_worker.layout import Line, ink_bbox

# Lines at least this share of the page width are candidates for the body column.
_LONG_LINE_SHARE = 0.35
_MIN_LONG_LINES = 3
# A margin column is narrow, and holds less text than the body.
_MAX_MARGIN_WIDTH_SHARE = 0.6
_MAX_MARGIN_CHAR_SHARE = 0.5

_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")
_LEADING_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s+(?=\S)")
_TRAILING_NUMBER_RE = re.compile(r"(?<=\S)\s+\d{1,4}\s*$")
_WORD_RE = re.compile(r"[^\W\d_]{3,}")
_ALNUM_RE = re.compile(r"[^\W_]")
_BREAK_RE = re.compile(r"^\s*[*·•⁂~◆❖✱]+(?:\s*[*·•⁂~◆❖✱]+)*\s*$")


@dataclass(frozen=True)
class PageColumns:
    body: tuple[BodyLine, ...]
    # Margin glosses, top to bottom; fragments on one row are joined into one line.
    glosses: tuple[str, ...]


def split_columns(lines: list[BodyLine], page_width: float, body_size: float) -> PageColumns:
    """Sort a page's lines into the body column and the margin glosses."""
    column = _body_column(lines, page_width)
    if column is None:
        return _no_margins(lines, body_size)
    left, right = column
    # Justified lines end at the median right edge; marks past it stick out.
    edge = statistics.median(
        bl.line.x1 for bl in lines if bl.line.x1 - bl.line.x0 >= page_width * _LONG_LINE_SHARE
    )
    lines = [_trim_edge_marks(bl, left, edge, body_size) for bl in lines]
    tolerance = 0.5 * body_size
    body: list[BodyLine] = []
    margin: list[BodyLine] = []
    for body_line in lines:
        line, text = body_line.line, body_line.text
        size = line.size or body_size
        if not text.strip():
            body.append(body_line)  # blank lines carry paragraph breaks
        elif line.x1 < left - tolerance or line.x0 > right + tolerance:
            margin.append(body_line)
        elif _is_junk(text):
            continue
        elif _NUMBER_RE.match(text) and (line.x0 > right - size or line.x1 < left + size):
            margin.append(body_line)  # a line number at the edge of the column
        else:
            # Gutter line numbers that OCR merged into a body line: "70 Puer qui ridet",
            # "quia māter eum 55".
            if line.x0 < left - 1.2 * size:
                text = _LEADING_NUMBER_RE.sub("", text)
            if line.x1 > right + tolerance:
                text = _TRAILING_NUMBER_RE.sub("", text)
            body.append(BodyLine(text, line, body_line.endnote_label))

    if not _is_margin_column(margin, body, left, right):
        return _no_margins(lines, body_size)
    glosses = [
        _strip_line_number(gloss)
        for gloss in _gloss_lines(margin)
        if not _NUMBER_RE.match(gloss) and _looks_like_text(gloss)
    ]
    # With the margins gone the body is a single column: read it top to bottom, and
    # join table cells that sit on one row.
    body.sort(key=lambda bl: (bl.line.top, bl.line.x0))
    return PageColumns(body=tuple(merge_rows(body, body_size)), glosses=tuple(glosses))


def _trim_edge_marks(body_line: BodyLine, left: float, right: float, body_size: float) -> BodyLine:
    """Drop short marks that OCR read into a body line from the margin beside it, such as
    the section numbers and letters of classical editions ("vas a 11", "d Pro. —").

    A mark starts past the column edge, after a word gap, and is at most 4 characters.
    """
    line, text = body_line.line, body_line.text
    spans = list(line.spans)
    inked = [i for i, span in enumerate(spans) if span["text"].strip()]
    if len(inked) < 2:
        return body_line
    gap = 0.3 * (line.size or body_size)
    first, second, last, before_last = inked[0], inked[1], inked[-1], inked[-2]
    cut_head = cut_tail = None
    mark = spans[last]["text"].strip()
    if (
        spans[last]["bbox"][0] > right
        and len(mark) <= 4
        and spans[last]["bbox"][0] - spans[before_last]["bbox"][2] > gap
        and text.rstrip().endswith(mark)
    ):
        cut_tail = last
        text = text.rstrip()[: -len(mark)].rstrip() + " "
    mark = spans[first]["text"].strip()
    if (
        spans[first]["bbox"][2] < left
        and len(mark) <= 4
        and spans[second]["bbox"][0] - spans[first]["bbox"][2] > gap
        and text.lstrip().startswith(mark)
        and second != cut_tail
    ):
        cut_head = first
        text = text.lstrip()[len(mark) :].lstrip()
    if cut_head is None and cut_tail is None:
        return body_line
    start = cut_head + 1 if cut_head is not None else 0
    kept = tuple(spans[start : cut_tail if cut_tail is not None else len(spans)])
    trimmed = Line(spans=kept, size=line.size, bbox=ink_bbox(kept, line.bbox))
    return BodyLine(text, trimmed, body_line.endnote_label)


def _no_margins(lines: list[BodyLine], body_size: float) -> PageColumns:
    """No margin column: keep MuPDF's reading order, drop junk, join row fragments."""
    body = [bl for bl in lines if not _is_junk(bl.text)]
    return PageColumns(body=tuple(merge_rows(body, body_size)), glosses=())


def merge_rows(lines: list[BodyLine], body_size: float) -> list[BodyLine]:
    """Join consecutive lines that sit side by side on one row (table cells, tab stops)."""
    out: list[BodyLine] = []
    for body_line in lines:
        prev = out[-1] if out else None
        if (
            prev is not None
            and prev.text.strip()
            and body_line.text.strip()
            and not body_line.endnote_label
            and _same_row(prev.line, body_line.line, body_size)
        ):
            out[-1] = _join(prev, body_line)
            continue
        out.append(body_line)
    return out


def _same_row(a: Line, b: Line, body_size: float) -> bool:
    height = min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1])
    return (
        abs(a.top - b.top) < 0.5 * height
        and b.x0 > a.x1 + 0.5 * (a.size or body_size)
        and abs(a.size - b.size) < 1.5
    )


def _join(a: BodyLine, b: BodyLine) -> BodyLine:
    space = {**a.line.spans[-1], "text": " "}
    bbox = (
        min(a.line.x0, b.line.x0),
        min(a.line.bbox[1], b.line.bbox[1]),
        max(a.line.x1, b.line.x1),
        max(a.line.bbox[3], b.line.bbox[3]),
    )
    line = Line(spans=(*a.line.spans, space, *b.line.spans), size=a.line.size, bbox=bbox)
    # The cells stay apart (CELL), so rows of several cells can become tables.
    return BodyLine(a.text.rstrip() + CELL + b.text.lstrip(), line, a.endnote_label)


def _body_column(lines: list[BodyLine], page_width: float) -> tuple[float, float] | None:
    """(left, right) edges of the main text column, or None if there is no clear one."""
    long_lines = [
        bl.line
        for bl in lines
        if bl.text.strip() and bl.line.x1 - bl.line.x0 >= page_width * _LONG_LINE_SHARE
    ]
    if len(long_lines) < _MIN_LONG_LINES:
        return None
    lefts = Counter(round(line.x0 / 3) * 3 for line in long_lines)
    left = min(line.x0 for line in long_lines if abs(line.x0 - lefts.most_common(1)[0][0]) < 6)
    rights = sorted(line.x1 for line in long_lines)
    right = rights[int(len(rights) * 0.8)]
    return left, right


def _is_margin_column(
    margin: list[BodyLine], body: list[BodyLine], left: float, right: float
) -> bool:
    """Only a narrow side column with less text than the body counts as margin."""
    if not margin:
        return False
    for side in (
        [bl.line for bl in margin if bl.line.x1 < left],
        [bl.line for bl in margin if bl.line.x0 > right],
    ):
        width = max(ln.x1 for ln in side) - min(ln.x0 for ln in side) if side else 0
        if width > (right - left) * _MAX_MARGIN_WIDTH_SHARE:
            return False
    margin_chars = sum(len(bl.text.strip()) for bl in margin)
    body_chars = sum(len(bl.text.strip()) for bl in body)
    return margin_chars <= body_chars * _MAX_MARGIN_CHAR_SHARE


def _gloss_lines(margin: list[BodyLine]) -> list[str]:
    """Margin lines top to bottom; fragments on the same row are joined left to right."""
    rows: list[list] = []
    for line in sorted((bl.line for bl in margin), key=lambda ln: (ln.top, ln.x0)):
        height = line.bbox[3] - line.bbox[1]
        if rows and abs(line.top - rows[-1][0].top) < 0.5 * height:
            rows[-1].append(line)
        else:
            rows.append([line])
    texts = [" ".join(ln.text.strip() for ln in sorted(row, key=lambda ln: ln.x0)) for row in rows]
    # Undo hyphenation across gloss lines: "inferus -a -um ↔ supe-" + "rus -a -um".
    out: list[str] = []
    for text in texts:
        if out and out[-1].endswith("-") and out[-1][-2:-1].isalpha() and text[:1].islower():
            out[-1] = out[-1][:-1] + text
        else:
            out.append(text)
    return out


def _strip_line_number(gloss: str) -> str:
    """Drop a line number (a multiple of 5) that OCR read into a gloss: "335 cūr ..."."""
    match = _LEADING_NUMBER_RE.match(gloss)
    if match and int(match.group(0)) % 5 == 0:
        return gloss[match.end() :]
    return gloss


def _is_junk(text: str) -> bool:
    """OCR noise from pictures and rules: no letters or digits, and not a section break
    such as ``* * *``."""
    return bool(text.strip()) and not _ALNUM_RE.search(text) and not _BREAK_RE.match(text)


def _looks_like_text(text: str) -> bool:
    """A gloss with a real word, or a grammatical ending like ``-um``."""
    return bool(_WORD_RE.search(text)) or any(
        token.startswith("-") and token[1:].isalpha() for token in text.split()
    )

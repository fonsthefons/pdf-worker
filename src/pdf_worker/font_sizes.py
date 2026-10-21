"""Font sizes for PDFs whose fonts misreport them.

OCR tools that redraw a scan as fonts made from its letter shapes (ClearScan-style)
make hundreds of fonts, each with its own scale and metrics: in the Timeo the same
12 pt print is "9.95" in one font and "7.90" in another, on the same line, and which
one sets more of a line decides its size. Lines seemed to change size every few lines,
and a third of the text came out as small print. Neither the reported sizes nor the
fonts' declared heights (made from whatever glyphs each font holds) can be trusted.

What can be is the leading: lines set with the same leading are set in the same size.
So each line's leading is the gap to its nearest neighbour in the column (the
baselines are exact), and over the whole book each leading takes the median size of
its lines: body lines (14 pt apart) one size, notes (10 pt apart) a smaller one; a
heading, alone in its spacing, keeps its own. Ordinary books mix sizes on a line
rarely (small capitals), so this is only done when most lines mixing fonts disagree;
the table is stored on the document in memory (``/PdfWorkerSameLeading``) and applied
by ``pdf_worker.layout.page_lines``.
"""

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import replace
from typing import TYPE_CHECKING

import pymupdf

if TYPE_CHECKING:
    from pdf_worker.layout import Line

LEADING_KEY = "PdfWorkerSameLeading"
_MIN_CHARS = 2  # a span shorter than this says little about its font
_RAISED = 0.15  # in ems: a span this far off the line's baseline is raised (a note number)
_SAME = 0.05  # sizes this close are the same
_MIN_MISMATCH_SHARE = 0.3  # of lines mixing fonts, for a book whose fonts misreport
_GAP_STEP = 0.5  # pt: leadings this close are the same
_MAX_GAP = 2.5  # in sizes: a neighbour farther away is not in the same block


def mark_misreporting(doc: pymupdf.Document) -> bool:
    """Whether ``doc``'s fonts misreport their sizes; if so, the size of each leading
    is noted on it (in memory)."""
    if not misreports(doc):
        return False
    table = leading_table(doc)
    doc.xref_set_key(doc.pdf_catalog(), LEADING_KEY, pymupdf.get_pdf_str(json.dumps(table)))
    return True


def sizes_by_leading(doc: pymupdf.Document) -> dict[float, float] | None:
    """Leading -> size, if ``doc``'s fonts misreport their sizes."""
    if not doc.is_pdf:
        return None
    kind, value = doc.xref_get_key(doc.pdf_catalog(), LEADING_KEY)
    return {float(k): v for k, v in json.loads(value).items()} if kind == "string" else None


def leading_table(doc: pymupdf.Document) -> dict[float, float]:
    """For each leading of the book (to ``_GAP_STEP``), the median size of the lines set
    with it, by characters: one size for the whole book, as a page's own fonts drift."""
    from pdf_worker.layout import page_lines

    sizes: dict[float, list[float]] = defaultdict(list)
    for page in doc:
        lines = page_lines(page)
        for line in lines:
            gap = _leading(line, lines)
            if gap is not None:
                sizes[_key(gap)].extend([line.size] * max(1, len(line.text.strip())))
    return {gap: round(statistics.median(s), 1) for gap, s in sizes.items() if s}


def misreports(doc: pymupdf.Document) -> bool:
    """A font per page or more (the Timeo has 1039; OCR layers 7-25, whose sizes vary
    word by word but agree with their leading), and most lines that mix fonts mix
    sizes too."""
    if len({font[3] for page in doc for font in page.get_fonts()}) < doc.page_count:
        return False
    mixed = mismatched = 0
    for page in doc:
        for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
            for line in block.get("lines", ()):
                sizes = {font: size for font, size in _level_spans(line["spans"])}
                if len(sizes) >= 2:
                    mixed += 1
                    mismatched += max(sizes.values()) > min(sizes.values()) * (1 + _SAME)
    return bool(mixed) and mismatched >= _MIN_MISMATCH_SHARE * mixed


def same_leading_sizes(lines: list["Line"], table: dict[float, float]) -> list["Line"]:
    """A page's lines, each set close to a neighbour taking its leading's size from
    ``table``; a line alone in its spacing (a heading) keeps its own."""
    out = []
    for line in lines:
        gap = _leading(line, lines)
        size = table.get(_key(gap)) if gap is not None else None
        out.append(replace(line, size=size) if size else line)
    return out


def _key(gap: float) -> float:
    return round(gap / _GAP_STEP) * _GAP_STEP


def _leading(line: "Line", lines: list["Line"]) -> float | None:
    """The gap from ``line``'s baseline to the nearest one above or below it in its
    column, if near enough to be in the same block."""
    best = None
    for other in lines:
        if other is line or min(line.x1, other.x1) <= max(line.x0, other.x0):
            continue  # not above or below it
        gap = abs(other.baseline - line.baseline)
        if gap > 1 and (best is None or gap < best):
            best = gap
    if best is None or best > _MAX_GAP * (line.size or best):
        return None
    return best


def _level_spans(spans: list[dict]) -> list[tuple[str, float]]:
    """(font, size) of a line's spans on its baseline (not raised)."""
    inked = [s for s in spans if len(s["text"].strip()) >= _MIN_CHARS]
    if not inked:
        return []
    weight: Counter[float] = Counter()
    for s in inked:
        weight[round(s["origin"][1], 1)] += len(s["text"].strip())
    baseline = weight.most_common(1)[0][0]
    return [
        (s["font"], s["size"])
        for s in inked
        if abs(s["origin"][1] - baseline) <= _RAISED * s["size"]
    ]

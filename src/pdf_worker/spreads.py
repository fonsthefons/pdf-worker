"""Cut each two-page spread of a scan into its two pages (docs/experiments/drop-in/
split_spreads.py, variant D of the drop-in experiment).

A sheet is a spread when it is wider than high and, of its text layer's lines
(``layout.page_lines``, lines under four characters left out), none crosses the band around
its middle (``BAND``), each side holds at least a third and reads as a page (most of its
lines alone on their row: a landscape table's cells share rows). A wider-than-high sheet with no
text layer is judged on its picture (``judge_image``). In a book where most sheets with
text are spreads, a wider-than-high sheet with nothing crossing its middle is cut too, at
the book's gutter ("by the book": a page that ends a chapter beside a full one). A sheet
without text or ink is never cut.

``split`` makes each spread two pages, left then right (the sheet twice, each with its half
as MediaBox: picture and text layer kept, the other half outside the page); other sheets
are copied. ``OUT.pages.json`` (and the return value): new page -> sheet, side.
"""

import json
import os
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from pdf_worker.document import open_pdf
from pdf_worker.layout import page_lines

BAND = 0.03  # of the sheet's width, each side of its middle
SHARE = 1 / 3  # of the lines, on each side
MIN_CHARS = 4
# The picture of a sheet without text: rendered at IMAGE_DPI, a pixel whose step to its
# right or lower neighbour exceeds CONTRAST grey levels is ink-like detail (print is sharp;
# a gutter's shadow is a smooth gradient, so it is allowed).
IMAGE_DPI = 36
CONTRAST = 48
QUIET = 0.02  # of a column's pixels: a column with no more detail is empty
INKED = 0.02  # of a half's pixels: a half with this much detail holds text
GAP = 0.015  # of the width: the empty band the gutter needs
NEAR = 0.1  # of the width, each side of the middle: where the band is looked for


@dataclass
class Sheet:
    """A sheet judged on its picture counts its inked halves as its lines (0-2) and a
    middle with no empty band as one crossing line."""

    width: float
    lines: int = 0  # of four characters or more
    left: int = 0
    right: int = 0
    crossing: int = 0
    gutter: float = 0.0  # where to cut
    landscape: bool = False
    by_book: bool = False
    # Each side's lines mostly alone on their row, as a page's: a table's cells share rows.
    pages: bool = True

    @property
    def rule(self) -> bool:
        """The rule alone: it also takes two-column pages (indexes, tables)."""
        return not self.crossing and min(self.left, self.right) >= max(1, self.lines * SHARE)

    @property
    def spread(self) -> bool:
        return self.rule and self.landscape and self.pages

    @property
    def cut(self) -> bool:
        return self.spread or self.by_book


def _rows(page) -> list[tuple[float, float, float, str]]:
    """(x0, x1, bottom, text) of the page's lines, in ``page_lines`` order, as the page is
    shown (``page_lines`` gives a /Rotate page's lines unrotated)."""
    rows = []
    for ln in page_lines(page):
        box = pymupdf.Rect(ln.bbox) * page.rotation_matrix
        rows.append((box.x0, box.x1, box.y1, ln.text.strip()))
    return rows


def judge(rows, width: float, height: float) -> Sheet:
    mid = width / 2
    long = [r for r in rows if len(r[3]) >= MIN_CHARS]
    sheet = Sheet(width, len(long), gutter=mid, landscape=width > height)
    sheet.crossing = sum(x0 < mid - BAND * width and x1 > mid + BAND * width for x0, x1, *_ in long)
    left = [r for r in long if r[0] + r[1] < width]
    right = [r for r in long if r[0] + r[1] >= width]
    sheet.left, sheet.right = len(left), len(right)
    sheet.pages = all(_reads_as_page(side) for side in (left, right))
    if left and right and max(r[1] for r in left) < min(r[0] for r in right):
        sheet.gutter = (max(r[1] for r in left) + min(r[0] for r in right)) / 2
    return sheet


def _reads_as_page(rows) -> bool:
    """Most of these lines are alone on their row (same bottom, to the point)."""
    on_row = Counter(round(r[2]) for r in rows)
    return 2 * sum(on_row[round(r[2])] == 1 for r in rows) > len(rows)


def _detail_columns(page) -> tuple[list[int], int]:
    """Per column of the page rendered at ``IMAGE_DPI``: its ink-like pixels; and the
    rendering's height."""
    pix = page.get_pixmap(dpi=IMAGE_DPI, colorspace=pymupdf.csGRAY, alpha=False)
    w, h, stride, data = pix.width, pix.height, pix.stride, pix.samples
    columns = [0] * w
    for y in range(h - 1):
        row, below = (
            data[y * stride : y * stride + w],
            data[(y + 1) * stride : (y + 1) * stride + w],
        )
        for x in range(w - 1):
            p = row[x]
            if abs(row[x + 1] - p) > CONTRAST or abs(below[x] - p) > CONTRAST:
                columns[x] += 1
    return columns, h


def judge_image(page) -> Sheet:
    """A sheet with no text layer: the longest run of empty columns near its middle is
    its gutter band; each half (beyond where the band is looked for) is inked or not."""
    columns, h = _detail_columns(page)
    w, width = len(columns), page.rect.width
    lo, hi = int(w * (0.5 - NEAR)), int(w * (0.5 + NEAR))
    run, at, start = 0, 0, None
    for x in range(lo, hi + 1):
        if x < hi and columns[x] <= QUIET * h:
            start = x if start is None else start
        elif start is not None:
            run, at = max((run, at), (x - start, start))
            start = None
    left, right = (int(sum(half) >= INKED * h * len(half)) for half in (columns[:lo], columns[hi:]))
    sheet = Sheet(width, left + right, left, right, landscape=page.rect.width > page.rect.height)
    sheet.crossing = int(run < GAP * w)
    sheet.gutter = (at + run / 2) / w * width if run else width / 2
    return sheet


def judge_book(doc) -> list[Sheet]:
    if not any(page.rect.width > page.rect.height for page in doc):
        return [Sheet(page.rect.width) for page in doc]  # nothing to cut: skip the reading
    sheets = []
    for page in doc:
        sheet = judge(_rows(page), page.rect.width, page.rect.height)
        if sheet.landscape and not sheet.lines:
            sheet = judge_image(page)
        sheets.append(sheet)
    spreads = [s for s in sheets if s.spread]
    if spreads and 2 * len(spreads) > sum(s.lines > 0 for s in sheets):
        gutter = statistics.median(s.gutter / s.width for s in spreads)
        for s in sheets:
            if not s.spread and s.lines and not s.crossing and s.landscape:
                s.by_book, s.gutter = True, gutter * s.width
    return sheets


def _half(page, sheet: Sheet, side: int) -> pymupdf.Rect:
    """The left (0) or right (1) half of the page, as a MediaBox (PDF coordinates)."""
    r = page.rect
    clip = pymupdf.Rect(r.x0, r.y0, sheet.gutter, r.y1)
    if side:
        clip = pymupdf.Rect(sheet.gutter, r.y0, r.x1, r.y1)
    box = clip * page.derotation_matrix * ~page.transformation_matrix
    return box.normalize()


def split(src: Path, out: Path, sheets: list[Sheet]) -> list[dict]:
    """Write ``out``: ``src`` with its ``sheets`` (``judge_book``'s) that are cut in two."""
    with open_pdf(src) as doc:
        for k in reversed(range(doc.page_count)):  # from the end: a copy moves what follows
            if sheets[k].cut:
                boxes = [_half(doc[k], sheets[k], side) for side in (0, 1)]
                # A full copy: a page listed twice by select() is one object, one MediaBox.
                doc.fullcopy_page(k, k + 1 if k + 1 < doc.page_count else -1)
                for side in (0, 1):
                    doc[k + side].set_mediabox(boxes[side])
        tmp = out.with_name(f".{out.name}.tmp")
        doc.save(tmp, garbage=3, deflate=True)
    os.replace(tmp, out)
    pages = [
        {"page": 0, "sheet": n + 1, "side": side}
        for n, sheet in enumerate(sheets)
        for side in (("left", "right") if sheet.cut else ("whole",))
    ]
    for number, entry in enumerate(pages, 1):
        entry["page"] = number
    tmp = out.with_name(f".{out.name}.pages.tmp")
    tmp.write_text(json.dumps(pages, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, out.with_suffix(".pages.json"))
    return pages

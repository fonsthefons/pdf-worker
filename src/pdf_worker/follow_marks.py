"""``convert`` following a book's marks (docs/marks-plan.md, Phase 2): the kind its marks
and style sheet (``style_sheet.classify``) give each line, for the pipeline's seams.

A line takes a kind when a mark covers it or the style sheet matched it; conflicts and
lines no example agrees with are left to today's rules (``None``). A scan's Paddle block
takes the kind most of its lines (more than half) have.
"""

import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable

import pymupdf

from pdf_worker import marks
from pdf_worker.layout import page_lines
from pdf_worker.marks import FURNITURE_KINDS
from pdf_worker.style_sheet import PLACE_KINDS, Label, PageLines, classify, key, measure

TITLE_LABELS = ("doc_title", "paragraph_title")  # the layout model's headings


def load(pdf_path) -> marks.Marks | None:
    """The book's marks file (``marks.default_marks_path``), if there is one; made on
    another PDF: a ``marks.MarksError``."""
    path = marks.default_marks_path(pdf_path)
    return marks.load(path, pdf_path) if path.exists() else None


def _kind(label: Label) -> str | None:
    """The line's kind (a heading's with its level: "heading 2"), if marked or matched; a
    match placed or sized like none of its examples (``odd``: doubtful in the review) is
    left to today's rules, as a conflict is."""
    if label.sure == "marked" or (label.sure == "matched" and not label.odd):
        return key(label.kind, label.level)
    return None


def _scan_kind(label: Label) -> str | None:
    """On a scan the style sheet matches by estimated sizes (Phase 1: body blocks 0.8 to
    1.3 of the body size, beyond its tolerance), and Paddle's layout model already labels
    every block: a match is followed there only for kinds known by their place (the page's
    edges, its margin) and headings. A mark is always followed."""
    if label.sure == "matched" and label.kind not in (*FURNITURE_KINDS, *PLACE_KINDS, "heading"):
        return None
    return _kind(label)


def _placer(
    found: Iterable[tuple[str | None, float | None]], tol: float
) -> Callable[[float], int] | None:
    """How a heading by today's rules is placed among the marked levels, from the (kind,
    size) of the book's lines: at the level whose lines' median size is nearest its size;
    of the levels about as near (within ``tol``, the style sheet's size tolerance: levels
    set in one size), the one with the most lines. None: no heading level marked."""
    by_level = defaultdict(list)
    for kind, size in found:
        if kind and kind.startswith("heading ") and size:
            by_level[int(kind.split()[1])].append(size)
    medians = {level: statistics.median(sizes) for level, sizes in by_level.items()}

    def place(size: float) -> int:
        best = min(abs(median - size) for median in medians.values())
        near = [level for level, median in medians.items() if abs(median - size) <= best + tol]
        return max(near, key=lambda level: (len(by_level[level]), -level))

    return place if medians else None


def text_kinds(
    doc: pymupdf.Document, book: marks.Marks
) -> tuple[dict[int, list[str | None]], dict[int, list[tuple]], dict[float, int]]:
    """Page index -> its lines' kinds (in ``page_lines`` order: call after ``convert``'s
    preparation of the text layer), page index -> the boxes of its note numbers
    (style-sheet matches and the spans of ``note-ref`` marks), and each size in the book
    (to 0.1 pt) -> the marked level a heading by today's rules of that size takes
    (``DocumentProfile.rule_levels``)."""
    # shortcut: holds every page's lines to measure the book (as the marking page does);
    # upgrade to a streaming measure if marked books get too big for memory.
    pages = [PageLines(page.rect.width, page.rect.height, page_lines(page)) for page in doc]
    measures = measure(pages)
    found = classify(pages, book, measures)
    kinds = {
        index: [_kind(label) for label in labels]
        for index, labels in enumerate(found.labels)
        if any(_kind(label) for label in labels)
    }
    place = _placer(
        (
            (kind, line.size)
            for index, labels in kinds.items()
            for line, kind in zip(pages[index].lines, labels, strict=True)
        ),
        measures.size_tol * measures.body,
    )
    sizes = {round(line.size, 1) for page in pages for line in page.lines if line.size}
    levels = {size: place(size) for size in sizes} if place else {}
    refs: defaultdict[int, list[tuple]] = defaultdict(list)
    for index, boxes in enumerate(found.refs):
        refs[index] += boxes
    for mark in book.marks:
        if mark.kind != "note-ref" or mark.page > len(pages):
            continue
        refs[mark.page - 1] += [
            tuple(span["bbox"])
            for line in pages[mark.page - 1].lines
            for span in line.spans
            if re.fullmatch(r"\s*\d{1,3}\s*", span["text"])
            and marks.inside(_middle(span["bbox"]), mark.shape)
        ]
    return kinds, {index: boxes for index, boxes in refs.items() if boxes}, levels


def _middle(box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def paddle_kinds(
    doc: pymupdf.Document, rows: list[dict], book: marks.Marks
) -> dict[int, dict[int, str]]:
    """Page index -> {block index in its row: kind} for a book built from Paddle's
    ``rows``; the lines are the marking page's (``marking.paddle_view``). A block Paddle
    took for a title that has no kind gets "level N": its place among the marked heading
    levels by its size (``_placer``; its lines' median estimated size), should today's
    rules keep it as a heading."""
    from pdf_worker.marking import paddle_view  # here: marking -> paddle_ocr -> convert

    by_page = {row["page"]: row for row in rows}
    pages = [
        PageLines(page.rect.width, page.rect.height, paddle_view(page, by_page.get(i))[0])
        for i, page in enumerate(doc)
    ]
    measures = measure(pages)
    found = classify(pages, book, measures)
    kinds = {}
    sizes: defaultdict[tuple[int, int], list[float]] = defaultdict(list)
    for index, (page, labels) in enumerate(zip(pages, found.labels, strict=True)):
        lines: Counter[int] = Counter()
        counts: defaultdict[int, Counter[str]] = defaultdict(Counter)
        for line, label, features in zip(page.lines, labels, measures.features[index], strict=True):
            lines[line.block] += 1
            if features.size:
                sizes[index, line.block].append(features.size)
            if kind := _scan_kind(label):
                counts[line.block][kind] += 1
        # More than half: a round share, chosen before the results.
        kinds[index] = {
            block: kind
            for block, count in counts.items()
            for kind, n in count.most_common(1)
            if 2 * n > lines[block]
        }
    size_of = {block: statistics.median(found) for block, found in sizes.items()}
    place = _placer(
        (
            (kind, size_of.get((index, block)))
            for index, page in kinds.items()
            for block, kind in page.items()
        ),
        measures.size_tol,
    )
    for index, page in kinds.items():
        for block, paddle in enumerate(by_page.get(index, {}).get("blocks", [])):
            size = size_of.get((index, block))
            if place and size and block not in page and paddle.get("label") in TITLE_LABELS:
                page[block] = f"level {place(size)}"
    return kinds

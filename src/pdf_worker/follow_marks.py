"""``convert`` following a book's marks (docs/marks-plan.md, Phase 2): the kind its marks
and style sheet (``style_sheet.classify``) give each line, for the pipeline's seams.

A line takes a kind when a mark covers it or the style sheet matched it; conflicts and
lines no example agrees with are left to today's rules (``None``). A scan's Paddle block
takes the kind most of its lines (more than half) have.
"""

import re
from collections import Counter, defaultdict

import pymupdf

from pdf_worker import marks
from pdf_worker.layout import page_lines
from pdf_worker.marks import FURNITURE_KINDS
from pdf_worker.style_sheet import PLACE_KINDS, Label, PageLines, classify


def load(pdf_path) -> marks.Marks | None:
    """The book's marks file (``marks.default_marks_path``), if there is one; made on
    another PDF: a ``marks.MarksError``."""
    path = marks.default_marks_path(pdf_path)
    return marks.load(path, pdf_path) if path.exists() else None


def _kind(label: Label) -> str | None:
    return label.kind if label.sure in ("marked", "matched") else None


def _scan_kind(label: Label) -> str | None:
    """On a scan the style sheet matches by estimated sizes (Phase 1: body blocks 0.8 to
    1.3 of the body size, beyond its tolerance), and Paddle's layout model already labels
    every block: a match is followed there only for kinds known by their place (the page's
    edges, its margin). A mark is always followed."""
    if label.sure == "matched" and label.kind not in (*FURNITURE_KINDS, *PLACE_KINDS):
        return None
    return _kind(label)


def text_kinds(
    doc: pymupdf.Document, book: marks.Marks
) -> tuple[dict[int, list[str | None]], dict[int, list[tuple]]]:
    """Page index -> its lines' kinds (in ``page_lines`` order: call after ``convert``'s
    preparation of the text layer), and page index -> the boxes of its note numbers
    (style-sheet matches and the spans of ``note-ref`` marks)."""
    # shortcut: holds every page's lines to measure the book (as the marking page does);
    # upgrade to a streaming measure if marked books get too big for memory.
    pages = [PageLines(page.rect.width, page.rect.height, page_lines(page)) for page in doc]
    found = classify(pages, book)
    kinds = {
        index: [_kind(label) for label in labels]
        for index, labels in enumerate(found.labels)
        if any(_kind(label) for label in labels)
    }
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
    return kinds, {index: boxes for index, boxes in refs.items() if boxes}


def _middle(box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def paddle_kinds(
    doc: pymupdf.Document, rows: list[dict], book: marks.Marks
) -> dict[int, dict[int, str]]:
    """Page index -> {block index in its row: kind} for a book built from Paddle's
    ``rows``; the lines are the marking page's (``marking.paddle_view``)."""
    from pdf_worker.marking import paddle_view  # here: marking -> paddle_ocr -> convert

    by_page = {row["page"]: row for row in rows}
    pages = [
        PageLines(page.rect.width, page.rect.height, paddle_view(page, by_page.get(i))[0])
        for i, page in enumerate(doc)
    ]
    found = classify(pages, book)
    kinds = {}
    for index, (page, labels) in enumerate(zip(pages, found.labels, strict=True)):
        lines: Counter[int] = Counter()
        counts: defaultdict[int, Counter[str]] = defaultdict(Counter)
        for line, label in zip(page.lines, labels, strict=True):
            lines[line.block] += 1
            if kind := _scan_kind(label):
                counts[line.block][kind] += 1
        # More than half: a round share, chosen before the results.
        kinds[index] = {
            block: kind
            for block, count in counts.items()
            for kind, n in count.most_common(1)
            if 2 * n > lines[block]
        }
    return kinds

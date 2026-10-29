"""A page as the pipeline sees it: each line with its part (furniture / footnote / body),
the layout model's label for it (``paddle_ocr.layout_pages``; "-" when none covers it),
its top as a share of the page height, its size and its text.

Usage: .venv/bin/python tools/page_parts.py PDF PAGE [--png OUT.png]

``--png`` draws the model's boxes on the page, a colour per label, each named at its
corner: what the model sees. The model runs once per PDF (cached, by default in the
repo's scratch/paddle-home, like the tests); without the Paddle environment there are no
labels.
"""

import argparse
import itertools
import os
from pathlib import Path

from pdf_worker import bilingual, font_sizes, glued_refs
from pdf_worker.document import open_pdf
from pdf_worker.footnotes import layout_page
from pdf_worker.layout import analyze_document, box_labels, page_lines
from pdf_worker.ocr import OcrError
from pdf_worker.paddle_ocr import layout_pages

os.environ.setdefault(
    "PDF_WORKER_PADDLE_CACHE", str(Path(__file__).resolve().parents[1] / "scratch" / "paddle-home")
)

COLOURS = [(0.9, 0.1, 0.1), (0.1, 0.5, 0.9), (0.1, 0.7, 0.2), (0.9, 0.5, 0), (0.6, 0.2, 0.8)]
COLOURS += [(0, 0.6, 0.6), (0.8, 0.2, 0.6), (0.5, 0.4, 0.1), (0.3, 0.3, 0.3)]

parser = argparse.ArgumentParser()
parser.add_argument("pdf")
parser.add_argument("page", type=int, help="1-based")
parser.add_argument("--png", help="draw the model's boxes on the page into this file")
args = parser.parse_args()

try:
    rows = layout_pages(args.pdf)
except OcrError as exc:
    print(f"(no layout model: {exc})")
    rows = {}
with open_pdf(args.pdf) as doc:
    index = args.page - 1
    # convert_pdf's preparation, but for re-reading garbled words (OCR).
    font_sizes.mark_misreporting(doc)
    glued_refs.mark_glued_refs(doc, skip=bilingual.facing_pages(doc)[1])
    profile = analyze_document(doc)
    previous = None  # a note running on from the page before, as the pipeline reads it
    for before in range(index):
        previous = layout_page(doc.load_page(before), before, profile, previous).trailing_label
    page = doc.load_page(index)
    layout = layout_page(page, index, profile, previous)
    parts = {(line.bbox, line.text): "furniture" for line in layout.furniture}
    parts.update({(bl.line.bbox, bl.line.text): "body" for bl in layout.lines})
    lines = page_lines(page)
    row = rows.get(index)
    labels = box_labels(page, row, lines) if row else [""] * len(lines)
    # On a page of chapter endnotes the lines the body leaves are notes' hung numbers.
    rest = "endnote" if index in profile.chapter_notes.note_pages else "footnote"
    for line, label in zip(lines, labels, strict=True):
        part = parts.get((line.bbox, line.text), rest)
        print(
            f"{part:9} {label or '-':17} {line.top / page.rect.height:5.1%} s{line.size:5.1f}",
            repr(line.text),
        )
    if args.png and row:
        scale = page.rect.width / row["width"]
        colours = dict(zip(sorted({b["label"] for b in row["blocks"]}), itertools.cycle(COLOURS)))
        for block in row["blocks"]:
            x0, y0, x1, y1 = (c * scale for c in block["bbox"])
            colour = colours[block["label"]]
            page.draw_rect((x0, y0, x1, y1), color=colour, width=1)
            page.insert_text((x0 + 1, y0 + 6), block["label"], fontsize=6, color=colour)
        page.get_pixmap(dpi=150, annots=False).save(args.png)
        print(f"boxes drawn in {args.png}")

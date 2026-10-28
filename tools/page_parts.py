"""A page as the pipeline sees it: each line with its part (furniture / footnote / body),
its top as a share of the page height, its size and its text.

Usage: .venv/bin/python tools/page_parts.py PDF PAGE
"""

import sys

from pdf_worker.document import open_pdf
from pdf_worker.footnotes import layout_page
from pdf_worker.layout import analyze_document, page_lines

with open_pdf(sys.argv[1]) as doc:
    index = int(sys.argv[2]) - 1
    page = doc.load_page(index)
    layout = layout_page(page, index, analyze_document(doc))
    parts = {(line.bbox, line.text): "furniture" for line in layout.furniture}
    parts.update({(bl.line.bbox, bl.line.text): "body" for bl in layout.lines})
    for line in page_lines(page):
        part = parts.get((line.bbox, line.text), "footnote")
        print(f"{part:9} {line.top / page.rect.height:5.1%} s{line.size:5.1f}", repr(line.text))

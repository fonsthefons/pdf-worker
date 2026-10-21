"""The lines the pipeline sees on one page (``layout.page_lines``), with geometry.

Usage: .venv/bin/python tools/page_lines.py PDF PAGE [MAX_LINES]
"""

import sys

import pymupdf

from pdf_worker.layout import page_lines

with pymupdf.open(sys.argv[1]) as doc:
    lines = page_lines(doc[int(sys.argv[2]) - 1])
    for i, line in enumerate(lines[: int(sys.argv[3]) if len(sys.argv) > 3 else None]):
        print(
            f"{i:3} x{line.x0:6.1f}-{line.x1:6.1f} base{line.baseline:7.1f} s{line.size:5.1f}",
            repr(line.text[:70]),
        )

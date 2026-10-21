"""Render part of a PDF page to a PNG (300 dpi), to look at what the scan prints.

Usage: .venv/bin/python tools/render_clip.py PDF PAGE X0 Y0 X1 Y1 OUT.png
"""

import sys

import pymupdf

with pymupdf.open(sys.argv[1]) as doc:
    page = doc[int(sys.argv[2]) - 1]
    rect = pymupdf.Rect(*(float(v) for v in sys.argv[3:7]))
    page.get_pixmap(clip=rect, dpi=300).save(sys.argv[7])

"""Find the pages of a PDF containing a phrase and show the lines around it.

Usage: .venv/bin/python tools/find_text.py PDF PHRASE
"""

import sys

import pymupdf

with pymupdf.open(sys.argv[1]) as doc:
    for page in doc:
        lines = [ln for ln in page.get_text().splitlines() if ln.strip()]
        for i, line in enumerate(lines):
            if sys.argv[2] in line:
                print(f"p{page.number + 1} line {i}/{len(lines)}:", lines[max(0, i - 2) : i + 3])

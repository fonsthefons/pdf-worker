"""Words of an outline section against the words of its summary .md: argv BLOCKS SECTION MD."""

import sys
from pathlib import Path

from pdf_worker import summarize as summ

blocks, section, md = sys.argv[1:4]
outline = summ.load_outline(blocks)
for node in summ.select(outline, [section]):
    print(f"{node.number} {node.title}: {node.words} words")
    for child in node.children:
        print(f"   {child.number} {child.title}: {child.words}")
    src = node.words
text = Path(md).read_text(encoding="utf-8")
out = len(text.split())
print(f"summary md: {out} words = {100 * out / src:.0f}%")

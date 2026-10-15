"""A book without its notes: footnotes, endnotes and their references all left out.

Margin references ("22b") are not notes and stay. Headings followed by nothing but
notes (an endnotes chapter, "NOTAS", and its per-chapter subheadings) go with them.
"""

from collections.abc import Iterable, Iterator
from dataclasses import replace

from pdf_worker.structure import REF_RE, Block, Gloss, Heading, Note, Paragraph, Table


def drop_notes(blocks: Iterable[Block]) -> Iterator[Block]:
    # Headings in a row ("Notes", "Chapter One") wait for what follows: text shows them,
    # notes then another heading (or the end) drop them.
    held: list[Block] = []
    held_notes = False
    for block in blocks:
        if isinstance(block, Note):
            held_notes = held_notes or bool(held)
            continue
        if isinstance(block, Heading):
            if held_notes:
                held, held_notes = [], False
            held.append(_strip(block))
            continue
        yield from held
        held, held_notes = [], False
        yield _strip(block)
    if not held_notes:
        yield from held


def _strip(block: Block) -> Block:
    if isinstance(block, Heading | Paragraph):
        return replace(block, text=REF_RE.sub("", block.text))
    if isinstance(block, Gloss):
        return replace(block, lines=tuple(REF_RE.sub("", line) for line in block.lines))
    if isinstance(block, Table):
        rows = tuple(tuple(REF_RE.sub("", cell) for cell in row) for row in block.rows)
        return replace(block, rows=rows)
    return block

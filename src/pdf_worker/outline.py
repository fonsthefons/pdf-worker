"""Heading levels from the whole book, in two passes over its saved blocks.

``collect`` reads the headings only (pass 1) and returns their new levels; ``apply``
streams the blocks again with those levels (pass 2). A heading the marks or the tags
gave a level keeps it. With bookmarks (``doc.get_toc()``), a heading a bookmark names
(in order, by its words, on the bookmark's page or later) takes the bookmark's level,
and one none names the level of the named heading before it, moved by the difference of
their size levels (headings before the first named one keep theirs). Without bookmarks
at two levels or more that name headings, the book's numbering ranks its numbered and
division headings (``heading_levels.rank_headings``; the others go to the top), but only
when type size gives no hierarchy (every heading after the front matter in one size
level) and no heading has marks or tags. The levels set here then close their gaps
(3/5/6 -> 1/2/3), unless the book has marks.
"""

from collections.abc import Iterable, Iterator
from dataclasses import replace

from pdf_worker.epub import _entry_key, _names
from pdf_worker.heading_levels import heading_key, rank_headings
from pdf_worker.inline import plain
from pdf_worker.structure import Block, Heading

KEPT = ("marks", "tags")
_MAX_LEVEL = 6


def collect(blocks: Iterable[Block], bookmarks: list, marked: bool = False) -> dict[int, int]:
    """Heading number (in book order, from 0) -> its new level. ``bookmarks``: (level,
    title, page) rows as ``doc.get_toc()`` gives them; ``marked``: the book has marks."""
    headings = [b for b in blocks if isinstance(b, Heading)]
    # Bookmarks that name no heading, or all at one level, say nothing of the hierarchy.
    levels = _from_bookmarks(headings, bookmarks) or _ranked(headings)
    levels = {k: v for k, v in levels.items() if headings[k].source not in KEPT}
    if levels and not marked:
        closed = {level: n for n, level in enumerate(sorted(set(levels.values())), 1)}
        levels = {k: closed[v] for k, v in levels.items()}
    return levels


def _from_bookmarks(headings: list[Heading], bookmarks: list) -> dict[int, int]:
    """Each heading a bookmark names (in order, on the bookmark's page or later) at its
    level; {} when none is named or all named ones are at one level."""
    words = [_entry_key(plain(h.text)) for h in headings]
    levels: dict[int, int] = {}
    start = 0
    for level, title, page, *_ in bookmarks:
        key = _entry_key(title)
        found = next(
            (
                k
                for k in range(start, len(words))
                if headings[k].page >= page - 1 and _names(key, words[k])  # page: from 1
            ),
            None,
        )
        if found is not None:
            levels[found], start = min(level, _MAX_LEVEL), found + 1
    if len(set(levels.values())) < 2:
        return {}
    # An unmatched heading: the level of the matched one before it (a marks or tags
    # heading's own), moved by the difference of their size levels.
    anchor = None
    for k, heading in enumerate(headings):
        if k in levels:
            anchor = (heading.level if heading.source in KEPT else levels[k]) - heading.level
        elif anchor is not None:
            levels[k] = max(1, min(heading.level + anchor, _MAX_LEVEL))
    return levels


def _ranked(headings: list[Heading]) -> dict[int, int]:
    """The headings ranked by their numbering when type size gives no hierarchy (every
    heading from the first numbered or division one on in one size level), in a book
    without marks or tags headings after its front matter (a tagged cover is fine); else
    {}. Only numbered and division headings are ranked; the others (front matter,
    BIBLIOGRAFÍA) take the top level."""
    keys = [heading_key(h) for h in headings]
    numbered = [k for k, key in enumerate(keys) if key[0] or key[1]]
    if not numbered or len({h.level for h in headings[numbered[0] :]}) != 1:
        return {}
    if any(h.source in KEPT for h in headings[numbered[0] :]):
        return {}
    ranked = rank_headings(headings[k] for k in numbered)
    levels = {k: h.level for k, h in zip(numbered, ranked, strict=True)}
    top = min(levels.values())
    return {k: levels.get(k, top) for k in range(len(headings))}


def apply(blocks: Iterable[Block], outline: dict[int, int]) -> Iterator[Block]:
    """``blocks`` with the headings' levels from ``collect``."""
    number = 0
    for block in blocks:
        if isinstance(block, Heading):
            if number in outline:
                block = replace(block, level=outline[number])
            number += 1
        yield block

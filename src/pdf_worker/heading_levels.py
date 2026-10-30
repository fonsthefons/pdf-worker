"""Heading levels from the book's own numbering.

A book nests its divisions in a fixed order, and each kind of heading keeps its rank
throughout the book. A heading's kind (``heading_key``) is the division word it starts
with, else its numbering style and whether it is in capitals; then its type size (the
level ``structure`` gave it from the book's heading sizes). Larger type ranks above
smaller; kinds set in the same size rank in the order they first appear (the book opens
a division before its subdivisions), except that a division word ranked above another
goes above it; a division word keeps the rank it first had in any type size.

Not used by the pipeline yet (quality plan, Phase 3 in PROGRESS.md): it raised level
agreement on the checked headings pages (62.8% -> 66.3%) but lowered it against the
reference EPUBs, which tag most headings at one level.
"""

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import replace

from pdf_worker.inline import plain
from pdf_worker.structure import REF_RE, Block, Heading

# Division words, highest rank first; the words of one rank are one division in Spanish
# and English.
DIVISIONS = (
    ("parte", "part"),
    ("libro", "book"),
    ("capitulo", "chapter"),
    ("seccion", "section"),
    ("leccion", "lesson"),
    ("tema",),
    ("articulo", "article"),
    ("cuestion", "question"),
)
_RANK = {word: rank for rank, words in enumerate(DIVISIONS) for word in words}
_MAX_LEVEL = 6
_STYLES = (
    ("decimal", re.compile(r"\d+(?:\.\d+)+\.?(?:\s|$)")),  # "4.2"
    ("arabic", re.compile(r"\d+[.)]?(?:\s|$)")),  # "4.", "4"
    ("roman", re.compile(r"[IVXLC]+[.)]?(?:\s|$)")),  # "IV."
    ("letter", re.compile(r"[a-zA-Z][.)](?:\s|$)")),  # "a)"
)


def _division(text: str) -> str:
    """The division word ``text`` starts with (its first name in ``DIVISIONS``), or ""."""
    first = text.split(maxsplit=1)[0] if text.split() else ""
    word = unicodedata.normalize("NFKD", first.lower())
    word = "".join(c for c in word if c.isalpha())
    for form in (word, word[:-1], word[:-2]):  # "Capítulos", "Lecciones"
        if form in _RANK:
            return DIVISIONS[_RANK[form]][0]
    return ""


def heading_key(heading: Heading) -> tuple[str, str, bool, int]:
    """(division word, numbering style, in capitals, size level)."""
    text = REF_RE.sub("", plain(heading.text)).strip()  # a note reference: "...FE[^p24-18]"
    word = _division(text)
    if word:  # the word names the division, whatever its case ("CAPÍTULO I", "Capítulo II")
        return word, "", False, heading.level
    style = next((name for name, rx in _STYLES if rx.match(text)), "")
    return word, style, text.isupper(), heading.level


def rank_headings(blocks: Iterable[Block]) -> Iterator[Block]:
    """Give each heading its kind's level. Front matter (headings before the first with
    a division word or a number) keeps its size levels and sets none."""
    kinds: dict[int, list[tuple]] = {}  # size level -> its keys, highest first
    for block in blocks:
        if not isinstance(block, Heading):
            yield block
            continue
        key = heading_key(block)
        word, style, _, size = key
        if not kinds and not (word or style):
            yield block
            continue
        if word:
            # A division word keeps the rank it first had, whatever its type size here.
            key = next((k for keys in kinds.values() for k in keys if k[0] == word), key)
            size = key[3]
        same_size = kinds.setdefault(size, [])
        if key not in same_size:
            # A new kind goes below the kinds seen in its type size, except a division
            # word ranked above one of theirs, which goes above it.
            # shortcut: headings already written keep their levels when this shifts
            # later kinds down; books open with their highest division, so it is rare.
            above = [
                i for i, k in enumerate(same_size) if word and k[0] and _RANK[word] < _RANK[k[0]]
            ]
            same_size.insert(above[0] if above else len(same_size), key)
        # Larger type ranks above smaller: each size's level, moved down by the extra
        # kinds of the larger sizes.
        extra = sum(len(keys) - 1 for s, keys in kinds.items() if s < size)
        yield replace(block, level=min(size + extra + same_size.index(key), _MAX_LEVEL))

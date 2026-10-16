"""Estimated margin references: labels the scan lost, placed between the ones found.

When "23b" and "23e" were found but 23c and 23d were not, the words between the two
found labels are split evenly over the sections in between and each missing label goes
before the word where its share starts. Labels missing before a section's first found
label or after its last have only one anchor and stay missing. An estimate's label
starts with ``ESTIMATED`` ("~23c"): text and Markdown show it as is, the EPUB, HTML and
PDF writers draw it pink instead of green.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import replace

from pdf_worker.inline import ESTIMATED, MARGIN_REF_RE, margin_ref, plain
from pdf_worker.structure import Block, Heading, Paragraph

_LABEL_RE = re.compile(r"(\d+)([a-e])")
_MAX_MISSING = 10  # more labels than this lost in a row: the anchors are suspect


def estimate_margin_refs(blocks: Iterable[Block]) -> Iterator[Block]:
    """The blocks with estimated labels added; a heading starts a new run of labels."""
    section: list[Block] = []
    for block in blocks:
        if isinstance(block, Heading):
            yield from _estimate(section)
            section = []
            yield block
        else:
            section.append(block)
    yield from _estimate(section)


def _value(label: str) -> int | None:
    match = _LABEL_RE.fullmatch(label)
    return int(match.group(1)) * 5 + "abcde".index(match.group(2)) if match else None


def _estimate(section: list[Block]) -> list[Block]:
    # Every word of the section's paragraphs: (block index, offset in its text), and
    # the found labels' values with the index of the word they stand before.
    words: list[tuple[int, int]] = []
    found: list[tuple[int, int]] = []
    for b, block in enumerate(section):
        if not isinstance(block, Paragraph):
            continue
        for token in re.finditer(r"\S+", block.text):
            for label in MARGIN_REF_RE.findall(token.group()):
                if (value := _value(label)) is not None:
                    found.append((value, len(words)))
            if plain(token.group()).strip():
                words.append((b, token.start()))
    inserts: dict[int, list[tuple[int, str]]] = {}
    for (v1, w1), (v2, w2) in zip(found, found[1:], strict=False):
        missing = v2 - v1 - 1
        if not 0 < missing <= _MAX_MISSING or w2 <= w1:
            continue
        for k in range(1, missing + 1):
            w = w1 + round((w2 - w1) * k / (missing + 1))
            if w1 < w < w2:
                b, at = words[w]
                label = f"{(v1 + k) // 5}{'abcde'[(v1 + k) % 5]}"
                inserts.setdefault(b, []).append((at, margin_ref(ESTIMATED + label)))
    out = list(section)
    for b, marks in inserts.items():
        text = out[b].text
        for at, mark in sorted(marks, reverse=True):
            text = text[:at] + mark + text[at:]
        out[b] = replace(out[b], text=text)
    return out

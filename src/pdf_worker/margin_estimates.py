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
from itertools import pairwise

from pdf_worker.inline import ESTIMATED, MARGIN_REF_RE, margin_ref, plain
from pdf_worker.margin_refs import OCR_DIGITS
from pdf_worker.structure import Block, Heading, Paragraph

_LABEL_RE = re.compile(r"(\d+)([a-e])")
_MAX_MISSING = 10  # more labels than this lost in a row: the anchors are suspect
# A misread bracketed reference: a few signs, perhaps split by a space, with at least
# one bracket ("[Iga]", "b8e]", "[2 5c]", "[24_.e]"); the space after it goes, as
# ``margin_refs.bracketed``.
_MISREAD_RE = re.compile(
    r"\[\s*([^\s\[\]]{1,5}(?: [^\s\[\]]{1,3}(?=\s*\]))?)\s*\]?\s*|(?<![^\s(])([^\s\[\]]{2,4})\]\s*"
)


def estimate_margin_refs(blocks: Iterable[Block]) -> Iterator[Block]:
    """The blocks with estimated labels added; a heading starts a new run of labels."""
    return _by_section(blocks, _estimate)


def recover_margin_refs(blocks: Iterable[Block]) -> Iterator[Block]:
    """The blocks with references printed in brackets that OCR misread past
    ``margin_refs.bracketed`` ("b8e]", "[Iga]") read as labels missing between two found
    ones: between 18d and 19c, a misreading one sign off 18e, 19a or 19b takes that
    label, in order. Runs before any estimate, which only fills what is still missing."""
    return _by_section(blocks, _recover)


def _by_section(blocks: Iterable[Block], fix) -> Iterator[Block]:
    section: list[Block] = []
    for block in blocks:
        if isinstance(block, Heading):
            yield from fix(section)
            section = []
            yield block
        else:
            section.append(block)
    yield from fix(section)


def label_value(label: str) -> int | None:
    """``"22b"`` -> 111: consecutive labels have consecutive values."""
    match = _LABEL_RE.fullmatch(label)
    return int(match.group(1)) * 5 + "abcde".index(match.group(2)) if match else None


def value_label(value: int) -> str:
    return f"{value // 5}{'abcde'[value % 5]}"


def _recover(section: list[Block]) -> list[Block]:
    found = []  # (value, block, start, end) of each label found
    for b, block in enumerate(section):
        if isinstance(block, Paragraph):
            for m in MARGIN_REF_RE.finditer(block.text):
                if (value := label_value(m.group(1))) is not None:
                    found.append((value, b, m.start(), m.end()))
    edits: dict[int, list[tuple[int, int, str]]] = {}
    for (v1, b1, _, at1), (v2, b2, at2, _) in pairwise(found):
        if not 0 < v2 - v1 - 1 <= _MAX_MISSING:
            continue
        last = v1
        for b in range(b1, b2 + 1):
            if not isinstance(section[b], Paragraph):
                continue
            text = section[b].text
            start, end = at1 if b == b1 else 0, at2 if b == b2 else len(text)
            for m in _MISREAD_RE.finditer(text, start, end):
                read = (m.group(1) or m.group(2)).translate(OCR_DIGITS)
                value = next((v for v in range(last + 1, v2) if _near(read, value_label(v))), None)
                if value is not None:
                    last = value
                    edits.setdefault(b, []).append((m.start(), m.end(), value_label(value)))
    out = list(section)
    for b, marks in edits.items():
        text = out[b].text
        for start, end, label in reversed(marks):
            text = text[:start] + margin_ref(label) + text[end:]
        out[b] = replace(out[b], text=text)
    return out


def _near(read: str, label: str) -> bool:
    """ "1ga" for 19a, "b8e" for 18e, "22h" for 22b: one sign off; "2 5c" for 25c and
    "24_.e" for 24e: the label, once spaces and stray marks are dropped."""
    read = read.replace(" ", "")
    if read[-1:] in ("l", "I", "|", "1") and read[-2:-1].isalpha() and _near(read[:-1], label):
        return True  # "[23el": the closing bracket read as "l" (as "1" by ``OCR_DIGITS``)
    if re.sub(r"[^\w]|_", "", read) == label:
        return True
    return len(read) == len(label) and sum(a != b for a, b in zip(read, label, strict=True)) <= 1


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
                if (value := label_value(label)) is not None:
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
                label = ESTIMATED + value_label(v1 + k)
                inserts.setdefault(b, []).append((at, margin_ref(label)))
    out = list(section)
    for b, marks in inserts.items():
        text = out[b].text
        for at, mark in sorted(marks, reverse=True):
            text = text[:at] + mark + text[at:]
        out[b] = replace(out[b], text=text)
    return out

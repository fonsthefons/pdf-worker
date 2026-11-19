"""A tagged PDF's structure tree: which lines make one paragraph (P), list item (LI, its
Lbl and LBody) or heading (H, H1-H6). ``footnotes.layout_page`` adds them to the rules and
the layout model. Lines outside the tree are left to the rules: PyMuPDF shows artifacts
and an element's lines on the page after its own (Chrome's print) alike.

PyMuPDF hands the tree over with the text (``TEXT_COLLECT_STRUCTURE``: nested blocks of
type 2 with their ``std`` role, down to ordinary text blocks), so no content stream or
MCID parsing is needed.
"""

import itertools
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace

import pymupdf

_FLAGS = pymupdf.TEXTFLAGS_DICT | pymupdf.TEXT_COLLECT_STRUCTURE
# shortcut: a bare H counts as H1; give it its Sect depth if a book nests bare Hs.
_HEADINGS = {"H": "h1", **{f"H{n}": f"h{n}" for n in range(1, 7)}}
# The tags are sound when this share of a page's text in the tree is in P/LI/H elements...
_PAGE_SHARE = 0.9
# ... on this share of the pages with text; else the whole book is left to the rules.
_BOOK_SHARE = 0.8
# A page with this many P elements, 90% of them one line each, tags lines, not paragraphs.
_MANY_PS = 15


@dataclass(frozen=True)
class TagBox:
    """A text line of the structure tree, and the element it is in."""

    bbox: tuple[float, float, float, float]
    # "p", "li", "h1".."h6"; "": in the tree but in none of those (a table cell): the rules.
    kind: str
    element: int  # one per P/LI/H element in the book (two lines of one LI share it); -1
    depth: int = 0  # the lists (L) it is in
    label: str | None = None  # its list item's printed label (Lbl), never renumbered


def read_tags(doc: pymupdf.Document) -> dict[int, list[TagBox]] | None:
    """Sound page's index -> the lines of its structure tree; None when the PDF has no
    tree or an unsound one (``_PAGE_SHARE``, ``_MANY_PS``, ``_BOOK_SHARE``)."""
    if not doc.is_pdf or doc.xref_get_key(doc.pdf_catalog(), "StructTreeRoot")[0] == "null":
        return None
    ids = itertools.count()
    tags: dict[int, list[TagBox]] = {}
    text_pages = sound_pages = 0
    for page in doc:
        boxes: list[TagBox] = []
        chars = [0, 0, 0]  # in P/LI/H elements, in the tree, outside it
        for block in page.get_text("dict", flags=_FLAGS)["blocks"]:
            if block["type"] == 2:
                boxes.extend(_walk(block, None, 0, ids, chars))
            elif block["type"] == 0:
                chars[2] += sum(_inked(line) for line in block["lines"])
        if chars[1] or chars[2]:
            text_pages += 1
            p_lines = Counter(box.element for box in boxes if box.kind == "p")
            sound = chars[1] > 0 and chars[0] >= _PAGE_SHARE * chars[1]
            # Some exports tag each printed line as a P: nearly all one-line Ps on a page
            # with many of them (a page of text, not a short list or poem) is unsound.
            if len(p_lines) >= _MANY_PS:
                sound = sound and sum(n == 1 for n in p_lines.values()) < 0.9 * len(p_lines)
            if sound:
                sound_pages += 1
                tags[page.number] = boxes
    if not text_pages or sound_pages < _BOOK_SHARE * text_pages:
        return None
    return tags


def _walk(
    block: dict, element: TagBox | None, depth: int, ids: Iterator[int], chars: list[int]
) -> Iterator[TagBox]:
    if block["type"] == 0:
        for line in block["lines"]:
            inked = _inked(line)
            chars[1] += inked
            bbox = tuple(line["bbox"])
            if element:
                chars[0] += inked
                yield replace(element, bbox=bbox)
            else:
                yield TagBox(bbox, "", -1, depth)
        return
    if block["type"] != 2:
        return
    std = block.get("std") or ""
    children = block.get("blocks") or []
    if std == "Artifact":
        return  # outside the text, as if not in the tree
    if std in _HEADINGS:
        element = TagBox((), _HEADINGS[std], next(ids), depth)
    elif std == "P" and not (element and element.kind == "li"):
        element = TagBox((), "p", next(ids), depth)  # a P in an LI's body is the item's
    elif std == "LI":
        label = next((_text(child) for child in children if child.get("std") == "Lbl"), None)
        element = TagBox((), "li", next(ids), depth, label.strip() if label else None)
    elif std == "L":
        depth += 1
    for child in children:
        yield from _walk(child, element, depth, ids, chars)


def _inked(line: dict) -> int:
    return sum(not c.isspace() for span in line["spans"] for c in span["text"])


def _text(block: dict) -> str:
    if block["type"] == 0:
        return " ".join("".join(s["text"] for s in line["spans"]) for line in block["lines"])
    return "".join(_text(child) for child in block.get("blocks") or [])


def tag_lines(lines: Sequence, tags: Sequence[TagBox]) -> list[TagBox | None]:
    """For each line (anything with a ``bbox``), the tagged line of the element whose
    lines cover more than half of it, else None (outside the tree)."""
    found: list[TagBox | None] = []
    for line in lines:
        x0, y0, x1, y1 = line.bbox
        covered: dict[int, float] = defaultdict(float)
        first: dict[int, TagBox] = {}
        for tag in tags:
            bx0, by0, bx1, by1 = tag.bbox
            area = max(0, min(x1, bx1) - max(x0, bx0)) * max(0, min(y1, by1) - max(y0, by0))
            if area > 0:
                covered[tag.element] += area
                first.setdefault(tag.element, tag)
        best = max(covered, key=covered.__getitem__, default=None)
        half = (x1 - x0) * (y1 - y0) / 2
        found.append(first[best] if best is not None and covered[best] > half else None)
    return found

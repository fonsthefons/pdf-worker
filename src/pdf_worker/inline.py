"""Inline markup carried in block text from the structure pass to the writers.

Besides footnote references (``[^label]``, see ``pdf_worker.structure``), block text may
hold two kinds of markers, delimited by private-use characters so they can't collide
with real text:

* page starts: where a PDF page begins, with its printed page label (for EPUB page
  lists, which give Kindle real page numbers);
* links: text that was a link in the PDF, to a web address or to a place in the book;
* margin references: the section numbers printed beside the text of classical editions
  (Stephanus "22", "b", "c" ...; see ``pdf_worker.margin_refs``). Not footnotes.
* italic and bold: on/off around whole words (``pdf_worker.styles``). Text operations may
  leave them unpaired; writers style each text piece by the state at it, so the output
  stays well-formed.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

# Between the cells of a table row (text pieces that sat side by side on one row).
CELL = ""
_PAGE_OPEN, _PAGE_CLOSE = "", ""
_LINK_OPEN, _LINK_MID, _LINK_CLOSE = "", "", ""
_TOKEN_RE = re.compile("(\\d+)\\|([^]*)|([^]*)|")
PAGE_MARK_RE = re.compile(f"{_PAGE_OPEN}\\d+\\|([^{_PAGE_CLOSE}]*){_PAGE_CLOSE}")
LEADING_PAGE_MARKS_RE = re.compile("^((?:[^]*)+)(.*)$", re.DOTALL)


ITALIC, END_ITALIC, BOLD, END_BOLD = "", "", "", ""
# A line break inside a paragraph (verse); the EPUB writer makes it <br/>.
LINE_BREAK = " "
STYLE_RE = re.compile("[-]")
_STYLE_SPLIT_RE = re.compile("([-])")

MARGIN_REF_RE = re.compile("([^]*)")


# A margin reference's label starting with this was estimated, not found on the page
# (``pdf_worker.margin_estimates``); writers that colour labels draw it pink.
ESTIMATED = "~"


@dataclass(frozen=True)
class MarginRef:
    label: str  # "22a", "22b" ... (raw OCR readings until structure labels them)


@dataclass(frozen=True)
class PageMark:
    index: int  # 0-based PDF page index
    label: str  # printed page number, e.g. "23" or "xii"


@dataclass(frozen=True)
class LinkOpen:
    target: str  # see ``page_target`` / ``uri_target``


@dataclass(frozen=True)
class LinkClose:
    pass


@dataclass(frozen=True)
class Style:
    italic: bool  # else bold
    on: bool


def styled(text: str, italic: bool = False, bold: bool = False) -> str:
    if italic:
        text = ITALIC + text + END_ITALIC
    return BOLD + text + END_BOLD if bold else text


def page_mark(index: int, label: str) -> str:
    return f"{_PAGE_OPEN}{index}|{label.replace(_PAGE_CLOSE, '')}{_PAGE_CLOSE}"


def margin_ref(label: str) -> str:
    return f"{label}"


def link(target: str, text: str) -> str:
    return f"{_LINK_OPEN}{target}{_LINK_MID}{text}{_LINK_CLOSE}"


def page_target(page: int, y: float) -> str:
    """A place in the book: PDF page index and the vertical position on it."""
    return f"p:{page}:{max(0.0, y):.0f}"


def uri_target(uri: str) -> str:
    return "u:" + uri.replace(_LINK_MID, "")


def parse_page_target(target: str) -> tuple[int, float] | None:
    if not target.startswith("p:"):
        return None
    page, y = target[2:].split(":")
    return int(page), float(y)


def pieces(text: str) -> Iterator[str | PageMark | LinkOpen | LinkClose | MarginRef | Style]:
    """Split block text into plain text and markers, in order (cells become spaces)."""
    for i, part in enumerate(_STYLE_SPLIT_RE.split(text)):  # text, style, text, ...
        if i % 2:
            yield Style(part in (ITALIC, END_ITALIC), part in (ITALIC, BOLD))
            continue
        for k, sub in enumerate(MARGIN_REF_RE.split(part)):  # text, label, text, ...
            if k % 2:
                yield MarginRef(sub)
            elif sub:
                yield from _pieces(sub)


def _pieces(text: str) -> Iterator[str | PageMark | LinkOpen | LinkClose]:
    text = text.replace(CELL, " ")
    last = 0
    for match in _TOKEN_RE.finditer(text):
        if match.start() > last:
            yield text[last : match.start()]
        if match.group(1) is not None:
            yield PageMark(int(match.group(1)), match.group(2))
        elif match.group(3) is not None:
            yield LinkOpen(match.group(3))
        else:
            yield LinkClose()
        last = match.end()
    if last < len(text):
        yield text[last:]


def plain(text: str) -> str:
    """The text without page, link, margin-reference and style markers (table cells
    joined by spaces)."""
    text = MARGIN_REF_RE.sub("", _TOKEN_RE.sub("", STYLE_RE.sub("", text)))
    return text.replace(CELL, " ")

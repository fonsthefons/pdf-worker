"""Inline markup carried in block text from the structure pass to the writers.

Besides footnote references (``[^label]``, see ``pdf_worker.structure``), block text may
hold two kinds of markers, delimited by private-use characters so they can't collide
with real text:

* page starts: where a PDF page begins, with its printed page label (for EPUB page
  lists, which give Kindle real page numbers);
* links: text that was a link in the PDF, to a web address or to a place in the book.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

# Between the cells of a table row (text pieces that sat side by side on one row).
CELL = ""
_PAGE_OPEN, _PAGE_CLOSE = "", ""
_LINK_OPEN, _LINK_MID, _LINK_CLOSE = "", "", ""
_TOKEN_RE = re.compile("(\\d+)\\|([^]*)|([^]*)|")
LEADING_PAGE_MARKS_RE = re.compile("^((?:[^]*)+)(.*)$", re.DOTALL)


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


def page_mark(index: int, label: str) -> str:
    return f"{_PAGE_OPEN}{index}|{label.replace(_PAGE_CLOSE, '')}{_PAGE_CLOSE}"


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


def pieces(text: str) -> Iterator[str | PageMark | LinkOpen | LinkClose]:
    """Split block text into plain text and markers, in order (cells become spaces)."""
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
    """The text without page and link markers (table cells joined by spaces)."""
    return _TOKEN_RE.sub("", text).replace(CELL, " ")

"""The book's index as links: printed page numbers become numbered marks.

"Kant, 287s, 298-302, 308; véase también 51" -> "Kant [1] [2] [3]; véase también [1]",
each mark a link to its printed page (the book's page marks give the PDF page). A
reflowed book has other pages, so the printed numbers would only mislead. The link
also names the entry's headword: writers land on the text of that page that has it
(``word_keys``), else on the page start.

Only for formats with links (EPUB, HTML, PDF); text and Markdown keep the numbers.
"""

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import replace

from pdf_worker.inline import BOLD, END_BOLD, END_ITALIC, ITALIC, PageMark, link, pieces, plain
from pdf_worker.structure import Block, Heading, Paragraph

# shortcut: an index runs from its heading to the next heading of the same or higher
# level that isn't an index too; a book with text after an unheaded index loses nothing,
# its numbers stay plain unless they look like page groups.
_INDEX_HEADING_RE = re.compile(r"\s*(?:[íi]ndice|index)\b", re.I)
_S = re.escape(ITALIC + END_ITALIC + BOLD + END_BOLD)
# A page reference: 131, 131s, 131ss, 105-109, 403n, 419*. Not inside a word or "(1736-".
_REF = r"(?<![\w(\-–])\d{1,4}(?:\s?[-–]\s?\d{1,4})?(?:ss|s|n|\*)?(?![\w\-–])"
_GROUP_RE = re.compile(rf"(?:[{_S}]*,\s*)?[{_S}]*{_REF}(?:[{_S}]*\s*,\s*[{_S}]*{_REF})*[{_S}]*")
_FIRST_RE = re.compile(rf"{_REF}")
_STYLES_RE = re.compile(f"[{_S}]")
_WORD_RE = re.compile(r"[^\W\d_]+")
_MIN_WORD, _MAX_WORD = 4, 6  # headword prefixes compared: "Idealismo" ~ "idealista"


def word_key(word: str) -> str:
    """Lower case, no accents: "Tomás" -> "tomas"."""
    decomposed = unicodedata.normalize("NFD", word.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def word_keys(text: str) -> set[str]:
    """The headword keys a page's ``text`` can answer: each word's first 4 to 6 letters."""
    keys = set()
    for word in _WORD_RE.findall(text):
        word = word_key(word)
        keys.update(word[:n] for n in range(_MIN_WORD, min(len(word), _MAX_WORD) + 1))
    return keys


def word_target(page: int, headword: str) -> str:
    """A place on PDF page ``page``: where ``headword`` is, else the page start."""
    return f"w:{page}:{word_key(headword)[:_MAX_WORD]}"


def parse_word_target(target: str) -> tuple[int, str] | None:
    if not target.startswith("w:"):
        return None
    page, key = target[2:].split(":")
    return int(page), key


def link_index(blocks: Iterable[Block]) -> Iterator[Block]:
    pages: dict[str, int] = {}  # printed label -> PDF page index
    level = None  # the index heading's level, while in the index
    for block in blocks:
        if isinstance(block, Heading | Paragraph):
            for piece in pieces(block.text):
                if isinstance(piece, PageMark):
                    pages.setdefault(piece.label, piece.index)
        if isinstance(block, Heading):
            if _INDEX_HEADING_RE.match(plain(block.text)):
                level = block.level
            elif level is not None and block.level <= level:
                level = None
        elif isinstance(block, Paragraph) and level is not None:
            block = replace(block, text=_linked(block.text, pages))
        yield block


def _linked(text: str, pages: dict[str, int]) -> str:
    out, last, headword = [], 0, ""
    for group in _GROUP_RE.finditer(text):
        firsts = [re.match(r"\d+", ref[0])[0] for ref in _FIRST_RE.finditer(group[0])]
        if not all(n in pages for n in firsts):
            continue
        before = text[last : group.start()]
        headword = _headword(plain(before), headword)
        marks = [link(word_target(pages[n], headword), f"[{k}]") for k, n in enumerate(firsts, 1)]
        # Styles in the group stay (an italic number's on/off), after the marks.
        out += [before.rstrip(), " ", " ".join(marks), "".join(_STYLES_RE.findall(group.group()))]
        last = group.end()
    return "".join(out) + text[last:]


def _headword(before: str, current: str) -> str:
    """The entry's headword: a new entry's first word (of 4+ letters if it has one); after
    ";" or ":" a sub-entry, which keeps the entry's ("Belleza; Kant, 189")."""
    if current and before.lstrip()[:1] in (";", ":"):
        return current
    words = _WORD_RE.findall(before)
    return next((w for w in words if len(w) >= _MIN_WORD), words[0] if words else current)

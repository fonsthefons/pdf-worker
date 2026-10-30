"""Last touches to a book's text, the same for every format.

* A space OCR put before punctuation goes: "sí , como" -> "sí, como".
* Typewriter quotes become typographic ones: d'Holbach -> d’Holbach, "la canalla" ->
  “la canalla”.
* Headings that aren't: a copyright line ("© 1960: Frederick Copleston", "Impreso en
  España") becomes small print, and a whole sentence (eight words or more ending in a
  full stop) a paragraph. OCR labels both as titles.
* Heading levels from the book's numbering (``pdf_worker.heading_levels``). Headings
  lose italic and bold.

Runs after the review file is applied (``pdf_worker.fixes``), whose finds are the
OCR's text with its straight quotes.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import replace

from pdf_worker.heading_levels import rank_headings
from pdf_worker.inline import END_BOLD, END_ITALIC, STYLE_RE, plain
from pdf_worker.structure import Block, Gloss, Heading, Note, Paragraph

_APOSTROPHE_RE = re.compile(r"(?<=\w)'(?=\w)")
# A quote opens at the start or after a space, an opening bracket, a dash or a marker
# (``pdf_worker.inline``: private-use characters).
_OPENS = "(?:^|(?<=[\\s(\\[{—–«¿¡-]))"
_OPENS += f"(?<![{END_ITALIC}{END_BOLD}])"  # not after the end of an italic word
_OPEN_DOUBLE_RE = re.compile(_OPENS + '"')
_OPEN_SINGLE_RE = re.compile(_OPENS + "'")
_COPYRIGHT_RE = re.compile(
    r"©|\bisbn\b|\bimpreso en\b|\bprinted in\b|dep[óo]sito legal|derechos reservados"
    r"|all rights reserved",
    re.I,
)
_SENTENCE_WORDS = 8
# OCR reads a wide gap before punctuation as a space ("Claro que sí , como"); a spaced
# ellipsis (". . .") keeps its spaces. French spaces before ; : ? ! (``_FRENCH_SPACE_RE``).
_SPACE_BEFORE_RE = re.compile(r"(?<=[^\s.]) +(?=[,;:)?!]|\.(?! \.))")
_FRENCH_SPACE_RE = re.compile(r"(?<=[^\s.]) +(?=[,)]|\.(?! \.))")


def curl_quotes(text: str) -> str:
    # shortcut: a quote inside a link's web address is curled too; none seen in books.
    text = _APOSTROPHE_RE.sub("’", text)
    text = _OPEN_DOUBLE_RE.sub("“", text).replace('"', "”")
    return _OPEN_SINGLE_RE.sub("‘", text).replace("'", "’")


def tidy(blocks: Iterable[Block], language: str = "") -> Iterator[Block]:
    space_re = _FRENCH_SPACE_RE if language == "fr" else _SPACE_BEFORE_RE
    return rank_headings(_tidy(blocks, space_re))


def _tidy(blocks: Iterable[Block], space_re: re.Pattern) -> Iterator[Block]:
    def touch(text: str) -> str:
        return curl_quotes(space_re.sub("", text))

    for block in blocks:
        if isinstance(block, Heading):
            # A heading's type is its look: italic or bold in it is no emphasis.
            block = replace(block, text=STYLE_RE.sub("", block.text))
            text = plain(block.text).strip()
            if _COPYRIGHT_RE.search(text):
                block = Paragraph(block.text, small=True, page=block.page, top=block.top)
            elif text.endswith(".") and len(text.split()) >= _SENTENCE_WORDS:
                block = Paragraph(block.text, page=block.page, top=block.top)
        if isinstance(block, Heading | Paragraph | Note):
            block = replace(block, text=touch(block.text))
        elif isinstance(block, Gloss):
            block = replace(block, lines=tuple(touch(line) for line in block.lines))
        yield block

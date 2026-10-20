"""Last touches to a book's text, the same for every format.

* Typewriter quotes become typographic ones: d'Holbach -> d’Holbach, "la canalla" ->
  “la canalla”.
* Headings that aren't: a copyright line ("© 1960: Frederick Copleston", "Impreso en
  España") becomes small print, and a whole sentence (eight words or more ending in a
  full stop) a paragraph. OCR labels both as titles.
* Subheadings: a short heading ("Textos", "Estudios") after a numbered one ("1. BAYLE")
  of the same level goes one level down. Headings lose italic and bold.

Runs after the review file is applied (``pdf_worker.fixes``), whose finds are the
OCR's text with its straight quotes.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import replace

from pdf_worker.inline import END_BOLD, END_ITALIC, STYLE_RE, plain
from pdf_worker.structure import Block, Gloss, Heading, Note, Paragraph

_APOSTROPHE_RE = re.compile(r"(?<=\w)'(?=\w)")
# A quote opens at the start or after a space, an opening bracket, a dash or a marker
# (``pdf_worker.inline``: private-use characters).
_OPENS = "(?:^|(?<=[\\s(\\[{—–«¿¡-]))"
_OPENS += f"(?<![{END_ITALIC}{END_BOLD}])"  # not after the end of an italic word
_OPEN_DOUBLE_RE = re.compile(_OPENS + '"')
_OPEN_SINGLE_RE = re.compile(_OPENS + "'")
_NUMBERED_RE = re.compile(r"\d+\.\s")  # "1. BAYLE", "13. D'Holbach"
_SUBHEADING_WORDS = 2  # "Textos", "Estudios", "Obras generales"
_COPYRIGHT_RE = re.compile(
    r"©|\bisbn\b|\bimpreso en\b|\bprinted in\b|dep[óo]sito legal|derechos reservados"
    r"|all rights reserved",
    re.I,
)
_SENTENCE_WORDS = 8


def curl_quotes(text: str) -> str:
    # shortcut: a quote inside a link's web address is curled too; none seen in books.
    text = _APOSTROPHE_RE.sub("’", text)
    text = _OPEN_DOUBLE_RE.sub("“", text).replace('"', "”")
    return _OPEN_SINGLE_RE.sub("‘", text).replace("'", "’")


def tidy(blocks: Iterable[Block]) -> Iterator[Block]:
    numbered = None  # the level of the last numbered heading, while its subheadings go on
    for block in blocks:
        if isinstance(block, Heading):
            # A heading's type is its look: italic or bold in it is no emphasis.
            block = replace(block, text=STYLE_RE.sub("", block.text))
            text = plain(block.text).strip()
            words = text.rstrip(".").split()
            if _COPYRIGHT_RE.search(text):
                block = Paragraph(block.text, small=True, page=block.page, top=block.top)
            elif text.endswith(".") and len(text.split()) >= _SENTENCE_WORDS:
                block = Paragraph(block.text, page=block.page, top=block.top)
            elif _NUMBERED_RE.match(text):
                numbered = block.level
            elif (
                block.level == numbered
                and len(words) <= _SUBHEADING_WORDS
                and text[:1].isupper()  # "cristiana": the heading's wrapped line
                and not any(c.isdigit() for c in text)
                and not text.isupper()
            ):
                # "Textos", "Estudios" under "1. BAYLE": OCR gives them its level.
                block = replace(block, level=block.level + 1)
            else:
                numbered = None
        if isinstance(block, Heading | Paragraph | Note):
            block = replace(block, text=curl_quotes(block.text))
        elif isinstance(block, Gloss):
            block = replace(block, lines=tuple(curl_quotes(line) for line in block.lines))
        yield block

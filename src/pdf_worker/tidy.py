"""Last touches to a book's text, the same for every format.

* Typewriter quotes become typographic ones: d'Holbach -> d’Holbach, "la canalla" ->
  “la canalla”.
* Headings that aren't: a copyright line ("© 1960: Frederick Copleston", "Impreso en
  España") becomes small print, and a whole sentence (eight words or more ending in a
  full stop) a paragraph. OCR labels both as titles.

Runs after the review file is applied (``pdf_worker.fixes``), whose finds are the
OCR's text with its straight quotes.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import replace

from pdf_worker.inline import plain
from pdf_worker.structure import Block, Gloss, Heading, Note, Paragraph

_APOSTROPHE_RE = re.compile(r"(?<=\w)'(?=\w)")
# A quote opens at the start or after a space, an opening bracket, a dash or a marker
# (``pdf_worker.inline``: private-use characters).
_OPENS = "(?:^|(?<=[\\s(\\[{—–«¿¡-]))"
_OPEN_DOUBLE_RE = re.compile(_OPENS + '"')
_OPEN_SINGLE_RE = re.compile(_OPENS + "'")
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
    for block in blocks:
        if isinstance(block, Heading):
            text = plain(block.text).strip()
            if _COPYRIGHT_RE.search(text):
                block = Paragraph(block.text, small=True, page=block.page, top=block.top)
            elif text.endswith(".") and len(text.split()) >= _SENTENCE_WORDS:
                block = Paragraph(block.text, page=block.page, top=block.top)
        if isinstance(block, Heading | Paragraph | Note):
            block = replace(block, text=curl_quotes(block.text))
        elif isinstance(block, Gloss):
            block = replace(block, lines=tuple(curl_quotes(line) for line in block.lines))
        yield block

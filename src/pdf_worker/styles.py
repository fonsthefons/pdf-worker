"""Italic, bold and accents for OCR'd text, from the PDF's own text layer and from Paddle.

A scan's text layer (the scanner's OCR) often knows its fonts, Times-Italic, and keeps
accents Paddle drops, while its words are worse than Paddle's. The layer's words inside an
OCR block are aligned with the block's words (accents, case and punctuation aside); a word
takes its partner's style, and its accents when the letters are the same.
Paddle itself marks a few italics as Markdown: ``*De l'esprit*``.
"""

import difflib
import re
import unicodedata

import pymupdf

from pdf_worker.document import TEXT_FLAGS
from pdf_worker.inline import BOLD, END_BOLD, END_ITALIC, ITALIC, plain

_REF_RE = re.compile(r"\[\^[^\]\s]+\]")  # structure.REF_RE; importing it is a cycle
_ITALIC_FLAG, _BOLD_FLAG = 2, 16  # MuPDF span flags
_MARKDOWN_ITALIC_RE = re.compile(r"(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])")
# Punctuation around a word stays out of its style: "(<i>Essai</i>),".
_WORD_RE = re.compile(
    r"^([(\[«“\"'¿¡]*)(.*?)((?:\[\^[^\]\s]+\])*[.,;:)\]»”\"'?!-]*)$", re.DOTALL
)  # note refs after a word stay out too: "<i>categórico</i>[^2]"
_MIN_MATCHED = 0.5  # of a block's words found in the layer: else the layer is elsewhere
_SLACK = 2  # points around an OCR block when gathering the layer's words

Word = tuple[str, int]  # text, MuPDF span flags


def layer_words(page: pymupdf.Page) -> list[tuple[pymupdf.Point, str, int]]:
    """The text layer's words with their centres and span flags."""
    words = []
    for block in page.get_text("dict", flags=TEXT_FLAGS)["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                x0, y0, x1, y1 = span["bbox"]
                centre = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)
                words += [(centre, word, span["flags"]) for word in span["text"].split()]
    return words


def words_in(words: list[tuple[pymupdf.Point, str, int]], rect: pymupdf.Rect) -> list[Word]:
    area = pymupdf.Rect(rect) + (-_SLACK, -_SLACK, _SLACK, _SLACK)
    return [(word, flags) for centre, word, flags in words if centre in area]


def span_text(span: dict) -> str:
    """A text-layer span's text, its words in italic or bold as its font is."""
    text = span["text"]
    core = text.strip()
    if not core or not span["flags"] & (_ITALIC_FLAG | _BOLD_FLAG):
        return text
    tokens = re.split(r"(\s+)", core)
    for flag, start, end in ((_ITALIC_FLAG, ITALIC, END_ITALIC), (_BOLD_FLAG, BOLD, END_BOLD)):
        tokens = _wrap(tokens, [bool(span["flags"] & flag)] * len(tokens), start, end)
    lead = text[: len(text) - len(text.lstrip())]
    return lead + "".join(tokens) + text[len(text.rstrip()) :]


def markdown_italics(text: str) -> str:
    return _MARKDOWN_ITALIC_RE.sub(lambda m: ITALIC + m.group(1) + END_ITALIC, text)


def apply_layer(text: str, layer: list[Word]) -> str:
    """``text`` with the accents its words lost and their italic or bold, both taken from
    their partners in ``layer``."""
    if not layer:
        return text
    tokens = re.split(r"(\s+|—)", text)  # word, space, word, ...: "categorico.—El" is two
    layer = _join_hyphens(layer)
    keys = [_key(token) if i % 2 == 0 else "" for i, token in enumerate(tokens)]
    at = [i for i, key in enumerate(keys) if key]
    theirs = [(_key(word), word, flags) for word, flags in layer]
    theirs = [t for t in theirs if t[0]]
    matcher = difflib.SequenceMatcher(None, [keys[i] for i in at], [t[0] for t in theirs], False)
    flags = [0] * len(tokens)
    accented = list(tokens)
    matched = 0
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            matched += i2 - i1
            for i, j in zip(range(i1, i2), range(j1, j2), strict=True):
                accented[at[i]] = _accents(tokens[at[i]], theirs[j][1])
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):  # misreadings
            for i, j in zip(range(i1, i2), range(j1, j2), strict=True):
                flags[at[i]] = theirs[j][2]
    if matched < len(at) * _MIN_MATCHED:
        return text
    tokens = accented
    # Words without letters ("1789", "—") take the style around them.
    for i in (i for i in range(0, len(tokens), 2) if not keys[i]):
        before = next((flags[k] for k in range(i - 2, -1, -2) if keys[k]), 0)
        after = next((flags[k] for k in range(i + 2, len(tokens), 2) if keys[k]), 0)
        flags[i] = before & after
    for flag, start, end in ((_ITALIC_FLAG, ITALIC, END_ITALIC), (_BOLD_FLAG, BOLD, END_BOLD)):
        tokens = _wrap(tokens, [bool(f & flag) for f in flags], start, end)
    return "".join(tokens)


def _wrap(tokens: list[str], on: list[bool], start: str, end: str) -> list[str]:
    """Runs of styled words between ``start`` and ``end``, punctuation outside."""
    tokens = list(tokens)
    for i in range(0, len(tokens), 2):
        lead, core, tail = _WORD_RE.match(tokens[i]).groups()
        if not on[i] or not core:
            continue
        if i < 2 or not on[i - 2]:
            lead += start
        if i + 2 >= len(tokens) or not on[i + 2]:
            tail = end + tail
        tokens[i] = lead + core + tail
    return tokens


def _join_hyphens(layer: list[Word]) -> list[Word]:
    """The layer's words split at a line end made whole: "cate-" "górico" -> "categórico"."""
    out: list[Word] = []
    for word, flags in layer:
        if out and out[-1][0][-2:-1].isalpha() and out[-1][0].endswith("-") and word[:1].islower():
            out[-1] = (out[-1][0][:-1] + word, out[-1][1])
        else:
            out.append((word, flags))
    return out


def _accents(word: str, theirs: str) -> str:
    """``word`` with the accents of ``theirs`` (the same letters) on its bare letters:
    Paddle's "categorico" for the layer's "categórico". A word with an accent keeps its own
    ("público", not the layer's "publicó")."""
    mine = [i for i, c in enumerate(word) if c.isalpha()]
    their = [c for c in unicodedata.normalize("NFC", plain(theirs)) if c.isalpha()]
    if len(mine) != len(their) or any(_base(word[i]) != word[i].casefold() for i in mine):
        return word
    out = list(word)
    for i, c in zip(mine, their, strict=True):
        if c.casefold() == word[i].casefold():
            continue
        if _base(c) != word[i].casefold():
            return word  # another letter: a misreading, not a lost accent
        out[i] = c.upper() if word[i].isupper() else c.lower()
    return "".join(out)


def _base(c: str) -> str:
    return unicodedata.normalize("NFD", c.casefold())[0]


def _key(word: str) -> str:
    """Letters only, without accents, lower case: "Enciclopedt·a." ~ "enciclopedta"."""
    letters = unicodedata.normalize("NFD", _REF_RE.sub("", plain(word)).casefold())
    return "".join(c for c in letters if c.isalpha())

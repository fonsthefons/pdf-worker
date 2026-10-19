"""Italic and bold for OCR'd text, from the PDF's own text layer and from Paddle.

A scan's text layer (the scanner's OCR) often knows its fonts, Times-Italic, while its
words are worse than Paddle's. The layer's words inside an OCR block are aligned with the
block's words (accents, case and punctuation aside); a word takes its partner's style.
Paddle itself marks a few italics as Markdown: ``*De l'esprit*``.
"""

import difflib
import re
import unicodedata

import pymupdf

from pdf_worker.inline import BOLD, END_BOLD, END_ITALIC, ITALIC, plain

_REF_RE = re.compile(r"\[\^[^\]\s]+\]")  # structure.REF_RE; importing it is a cycle
_ITALIC_FLAG, _BOLD_FLAG = 2, 16  # MuPDF span flags
_MARKDOWN_ITALIC_RE = re.compile(r"(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])")
# Punctuation around a word stays out of its style: "(<i>Essai</i>),".
_WORD_RE = re.compile(r"^([(\[«“\"'¿¡]*)(.*?)([.,;:)\]»”\"'?!-]*)$", re.DOTALL)
_MIN_MATCHED = 0.5  # of a block's words found in the layer: else the layer is elsewhere
_SLACK = 2  # points around an OCR block when gathering the layer's words

Word = tuple[str, int]  # text, MuPDF span flags


def layer_words(page: pymupdf.Page) -> list[tuple[pymupdf.Point, str, int]]:
    """The text layer's words with their centres and span flags; empty when no word is
    italic or bold (nothing to learn, as in a layer of our own OCR)."""
    words = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                x0, y0, x1, y1 = span["bbox"]
                centre = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)
                words += [(centre, word, span["flags"]) for word in span["text"].split()]
    if not any(flags & (_ITALIC_FLAG | _BOLD_FLAG) for _, _, flags in words):
        return []
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


def apply_styles(text: str, layer: list[Word]) -> str:
    """``text`` with its words in italic or bold where their partners in ``layer`` are."""
    if not layer:
        return text
    tokens = re.split(r"(\s+)", text)  # word, space, word, ...
    keys = [_key(token) if i % 2 == 0 else "" for i, token in enumerate(tokens)]
    at = [i for i, key in enumerate(keys) if key]
    theirs = [(_key(word), flags) for word, flags in layer]
    theirs = [(key, flags) for key, flags in theirs if key]
    matcher = difflib.SequenceMatcher(None, [keys[i] for i in at], [k for k, _ in theirs], False)
    flags = [0] * len(tokens)
    matched = 0
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            matched += i2 - i1
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):  # misreadings
            for i, j in zip(range(i1, i2), range(j1, j2), strict=True):
                flags[at[i]] = theirs[j][1]
    if matched < len(at) * _MIN_MATCHED:
        return text
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


def _key(word: str) -> str:
    """Letters only, without accents, lower case: "Enciclopedt·a." ~ "enciclopedta"."""
    letters = unicodedata.normalize("NFD", _REF_RE.sub("", plain(word)).casefold())
    return "".join(c for c in letters if c.isalpha())

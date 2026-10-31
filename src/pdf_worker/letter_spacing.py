"""Titles set letter-spaced ("E l c o m p u e s t o d e s u s t a n c ia"): OCR reads
each letter or two as a word. A run of ``MIN_PIECES`` or more one- or two-letter pieces is
joined and split again into words the book itself uses elsewhere (its own vocabulary,
not a fixed list): the fewest words, and among those the ones the book uses most, a
capital starting a word rather than inside one. A run no such split covers stays."""

import math
import re
from collections.abc import Mapping
from itertools import pairwise

WORD_RE = re.compile(r"[^\W\d_]+")
MIN_PIECES = 4
_MAX_WORD = 40
_PIECE_RE = re.compile(r"([^\W\d_]+)([,.;:]?)$")  # letters, maybe a closing mark


def letter_spaced(text: str) -> bool:
    """The line has a run of ``MIN_PIECES`` or more one- or two-letter pieces."""
    short = 0
    for token in text.split():
        short = short + 1 if token.isalpha() and len(token) <= 2 else 0
        if short >= MIN_PIECES:
            return True
    return False


def respace(text: str, vocabulary: Mapping[str, int]) -> str:
    """``text`` with its letter-spaced runs split into the book's words. ``vocabulary``:
    the book's words, lower case, and how often it uses each."""
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        if not tokens[i].isalpha():
            out.append(tokens[i])
            i += 1
            continue
        j = i
        while j < len(tokens) and tokens[j].isalpha():
            j += 1
        run, mark = tokens[i:j], ""
        closing = _PIECE_RE.match(tokens[j]) if j < len(tokens) else None
        if closing:  # "E l se r," : the run ends at the comma
            run, mark = [*run, closing.group(1)], closing.group(2)
            j += 1
        words = _respace_run(run, vocabulary)
        if words is run:
            out.extend(tokens[i:j])
        else:
            out.extend([*words[:-1], words[-1] + mark])
        i = j
    return " ".join(out) if out != tokens else text


def _respace_run(run: list[str], vocabulary: Mapping[str, int]) -> list[str]:
    if not letter_spaced(" ".join(run)):
        return run
    joined = "".join(run)
    words = _split(joined, vocabulary)
    if not words or len(words) >= len(run):
        return run
    # A split whose letters are mostly in one- or two-letter words is no reading: the
    # letters weren't the book's words ("yB i PE G VA", Guaraní read as Spanish).
    short = sum(len(word) for word in words if len(word) <= 2)
    return run if 2 * short >= len(joined) else words


def _split(text: str, vocabulary: Mapping[str, int]) -> list[str] | None:
    """``text`` as words of ``vocabulary`` (see the module), or None."""
    lower = text.lower()
    # best[end]: (cost, start) of the best split of text[:end]
    best: list[tuple[tuple, int] | None] = [((0, 0, 0.0), 0)] + [None] * len(text)
    for end in range(1, len(text) + 1):
        for start in range(max(0, end - _MAX_WORD), end):
            count = vocabulary.get(lower[start:end])
            if best[start] is None or not count:
                continue
            words, inner, rarity = best[start][0]
            piece = text[start:end]
            inner += any(a.islower() and b.isupper() for a, b in pairwise(piece))
            cost = (words + 1, inner, rarity - math.log(count))
            if best[end] is None or cost < best[end][0]:
                best[end] = (cost, start)
    if best[-1] is None:
        return None
    words, end = [], len(text)
    while end:
        start = best[end][1]
        words.append(text[start:end])
        end = start
    return words[::-1]

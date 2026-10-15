"""Footnote numbers on PaddleOCR-VL pages: notes count up through the book.

Paddle drops or misreads the small numbers: a note's "⁵" comes as "³" or not at all, a
reference "diosa⁷" as "diosa²", and some references vanish ("cueste⁵"). Notes are
numbered in sequence, so a page's notes take the numbers after the previous page's last
note; a number read on the page wins when it fits (a note Paddle missed); a new count
from 1 needs the page's references to start from 1 too. The references in the text then
take the page's numbers in order: a misread one gets the number missing at its place,
and a dropped one is put back where Tesseract saw a stray mark after a word ("cueste 5",
"misma !0?").
"""

import difflib
import re
from collections.abc import Sequence

from pdf_worker.margin_refs import ScanWord, norm

_TO_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_FROM_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
SUPERSCRIPT_RE = re.compile("[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
# A note's own number: superscript, plain, or a mark the model made of it ("* ").
_NOTE_NUMBER_RE = re.compile(r"^(?:([⁰¹²³⁴⁵⁶⁷⁸⁹]+)\s*|(\d{1,3})\s+|([*'’‘\"“”^°])\s+)(?=\S)")
_MAX_SKIPPED = 2  # a read number this far ahead means Paddle missed notes
# What Tesseract makes of a small reference after a word: "5,", "!0?", "!!.", "*".
_STRAY_RE = re.compile(r"^[\d!¡*'’°]{1,3}[.,;:?!»)]*$")
_STRONG, _WEAK = 1, 0  # a stray digit or "!" against a stray "?"
# A reference Paddle wrote in plain digits, as a word of its own: "su número 27."
_BARE_REF_RE = re.compile(r"(\d{1,3})([.,;:?!»)]*)")
_PADDLE = 2  # Paddle saw a reference there, with another number


def sup(number: int) -> str:
    return str(number).translate(_TO_SUP)


def from_sup(text: str) -> int:
    return int(text.translate(_FROM_SUP))


def number_notes(
    notes: Sequence[str], refs: Sequence[int], last: int | None
) -> tuple[list[str], list[int | None]]:
    """Give a page's notes their numbers.

    ``refs`` are the reference numbers Paddle read on the page, ``last`` the previous
    page's last note (None: no count yet). Returns the notes, each starting with its
    number as superscript, and the numbers (None: the previous page's last note going on,
    or no number to be had)."""
    expected = last + 1 if last is not None else None
    if refs and refs[0] == 1:
        expected = 1  # a new count: a chapter's, or the page's
    # With no count yet, extra notes at the top go on from the page before (as many as
    # the notes outnumber the references).
    skip = max(0, len(notes) - len(refs)) if expected is None else 0
    texts, numbers = [], []
    # An unnumbered first note goes on from the previous page when it starts lowercase,
    # or when the next note has the number due ("Hermes 88 (1960)…", then "¹⁴").
    second = _NOTE_NUMBER_RE.match(notes[1]) if len(notes) > 1 else None
    second_read = second and (second.group(1) or second.group(2))
    next_is_due = bool(second_read) and expected is not None and from_sup(second_read) == expected
    for i, note in enumerate(notes):
        match = _NOTE_NUMBER_RE.match(note)
        body = note[match.end() :] if match else note
        goes_on = i == 0 and last is not None and (body[:1].islower() or next_is_due)
        if not match and (i < skip or goes_on):
            texts.append(note)
            numbers.append(None)
            continue
        read = None
        if match and (match.group(1) or match.group(2)):
            read = from_sup(match.group(1) or match.group(2))
        if expected is None:
            k = len([n for n in numbers if n is not None])
            number = read if read is not None else (refs[k] if k < len(refs) else None)
        # A read "1" alone is no new count (note 13 came as "1"): that needs the page's
        # references to start from 1 too (expected is then 1).
        elif read is not None and expected <= read <= expected + _MAX_SKIPPED:
            number = read
        else:
            number = expected
        if number is None:
            texts.append(note)
            numbers.append(None)
            continue
        texts.append(f"{sup(number)} {body}")
        numbers.append(number)
        expected = number + 1
    return texts, numbers


def fix_refs(
    texts: Sequence[str], numbers: Sequence[int | None], scan_words: Sequence[ScanWord]
) -> list[str]:
    """Give the references in ``texts`` (a page's body blocks) the page's note
    ``numbers``: misread ones are renumbered, dropped ones put back where the scan
    shows a stray mark. A gap between references that are right is only filled when
    the places found there match the numbers missing in it."""
    wanted = sorted({n for n in numbers if n is not None})
    if not wanted:
        return list(texts)
    words = [(b, m) for b, text in enumerate(texts) for m in re.finditer(r"\S+", text)]
    found = []  # (word, number read)
    bare = set()  # words that are a due note's number in plain digits: "número 27."
    for g, (_, m) in enumerate(words):
        ref = SUPERSCRIPT_RE.search(m.group())
        plain = _BARE_REF_RE.fullmatch(m.group())
        if ref:
            found.append((g, from_sup(ref.group())))
        elif g and plain and int(plain.group(1)) in wanted:
            found.append((g, int(plain.group(1))))
            bare.add(g)
    anchors = []  # (word, number): references whose number fits
    places: dict[int, int] = {}  # word -> strength of the evidence for a reference
    for g, n in found:
        if n in wanted and (not anchors or n > anchors[-1][1]):
            anchors.append((g, n))
        elif g not in bare:  # a plain number out of order is just a number
            places[g] = _PADDLE
    for g, strength in _stray_marks([m.group() for _, m in words], scan_words):
        if g not in places and g not in {a[0] for a in anchors}:
            places[g] = strength
    assigned: dict[int, int] = {}
    bounds = [(-1, wanted[0] - 1), *anchors, (len(words), wanted[-1] + 1)]
    for (g_lo, n_lo), (g_hi, n_hi) in zip(bounds, bounds[1:], strict=False):
        missing = [n for n in wanted if n_lo < n < n_hi]
        if not missing:
            continue
        for level in (_PADDLE, _STRONG, _WEAK):
            gap = sorted(g for g, s in places.items() if g_lo < g < g_hi and s >= level)
            if len(gap) == len(missing):
                assigned.update(zip(gap, missing, strict=True))
                break
    for g, n in anchors:
        if g in bare:
            assigned[g] = n
    out = list(texts)
    for g in sorted(assigned, reverse=True):  # back to front: spans stay valid
        b, m = words[g]
        word = m.group()
        if g in bare:  # "número 27." -> "número²⁷."
            tail = _BARE_REF_RE.fullmatch(word).group(2)
            before = out[b][: m.start()]
            if words[g - 1][0] == b:
                before = before.rstrip()
            out[b] = before + sup(assigned[g]) + tail + out[b][m.end() :]
            continue
        if SUPERSCRIPT_RE.search(word):
            word = SUPERSCRIPT_RE.sub(sup(assigned[g]), word, count=1)
        else:
            word = add_ref(word, assigned[g])
        out[b] = out[b][: m.start()] + word + out[b][m.end() :]
    return out


def add_ref(word: str, number: int) -> str:
    """The reference after the word's last letter: "misma?" -> "misma¹⁰?"."""
    end = next((i + 1 for i in range(len(word) - 1, -1, -1) if word[i].isalnum()), 0)
    return word[:end] + sup(number) + word[end:]


def _stray_marks(words: Sequence[str], scan_words: Sequence[ScanWord]) -> list[tuple[int, int]]:
    """Paddle words after which Tesseract read a mark Paddle doesn't have:
    ``[(word, strength)]``."""
    body = [w.text for w in scan_words if not w.margin]
    ours = [norm(w) for w in body]
    theirs = [norm(SUPERSCRIPT_RE.sub("", w)) for w in words]
    marks = []
    matcher = difflib.SequenceMatcher(None, ours, theirs, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "insert":
            continue
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                extra = set(_tail(body[i1 + k])) - set(_tail(SUPERSCRIPT_RE.sub("", words[j1 + k])))
                if extra & set("0123456789!¡*'’°"):
                    marks.append((j1 + k, _STRONG))
                elif "?" in extra:
                    marks.append((j1 + k, _WEAK))
            continue
        for i in range(i1, i2):  # Tesseract words Paddle hasn't: a stray mark?
            if _STRAY_RE.match(body[i]) and j1 > 0:
                marks.append((min(max(j1 + i - i1 - 1, j1 - 1), max(j2 - 1, j1 - 1)), _STRONG))
    return marks


def _tail(word: str) -> str:
    """What follows a word's last letter ("prudencia?." -> "?.")."""
    for i in range(len(word) - 1, -1, -1):
        if word[i].isalpha():
            return word[i + 1 :]
    return word

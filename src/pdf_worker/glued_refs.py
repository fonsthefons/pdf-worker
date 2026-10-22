"""Note references flattened onto the line: "inteligentes74• Puesto que".

The Timeo's OCR redraw (ClearScan-style, see ``pdf_worker.font_sizes``) sets the printed
"inteligentes⁷⁴." in body-size digits on the baseline, glued to the word, and reads the
period after it as "•"; a few it flags as superscript. Digits glued to a word are also
misread old-style figures ("x999" for 1999), so only those that count up through the
book as notes do (..., 7, 8, 9 ..., with gaps where OCR lost some) are taken. Their places
are stored on the pages (in memory, ``/PdfWorkerGluedRefs``) and
``pdf_worker.layout.page_lines`` writes them as superscript digits, to be matched with
their notes as any others.
"""

import json
import re
from collections.abc import Collection
from itertools import pairwise

import pymupdf

from pdf_worker.consensus import _union
from pdf_worker.document import TEXT_FLAGS
from pdf_worker.endnotes import LOSSY_STEP, lossy_min_run, runs_from_anywhere
from pdf_worker.margin_refs import OCR_DIGITS

REFS_KEY = "PdfWorkerGluedRefs"
_SUPERSCRIPT = 1  # MuPDF span flag
_TO_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_NUMBER_RE = re.compile(r"(?<!\d)\d{1,3}(?!\d)")
# A number glued after a word's letter or closing quote, ending the word:
# "inteligentes74•", "«generado»17.", "(46d)28".
_GLUED_RE = re.compile(r"(?:(?<=[^\W\d_]|[»”)])|(?<=[^\W\d_] ))\d{1,3}(?=•?[.,;:?!»”)]*(?:\s|$))")
# Signs OCR reads small digits as: "oficio'º" is "oficio¹⁰".
_QUOTES = "'’‘´`"
_MISREAD = {"1": _QUOTES + "|", "0": "º°"}
_NOTE_START_RE = re.compile(r"^\s*(\d{1,3})\s+(?=[^\W\d_])")
# A reference's place: after a word ("uniones?'9", "«generado»17"), before a space or
# a dash ("vejez38- que").
_AFTER_WORD = r"(?:(?<=[^\W\d_])|(?<=[»”\")?!]))"
_BEFORE_SPACE = r"(?=•?[.,;:?!»”)\-–—]*(?:\s|$))"
# Further misreadings, taken only in a gap where a sign fits one missing number alone
# ("descritos6" for descrito⁵⁶, "9+" for 94, "³0" for 80): any word ends in "s".
_LOOSE = {"5": "s", "4": "+"}
_CONFUSED = {"3": "8", "8": "3"}
_AS_DIGIT = {c: d for d, signs in (_MISREAD | _LOOSE).items() for c in signs}
# Last, references read past any reading ("mundo”9•" 119, "posible111º" 120,
# "concierto1112" 122): where a gap holds as many signs glued to words, a digit among
# them, as numbers are missing, they are those numbers in order. Few at a time only.
_MAX_COUNTED = 6
# References count up nearly one by one (the Timeo's: 0.76, 0.55 of the numbers in their
# span); numbers after words that only climb ("AAS 42 (1950)", "AAS 53", ...) skip most.
_MIN_RUN_DENSITY = 0.5
_GLUED_SIGNS_RE = re.compile(
    rf"{_AFTER_WORD}[{re.escape('0123456789' + ''.join(_AS_DIGIT))}]{{1,4}}{_BEFORE_SPACE}"
)


def mark_glued_refs(doc: pymupdf.Document, skip: Collection[int] = ()) -> int:
    """Store the places of ``doc``'s glued references on its pages (in memory);
    returns how many."""
    boxes: dict[int, list] = {}
    lines = _lines(doc, skip)
    found = _candidates(lines)
    # A few notes a page: "Page 1" ... "Page 4" on four pages aren't references.
    least = lossy_min_run(doc.page_count - len(skip))
    noted = _note_numbers(lines)
    for run in runs_from_anywhere(found):
        if len(run.items) >= least and _density(run.items) >= _MIN_RUN_DENSITY:
            for _, (index, box, _) in run.items:
                boxes.setdefault(index, []).append(box)
            for number, (index, box) in _missing(run.items, lines, noted):
                boxes.setdefault(index, []).append([*box, number])
    for index, page_boxes in boxes.items():
        doc.xref_set_key(
            doc.load_page(index).xref, REFS_KEY, pymupdf.get_pdf_str(json.dumps(page_boxes))
        )
    return sum(len(page_boxes) for page_boxes in boxes.values())


def _density(items: list[tuple[int, tuple]]) -> float:
    """The share of the numbers from a run's first to its last that it has."""
    numbers = {n for n, _ in items}
    return len(numbers) / (max(numbers) - min(numbers) + 1)


def _note_numbers(lines: list[tuple[int, list, str, list]]) -> set[int]:
    """Numbers that start a line or stand alone on one, as notes are numbered ("30 Sobre",
    "29" hung beside its note, misread "3.¡." for 34): the notes the book has."""
    found = set()
    for _, _, text, _ in lines:
        digits = "".join(text.split()).replace(".¡.", "4").translate(OCR_DIGITS)
        start = _NOTE_START_RE.match(text)
        if digits.isdigit() and len(digits) <= 3:
            found.add(int(digits))
        elif start:
            found.add(int(start.group(1)))
    return found


def _lines(doc: pymupdf.Document, skip: Collection[int]) -> list[tuple[int, list, str, list]]:
    """The text lines of the pages not skipped, in order: (page, chars, text, raised)."""
    out = []
    for page in doc:
        if page.number in skip:
            continue
        for block in page.get_text("rawdict", flags=TEXT_FLAGS)["blocks"]:
            for line in block.get("lines", ()):
                chars, raised = [], []
                for span in line["spans"]:
                    raised += [bool(span["flags"] & _SUPERSCRIPT)] * len(span["chars"])
                    chars += span["chars"]
                text = "".join(c["c"] for c in chars)
                if len(text) == len(chars):  # else a glyph of several characters
                    out.append((page.number, chars, text, raised))
    return out


def _candidates(lines: list[tuple[int, list, str, list]]) -> list[tuple[int, tuple]]:
    """Numbers glued to a word or flagged as superscript:
    ``(number, (page, box, (line, start, end)))``."""
    found = []
    for i, (page, chars, text, raised) in enumerate(lines):
        for match in _NUMBER_RE.finditer(text):
            start, end = match.span()
            if _GLUED_RE.match(text, start) or all(raised[start:end]):
                box = _union(chars[start:end])
                found.append((int(match.group()), (page, box, (i, start, end))))
    return found


def _missing(
    run: list[tuple[int, tuple]],
    lines: list[tuple[int, list, str, list]],
    noted: Collection[int] = (),
) -> list:
    """References a run skips, looked for where they must be: between the two found
    around them, or on the page before the first and after the last. Only that number,
    and only in a reference's shape there, is taken: ``[(number, (page, box))]``. When
    the notes have it and a note beside it (``noted``: 17, 18, 19), the reference is
    there too, so a lone sign glued to a word in its place is taken even when misread
    beyond recognition ("mujeres'3" for 18)."""
    out = []

    def hits_of(pattern: re.Pattern, start: tuple[int, int], end: tuple[int, int]) -> list:
        hits = []
        for i in range(start[0], end[0] + 1):
            page, chars, text, raised = lines[i]
            lo = start[1] if i == start[0] else 0
            hi = end[1] if i == end[0] else len(text)
            for match in pattern.finditer(text):
                s, e = match.span()
                # A closing quote alone isn't a misread "1".
                if lo <= s and e <= hi and match.group().strip(_QUOTES):
                    hits.append((i, s, e, page, _union(chars[s:e])))
        return hits

    def search(
        number: int,
        start: tuple[int, int],
        end: tuple[int, int],
        last: bool = False,
        misread: bool = False,
    ):
        if misread:
            hits = []
            if number in noted and {number - 1, number + 1} & set(noted):
                hits = hits_of(_misread_re(len(str(number))), start, end)
            hits = hits if len(hits) == 1 else []  # only one sign it can be
        else:
            hits = hits_of(_number_re(number), start, end)
        hit = hits[-1] if last and hits else hits[0] if hits else None
        if hit:
            out.append((str(number), (hit[3], hit[4])))
        return hit

    first, (_, _, (line, start, _)) = run[0]
    page = run[0][1][0]
    top = next(i for i in range(line, -1, -1) if i == 0 or lines[i - 1][0] != page)
    end = (line, start)
    for number in range(first - 1, 0, -1):  # before the first: back to the page's top
        hit = search(number, (top, 0), end, last=True)
        if not hit:
            break
        end = (hit[0], hit[1])
    for (a, (_, _, (la, sa, ea))), (b, (_, _, (lb, sb, eb))) in pairwise(run):
        places = {a: (la, sa, ea), b: (lb, sb, eb)}  # number -> (line, start, end)
        at = (la, ea)
        for number in range(a + 1, b):
            hit = search(number, at, (lb, sb))
            if hit:
                places[number] = hit[:3]
                at = (hit[0], hit[2])
        for number in range(a + 1, b):  # misread ones: between the two found around them
            if number not in places:
                below = places[max(n for n in places if n < number)]
                above = places[min(n for n in places if n > number)]
                hit = search(number, (below[0], below[2]), above[:2], misread=True)
                if hit:
                    places[number] = hit[:3]
        for number in range(a + 1, b):  # misread further: a sign that fits it alone
            if number in places or number not in noted:
                continue
            below = places[max(n for n in places if n < number)]
            above = places[min(n for n in places if n > number)]
            pattern = _loose_re(len(str(number)))
            hits = [
                h
                for h in hits_of(pattern, (below[0], below[2]), above[:2])
                if _fits(lines[h[0]][2][h[1] : h[2]], number)
            ]
            others = [n for n in range(a + 1, b) if n not in places and n != number]
            if len(hits) == 1 and not any(
                _fits(lines[hits[0][0]][2][hits[0][1] : hits[0][2]], n) for n in others
            ):
                out.append((str(number), (hits[0][3], hits[0][4])))
                places[number] = hits[0][:3]
        for lo, hi in pairwise(sorted(places)):  # misread past reading: counted in order
            lost = range(lo + 1, hi)
            if not 0 < len(lost) <= _MAX_COUNTED:
                continue
            hits = [
                h
                for h in hits_of(_GLUED_SIGNS_RE, (places[lo][0], places[lo][2]), places[hi][:2])
                if any(c.isdigit() for c in lines[h[0]][2][h[1] : h[2]])
            ]
            if len(hits) == len(lost):
                out += [(str(n), (h[3], h[4])) for n, h in zip(lost, hits, strict=True)]
    last, (page, _, (line, _, end_at)) = run[-1]
    bottom = next(
        i for i in range(line, len(lines)) if i + 1 == len(lines) or lines[i + 1][0] != page
    )
    at = (line, end_at)
    for number in range(last + 1, last + LOSSY_STEP):  # after the last: to the page's foot
        hit = search(number, at, (bottom, len(lines[bottom][2])))
        if not hit:
            break
        at = (hit[0], hit[2])
    return out


def _number_re(number: int) -> re.Pattern:
    """``number`` as a reference: glued to a word's end, its digits perhaps misread
    ("oficio'º" for 10), or apart from the words but before punctuation ("tres... 2 ,")."""
    digits = "".join(f"[{re.escape(d + _MISREAD.get(d, ''))}]" for d in str(number))
    return re.compile(rf"{_AFTER_WORD}{digits}{_BEFORE_SPACE}|(?<=\s){number}(?=\s*[.,;:?!»”)])")


def _misread_re(length: int) -> re.Pattern:
    """Any ``length`` digits or signs read for them, glued to a word's end ("'3")."""
    signs = re.escape("0123456789" + "".join(_MISREAD.values()))
    return re.compile(rf"{_AFTER_WORD}[{signs}]{{{length}}}{_BEFORE_SPACE}")


def _loose_re(length: int) -> re.Pattern:
    signs = re.escape("0123456789" + "".join(_AS_DIGIT))
    return re.compile(rf"{_AFTER_WORD}[{signs}]{{{length}}}{_BEFORE_SPACE}")


def _fits(read: str, number: int) -> bool:
    """A reading with a digit in it that, its signs taken as digits ("s6" -> 56) and 3
    and 8 as either, is ``number``."""
    digits = "".join(_AS_DIGIT.get(c, c) for c in read)
    return (
        len(digits) == len(str(number))
        and any(c.isdigit() for c in read)
        and all(r == d or _CONFUSED.get(r) == d for r, d in zip(digits, str(number), strict=True))
    )


def page_refs(page: pymupdf.Page) -> list[list[float]]:
    kind, value = page.parent.xref_get_key(page.xref, REFS_KEY)
    return json.loads(value) if kind == "string" else []


def apply_refs(chars: list[dict], boxes: list[list[float]]) -> None:
    """Write the glued references in a line's ``rawdict`` characters as superscript
    digits, and a "•" right after one as the period it is. A box with a number (a
    reference found where a run skipped it) takes that number, whatever was read."""

    def inside(char: dict, box: list) -> bool:
        x0, y0, x1, y1 = char["bbox"]
        return box[0] <= (x0 + x1) / 2 <= box[2] and box[1] <= (y0 + y1) / 2 <= box[3]

    for box in (b for b in boxes if len(b) == 5):
        found = [c for c in chars if c["c"] and inside(c, box)]
        digits = list(box[4].translate(_TO_SUP))
        if found:  # a digit a character ("'º" -> "¹⁰"), as superscripts are read one by one
            for char in found:
                char["c"] = digits.pop(0) if digits else ""
            found[-1]["c"] += "".join(digits)
    boxes = [b for b in boxes if len(b) == 4]
    for i, char in enumerate(chars):
        if char["c"].isdigit() and any(inside(char, box) for box in boxes):
            char["c"] = char["c"].translate(_TO_SUP)
            after = [c["c"] for c in chars[i + 1 : i + 3]]
            if after[:1] == ["•"]:
                chars[i + 1]["c"] = "."
            elif after == [" ", "•"]:  # "exactitud188 •": the period moves up
                chars[i + 1]["c"], chars[i + 2]["c"] = ".", ""

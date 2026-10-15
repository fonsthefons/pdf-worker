"""Margin references: the section numbers printed beside the text of classical editions.

Plato is cited by Stephanus page and section ("22b"): editions print the page number
("22") and the section letters ("b", "c", "d", "e") in the margin, beside the line where
each section starts. They are not text and not footnotes. Here they become inline
markers (``pdf_worker.inline.margin_ref``) at the start of their line, labelled in full
("22a", "22b" ...), which every writer shows set apart from the text.

OCR layers that keep the printed lines carry the marks at the line ends, where
``pdf_worker.margins`` finds them. PaddleOCR-VL rewrites each paragraph as one block and
drops or garbles the marks ("por c fuego" -> "por el juego"), so for Paddle the scan
itself is searched: ink beside the text column is read on its own, and its line is
matched with Paddle's words (``mark_paddle_blocks``). The marks are stored on the page
(``/PdfWorkerMarginRefs``: the box of the word that starts the mark's line, and the
reading) and put into the text by ``pdf_worker.layout.page_lines``.

Small letters are often misread, so labels follow the sequence: after "22b" comes "22c",
after "22e" comes "23a"; a reading that doesn't fit takes the next label.
"""

import difflib
import json
import re
import statistics
import subprocess
from dataclasses import dataclass

import pymupdf

from pdf_worker.inline import margin_ref

MARKS_KEY = "PdfWorkerMarginRefs"
UNREADABLE = "?"
_DPI = 300
_MARK_RE = re.compile(r"^(\d{1,4})?([a-e])?$")
_NORM_RE = re.compile(r"[^\w]+")
# Ink this far (in line heights) beside the text column is searched for marks.
_GAP, _REACH = 0.15, 1.6
_LONG_LINE_SHARE = 0.35


def is_mark(text: str) -> bool:
    """Text that reads as a section mark: "22", "22b" or a letter "a" to "e"."""
    return bool(text) and bool(_MARK_RE.match(text))


def has_letter(reading: str) -> bool:
    match = _MARK_RE.match(reading)
    return bool(match and match.group(2))


def next_label(previous: str | None, reading: str) -> str | None:
    """The full label of a mark read as ``reading`` after the label ``previous``.

    A number starts its section "a"; a letter takes the current number. Letters run
    a to e and then the number goes up, so a reading that breaks the order (a misread
    letter, an unreadable mark) takes the next label instead. Without a number yet, a
    letter stays a bare letter and an unreadable mark is dropped (None).
    """
    expected = None
    if previous and previous[:-1].isdigit():
        number, letter = int(previous[:-1]), previous[-1]
        expected = f"{number}{chr(ord(letter) + 1)}" if letter < "e" else f"{number + 1}a"
    match = _MARK_RE.match(reading)
    if not match or not reading:
        return expected
    digits, letter = match.groups()
    if digits:
        label = f"{int(digits)}{letter or 'a'}"
        if expected is None or int(digits) in (int(expected[:-1]), int(expected[:-1]) + 1):
            return label
        return expected  # a misread number: keep counting
    if expected is None:
        return letter
    # One mark may have been missed: the letter after the expected one is believed.
    if expected[-1] != "a" and ord(letter) - ord(expected[-1]) in (0, 1):
        return expected[:-1] + letter
    return expected


# -- marks stored on the page -------------------------------------------------------------


def page_marks(page: pymupdf.Page) -> list[list]:
    kind, value = page.parent.xref_get_key(page.xref, MARKS_KEY)
    if kind != "string":
        return []
    try:
        return json.loads(value)
    except ValueError:
        return []


def apply_marks(chars: list[dict], marks: list[list]) -> None:
    """Put stored marks into a line's ``rawdict`` characters, before the first character
    of the word they were stored at."""
    for x0, y0, _, y1, reading in marks:
        for char in chars:
            cy = (char["bbox"][1] + char["bbox"][3]) / 2
            # The word's first letter: a line packed close above may reach into the box.
            if abs(char["bbox"][0] - x0) < 1 and y0 <= cy <= y1 and not char["c"].isspace():
                char["c"] = margin_ref(reading) + char["c"]
                break


# -- finding marks in the scan ------------------------------------------------------------


@dataclass(frozen=True)
class ScanWord:
    text: str
    line: int  # index of its printed line, top to bottom
    margin: bool  # beside the text column: a mark as Tesseract read it


@dataclass(frozen=True)
class ScanMark:
    reading: str  # "22", "b" ..., or UNREADABLE
    line: int


@dataclass
class PageScan:
    words: list[ScanWord]  # reading order
    marks: list[ScanMark]


def scan_page(page: pymupdf.Page, tesseract: str, language: str) -> PageScan:
    """Find the marks beside the text column of a scanned page, and its printed lines."""
    import cv2

    from pdf_worker.consensus import _page_image

    gray = _page_image(page)
    lines = _tesseract_lines(gray, tesseract, language)
    long_lines = [ln for ln in lines if ln[-1][2] - ln[0][0] >= gray.shape[1] * _LONG_LINE_SHARE]
    if len(long_lines) < 3:
        return PageScan([], [])
    left = statistics.median(ln[0][0] for ln in long_lines)
    right = statistics.median(ln[-1][2] for ln in long_lines)
    height = statistics.median(max(w[3] for w in ln) - min(w[1] for w in ln) for ln in long_lines)
    words = []
    body_boxes = []
    for index, line in enumerate(lines):
        for x0, y0, x1, y1, text in line:
            margin = not left - _GAP * height < (x0 + x1) / 2 < right + _GAP * height
            words.append(ScanWord(text, index, margin))
            if not margin:
                body_boxes.append((x0, y0, x1, y1))
    top = min(w[1] for ln in long_lines for w in ln) - height
    bottom = max(w[3] for ln in long_lines for w in ln) + height
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    marks = []
    for side in (
        (right + _GAP * height, right + _REACH * height),
        (left - _REACH * height, left - _GAP * height),
    ):
        for box in _blobs(ink, side, (top, bottom), height, body_boxes):
            line = _line_of(box, lines, words, height)
            if line is not None:
                reading = _read(gray, box, height, tesseract)
                if reading == UNREADABLE:  # the page's reading of it, if that was a mark
                    reading = next(
                        (w[4] for w in lines[line] if _overlaps(w[:4], box) and is_mark(w[4])),
                        reading,
                    )
                marks.append((line, reading))
    # A mark split into pieces ("1" + "16", "?" + "?") is still one mark: keep the
    # line's best reading. shortcut: two real marks on one line become one; none seen.
    best: dict[int, str] = {}
    for line, reading in marks:
        old = best.get(line)
        if old is None or _rank(reading) > _rank(old):
            best[line] = reading
    return PageScan(words, [ScanMark(best[line], line) for line in sorted(best)])


def _rank(reading: str) -> tuple[bool, int]:
    """Readable marks first, then the longer reading ("16" over "1")."""
    return is_mark(reading), len(reading)


def _tesseract_lines(gray, tesseract: str, language: str) -> list[list[tuple]]:
    """Printed lines top to bottom, each a list of words ``(x0, y0, x1, y1, text)``."""
    import cv2

    ok, png = cv2.imencode(".png", gray)
    result = subprocess.run(
        [tesseract, "stdin", "stdout", "-l", language, "--dpi", str(_DPI), "tsv"],
        input=png.tobytes() if ok else b"",
        capture_output=True,
        check=False,
    )
    lines: dict[tuple, list] = {}
    for row in result.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
        cells = row.split("\t")
        if len(cells) == 12 and cells[0] == "5" and cells[11].strip():
            x, y, w, h = map(int, cells[6:10])
            lines.setdefault(tuple(cells[2:5]), []).append((x, y, x + w, y + h, cells[11]))
    return sorted(lines.values(), key=lambda ln: (min(w[1] for w in ln), ln[0][0]))


def _blobs(ink, xs, ys, height, body_boxes) -> list[tuple[int, int, int, int]]:
    """Mark-sized groups of ink in the strip ``xs`` x ``ys``, away from body words."""
    import cv2

    x0, x1 = max(0, int(xs[0])), min(ink.shape[1], int(xs[1]))
    y0, y1 = max(0, int(ys[0])), min(ink.shape[0], int(ys[1]))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return []
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink[y0:y1, x0:x1])
    parts = []
    for i in range(1, count):
        x, y, w, h, _ = stats[i]
        box = (x0 + x, y0 + y, x0 + x + w, y0 + y + h)
        if not 0.15 * height <= h <= 1.2 * height or w > 2 * height:
            continue  # dust, or a scanner's dark edge
        if any(_overlaps(box, b) for b in body_boxes):
            continue
        parts.append(box)
    groups: list[list[int]] = []
    for box in sorted(parts):
        last = groups[-1] if groups else None
        if last and box[0] - last[2] < 0.4 * height and box[1] < last[3] and box[3] > last[1]:
            last[:] = [last[0], min(last[1], box[1]), max(last[2], box[2]), max(last[3], box[3])]
        else:
            groups.append(list(box))
    return [tuple(g) for g in groups if g[3] - g[1] >= 0.25 * height and g[2] - g[0] <= 2 * height]


def _overlaps(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _line_of(box, lines, words: list[ScanWord], height: float) -> int | None:
    """The body line beside the mark."""
    center = (box[1] + box[3]) / 2
    body_lines = {w.line for w in words if not w.margin}
    best = None
    for index in body_lines:
        line = lines[index]
        distance = abs(center - (min(w[1] for w in line) + max(w[3] for w in line)) / 2)
        if distance < 0.6 * height and (best is None or distance < best[0]):
            best = (distance, index)
    return best[1] if best else None


def _read(gray, box, height: float, tesseract: str) -> str:
    """The mark read on its own, as digits and the letters a to e."""
    import cv2

    pad = int(0.4 * height)
    y0, x0 = max(0, box[1] - pad), max(0, box[0] - pad)
    # Twice the size, read as one line: best on the sample's small italic letters.
    crop = cv2.resize(gray[y0 : box[3] + pad, x0 : box[2] + pad], None, fx=2, fy=2)
    crop = cv2.copyMakeBorder(crop, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    ok, png = cv2.imencode(".png", crop)
    result = subprocess.run(
        [tesseract, "stdin", "stdout", "--psm", "7",
         "-c", "tessedit_char_whitelist=0123456789abcde"],
        input=png.tobytes() if ok else b"",
        capture_output=True,
        check=False,
    )  # fmt: skip
    text = "".join(result.stdout.decode("utf-8", errors="replace").split())
    return text if is_mark(text) else UNREADABLE


# -- Paddle -------------------------------------------------------------------------------


def norm(word: str) -> str:
    return _NORM_RE.sub("", word.lower())


def mark_paddle_blocks(
    texts: list[str], scan: PageScan
) -> tuple[list[str], list[tuple[int, int, str]]]:
    """Match the scan's marks with Paddle's text blocks.

    Returns the texts with the marks Paddle read into them taken out ("a los 22
    sacerdotes"), and the marks as ``(block, word index, reading)``: the word that
    starts the mark's printed line.
    """
    if not scan.marks:
        return texts, []
    where = [(b, i) for b, text in enumerate(texts) for i, _ in enumerate(text.split())]
    theirs = [norm(w) for text in texts for w in text.split()]
    ours = [norm(w.text) for w in scan.words]
    to_theirs: dict[int, int] = {}
    drop = set()
    mark_lines = {m.line for m in scan.marks}
    body = [i for i, w in enumerate(scan.words) if not w.margin]
    line_ends = {
        i for i, k in zip(body, body[1:], strict=False) if scan.words[k].line != scan.words[i].line
    }
    matcher = difflib.SequenceMatcher(None, ours, theirs, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "insert" and i1 - 1 in line_ends:
            # Between two printed lines, next to a mark: the mark, read into the text
            # where the page's own reading has nothing ("solemnemente y b pongo").
            line = scan.words[i1 - 1].line
            if {line, line + 1} & mark_lines:
                drop.update(j for j in range(j1, j2) if is_mark(theirs[j]))
        for k in range(i2 - i1):
            if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
                to_theirs[i1 + k] = j1 + k
                margin = scan.words[i1 + k].margin
                if margin and (op == "equal" or len(theirs[j1 + k]) <= 3):
                    drop.add(j1 + k)  # Paddle read the mark into the text
            elif op in ("replace", "delete"):
                to_theirs[i1 + k] = min(j1 + k, j2 - 1) if j2 > j1 else j1
    marks = []
    for mark in scan.marks:
        first = next(
            (i for i, w in enumerate(scan.words) if w.line == mark.line and not w.margin), None
        )
        j = to_theirs.get(first) if first is not None else None
        while j is not None and j in drop:
            j += 1
        if j is not None and j < len(where):
            block, index = where[j]
            kept = sum(1 for k, (b, _) in enumerate(where[:j]) if b == block and k in drop)
            marks.append((block, index - kept, mark.reading))
    out = []
    for b, text in enumerate(texts):
        dropped = {where[j][1] for j in drop if where[j][0] == b}
        spans = [m.span() for i, m in enumerate(re.finditer(r"\S+\s*", text)) if i in dropped]
        for start, end in reversed(spans):
            text = text[:start] + text[end:]
        out.append(text)
    return out, marks

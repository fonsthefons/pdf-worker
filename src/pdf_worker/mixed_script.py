"""Text in two scripts at once: a table of Greek variants with Spanish/Latin comments.

PaddleOCR-VL reads polytonic Greek as Latin look-alikes ("τὰ δέοντα" -> "tà šèovta").
Tesseract reads it well with its Greek model but then garbles the Latin words
("corchetes" -> "οογέπειες"), and the other way round with the main language. So the
region is read twice and, word by word (matched by position), the more confident
reading is kept.
"""

import subprocess
from dataclasses import dataclass

import pymupdf

GREEK = "grc"
_DPI = 400
_MIN_OVERLAP = 0.5  # of the smaller box: the same word in both readings


@dataclass(frozen=True)
class Word:
    box: tuple[int, int, int, int]
    conf: float
    text: str
    line: tuple  # Tesseract's (block, paragraph, line)


def read_mixed(
    page: pymupdf.Page, rect: pymupdf.Rect, tesseract: str, language: str, second: str = GREEK
) -> list[str]:
    """The lines of ``rect`` on ``page``, each word from whichever of ``language`` and
    ``second`` read it more confidently."""
    pix = page.get_pixmap(dpi=_DPI, clip=rect, colorspace=pymupdf.csGRAY, annots=False)
    png = pix.tobytes("png")
    return merge_readings(_tsv(png, tesseract, language), _tsv(png, tesseract, second))


def merge_readings(main: list[Word], other: list[Word]) -> list[str]:
    """``main``'s lines, each word replaced by ``other``'s reading of the same box when
    that one is more confident."""
    lines: dict[tuple, list[str]] = {}
    used: set[int] = set()
    for word in main:
        match = None
        for i, candidate in enumerate(other):
            if i not in used and _overlap(word.box, candidate.box) >= _MIN_OVERLAP:
                match = i
                break
        text = word.text
        if match is not None:
            used.add(match)
            if other[match].conf > word.conf:
                text = other[match].text
        lines.setdefault(word.line, []).append(text)
    return [" ".join(words) for words in lines.values()]


def _overlap(a: tuple, b: tuple) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / max(smaller, 1)


def _tsv(png: bytes, tesseract: str, language: str) -> list[Word]:
    result = subprocess.run(
        [tesseract, "stdin", "stdout", "-l", language, "--psm", "6", "--dpi", str(_DPI), "tsv"],
        input=png,
        capture_output=True,
        check=False,
    )
    words = []
    for row in result.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
        cells = row.split("\t")
        if len(cells) == 12 and cells[0] == "5" and cells[11].strip():
            x, y, w, h = map(int, cells[6:10])
            words.append(Word((x, y, x + w, y + h), float(cells[10]), cells[11], tuple(cells[2:5])))
    return words

"""Fix OCR misreadings by asking more engines: a word-by-word majority vote.

A poor scan's text layer misreads a few words in every hundred ("parce" for "parte",
"Jo" for "lo"). Other OCR engines misread different words. Each scanned page is read
again by Tesseract and by Apple Vision; the readings are aligned word by word with the
page's own layer, and where both other readings agree on another word, that word
wins. On the sample book (Platón, Diálogos VI) word recall went from 92.4% to 93.2% on
clean pages and from 94.5% to 96.7% on underlined ones, and precision rose with it.

The fixes are stored on each page (``/PdfWorkerFixes``: the word's box, the old and the
new word) and applied by ``pdf_worker.layout.page_lines``, so every command reads the
corrected words while sizes, fonts and positions stay as they were.

Apple Vision comes from ``ocrmac`` (macOS). Without it there is no majority to be had
and pages are left as they are.
"""

import difflib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pymupdf

from pdf_worker import tesseract_cache

if TYPE_CHECKING:
    import numpy as np

FIXES_KEY = "PdfWorkerFixes"
_DPI = 300
_LETTERS_RE = re.compile(r"[^\W\d_]+")
# Tesseract language -> Apple Vision language.
_VISION_LANGUAGES = {
    "spa": "es-ES",
    "eng": "en-US",
    "fra": "fr-FR",
    "deu": "de-DE",
    "ita": "it-IT",
    "por": "pt-BR",
}


@dataclass(frozen=True)
class Token:
    text: str
    bbox: tuple[float, float, float, float]


@dataclass
class VoteReport:
    pages: int = 0  # pages read again
    fixes: int = 0  # words changed
    skipped: str = ""  # why nothing was done, if so


def vision_available() -> bool:
    try:
        import ocrmac  # noqa: F401
    except ImportError:
        return False
    return True


def vote_pdf(
    pdf_path: str | Path,
    output_path: str | Path,
    languages: Collection[str],
    original: str | Path | None = None,
    redone: Collection[int] = (),
    jobs: int = 4,
) -> VoteReport:
    """Write ``output_path``: ``pdf_path`` with per-word fixes on its scanned pages.

    ``redone`` pages (1-based) were OCR'd by Tesseract from ``original``, whose layer
    then stands in for the Tesseract re-read (the same engine twice would agree with
    itself).
    """
    from pdf_worker.ocr import tesseract_path

    report = VoteReport()
    if not vision_available():
        report.skipped = "Apple Vision (ocrmac) is not available"
        return report
    tesseract = tesseract_path()
    language = "+".join(languages)
    with pymupdf.open(pdf_path) as doc, pymupdf.open(original or pdf_path) as source:
        indexes = [i for i in range(doc.page_count) if _is_scanned(doc.load_page(i))]

        def read(index: int) -> list[list[str]]:
            gray = _page_image(doc.load_page(index))
            others = [_vision_words(gray, languages)]
            if index + 1 in redone:
                others.append([t.text for t in page_tokens(source.load_page(index))])
            else:
                others.append(_tesseract_words(gray, tesseract, language))
            return others

        # Tesseract runs as a subprocess, so threads read pages in parallel.
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            readings = dict(zip(indexes, pool.map(read, indexes), strict=True))
        counts = Counter(
            token.text.lower()
            for i in range(doc.page_count)
            for token in page_tokens(doc.load_page(i))
        )
        for index, others in readings.items():
            page = doc.load_page(index)
            fixes = vote(page_tokens(page), others, counts)
            if fixes:
                doc.xref_set_key(page.xref, FIXES_KEY, pymupdf.get_pdf_str(json.dumps(fixes)))
            report.fixes += len(fixes)
        report.pages = len(indexes)
        doc.save(output_path, garbage=3, deflate=True)
    return report


def vote(tokens: list[Token], others: list[list[str]], counts: Counter) -> list[list]:
    """Fixes ``[x0, y0, x1, y1, old, new]`` where every other reading agrees on a
    different word than the page's own token (compared ignoring case).

    The engines sometimes misread a broken letter the same way ("el" -> "ol"), so the
    new word must also be a word of the book (``counts``, from its own layer) and more
    common there than the old one, unless only an accent is added ("si" -> "sí").
    Accents are never taken away."""
    words = [t.text.lower() for t in tokens]
    votes = [Counter() for _ in tokens]
    for other in others:
        lowered = [w.lower() for w in other]
        matcher = difflib.SequenceMatcher(None, words, lowered, autojunk=False)
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "replace" and i2 - i1 == j2 - j1:
                for k in range(i2 - i1):
                    votes[i1 + k][lowered[j1 + k]] += 1
    fixes = []
    for token, tally in zip(tokens, votes, strict=True):
        if not tally:
            continue
        word, count = tally.most_common(1)[0]
        if count < len(others):  # the other readings must all agree, against the page
            continue
        old = token.text.lower()
        accent_only = _base(word) == _base(old)
        if accent_only and len(_marks(word)) <= len(_marks(old)):
            continue  # engines drop accents together ("así" -> "asi"); never take one away
        # The old word's count includes this very token: leave it out.
        if counts[word] and (accent_only or counts[word] > counts[old] - 1):
            fixes.append([*token.bbox, token.text, _same_case(word, token.text)])
    return fixes


def _marks(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word) if unicodedata.combining(c))


def _base(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word) if not unicodedata.combining(c))


def page_tokens(page: pymupdf.Page) -> list[Token]:
    """The page's words (letter runs) with their boxes, lines top to bottom."""
    lines = [
        line
        for block in page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
        for line in block.get("lines", ())
    ]
    lines.sort(key=lambda line: (line["bbox"][1], line["bbox"][0]))
    tokens = []
    for line in lines:
        chars = [char for span in line["spans"] for char in span["chars"]]
        for run in _letter_runs(chars):
            tokens.append(Token("".join(c["c"] for c in run), _union(run)))
    return tokens


def apply_fixes(chars: list[dict], fixes: list[list]) -> None:
    """Put fixed words into a line's ``rawdict`` characters: the old word's first
    character takes the new word and the rest go empty, so positions stay the same."""
    for run in _letter_runs(chars):
        text = "".join(c["c"] for c in run)
        x0, y0, x1, y1 = _union(run)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for fx0, fy0, fx1, fy1, old, new in fixes:
            if old == text and fx0 <= cx <= fx1 and fy0 <= cy <= fy1:
                run[0]["c"] = new
                for other in run[1:]:
                    other["c"] = ""
                break


def _letter_runs(chars: list[dict]) -> list[list[dict]]:
    runs: list[list[dict]] = []
    current: list[dict] = []
    for char in chars:
        if char["c"].isalpha():
            current.append(char)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def page_fixes(page: pymupdf.Page) -> list[list]:
    kind, value = page.parent.xref_get_key(page.xref, FIXES_KEY)
    if kind != "string":
        return []
    try:
        return json.loads(value)
    except ValueError:
        return []


def _same_case(word: str, like: str) -> str:
    if like.isupper() and len(like) > 1:
        return word.upper()
    if like[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


def _union(chars: list[dict]) -> tuple[float, float, float, float]:
    return (
        min(c["bbox"][0] for c in chars),
        min(c["bbox"][1] for c in chars),
        max(c["bbox"][2] for c in chars),
        max(c["bbox"][3] for c in chars),
    )


def _is_scanned(page: pymupdf.Page) -> bool:
    from pdf_worker.ocr_check import _is_scanned as is_scanned

    return is_scanned(page)


def _page_image(page: pymupdf.Page) -> "np.ndarray":
    """300 dpi greyscale, with hand-drawn underlines erased (if any)."""
    import numpy as np

    from pdf_worker.underlines import MIN_UNDERLINES, erase_underlines

    pix = page.get_pixmap(dpi=_DPI, colorspace=pymupdf.csGRAY, annots=False)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)
    gray = gray[:, : pix.width].copy()
    cleaned, broken = erase_underlines(gray, _DPI)
    return cleaned if broken >= MIN_UNDERLINES else gray


def _tesseract_words(gray: "np.ndarray", tesseract: str, language: str) -> list[str]:
    import cv2

    ok, png = cv2.imencode(".png", gray)
    stdout = tesseract_cache.run(
        tesseract,
        ["stdin", "stdout", "-l", language, "--dpi", str(_DPI)],
        png.tobytes() if ok else b"",
    )
    return _words(stdout.decode("utf-8", errors="replace"))


def _vision_words(gray: "np.ndarray", languages: Collection[str]) -> list[str]:
    from ocrmac import ocrmac
    from PIL import Image

    preferred = [_VISION_LANGUAGES[code] for code in languages if code in _VISION_LANGUAGES]
    found = ocrmac.OCR(Image.fromarray(gray), language_preference=preferred or None).recognize()
    # (text, confidence, (x, y, w, h)), y measured from the bottom: read top down.
    found.sort(key=lambda item: (-round(item[2][1] + item[2][3], 2), item[2][0]))
    return _words("\n".join(item[0] for item in found))


def _words(text: str) -> list[str]:
    """Letter runs. Hyphenation stays ("refuta", "ción"), as in the page's own layer."""
    return _LETTERS_RE.findall(text)

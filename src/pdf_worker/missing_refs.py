"""Find note references the OCR lost, on the page of their note.

A page's notes say which references must be in its text. When one is missing after
``note_numbers.fix_refs`` (Paddle and Tesseract both lost "causa⁸"), it lies between the
page's neighbouring references, usually a few lines. Three tries look there, cheapest
first, and stop at the first that finds it:

1. the PDF's own text layer (an older OCR): the number set smaller, right after a word;
2. Tesseract again, on just those lines at a high resolution;
3. PaddleOCR-VL again, on a crop of those lines.

A try counts only when it gives exactly one word with the number, and that word is in
the stretch of Paddle's text exactly once. Otherwise the reference stays missing.
"""

import re
import shutil
import tempfile
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path

import pymupdf

from pdf_worker.margin_refs import _tesseract_lines, norm
from pdf_worker.note_numbers import SUPERSCRIPT_RE, add_ref, from_sup, sup

_SMALLER = 0.85  # a reference is set at most this share of its word's size
_PAD = 4  # points around the stretch: a raised number reaches above the line
_TESS_DPI = 600
_CROP_DPI = 400
_GLUED_RE = re.compile(r"^(.*[^\W\d_])(\d{1,3})\W*$")  # Tesseract's "causa8."
_BODY_LABELS = {"text"}

Try = Callable[[pymupdf.Page, pymupdf.Rect, int], str | None]


def missing_numbers(blocks: Sequence[list]) -> list[int]:
    """The numbers of the page's notes that no reference in its text has."""
    notes = {
        from_sup(m.group())
        for b in blocks
        if b[0] == "footnote"
        for m in [SUPERSCRIPT_RE.match(b[2])]
        if m
    }
    refs = {from_sup(r) for b in blocks if b[0] != "footnote" for r in SUPERSCRIPT_RE.findall(b[2])}
    return sorted(notes - refs)


def restore(
    page: pymupdf.Page, blocks: list[list], tries: Sequence[tuple[str, Try]]
) -> list[tuple[int, str]]:
    """Put back the page's missing references in ``blocks`` (``[label, rect, text]``,
    changed in place). Returns ``[(number, name of the try that found it)]``."""
    found = []
    for number in missing_numbers(blocks):
        words = [
            (b, m)
            for b, block in enumerate(blocks)
            if block[0] in _BODY_LABELS
            for m in re.finditer(r"\S+", block[2])
        ]
        if not words:
            break
        lo, hi = _stretch(words, number)
        region = pymupdf.Rect()
        for b in {words[g][0] for g in range(lo, hi + 1)}:
            region |= blocks[b][1]
        region = (region + (-_PAD, -_PAD, _PAD, _PAD)) & page.rect
        for name, attempt in tries:
            word = attempt(page, region, number)
            g = _place(words, lo, hi, word) if word else None
            if g is not None:
                b, m = words[g]
                blocks[b][2] = (
                    blocks[b][2][: m.start()] + add_ref(m.group(), number) + blocks[b][2][m.end() :]
                )
                found.append((number, name))
                break
    return found


def _stretch(words, number: int) -> tuple[int, int]:
    """The words between the references before and after ``number`` (inclusive)."""
    lo, hi = 0, len(words) - 1
    for g, (_, m) in enumerate(words):
        for r in SUPERSCRIPT_RE.findall(m.group()):
            if from_sup(r) < number:
                lo = g
            elif from_sup(r) > number and hi == len(words) - 1:
                hi = g
    return lo, max(lo, hi)


def _place(words, lo: int, hi: int, word: str) -> int | None:
    """The one word in the stretch that is ``word`` and has no reference yet."""
    key = norm(word)
    hits = [
        g
        for g in range(lo, hi + 1)
        if key
        and norm(words[g][1].group()) == key
        and not SUPERSCRIPT_RE.search(words[g][1].group())
    ]
    return hits[0] if len(hits) == 1 else None


def _one(candidates: list[str]) -> str | None:
    return candidates[0] if len(candidates) == 1 else None


# -- the tries ----------------------------------------------------------------------------


def text_layer(page: pymupdf.Page, region: pymupdf.Rect, number: int) -> str | None:
    """The word before a smaller ``number`` in the page's own text layer."""
    want = re.compile(rf"{number}[.,;:]?")
    candidates = []
    for block in page.get_text("dict", clip=region)["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            for i, span in enumerate(spans):
                if not want.fullmatch(span["text"].strip()) or i == 0:
                    continue
                word = ""
                size = 0.0
                for prev in reversed(spans[:i]):  # the word may be in pieces: "lím" "ite,"
                    if not prev["text"].strip() or prev["text"][-1].isspace():
                        break
                    piece = prev["text"].split()[-1]
                    word = piece + word
                    size = max(size, prev["size"])
                    if piece != prev["text"]:
                        break  # the span holds earlier words too
                if word and word[-1].isalpha() and span["size"] <= size * _SMALLER:
                    candidates.append(word)
    return _one(candidates)


def tesseract_try(tesseract: str, language: str) -> Try:
    def attempt(page: pymupdf.Page, region: pymupdf.Rect, number: int) -> str | None:
        import numpy

        pix = page.get_pixmap(dpi=_TESS_DPI, clip=region, colorspace=pymupdf.csGRAY, annots=False)
        gray = numpy.frombuffer(pix.samples, dtype=numpy.uint8).reshape(pix.height, pix.width)
        tokens = [w[4] for line in _tesseract_lines(gray, tesseract, language) for w in line]
        return _one(_after_word(tokens, number))

    return attempt


def _after_word(tokens: Sequence[str], number: int) -> list[str]:
    """Words a reading shows ``number`` right after: "causa8." or "causa 8."."""
    out = []
    for i, token in enumerate(tokens):
        glued = _GLUED_RE.match(token)
        if glued and int(glued.group(2)) == number:
            out.append(glued.group(1))
        elif i and re.fullmatch(rf"{number}\W*", token) and tokens[i - 1][-1:].isalpha():
            out.append(tokens[i - 1])
    return out


class PaddleClips:
    """Paddle on a crop of the page. The MLX server starts at the first crop and stops
    at ``close``. shortcut: crops are not cached, so a rerun may read them differently;
    cache them like the pages if this try ends up deciding often."""

    def __init__(self) -> None:
        self._stack = ExitStack()
        self._server: str | None = None
        self._work: Path | None = None
        self.failed = False

    def __call__(self, page: pymupdf.Page, region: pymupdf.Rect, number: int) -> str | None:
        from pdf_worker import paddle_ocr
        from pdf_worker.ocr import OcrError

        if self.failed:
            return None
        try:
            python = paddle_ocr.paddle_python()
            if self._server is None:
                root = paddle_ocr.cache_dir()
                root.mkdir(parents=True, exist_ok=True)
                self._work = Path(tempfile.mkdtemp(dir=root, prefix=".clips."))
                self._stack.callback(shutil.rmtree, self._work, True)
                self._server = self._stack.enter_context(paddle_ocr._mlx_server(python))
            crop = self._work / "crop.pdf"
            with pymupdf.open() as doc:
                doc.new_page(width=region.width, height=region.height).show_pdf_page(
                    pymupdf.Rect(0, 0, region.width, region.height),
                    page.parent,
                    page.number,
                    clip=region,
                )
                doc.save(crop)
            out = self._work / "crop.jsonl"
            paddle_ocr._run_worker(
                python, crop, [0], out, self._work, self._server, False, dpi=_CROP_DPI
            )
            rows = paddle_ocr._read_rows(out)
        except OcrError:
            self.failed = True  # no Paddle here: don't try again on every page
            return None
        text = " ".join(
            paddle_ocr.clean_text(b.get("text", "")) for row in rows.values() for b in row["blocks"]
        )
        candidates = [
            m.group(1)
            for m in re.finditer(rf"(\S*[^\W\d_])[^\w\s]?{sup(number)}(?![⁰¹²³⁴⁵⁶⁷⁸⁹])", text)
        ]
        return _one(candidates)

    def close(self) -> None:
        self._stack.close()

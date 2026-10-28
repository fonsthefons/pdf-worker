"""Pick the best of several PDFs of one book (a folder in the inbox) before building it.

Ranked by what matters most to the build: how much OCR the copy needs (none; only the
pages with no text; the whole book), single pages before two-page spreads, then the
suspicious words per 1,000 in a sample of its text layer (split words, which the build
joins, not counted). A few seconds a copy: nothing is built.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from ai_client import check

from pdf_worker.convert import guess_language
from pdf_worker.document import open_pdf
from pdf_worker.fixes import SPELL_LANGUAGES, _words
from pdf_worker.ocr_check import assess_text_layer

OCR_NEEDED = ("none", "pages with no text", "whole book")  # best first
_SAMPLE_PAGES = 20
_WORD_RE = re.compile(r"[^\W\d_]+")


@dataclass(frozen=True)
class CopyCheck:
    path: Path
    pages: int
    ocr: str  # one of OCR_NEEDED
    spreads: bool  # most pages are wider than tall: two book pages side by side
    suspicious: float  # per 1,000 words of the sample; 0 when the language isn't checked

    @property
    def rank(self) -> tuple:
        return OCR_NEEDED.index(self.ocr), self.spreads, self.suspicious

    def summary(self) -> str:
        spreads = ", two-page spreads" if self.spreads else ""
        return (
            f"{self.pages} pages, OCR: {self.ocr}{spreads}, "
            f"{self.suspicious:.1f} suspicious words per 1,000"
        )


def check_copy(path: str | Path) -> CopyCheck:
    path = Path(path)
    with open_pdf(path) as doc:
        layer = assess_text_layer(doc)
        count = doc.page_count
        spreads = sum(p.rect.width > p.rect.height for p in doc) * 2 > count
        step = max(1, count // _SAMPLE_PAGES)
        text = "\n".join(doc[i].get_text() for i in range(0, count, step))
    ocr = {None: "none", "skip": "pages with no text"}.get(layer.mode, "whole book")
    language = guess_language(text)
    suspicious = 0.0
    if language in SPELL_LANGUAGES:
        flags = [f for f in check.text(text, _words(language)) if f.kind != "split"]
        suspicious = 1000 * len(flags) / max(1, len(_WORD_RE.findall(text)))
    return CopyCheck(path, count, ocr, spreads, suspicious)


def rank_copies(paths: list[Path]) -> list[CopyCheck]:
    """The copies' checks, best first."""
    return sorted((check_copy(p) for p in paths), key=lambda c: c.rank)

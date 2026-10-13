"""Does a PDF need OCR, and which kind? A quick look at a sample of its pages.

* No text on most pages: OCR the pages without text (``skip``).
* Scanned pages (one full-page image each) whose text layer is broken into single
  words or full of misread characters: replace that layer (``redo``).
* Otherwise the text layer is good: no OCR.
"""

import re
from dataclasses import dataclass

import pymupdf

from pdf_worker.layout import page_lines

_SAMPLE_PAGES = 24
_FULL_PAGE_SHARE = 0.8
# Thresholds, from the samples: Kant / the court opinion / 9-11 report (digital), the
# Familia Romana and Gibbon scans (old OCR layers).
_MIN_TEXT_PAGES = 0.5  # share of pages that must have text
# Share of lines whose words have very different font sizes: Tesseract layers ≤ 0.07,
# archive.org's word-by-word layer 0.3.
_MAX_JITTERY_LINES = 0.2
_MAX_SUSPECT_WORDS = 0.01  # share of words that look misread
_WORD_RE = re.compile(r"\S+")
# Misread words: digits inside letters ("0RBERG", "satis8"), stray symbols inside a
# word, or a capital after lower-case letters ("liBer").
_SUSPECT_RE = re.compile(r"[^\W\d_]\d|\d[^\W\d_]{2}|[^\W\d_][~|\\^{}<>°][^\W\d_]|[a-z][A-Z]")


@dataclass(frozen=True)
class TextLayerReport:
    mode: str | None  # "skip", "redo", or None (no OCR needed)
    reason: str
    text_pages: float = 0.0  # share of sampled pages with text
    scanned_pages: float = 0.0  # share of sampled pages that are one full-page image
    jittery_lines: float = 0.0
    suspect_words: float = 0.0


def assess_text_layer(doc: pymupdf.Document) -> TextLayerReport:
    count = doc.page_count
    if not count:
        return TextLayerReport(None, "empty document")
    step = max(1, count // _SAMPLE_PAGES)
    indices = list(range(0, count, step))[:_SAMPLE_PAGES]
    with_text = scanned = words = lines_seen = suspect = jittery = 0
    for index in indices:
        page = doc.load_page(index)
        lines = [line for line in page_lines(page) if line.text.strip()]
        if lines:
            with_text += 1
        if _is_scanned(page):
            scanned += 1
        for line in lines:
            tokens = _WORD_RE.findall(line.text)
            words += len(tokens)
            suspect += sum(1 for token in tokens if _SUSPECT_RE.search(token))
            sizes = [span["size"] for span in line.spans if span["text"].strip()]
            if len(sizes) > 1 and max(sizes) > min(sizes) * 1.25:
                jittery += 1
        lines_seen += len(lines)
    sampled = len(indices)
    report = dict(
        text_pages=with_text / sampled,
        scanned_pages=scanned / sampled,
        jittery_lines=jittery / lines_seen if lines_seen else 0.0,
        suspect_words=suspect / words if words else 0.0,
    )
    if report["text_pages"] < _MIN_TEXT_PAGES:
        return TextLayerReport("skip", "most pages have no text layer", **report)
    if report["scanned_pages"] >= 0.5:
        if report["jittery_lines"] > _MAX_JITTERY_LINES:
            return TextLayerReport("redo", "the scan's text layer is word-by-word", **report)
        if report["suspect_words"] > _MAX_SUSPECT_WORDS:
            return TextLayerReport("redo", "the scan's text layer has many misreadings", **report)
        if report["text_pages"] < 1.0:
            return TextLayerReport("skip", "some scanned pages have no text", **report)
    return TextLayerReport(None, "the text layer looks good", **report)


def _is_scanned(page: pymupdf.Page) -> bool:
    area = page.rect.width * page.rect.height
    for info in page.get_images(full=True):
        for rect in page.get_image_rects(info[0]):
            if rect.width * rect.height >= area * _FULL_PAGE_SHARE:
                return True
    return False

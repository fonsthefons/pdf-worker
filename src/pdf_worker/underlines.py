"""Hand-drawn underlines in scanned books: find them, and erase them before OCR.

Readers underline passages in pencil or pen. On a black-and-white scan the line breaks
up into dots and dashes just under the text, and OCR reads them as letters ("jla",
"deseos.)La", "iinujltáiieanjentee"). Underline fragments are thin blobs that line up
side by side at one height; full stops, accents and dashes stand alone. Erasing the
chains gives Tesseract clean text: on the sample book (Platón, Diálogos VI) word recall
on an underlined page went from 85% (the scan's own OCR layer) to 95%.

Needs numpy and OpenCV (the ``ocr`` extra).
"""

import cv2
import numpy as np
import pymupdf

# Sizes in pixels at 300 dpi (scaled to the image's resolution): a fragment is at most
# 8 px tall; fragments chain when at most 25 px apart and 5 px off level; a chain of 3+
# fragments at least 80 px long is an underline, and so is one thin rule twice as long.
_REFERENCE_DPI = 300
_MAX_HEIGHT = 8
_MAX_GAP = 25
_MAX_DRIFT = 5
_MIN_LENGTH = 80
_MIN_FRAGMENTS = 3
# A page with this many broken (hand-drawn) underlines is an underlined page; printed
# rules such as a footnote separator are one solid line and don't count.
MIN_UNDERLINES = 3
_DETECT_DPI = 150


def find_underlines(ink: np.ndarray, dpi: float) -> tuple[np.ndarray, int]:
    """``ink`` is a 2-D array, non-zero where the page is dark.

    Returns a boolean mask of the underline pixels, and how many broken underlines
    (chains of fragments) were found.
    """
    scale = dpi / _REFERENCE_DPI
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        (ink > 0).astype(np.uint8), connectivity=8
    )
    lefts = stats[:, cv2.CC_STAT_LEFT]
    rights = lefts + stats[:, cv2.CC_STAT_WIDTH]
    thin = [i for i in range(1, count) if stats[i, cv2.CC_STAT_HEIGHT] <= _MAX_HEIGHT * scale]
    thin.sort(key=lambda i: lefts[i])
    parent = {i: i for i in thin}

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for position, a in enumerate(thin):
        for b in thin[position + 1 :]:
            if lefts[b] - rights[a] > _MAX_GAP * scale:
                break
            if abs(centroids[a][1] - centroids[b][1]) <= _MAX_DRIFT * scale:
                parent[root(b)] = root(a)
    chains: dict[int, list[int]] = {}
    for i in thin:
        chains.setdefault(root(i), []).append(i)
    erase = np.zeros(count, dtype=bool)
    broken = 0
    for members in chains.values():
        length = max(rights[i] for i in members) - min(lefts[i] for i in members)
        if len(members) >= _MIN_FRAGMENTS and length >= _MIN_LENGTH * scale:
            broken += 1
            erase[members] = True
        elif length >= 2 * _MIN_LENGTH * scale:
            erase[members] = True
    return erase[labels], broken


def erase_underlines(gray: np.ndarray, dpi: float) -> tuple[np.ndarray, int]:
    """The 8-bit grayscale page as black and white with its underlines erased, and how
    many broken underlines there were. Black and white drops the faint grey of pencil
    marks too thin to be ink."""
    ink = gray < 128
    mask, broken = find_underlines(ink, dpi)
    return np.where(ink & ~mask, 0, 255).astype(np.uint8), broken


def is_underlined(page: pymupdf.Page) -> bool:
    """Does this (scanned) page have hand-drawn underlines? A quick low-resolution look."""
    pix = page.get_pixmap(dpi=_DETECT_DPI, colorspace=pymupdf.csGRAY, annots=False)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)
    _, broken = find_underlines(gray[:, : pix.width] < 128, _DETECT_DPI)
    return broken >= MIN_UNDERLINES

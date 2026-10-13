"""Pictures for rebuilt books: embedded figures, illustrations in scans, and a cover.

Everything is rendered from the page (``get_pixmap`` with a clip) rather than copied out
of the PDF: that handles every image codec, transparency masks and drawings on top of
the picture, and gives small JPEGs. One page is handled at a time.

* Digital PDFs: each embedded image that isn't a full-page background and isn't
  repeated on many pages (logos, rules) becomes a figure.
* Scanned pages (one full-page image): illustrations are found as tall bands of ink
  with no lines of text, and cropped from the scan.
"""

from dataclasses import dataclass

import pymupdf

from pdf_worker.layout import Line

# Rendering: enough for an e-reader, small enough for Send to Kindle's size limits.
FIGURE_DPI = 120
COVER_HEIGHT_PX = 1600
JPEG_QUALITY = 80
# An image covering this share of the page is the page itself (a scan or background).
_FULL_PAGE_SHARE = 0.8
# Figures smaller than this (share of page area, or points on a side) are decoration.
_MIN_SHARE = 0.015
_MIN_SIDE = 36.0
# Scans: analysis resolution, darkness threshold, and minimum illustration size.
_SCAN_DPI = 36
_INK_CONTRAST = 55  # grey levels below the paper that count as ink
_MIN_INK_SHARE = 0.03  # share of a row's pixels that must be dark
_MIN_BAND_SHARE = 0.12  # share of the page height
_MIN_WIDTH_SHARE = 0.25  # share of the page width
# A column (row) in the outer tenth of the page that is dark over 60% of it is a scan edge.
_EDGE_SHARE = 0.6
_EDGE_ZONE = 0.1
_MAX_GAP_ROWS = 3
# Text lines at least this long count as text; shorter ones may be labels in a picture.
_TEXT_LINE_CHARS = 12
_PAD = 3.0  # points of margin around a cropped picture


@dataclass(frozen=True)
class PageImage:
    rect: pymupdf.Rect  # where the picture sits on the page
    data: bytes  # JPEG
    width: int  # pixels
    height: int

    @property
    def top(self) -> float:
        return self.rect.y0


def page_images(
    page: pymupdf.Page, lines: list[Line], repeated: set[int] = frozenset()
) -> list[PageImage]:
    """The page's pictures, top to bottom. ``repeated`` are image xrefs to skip."""
    area = page.rect.width * page.rect.height
    rects: list[pymupdf.Rect] = []
    scanned = False
    for info in page.get_images(full=True):
        xref = info[0]
        if xref in repeated:
            continue
        for rect in page.get_image_rects(xref):
            rect = rect & page.rect
            if rect.is_empty:
                continue
            share = rect.width * rect.height / area
            if share >= _FULL_PAGE_SHARE:
                scanned = True
            elif share >= _MIN_SHARE and min(rect.width, rect.height) >= _MIN_SIDE:
                rects.append(rect)
    if scanned and not rects:
        rects = _illustrations_in_scan(page, lines)
    return [_render(page, rect) for rect in _merge(rects)]


def render_cover(page: pymupdf.Page) -> bytes:
    """The first page as a JPEG cover, about ``COVER_HEIGHT_PX`` tall."""
    zoom = COVER_HEIGHT_PX / max(page.rect.height, 1.0)
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB)
    return pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY)


def labels_inside(lines: list[Line], images: list[PageImage]) -> set[int]:
    """Indices of short lines lying inside a picture: its labels, kept in the image."""
    inside = set()
    for index, line in enumerate(lines):
        if len(line.text.strip()) >= _TEXT_LINE_CHARS:
            continue
        box = pymupdf.Rect(line.bbox)
        if any(image.rect.contains(box) for image in images):
            inside.add(index)
    return inside


def _render(page: pymupdf.Page, rect: pymupdf.Rect) -> PageImage:
    rect = (rect + (-_PAD, -_PAD, _PAD, _PAD)) & page.rect
    pixmap = page.get_pixmap(clip=rect, dpi=FIGURE_DPI, colorspace=pymupdf.csRGB)
    data = pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
    return PageImage(rect=rect, data=data, width=pixmap.width, height=pixmap.height)


def _merge(rects: list[pymupdf.Rect]) -> list[pymupdf.Rect]:
    """Overlapping pieces of one figure (tiled images) become one, top to bottom."""
    merged: list[pymupdf.Rect] = []
    for rect in sorted(rects, key=lambda r: (r.y0, r.x0)):
        for i, other in enumerate(merged):
            if other.intersects(rect):
                merged[i] = other | rect
                break
        else:
            merged.append(pymupdf.Rect(rect))
    return merged


def _illustrations_in_scan(page: pymupdf.Page, lines: list[Line]) -> list[pymupdf.Rect]:
    """Tall bands of ink without lines of text, on a scanned page."""
    pixmap = page.get_pixmap(dpi=_SCAN_DPI, colorspace=pymupdf.csGRAY)
    width, height, samples = pixmap.width, pixmap.height, pixmap.samples
    scale = height / page.rect.height
    # "Ink" is anything clearly darker than this scan's paper (watercolours are light).
    sample = sorted(samples[:: max(1, len(samples) // 4000)])
    paper = sample[int(len(sample) * 0.9)] if sample else 255
    dark = paper - _INK_CONTRAST
    # Blank out every line of text, so only picture ink remains (a picture's labels
    # just leave small holes in it).
    pixels = bytearray(samples)
    blank = bytes([255]) * width
    for line in lines:
        if not line.text.strip():
            continue
        x0, x1 = max(0, int(line.bbox[0] * scale) - 1), min(width, int(line.bbox[2] * scale) + 2)
        for row in range(
            max(0, int(line.bbox[1] * scale) - 1), min(height, int(line.bbox[3] * scale) + 2)
        ):
            pixels[row * width + x0 : row * width + x1] = blank[: x1 - x0]
    _blank_scan_edges(pixels, width, height, dark)
    samples = bytes(pixels)
    min_ink = max(1, int(width * _MIN_INK_SHARE))
    inked = [
        sum(1 for value in samples[row * width : (row + 1) * width] if value < dark) >= min_ink
        for row in range(height)
    ]
    rects = []
    for start, end in _runs(inked):
        if end - start < height * _MIN_BAND_SHARE:
            continue
        left, right = _ink_columns(samples, width, start, end, dark)
        if right - left < width * _MIN_WIDTH_SHARE:
            continue
        rects.append(
            pymupdf.Rect(left / scale, start / scale, right / scale, end / scale) & page.rect
        )
    return rects


def _blank_scan_edges(pixels: bytearray, width: int, height: int, dark: int) -> None:
    """Blank columns and rows near the page's edges that are dark across most of it: the
    black edges a scanner leaves beside the paper. A picture's frame only spans the
    picture, and a wide picture sits inside the margins."""
    columns = [0] * width
    rows = [0] * height
    for row in range(height):
        offset = row * width
        for column in range(width):
            if pixels[offset + column] < dark:
                columns[column] += 1
                rows[row] += 1
    near_x, near_y = int(width * _EDGE_ZONE), int(height * _EDGE_ZONE)
    for column, count in enumerate(columns):
        if count >= _EDGE_SHARE * height and not near_x <= column < width - near_x:
            for row in range(height):
                pixels[row * width + column] = 255
    for row, count in enumerate(rows):
        if count >= _EDGE_SHARE * width and not near_y <= row < height - near_y:
            pixels[row * width : (row + 1) * width] = bytes([255]) * width


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    """Runs of True rows, bridging gaps of up to ``_MAX_GAP_ROWS``."""
    runs: list[tuple[int, int]] = []
    start = None
    gap = 0
    for row, flag in enumerate(flags):
        if flag:
            if start is None:
                start = row
            gap = 0
        elif start is not None:
            gap += 1
            if gap > _MAX_GAP_ROWS:
                runs.append((start, row - gap + 1))
                start, gap = None, 0
    if start is not None:
        runs.append((start, len(flags) - gap))
    return runs


def _ink_columns(samples: bytes, width: int, start: int, end: int, dark: int) -> tuple[int, int]:
    """Left and right edges of the ink between rows ``start`` and ``end``."""
    counts = [0] * width
    for row in range(start, end):
        offset = row * width
        for column in range(width):
            if samples[offset + column] < dark:
                counts[column] += 1
    threshold = max(1, (end - start) // 10)
    columns = [c for c, n in enumerate(counts) if n >= threshold]
    return (columns[0], columns[-1] + 1) if columns else (0, 0)

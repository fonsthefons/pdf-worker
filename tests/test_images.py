import shutil
import subprocess
import zipfile

import pymupdf
import pytest

from pdf_worker.convert import convert_pdf

EPUBCHECK = shutil.which("epubcheck") or shutil.which("/opt/homebrew/bin/epubcheck")
BODY = 11
TEXT = [
    "The quick brown fox jumps over the lazy dog and keeps running far",
    "away across the green fields until the evening light finally fades",
    "into a calm and quiet night where every sound seems to have gone.",
]


def _picture(width=200, height=120, colour=(200, 40, 40)):
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pixmap.set_rect(pixmap.irect, colour)
    return pixmap


def _digital_book(tmp_path):
    """Two pages: text, a figure between paragraphs, and a logo on every page."""
    path = tmp_path / "book.pdf"
    doc = pymupdf.open()
    logo = _picture(40, 40, (0, 0, 200)).tobytes("png")
    for n in range(2):
        page = doc.new_page()
        for i, text in enumerate(TEXT):
            page.insert_text((72, 100 + 15 * i), text, fontsize=BODY)
        if n == 0:
            page.insert_image(pymupdf.Rect(72, 160, 372, 340), pixmap=_picture())
        for i, text in enumerate(TEXT):
            page.insert_text((72, 380 + 15 * i), f"After the figure: {text}", fontsize=BODY)
        page.insert_image(pymupdf.Rect(500, 30, 540, 70), stream=logo)
    doc.save(path)
    doc.close()
    return path


def _scanned_page(tmp_path):
    """A page that is one big image: a text band, an illustration, a text band."""
    source = pymupdf.open()
    page = source.new_page()
    for i, text in enumerate(TEXT * 2):
        page.insert_text((72, 90 + 15 * i), text, fontsize=BODY)
    page.draw_rect(pymupdf.Rect(100, 260, 480, 480), color=(0.2, 0.5, 0.2), fill=(0.3, 0.7, 0.3))
    for i, text in enumerate(TEXT * 2):
        page.insert_text((72, 540 + 15 * i), text, fontsize=BODY)
    scan = page.get_pixmap(dpi=100)
    path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    target = doc.new_page()
    target.insert_image(target.rect, pixmap=scan)
    # An invisible text layer, as OCR would give, for the text bands only.
    for i, text in enumerate(TEXT * 2):
        target.insert_text((72, 90 + 15 * i), text, fontsize=BODY, render_mode=3)
        target.insert_text((72, 540 + 15 * i), text, fontsize=BODY, render_mode=3)
    doc.save(path)
    doc.close()
    source.close()
    return path


def _zip_names(path):
    with zipfile.ZipFile(path) as zf:
        return zf.namelist(), {n: zf.read(n) for n in zf.namelist()}


def test_figure_is_kept_between_paragraphs_and_logo_dropped(tmp_path):
    out = tmp_path / "book.epub"

    report = convert_pdf(_digital_book(tmp_path), out, "epub")

    names, data = _zip_names(out)
    assert report.stats.images == 1  # the figure; the logo repeats on every page
    assert "OEBPS/images/img1.jpg" in names
    assert data["OEBPS/images/img1.jpg"][:2] == b"\xff\xd8"  # a JPEG
    chapter = data["OEBPS/c001.xhtml"].decode()
    before = chapter.index("lazy dog")
    figure = chapter.index('<img src="images/img1.jpg"')
    after = chapter.index("After the figure")
    assert before < figure < after


def test_cover_is_the_first_page(tmp_path):
    out = tmp_path / "book.epub"

    convert_pdf(_digital_book(tmp_path), out, "epub")

    names, data = _zip_names(out)
    opf = data["OEBPS/content.opf"].decode()
    assert 'properties="cover-image"' in opf
    assert '<meta name="cover" content="cover-image"/>' in opf
    assert opf.index('idref="cover"') < opf.index('idref="c1"')
    assert "OEBPS/images/cover.jpg" in names


def test_no_images_and_no_cover_options(tmp_path):
    out = tmp_path / "book.epub"

    report = convert_pdf(_digital_book(tmp_path), out, "epub", images=False, cover=False)

    names, _ = _zip_names(out)
    assert report.stats.images == 0
    assert not [n for n in names if n.startswith("OEBPS/images/")]


def test_illustration_is_cropped_from_a_scan(tmp_path):
    out = tmp_path / "scan.epub"

    report = convert_pdf(_scanned_page(tmp_path), out, "epub", cover=False)

    assert report.stats.images == 1
    with zipfile.ZipFile(out) as zf:
        picture = pymupdf.Pixmap(zf.read("OEBPS/images/img1.jpg"))
    # The crop is the green box (380 x 220 pt at 120 dpi), not the whole page.
    assert 600 < picture.width < 700 and 340 < picture.height < 420


def test_markdown_saves_pictures_next_to_the_file(tmp_path):
    out = tmp_path / "book.md"

    convert_pdf(_digital_book(tmp_path), out, "md")

    assert "![](<book_images/img1.jpg>)" in out.read_text(encoding="utf-8")
    assert (tmp_path / "book_images" / "img1.jpg").is_file()


@pytest.mark.skipif(EPUBCHECK is None, reason="epubcheck not installed")
def test_epub_with_pictures_passes_epubcheck(tmp_path):
    out = tmp_path / "book.epub"
    convert_pdf(_digital_book(tmp_path), out, "epub")

    result = subprocess.run([EPUBCHECK, str(out)], capture_output=True, text=True)

    assert "No errors or warnings detected" in result.stdout, result.stdout

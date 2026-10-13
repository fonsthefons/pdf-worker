import shutil
import zipfile

import pymupdf
import pytest

from pdf_worker.cli import main
from pdf_worker.ocr_check import assess_text_layer

TEXT = [
    "The quick brown fox jumps over the lazy dog and keeps running far",
    "away across the green fields until the evening light finally fades",
    "into a calm and quiet night where every sound seems to have gone.",
]
HAS_TESSERACT = bool(shutil.which("tesseract") or shutil.which("/opt/homebrew/bin/tesseract"))


def _digital(tmp_path, name="digital.pdf"):
    path = tmp_path / name
    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page()
        for i, text in enumerate(TEXT * 3):
            page.insert_text((72, 100 + 15 * i), text, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def _scan(tmp_path, name="scan.pdf", ocr_text=None):
    """Image-only pages; ``ocr_text`` adds an invisible text layer (an old OCR)."""
    source = pymupdf.open()
    page = source.new_page()
    for i, text in enumerate(TEXT * 3):
        page.insert_text((72, 100 + 18 * i), text, fontsize=14)
    picture = page.get_pixmap(dpi=200)
    path = tmp_path / name
    doc = pymupdf.open()
    for _ in range(3):
        target = doc.new_page()
        target.insert_image(target.rect, pixmap=picture)
        for i, text in enumerate(ocr_text or []):
            target.insert_text((72, 100 + 18 * i), text, fontsize=14, render_mode=3)
    doc.save(path)
    doc.close()
    source.close()
    return path


def test_digital_text_needs_no_ocr(tmp_path):
    with pymupdf.open(_digital(tmp_path)) as doc:
        report = assess_text_layer(doc)

    assert report.mode is None


def test_image_only_pages_need_ocr(tmp_path):
    with pymupdf.open(_scan(tmp_path)) as doc:
        report = assess_text_layer(doc)

    assert report.mode == "skip"
    assert report.scanned_pages == 1.0


def test_misread_ocr_layer_is_redone(tmp_path):
    garbled = ["Tbe qu1ck br0wn f0x jumps 0ver tlie lazy d0g", "a~d keeps runn1ng far awa|y"]
    with pymupdf.open(_scan(tmp_path, ocr_text=garbled)) as doc:
        report = assess_text_layer(doc)

    assert report.mode == "redo"
    assert report.suspect_words > 0.01


def test_kindle_command_on_digital_pdf(tmp_path, capsys):
    pdf = _digital(tmp_path, "book.pdf")

    assert main(["kindle", str(pdf)]) == 0

    out = capsys.readouterr().out
    assert "no OCR needed" in out
    assert zipfile.is_zipfile(tmp_path / "book.epub")


@pytest.mark.skipif(not HAS_TESSERACT, reason="Tesseract not installed")
def test_kindle_command_ocrs_a_scan(tmp_path, capsys):
    pytest.importorskip("ocrmypdf")
    pdf = _scan(tmp_path, "scan.pdf")

    assert main(["kindle", str(pdf), "--ocr-lang", "eng"]) == 0

    out = capsys.readouterr().out
    assert "so it was OCR'd (skip)" in out
    with zipfile.ZipFile(tmp_path / "scan.epub") as zf:
        text = "".join(zf.read(n).decode() for n in zf.namelist() if n.endswith(".xhtml"))
    assert "quick brown fox" in text
    assert [p.name for p in tmp_path.iterdir() if ".ocr." in p.name] == []  # temp removed

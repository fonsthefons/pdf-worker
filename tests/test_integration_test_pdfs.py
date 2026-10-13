"""Runs extraction against the real sample PDFs in test_pdfs/.

These are slower than the unit tests; skip them with ``pytest -m "not integration"``.
"""

import re
import shutil
import subprocess
import zipfile

import pymupdf
import pytest
from conftest import TEST_PDFS_DIR

from pdf_worker.convert import convert_pdf
from pdf_worker.text_extraction import extract_text_to_file

pytestmark = pytest.mark.integration

GOOD_TEXT_PDF = TEST_PDFS_DIR / "Critica de la Razon Pura - Immanuel Kant.pdf"
BAD_TEXT_PDF = TEST_PDFS_DIR / "Familia Romana Lingua Latina.pdf"
ENDNOTES_PDF = TEST_PDFS_DIR / "Magnifica Humanitas Encíclica May 15 2026.pdf"
# Public-domain downloads (see README): bottom-of-page footnotes, chapter endnotes, and a
# scanned book with footnotes.
COURT_PDF = TEST_PDFS_DIR / "Trump v CASA (US Supreme Court 2025).pdf"
REPORT_PDF = TEST_PDFS_DIR / "9-11 Commission Report.pdf"
SCAN_PDF = TEST_PDFS_DIR / "Gibbon Decline and Fall vol 1 (1872 scan).pdf"
# Born-digital Spanish reader of the Greek New Testament: polytonic Greek + Spanish.
GREEK_PDF = TEST_PDFS_DIR / "sample-text-spanish-ancient-greek.pdf"
# A poor ABBYY FineReader scan with pencil underlining (Platón, Diálogos VI).
PLATON_PDF = TEST_PDFS_DIR / "platon_dialogos_vi_bad.pdf"


def _require(path):
    if not path.is_file():
        pytest.skip(f"sample PDF not present: {path.name}")


def test_good_text_pdf_extracts_cleanly(tmp_path):
    _require(GOOD_TEXT_PDF)
    out = tmp_path / "kant.txt"

    report = extract_text_to_file(GOOD_TEXT_PDF, out)

    assert report.page_count == 206
    assert report.empty_pages == []
    head = out.read_text(encoding="utf-8")[:2000]
    assert "Crítica de la razón pura" in head


def test_bad_text_pdf_extracts_and_flags_image_only_pages(tmp_path):
    _require(BAD_TEXT_PDF)
    out = tmp_path / "familia.txt"

    report = extract_text_to_file(BAD_TEXT_PDF, out)

    assert report.page_count == 332
    # Cover and back pages are scanned images with no text layer.
    assert report.empty_pages == [1, 2, 331, 332]
    assert report.char_count > 0
    # Margin glosses, line numbers and numbered exercises must not look like notes.
    assert report.footnote_count == 0


def test_bracketed_endnotes_are_all_linked(tmp_path):
    _require(ENDNOTES_PDF)
    out = tmp_path / "humanitas.txt"

    report = extract_text_to_file(ENDNOTES_PDF, out)

    assert report.footnote_count == 224
    assert report.footnote_reference_count == 224
    assert report.undefined_footnotes == report.unreferenced_footnotes == []
    text = out.read_text(encoding="utf-8")
    assert "esclarece en el misterio del Verbo encarnado».[^1]" in text
    assert "\n[^1]: Conc. Ecum. Vat. II, Const. past. Gaudium et spes, 22" in text


def test_convert_endnotes_pdf_to_valid_epub(tmp_path):
    _require(ENDNOTES_PDF)
    out = tmp_path / "humanitas.epub"

    report = convert_pdf(ENDNOTES_PDF, out, "epub")

    assert report.stats.notes == 224
    assert report.metadata.language == "es"
    # Section subheadings are set in other (Type3) fonts without a bold flag: still
    # headings, so the EPUB's own contents lists every section.
    assert report.stats.headings >= 90
    # The index at the top links every section; each link lands on its section.
    with zipfile.ZipFile(out) as zf:
        files = {n: zf.read(n).decode() for n in zf.namelist() if n.endswith(".xhtml")}
    first = files["OEBPS/c001.xhtml"]
    href = re.search(r'<a href="(c\d+\.xhtml#\w+)">Dos imágenes bíblicas</a>', first).group(1)
    target_file, anchor = href.split("#")
    target = files[f"OEBPS/{target_file}"]
    at = target.index(f'id="{anchor}"')
    assert "Dos imágenes bíblicas" in target[at : at + 120]
    epubcheck = shutil.which("epubcheck") or shutil.which("/opt/homebrew/bin/epubcheck")
    if epubcheck:
        result = subprocess.run([epubcheck, str(out)], capture_output=True, text=True)
        assert "No errors or warnings detected" in result.stdout, result.stdout


def test_convert_book_to_markdown(tmp_path):
    _require(GOOD_TEXT_PDF)
    out = tmp_path / "kant.md"

    report = convert_pdf(GOOD_TEXT_PDF, out, "md")

    text = out.read_text(encoding="utf-8")
    assert "# Crítica de la razón pura" in text
    assert report.stats.paragraphs > 800
    # Paragraphs are reflowed: no hard line breaks inside them.
    assert "La razón humana tiene, en una especie de sus conocimientos, el destino" in text


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract not installed")
def test_ocr_redo_on_scanned_book(tmp_path):
    _require(BAD_TEXT_PDF)
    pytest.importorskip("ocrmypdf")
    from pdf_worker.ocr import ocr_pdf

    # The cover (image only) and page 25 (a poor existing OCR layer, replaced by redo).
    sample = tmp_path / "sample.pdf"
    with pymupdf.open(BAD_TEXT_PDF) as doc, pymupdf.open() as small:
        small.insert_pdf(doc, from_page=0, to_page=0)
        small.insert_pdf(doc, from_page=24, to_page=24)
        small.save(sample)

    report = ocr_pdf(sample, tmp_path / "out.pdf", mode="redo")

    assert report.languages == ["lat"] and report.languages_guessed
    assert report.empty_pages_before == [1] and report.empty_pages_after == []
    with pymupdf.open(tmp_path / "out.pdf") as doc:
        cover, body = (page.get_text("text") for page in doc)
    assert "FAMILIA" in cover
    assert "Puer qui ridet est" in body
    # Tesseract reads long vowels as accents; they are turned back into macrons.
    assert report.macrons_restored
    assert "Iūlia" in body and "Iülia" not in body


def test_greek_words_are_not_glued_together(tmp_path):
    _require(GREEK_PDF)
    out = tmp_path / "greek.txt"

    extract_text_to_file(GREEK_PDF, out)

    text = out.read_text(encoding="utf-8")
    # MuPDF alone gives "καὶἦλθεν", "τοῦἸορδάνου" and "ὁθεὸς".
    assert "καὶ ἦλθεν" in text and "τοῦ Ἰορδάνου" in text and "ὁ θεὸς" in text
    assert "καὶἦλθεν" not in text


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract not installed")
def test_ocr_scanned_spanish_book_with_greek(tmp_path):
    _require(GREEK_PDF)
    pytest.importorskip("ocrmypdf")
    from pdf_worker.ocr import ocr_pdf

    # Page 8 (Spanish introduction) and page 20 (Greek text, Spanish glosses), as images.
    scan = tmp_path / "scan.pdf"
    with pymupdf.open(GREEK_PDF) as doc, pymupdf.open() as out:
        for index in (7, 19):
            page = doc.load_page(index)
            target = out.new_page(width=page.rect.width, height=page.rect.height)
            target.insert_image(target.rect, pixmap=page.get_pixmap(dpi=300))
        out.save(scan)

    report = ocr_pdf(scan, tmp_path / "out.pdf")

    assert report.languages == ["spa", "grc"] and report.languages_guessed
    with pymupdf.open(tmp_path / "out.pdf") as doc:
        intro, gospel = (page.get_text("text") for page in doc)
    assert "Los dos primeros capítulos están escritos" in intro
    assert "τὴν ὁδὸν κυρίου" in gospel and "vecino, cercano" in gospel


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract not installed")
def test_ocr_then_convert_separates_glosses_and_line_numbers(tmp_path):
    _require(BAD_TEXT_PDF)
    pytest.importorskip("ocrmypdf")
    from pdf_worker.ocr import ocr_pdf

    sample = tmp_path / "sample.pdf"
    with pymupdf.open(BAD_TEXT_PDF) as doc, pymupdf.open() as small:
        small.insert_pdf(doc, from_page=24, to_page=25)  # pp. 25-26: recto and verso
        small.save(sample)
    ocr_pdf(sample, tmp_path / "ocr.pdf", languages="lat", mode="redo")

    report = convert_pdf(tmp_path / "ocr.pdf", tmp_path / "out.md", "md")

    text = (tmp_path / "out.md").read_text(encoding="utf-8")
    # Body text reads as one paragraph: no gutter line numbers, no glosses inside it.
    assert "Puer qui ridet est Mārcus. Quae est puella quae plorat? Puella quae" in text
    assert "> puer qui ridet\\\n> puella quae plorat\\\n" in text
    assert "\n75\n" not in text and "\n105\n" not in text
    assert report.stats.glosses >= 2


def test_court_opinion_footnotes_all_linked(tmp_path):
    _require(COURT_PDF)

    report = extract_text_to_file(COURT_PDF, tmp_path / "court.txt")

    # 42 footnotes over the majority, concurrences and dissents; a watermark sits
    # across the notes on some pages.
    assert report.footnote_count == report.footnote_reference_count == 42
    assert report.undefined_footnotes == report.unreferenced_footnotes == []
    text = (tmp_path / "court.txt").read_text(encoding="utf-8")
    assert "Congress has granted federal courts no such \npower.[^p12-4]" in text


def test_report_chapter_endnotes_linked(tmp_path):
    _require(REPORT_PDF)

    report = extract_text_to_file(REPORT_PDF, tmp_path / "report.txt")

    # 13 chapters of superscript-numbered notes collected in a "Notes" section.
    assert report.footnote_reference_count == 1742
    assert len(report.undefined_footnotes) == 0
    assert len(report.unreferenced_footnotes) <= 2
    text = (tmp_path / "report.txt").read_text(encoding="utf-8")
    assert "\n[^c1-1]: No physical, documentary, or analytical evidence" in text

    convert = convert_pdf(REPORT_PDF, tmp_path / "report.epub", "epub")
    assert convert.stats.notes >= 1742
    assert convert.metadata.title != "201-635.job"  # junk PDF title is ignored
    # Kindle page numbers follow the printed book: front matter i-xviii, then 1, 2, ...
    with zipfile.ZipFile(tmp_path / "report.epub") as zf:
        nav = zf.read("OEBPS/nav.xhtml").decode()
    labels = re.findall(r'#pg\d+">([^<]+)</a>', nav)
    assert labels[:3] == ["i", "ii", "iii"]
    assert labels[18:21] == ["1", "2", "3"]


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract not installed")
def test_scanned_book_footnotes_after_ocr(tmp_path):
    _require(SCAN_PDF)
    pytest.importorskip("ocrmypdf")
    from pdf_worker.ocr import ocr_pdf

    sample = tmp_path / "sample.pdf"
    with pymupdf.open(SCAN_PDF) as doc, pymupdf.open() as small:
        # pp. 250-251: a one-column note, then notes set in two columns.
        small.insert_pdf(doc, from_page=249, to_page=250)
        small.save(sample)
    ocr_pdf(sample, tmp_path / "ocr.pdf", languages="eng", mode="redo")

    report = extract_text_to_file(tmp_path / "ocr.pdf", tmp_path / "out.txt")

    text = (tmp_path / "out.txt").read_text(encoding="utf-8")
    assert report.footnote_count >= 2
    assert "]: It is much to be regretted" in text
    # The notes left the body: the body text runs on without them.
    body_page_1 = text.split("\f")[0].split("\n[^")[0]
    assert "regretted" not in body_page_1


def _platon_pages(tmp_path, *pages):
    _require(PLATON_PDF)
    sample = tmp_path / "platon.pdf"
    with pymupdf.open(PLATON_PDF) as doc, pymupdf.open() as small:
        for page in pages:
            small.insert_pdf(doc, from_page=page - 1, to_page=page - 1)
        small.save(sample)
    return sample


def test_abbyy_scan_layer_converts_to_clean_dialogue(tmp_path):
    # pp. 19-20: the start of the Filebo, Stephanus numbers in the margins.
    sample = _platon_pages(tmp_path, 19, 20)

    convert_pdf(sample, tmp_path / "out.md", "md")

    text = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert "qué tesis vas a asumir ahora" in text  # margin "11" dropped
    assert "Resumamos ¿quieres? una y otra.\n" in text  # margin "b" dropped
    assert "La refutación por" in text  # soft hyphen joined, no paragraph break
    assert "verdaderos— resultan" in text
    assert "\n\nPro. — En efecto, es necesario.\n" in text  # margin "d" dropped
    assert "\n\nFilebo. — Exactísimamente, Sócrates.\n" in text  # speaker turn


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract not installed")
def test_underlined_scan_pages_are_read_without_the_underlines(tmp_path):
    pytest.importorskip("ocrmypdf")
    pytest.importorskip("cv2")
    from pdf_worker.ocr import ocr_pdf

    # p. 13 is underlined in pencil; p. 19's MediaBox starts at x=330 (a spread's half).
    sample = _platon_pages(tmp_path, 13, 19)

    report = ocr_pdf(sample, tmp_path / "ocr.pdf", languages="spa", mode="redo")

    assert report.underlines_erased
    with pymupdf.open(tmp_path / "ocr.pdf") as doc:
        underlined, spread = doc[0].get_text(), doc[1].get_text()
    assert "simultáneamente" in underlined  # ABBYY: "iinujltáiieanjentee"
    assert "Lo que produce placer es el hecho" in underlined  # ABBYY: "produce,placer_.es el ,hecho"
    assert "Considera, pues, Protarco" in spread


def test_footnote_mode_matches_raw_text_when_no_notes(tmp_path):
    _require(GOOD_TEXT_PDF)
    marked = extract_text_to_file(GOOD_TEXT_PDF, tmp_path / "marked.txt")
    raw = extract_text_to_file(GOOD_TEXT_PDF, tmp_path / "raw.txt", footnotes=False)

    assert marked.footnote_count == 0
    assert (tmp_path / "marked.txt").read_bytes() == (tmp_path / "raw.txt").read_bytes()
    assert raw.char_count == marked.char_count

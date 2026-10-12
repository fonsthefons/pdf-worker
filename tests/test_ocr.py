import shutil

import pymupdf
import pytest

from pdf_worker import ocr
from pdf_worker.cli import main
from pdf_worker.errors import PdfOpenError

pytest.importorskip("ocrmypdf")
pytestmark = pytest.mark.skipif(
    not (shutil.which("tesseract") or shutil.which("/opt/homebrew/bin/tesseract")),
    reason="Tesseract not installed",
)

ENGLISH = [
    "The quick brown fox jumps over the lazy dog.",
    "It was the best of times, it was the worst of times,",
    "it was the age of wisdom, it was the age of foolishness.",
]
SPANISH = [
    "En un lugar de la Mancha, de cuyo nombre no quiero acordarme,",
    "no ha mucho tiempo que vivía un hidalgo de los de lanza en",
    "astillero, adarga antigua, rocín flaco y galgo corredor. Una olla",
    "de algo más vaca que carnero, salpicón las más noches, duelos y",
    "quebrantos los sábados, lentejas los viernes, algún palomino de",
    "añadidura los domingos, consumían las tres partes de su hacienda.",
]


@pytest.fixture
def make_scan(tmp_path):
    """Build an image-only PDF: each page's lines are rendered to a picture."""

    def _make(pages, name="scan.pdf"):
        path = tmp_path / name
        out = pymupdf.open()
        for lines in pages:
            src = pymupdf.open()
            page = src.new_page()
            for i, line in enumerate(lines):
                page.insert_text((60, 90 + 22 * i), line, fontsize=14)
            pixmap = page.get_pixmap(dpi=200)
            target = out.new_page()
            target.insert_image(target.rect, pixmap=pixmap)
            src.close()
        out.save(path)
        out.close()
        return path

    return _make


def _text(path):
    with pymupdf.open(path) as doc:
        return [page.get_text("text") for page in doc]


def test_ocr_adds_text_to_image_only_pages(make_scan, tmp_path):
    scan = make_scan([ENGLISH, []])
    out = tmp_path / "out.pdf"

    report = ocr.ocr_pdf(scan, out, languages="eng")

    pages = _text(out)
    assert "quick brown fox" in pages[0]
    assert "age of wisdom" in pages[0]
    assert report.page_count == 2
    assert report.empty_pages_before == [1, 2]
    assert report.empty_pages_after == [2]  # the blank page stays blank
    assert report.languages == ["eng"] and not report.languages_guessed
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".out.pdf")] == []


def test_skip_mode_keeps_existing_text(make_pdf, tmp_path):
    pdf = make_pdf(["Digital text that must stay exactly as it is."])
    out = tmp_path / "out.pdf"

    ocr.ocr_pdf(pdf, out, languages="eng", mode="skip")

    assert _text(out)[0].strip() == "Digital text that must stay exactly as it is."


def test_language_is_guessed_from_a_scan(make_scan, tmp_path):
    scan = make_scan([SPANISH, SPANISH])

    assert ocr.guess_ocr_languages(scan) == ["spa"]

    report = ocr.ocr_pdf(scan, tmp_path / "out.pdf")

    assert report.languages == ["spa"] and report.languages_guessed
    assert "vivía un hidalgo" in _text(tmp_path / "out.pdf")[0]


def test_language_is_guessed_from_text_layer(make_pdf):
    pdf = make_pdf(["\n".join(SPANISH * 3)])

    assert ocr.guess_ocr_languages(pdf) == ["spa"]


LATIN_ACCENTED = [
    "Roma in Italià est. Aegyptus in Africà nón est.",
    "Iülia et Màrcus in vìllà sunt. Quintus nón ridet.",
]


def test_latin_accents_become_macrons(make_scan, tmp_path):
    scan = make_scan([LATIN_ACCENTED])

    report = ocr.ocr_pdf(scan, tmp_path / "out.pdf", languages="lat")

    text = _text(tmp_path / "out.pdf")[0]
    assert report.macrons_restored
    assert "nōn" in text and "Italiā" in text
    assert not set("àóüì") & set(text)


def test_latin_macrons_can_be_turned_off(make_scan, tmp_path):
    scan = make_scan([LATIN_ACCENTED])

    report = ocr.ocr_pdf(scan, tmp_path / "out.pdf", languages="lat", latin_macrons=False)

    text = _text(tmp_path / "out.pdf")[0]
    assert not report.macrons_restored
    assert "nón" in text and "ā" not in text


def test_parse_languages():
    assert ocr.parse_languages("lat+eng") == ["lat", "eng"]
    assert ocr.parse_languages(["spa"]) == ["spa"]
    assert ocr.parse_languages(" ") is None
    assert ocr.parse_languages(None) is None


def test_missing_language_is_reported(make_scan, tmp_path):
    scan = make_scan([ENGLISH])

    with pytest.raises(ocr.OcrLanguageMissingError, match="xyz"):
        ocr.ocr_pdf(scan, tmp_path / "out.pdf", languages="eng+xyz")


def test_bad_mode_and_bad_input(make_pdf, tmp_path):
    with pytest.raises(ocr.OcrError):
        ocr.ocr_pdf(make_pdf(["x"]), tmp_path / "out.pdf", mode="sometimes")
    with pytest.raises(PdfOpenError):
        ocr.ocr_pdf(tmp_path / "missing.pdf", tmp_path / "out.pdf", languages="eng")


def test_missing_tesseract_is_a_clean_error(make_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)

    with pytest.raises(ocr.OcrEngineMissingError, match="brew install tesseract"):
        ocr.ocr_pdf(make_pdf(["x"]), tmp_path / "out.pdf")


def test_cli_ocr_command(make_scan, tmp_path, capsys):
    scan = make_scan([ENGLISH], name="book.pdf")

    assert main(["ocr", str(scan), "--lang", "eng"]) == 0

    assert "quick brown fox" in _text(tmp_path / "book.ocr.pdf")[0]
    assert "pages without text 1 -> 0 of 1" in capsys.readouterr().out


def test_cli_extract_text_with_ocr(make_scan, tmp_path):
    scan = make_scan([ENGLISH], name="book.pdf")
    out = tmp_path / "text" / "book.txt"

    assert main(["extract-text", str(scan), "-o", str(out), "--ocr", "--ocr-lang", "eng"]) == 0

    assert "quick brown fox" in out.read_text(encoding="utf-8")
    assert sorted(p.name for p in out.parent.iterdir()) == ["book.txt"]  # temp PDF removed


def test_cli_convert_with_ocr_keeps_title(make_scan, tmp_path):
    scan = make_scan([ENGLISH], name="My Book.pdf")
    out = tmp_path / "book.md"

    assert main(["convert", str(scan), "-o", str(out), "--ocr", "--ocr-lang", "eng"]) == 0

    text = out.read_text(encoding="utf-8")
    assert 'title: "My Book"' in text
    assert "quick brown fox" in text


def test_cli_reports_missing_language(make_scan, tmp_path, capsys):
    scan = make_scan([ENGLISH])

    assert main(["ocr", str(scan), "--lang", "xyz"]) == 1
    assert "not installed: xyz" in capsys.readouterr().err

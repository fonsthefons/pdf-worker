import pytest

pytest.importorskip("ocrmypdf")

from pdf_worker.ocr_latin_plugin import restore_hocr, restore_text  # noqa: E402


def _par(text):
    words = "".join(
        f"<span class='ocrx_word' title='bbox 1 2 3 4'>{w}</span> " for w in text.split()
    )
    return f"<p class='ocr_par' id='par_1_1' lang='lat' title='bbox 0 0 9 9'>{words}</p>"


def test_hocr_restores_only_latin_paragraphs():
    latin = _par("Roma in Italià est et nón in Africà. Quintus et Iülia sunt in vìllà.")
    spanish = _par("La canción que se oía en el jardín.")
    heading = _par("Càput")

    out = restore_hocr(f"<div>{heading}{latin}{spanish}</div>", default=False)

    assert "Italiā" in out and "nōn" in out
    assert "canción" in out and "oía" in out and "jardín" in out
    assert "Cāput" in out  # undecided: follows the page, which reads as Latin


def test_text_restores_only_latin_paragraphs():
    text = "Roma in Italià est et nón in Africà.\n\nLa canción que se oía en el jardín.\n"

    assert restore_text(text, default=False) == (
        "Roma in Italiā est et nōn in Africā.\n\nLa canción que se oía en el jardín.\n"
    )

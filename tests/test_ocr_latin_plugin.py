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


def test_short_latin_lines_on_a_spanish_page():
    spanish = _par(
        "En un lugar de la Mancha, de cuyo nombre no quiero acordarme, no ha mucho "
        "tiempo que vivía un hidalgo de los de lanza en astillero."
    )
    heading = _par("Càput Secùndum")  # no stopwords: the Latin "-um" ending decides
    place = _par("Rôma in Itàlià")  # "in" is Latin, not Spanish (English isn't OCR'd)
    name = _par("Pàblo")  # nothing to tell: follows the page, which is Spanish

    out = restore_hocr(f"<div>{spanish}{heading}{place}{name}</div>", False, {"es"})

    assert "vivía" in out and "Pàblo" in out
    assert all(word in out for word in (">Cāput<", ">Secūndum<", ">Rōma<", ">Itāliā<"))


def test_text_restores_only_latin_paragraphs():
    text = "Roma in Italià est et nón in Africà.\n\nLa canción que se oía en el jardín.\n"

    assert restore_text(text, default=False) == (
        "Roma in Italiā est et nōn in Africā.\n\nLa canción que se oía en el jardín.\n"
    )

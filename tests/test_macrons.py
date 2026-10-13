import unicodedata

import pytest

from pdf_worker.macrons import reads_as_latin, restore_macrons, restore_macrons_if_latin


@pytest.mark.parametrize(
    ("ocr", "expected"),
    [
        ("Puer qui ridet est Màrcus.", "Puer qui ridet est Mārcus."),
        ("Iülia et Iülius", "Iūlia et Iūlius"),
        ("Aegyptus in Európà nón est", "Aegyptus in Eurōpā nōn est"),
        ("Rhênus et Nìlus", "Rhēnus et Nīlus"),
        ("ÀB ÉO", "ĀB ĒO"),
        ("Maàrcus", "Mārcus"),  # long vowel read twice
        ("nàávis", "nāvis"),
        ("portus -üs", "portus -ūs"),
        ("Euröpå et Åfricä", "Eurōpā et Āfricā"),  # PaddleOCR-VL's variants
        ("Puella plorat.", "Puella plorat."),  # unaccented text is untouched
    ],
)
def test_restore_macrons(ocr, expected):
    assert restore_macrons(ocr) == expected


def test_decomposed_input_is_handled():
    assert restore_macrons(unicodedata.normalize("NFD", "Màrcus")) == "Mārcus"


def test_only_latin_text_is_restored():
    latin = "Roma in Italià est et Aegyptus nón est in Európà."
    spanish = "La canción que se oía en el jardín de la casa."
    assert (
        restore_macrons_if_latin(latin, default=False)
        == "Roma in Italiā est et Aegyptus nōn est in Eurōpā."
    )
    assert restore_macrons_if_latin(spanish, default=True) == spanish
    # Too few words to tell: the default decides.
    assert reads_as_latin("Càput I", default=True)
    assert not reads_as_latin("Capítulo I", default=False)


def test_markup_is_untouched():
    hocr = "<span class='ocrx_word' title='bbox 1 2 3 4; x_wconf 96'>nón</span>"
    assert restore_macrons(hocr) == hocr.replace("nón", "nōn")

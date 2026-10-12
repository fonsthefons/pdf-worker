import unicodedata

import pytest

from pdf_worker.macrons import restore_macrons


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


def test_markup_is_untouched():
    hocr = "<span class='ocrx_word' title='bbox 1 2 3 4; x_wconf 96'>nón</span>"
    assert restore_macrons(hocr) == hocr.replace("nón", "nōn")

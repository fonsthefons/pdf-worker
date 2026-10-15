"""Footnote numbers on PaddleOCR-VL pages (from test_platon_bad_5, Filebo 11a-13a)."""

from pdf_worker.margin_refs import PageScan, ScanMark, ScanWord, mark_paddle_blocks
from pdf_worker.note_numbers import fix_refs, number_notes


def _scan(text: str) -> list[ScanWord]:
    return [ScanWord(w, 0, False) for w in text.split()]


def test_notes_count_on_from_the_previous_page_whatever_was_read():
    # Paddle dropped note 3's number, read 5 as "³" and 8 as "*".
    notes = ["Para calificar.", "⁴ Partimos.", "³ GADAMER.", "6 Frente."]
    texts, numbers = number_notes(notes, [3, 4, 6], last=2)
    assert numbers == [3, 4, 5, 6]
    assert texts[0] == "³ Para calificar." and texts[2] == "⁵ GADAMER."

    texts, numbers = number_notes(["7 Filebo.", "* Recordemos."], [2, 8], last=6)
    assert numbers == [7, 8] and texts[1] == "⁸ Recordemos."

    # The previous page's note going on, then unnumbered notes.
    texts, numbers = number_notes(["llamado Zeus.", "⁹ En el.", "¹⁰ Esta.", "Estos."], [11], 8)
    assert numbers == [None, 9, 10, 11] and texts[0] == "llamado Zeus."


def test_a_reference_that_starts_at_one_is_a_new_count():
    _, numbers = number_notes(["Una nota.", "Otra."], [1, 2], last=40)
    assert numbers == [1, 2]


def test_misread_and_dropped_references_take_the_missing_numbers():
    # "diosa²" is note 7; Tesseract saw "cueste 5," where Paddle has no reference.
    assert fix_refs(["a la propia diosa². grato⁸; mas"], [7, 8], []) == [
        "a la propia diosa⁷. grato⁸; mas"
    ]
    texts = ["Filebo⁴? la verdad, cuesta lo que cuesta. los hombres⁶. ¿O no"]
    scan = _scan("Filebo *? la verdad, cueste lo que cueste 5, los hombres 4. ¿O no")
    assert fix_refs(texts, [3, 4, 5, 6], scan) == [
        "Filebo⁴? la verdad, cuesta lo que cuesta⁵. los hombres⁶. ¿O no"
    ]


def test_a_stray_question_mark_counts_only_when_it_fills_the_gap():
    texts = ["en su misma prudencia. ¿Cómo no? a sí misma? de este principio¹¹. Desde"]
    scan = _scan("en su misma prudencia?. ¿Cómo no? a sí misma !0? de este principio !!. Desde")
    assert fix_refs(texts, [None, 9, 10, 11], scan) == [
        "en su misma prudencia⁹. ¿Cómo no? a sí misma¹⁰? de este principio¹¹. Desde"
    ]
    # One place for two missing numbers: left alone.
    assert fix_refs(texts, [9, 10, 11], _scan("en su misma prudencia. a sí misma !0?")) == texts


def test_a_margin_letter_read_into_the_text_between_lines_is_taken_out():
    words = [
        *(ScanWord(w, 0, False) for w in ["renuncio", "solemnemente", "y"]),
        *(ScanWord(w, 1, False) for w in ["pongo", "ahora"]),
    ]
    scan = PageScan(words, [ScanMark("b", 0)])

    cleaned, marks = mark_paddle_blocks(["renuncio solemnemente y b pongo ahora"], scan)

    assert cleaned == ["renuncio solemnemente y pongo ahora"]
    assert marks == [(0, 0, "b")]

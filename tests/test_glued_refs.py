import pymupdf

from pdf_worker.endnotes import LOSSY_STEP, runs_from_anywhere, sequences
from pdf_worker.glued_refs import _missing, apply_refs, mark_glued_refs, page_refs
from pdf_worker.layout import Line, hung_mark, plain_note_start


def _chars(text: str) -> list[dict]:
    return [{"c": c, "bbox": (10.0 * i, 0.0, 10.0 * i + 8, 10.0)} for i, c in enumerate(text)]


def test_a_glued_reference_becomes_superscript_and_its_period_comes_back():
    chars = _chars("tes74• Pu")
    apply_refs(chars, [[30.0, 0.0, 48.0, 10.0]])  # the box of "74"
    assert "".join(c["c"] for c in chars) == "tes⁷⁴. Pu"

    chars = _chars("tud88 • Pe")
    apply_refs(chars, [[30.0, 0.0, 48.0, 10.0]])
    assert "".join(c["c"] for c in chars) == "tud⁸⁸. Pe"


def test_numbers_that_only_climb_are_not_references(make_pdf):
    # A born-digital book's notes: "AAS 42 (1950)", "AAS 53 (1961)", ... climb, with gaps.
    sparse = "\n".join(f"Carta enc. AAS {n} (19{n})" for n in (7, 20, 33, 42, 53, 63))
    dense = "\n".join(f"las cosas{n} y otras" for n in (1, 2, 3, 5, 6))
    with pymupdf.open(make_pdf([sparse, dense])) as doc:
        assert mark_glued_refs(doc) == 5
        assert page_refs(doc[0]) == []


def test_lossy_runs_skip_lost_numbers_and_stray_ones_dont_end_them():
    numbers = [1, 2, 3, 1, 1, 9, 30, 10, 22]  # stray "1"s, "30" misread, 11-21 lost
    runs = sequences([(n, i) for i, n in enumerate(numbers)], LOSSY_STEP, LOSSY_STEP)
    assert [n for n, _ in runs[0].items] == [1, 2, 3, 9, 10, 22]


def _line(x0: float, x1: float, baseline: float, text: str) -> Line:
    span = {"text": text, "flags": 0, "origin": (x0, baseline), "size": 7.0}
    return Line(spans=(span,), size=7.0, bbox=(x0, baseline - 7, x1, baseline + 2))


def test_a_run_starts_at_any_number():
    # Pages 168-169 of the Timeo: notes 3-9, and an "8" in the Greek page before them.
    found = [(n, (0, None)) for n in (8, 3, 4, 5, 6, 7, 8, 9)]

    longest = max(runs_from_anywhere(found), key=lambda run: len(run.items))
    assert [n for n, _ in longest.items] == [3, 4, 5, 6, 7, 8, 9]


def test_references_a_run_skips_are_found_where_they_must_be():
    texts = [
        "Uno, dos, tres . . . 2 , pero el cuarto3 y los 4 hombres",  # "4": a numeral
        "de los invitados9 y el oficio'º. Dijo’ y",  # 10 read "'º"; "’" alone is a quote
    ]
    lines = [
        (0, [{"c": c, "bbox": (x, 10 * i, x + 1, 10 * i + 8)} for x, c in enumerate(t)], t, [])
        for i, t in enumerate(texts)
    ]
    three, nine = texts[0].index("3"), texts[1].index("9")
    run = [(3, (0, None, (0, three, three + 1))), (9, (0, None, (1, nine, nine + 1)))]

    assert [number for number, _ in _missing(run, lines)] == ["2", "10"]


def test_a_reference_misread_beyond_reading_is_found_when_the_notes_have_it():
    text = "hombres y mujeres'3, deben ... uniones?'9• del estado2º."
    chars = [{"c": c, "bbox": (x, 0, x + 1, 8)} for x, c in enumerate(text)]
    lines = [(0, chars, text, [])]
    start = text.index("hombres")
    run = [(17, (0, None, (0, 0, start))), (21, (0, None, (0, len(text), len(text))))]

    # 18 with no note to say so: the one sign glued in its gap, counted in.
    assert [n for n, _ in _missing(run, lines)] == ["19", "20", "18"]
    assert [n for n, _ in _missing(run, lines, noted={17, 18, 19})] == ["19", "20", "18"]


def test_references_misread_further_are_found_where_only_they_fit():
    # Timeo 3: 56, 58, 59 read with "s" for 5, 57 lost to "s?"; 80 and 81 with 3 for 8.
    text = (
        "los acontecimien tos que ha descritos6• Faetonte pereció fulminados?. "
        "un mitos8; pero la desviacións9 de los cuerpos ... adversidad60. "
        "las islas79. el verdadero30• Pues de Libia3’. Ahora82."
    )
    chars = [{"c": c, "bbox": (x, 0, x + 1, 8)} for x, c in enumerate(text)]
    lines = [(0, chars, text, [])]

    def at(word):
        end = text.index(word) + len(word)
        return (0, None, (0, end - 2, end))

    run = [(55, at("los")), (60, at("adversidad60")), (79, at("islas79")), (82, at("Ahora82"))]
    found = {n: text[box[0] : box[2]] for n, (_, box) in _missing(run, lines, set(range(50, 90)))}

    assert found == {"56": "s6", "58": "s8", "59": "s9", "80": "30", "81": "3’"}


def test_references_read_past_reading_are_counted_into_their_gap():
    # Timeo 30a: 119-122 read "”9•", "111º", "1111", "1112"; 118 and 123 read right.
    text = (
        'ninguna envidia118 de nada. del mundo"9• Como no hubiera en lo posible111º nada '
        "malo, tomó entonces1111 todo, sin orden ni concierto1112, y del alma123. Así"
    )
    chars = [{"c": c, "bbox": (x, 0, x + 1, 8)} for x, c in enumerate(text)]
    lines = [(0, chars, text, [])]

    def at(word):
        end = text.index(word) + len(word)
        return (0, None, (0, end - 3, end))

    run = [(118, at("envidia118")), (123, at("alma123"))]
    found = {n: text[box[0] : box[2]] for n, (_, box) in _missing(run, lines)}

    assert found == {"119": "9", "120": "111º", "121": "1111", "122": "1112"}
    # One sign too many or too few in the gap: nothing is guessed.
    text = text.replace("posible111º", "posible")
    lines = [(0, chars[: len(text)], text, [])]
    assert _missing([(118, at("envidia118")), (123, at("alma123"))], lines) == []


def test_a_found_reference_takes_its_number_over_what_was_read():
    chars = [{"c": c, "bbox": (i, 0, i + 1, 10)} for i, c in enumerate("oficio'º.")]
    apply_refs(chars, [[6, 0, 8, 10, "10"]])

    assert "".join(c["c"] for c in chars) == "oficio¹⁰."


def test_a_note_number_hung_in_the_margin_starts_the_line_beside_it():
    lines = [
        _line(50, 58, 163.1, "73 "),
        _line(50, 58, 219.1, ".¡. "),  # 4, misread
        _line(66, 340, 162.8, "De este modo traduzco"),
        _line(66, 340, 217.8, "Sobre las relaciones"),
    ]
    assert plain_note_start(lines, 0) == (73, 2)
    assert plain_note_start(lines, 1) == (4, 3)
    assert plain_note_start(lines, 2) is None


def test_a_note_number_misread_with_letters_is_a_mark_only_at_the_numbers():
    lines = [
        _line(54, 340, 110, "H7 Como veremos infra, 58c-6ob."),
        _line(53, 340, 404, ".i,57 Entre los icosaedros que componen"),
        _line(69, 340, 413, "cios más grandes que entre los octaedros"),
        _line(69, 340, 450, "12 , 1274a 2 2 , Locro recibía sus leyes"),  # in the text column
        _line(69, 340, 459, "la «disociación» o la «asociación» de los"),
        _line(69, 340, 468, "tos, procesos que provocan, bien la"),
    ]
    assert [hung_mark(lines, i) for i in range(4)] == [0, 1, None, None]
    # Hung alone beside its line: five signs at the numbers ("lllll" for 122).
    lines.append(_line(53, 66, 413, "lllll "))
    assert hung_mark(lines, 6) == 2

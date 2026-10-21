from pdf_worker.endnotes import LOSSY_STEP, sequences
from pdf_worker.glued_refs import apply_refs
from pdf_worker.layout import Line, plain_note_start


def _chars(text: str) -> list[dict]:
    return [{"c": c, "bbox": (10.0 * i, 0.0, 10.0 * i + 8, 10.0)} for i, c in enumerate(text)]


def test_a_glued_reference_becomes_superscript_and_its_period_comes_back():
    chars = _chars("tes74• Pu")
    apply_refs(chars, [[30.0, 0.0, 48.0, 10.0]])  # the box of "74"
    assert "".join(c["c"] for c in chars) == "tes⁷⁴. Pu"

    chars = _chars("tud88 • Pe")
    apply_refs(chars, [[30.0, 0.0, 48.0, 10.0]])
    assert "".join(c["c"] for c in chars) == "tud⁸⁸. Pe"


def test_lossy_runs_skip_lost_numbers_and_stray_ones_dont_end_them():
    numbers = [1, 2, 3, 1, 1, 9, 30, 10, 22]  # stray "1"s, "30" misread, 11-21 lost
    runs = sequences([(n, i) for i, n in enumerate(numbers)], LOSSY_STEP, LOSSY_STEP)
    assert [n for n, _ in runs[0].items] == [1, 2, 3, 9, 10, 22]


def _line(x0: float, x1: float, baseline: float, text: str) -> Line:
    span = {"text": text, "flags": 0, "origin": (x0, baseline), "size": 7.0}
    return Line(spans=(span,), size=7.0, bbox=(x0, baseline - 7, x1, baseline + 2))


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

from pdf_worker.heading_levels import heading_key, rank_headings
from pdf_worker.structure import Heading, Paragraph


def _levels(*headings: tuple[str, int]) -> list[int]:
    return [h.level for h in rank_headings(Heading(t, level) for t, level in headings)]


def test_heading_key():
    # The division word names the division, whatever its case.
    assert heading_key(Heading("CAPÍTULO IV", 2)) == ("capitulo", "", False, 2)
    assert heading_key(Heading("Capítulos I-II: La Ilustración", 2)) == heading_key(
        Heading("CAPÍTULO IV", 2)
    )
    assert heading_key(Heading("Lecciones de lógica", 1))[0] == "leccion"
    assert heading_key(Heading("Chapter 3", 1))[0] == "capitulo"  # one rank for both languages
    assert heading_key(Heading("IV. Obras", 3)) == ("", "roman", False, 3)
    assert heading_key(Heading("4. EL ALMA", 3)) == ("", "arabic", True, 3)
    assert heading_key(Heading("4.2 El alma", 3))[1] == "decimal"
    assert heading_key(Heading("a) Naturaleza", 3))[1] == "letter"
    assert heading_key(Heading("Introducción", 3)) == ("", "", False, 3)
    assert heading_key(Heading("Partida de caza", 3))[0] == ""  # a whole word only


def test_kinds_in_one_size_nest_by_their_numbering():
    assert _levels(
        ("Capítulo 1. El alma", 2),
        ("1. Noción", 2),
        ("a) Primera", 2),
        ("2. Otra noción", 2),
        ("b) Segunda", 2),
        ("Capítulo 2. La vida", 2),
        ("1. Noción", 2),
    ) == [2, 3, 4, 3, 4, 2, 3]


def test_a_higher_division_word_goes_above_the_current_one():
    assert _levels(
        ("Capítulo 1", 1),
        ("1. Uno", 1),
        ("Parte segunda", 1),
        ("Capítulo 2", 1),
        ("1. Uno", 1),
        ("Sección 1", 1),
    ) == [1, 2, 1, 2, 3, 4]


def test_larger_type_ranks_above_smaller():
    assert _levels(("1. Uno", 2), ("Textos", 2), ("DIOS", 1), ("1. Dos", 2), ("Textos", 2)) == [
        2,
        3,
        1,
        2,
        3,
    ]
    # Two kinds in the larger size move the smaller one down.
    assert _levels(("Capítulo 1", 1), ("TÍTULO", 1), ("1. Uno", 2)) == [1, 2, 3]


def test_front_matter_keeps_its_size_level():
    assert _levels(
        ("PRÓLOGO", 2),
        ("Índice", 1),
        ("1. Uno", 3),
        ("Índice", 1),
        ("2. Dos", 3),
    ) == [2, 1, 3, 1, 3]
    # A book without numbers or division words keeps its size levels throughout.
    assert _levels(("Uno", 1), ("Dos", 2), ("Tres", 1)) == [1, 2, 1]


def test_size_tells_apart_kinds_otherwise_the_same():
    assert _levels(
        ("1. Uno", 1),
        ("Textos", 2),
        ("Textos", 3),  # smaller type: another kind
        ("2. Dos", 1),
        ("Textos", 3),
    ) == [1, 2, 3, 1, 3]


def test_a_division_word_keeps_its_rank_in_any_size():
    # "Capítulo IX" set smaller than the chapters before it is still a chapter.
    assert _levels(("Capítulo I", 1), ("1. Uno", 2), ("Capítulo IX", 2), ("1. Uno", 2)) == [
        1,
        2,
        1,
        2,
    ]


def test_a_note_reference_does_not_change_the_kind():
    assert heading_key(Heading("1. NOTAS SOBRE LA FE[^p24-18]", 2)) == heading_key(
        Heading("2. LÍMITES", 2)
    )


def test_levels_stop_at_6():
    styles = ["Parte 1", "Capítulo 1", "1. a", "1.1 b", "a) c", "I. d", "Texto", "Otro"]
    assert _levels(*((s, 1) for s in styles)) == [1, 2, 3, 4, 5, 6, 6, 6]


def test_other_blocks_pass_through():
    blocks = [Paragraph("texto"), Heading("1. Uno", 2), Paragraph("más")]
    assert list(rank_headings(blocks)) == [blocks[0], Heading("1. Uno", 2), blocks[2]]

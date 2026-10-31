from pdf_worker.letter_spacing import respace

WORDS = dict.fromkeys(
    ["el", "compuesto", "de", "sustancia", "y", "accidentes", "capítulo", "i", "la", "fe"], 5
)


def test_letter_spaced_runs_are_split_into_the_books_words():
    text = "3. E l c o m p u e s t o d e s u s t a n c ia y a c c id e n t e s"
    assert respace(text, WORDS) == "3. El compuesto de sustancia y accidentes"
    assert respace("C a pít u l o I", WORDS) == "Capítulo I"
    assert respace("E l s e r, a c t o", {"el": 9, "ser": 9, "acto": 9}) == "El ser, acto"
    words = {"el": 9, "ente": 9, "y": 9, "la": 9, "verdad": 9}
    assert respace("1. E l e n t e y l a v e r d a d", words) == "1. El ente y la verdad"


def test_ties_go_to_capitals_starting_words_then_to_the_books_common_words():
    words = {"primer": 9, "primera": 9, "aparte": 9, "parte": 9}
    assert respace("P r im e r a P a r t e", words) == "Primera Parte"
    words = {"funda": 2, "dose": 2, "nel": 2, "fundados": 9, "en": 50, "el": 50, "ser": 50}
    assert respace("f u n d a d o s e n e l s e r", words) == "fundados en el ser"


def test_a_split_mostly_into_short_words_is_no_reading():
    words = {"yb": 3, "i": 9, "pe": 3, "g": 3, "va": 3, "y": 9, "ba": 3}
    assert respace("y B i PE G V A Y B A", words) == "y B i PE G V A Y B A"


def test_runs_no_split_covers_and_plain_short_words_stay():
    assert respace("X q z w v k", WORDS) == "X q z w v k"
    assert respace("LA FE Y EL CAPÍTULO", WORDS) == "LA FE Y EL CAPÍTULO"
    assert respace("Capítulo  I", WORDS) == "Capítulo  I"  # no run: untouched

from pdf_worker.bilingual import _choose, apply_words, facing_pages, suspect
from pdf_worker.document import open_pdf

SPANISH = "\n".join(
    ["el dios hizo que la tierra y el fuego estuvieran en medio de los otros con una medida"] * 4
)
GREEK_AS_LATIN = "\n".join(["Aó'YT)aá am Ta ÉmTax0évrn x0és Í]yoúµEvos orrEp év cirram"] * 5)
TABLE = "\n".join(["µliedro Caras Vértices Aristas Agua Fuego Tierra Aire Elemento"] * 5)


def test_the_original_on_facing_pages_is_left_out_but_not_a_lone_table(make_pdf):
    pages = [SPANISH, TABLE, SPANISH, SPANISH]  # a table between Spanish pages: kept
    for _ in range(12):
        pages += [GREEK_AS_LATIN, SPANISH]

    with open_pdf(make_pdf(pages)) as doc:
        language, facing = facing_pages(doc)

    assert language == "es"
    assert facing == set(range(4, 28, 2))


def test_a_few_foreign_pages_are_no_bilingual_edition(make_pdf):
    with open_pdf(make_pdf([SPANISH, GREEK_AS_LATIN, SPANISH, GREEK_AS_LATIN, SPANISH])) as doc:
        assert facing_pages(doc)[1] == set()


def test_garbled_tokens_are_suspect_but_references_and_note_numbers_are_not():
    assert suspect("i(CllQLOµóB") and suspect("Ref>ública") and suspect("conJantipa,")
    assert not suspect("[I7d]") and not suspect("cuerpo615,") and not suspect("(51d-e)")
    assert not suspect("República") and not suspect("http://a.b/c_d")


def test_greek_wins_when_confident_else_the_books_language():
    assert _choose([("χωρισμός", 96)], [("xweuoós", 0)]) == "χωρισμός"
    assert _choose([("Κερύδιϊιοα", 19)], [("República", 96)]) == "República"
    assert _choose([("ζο5845", 35)], [("c0sas", 40)]) is None


def test_a_re_read_word_replaces_the_whole_token_in_place():
    chars = [{"c": c, "bbox": (i, 0, i + 1, 10)} for i, c in enumerate("ver (ó.>..lÍ&La) x")]
    apply_words(chars, [[4, 0, 16, 10, "(ó.>..lÍ&La)", "(ἀλήθεια)"]])

    assert "".join(c["c"] for c in chars) == "ver (ἀλήθεια) x"

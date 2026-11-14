from types import SimpleNamespace

import pymupdf

from pdf_worker import bilingual, fixes
from pdf_worker.bilingual import (
    _choose,
    apply_words,
    drop_greek,
    facing_pages,
    mark_words,
    page_words,
    suspect,
)
from pdf_worker.document import open_pdf
from pdf_worker.fixes import Review
from pdf_worker.inline import page_mark
from pdf_worker.structure import Paragraph

SPANISH = "\n".join(
    ["el dios hizo que la tierra y el fuego estuvieran en medio de los otros con una medida"] * 4
)
GREEK_AS_LATIN = "\n".join(["Aó'YT)aá am Ta ÉmTax0évrn x0és Í]yoúµEvos orrEp év cirram"] * 5)
GREEK = "\n".join(
    ["ἐπιβατὸν ἐπὶ τὰς ἄλλας νήσους τοῖς τότε ἐγίγνετο πορευομένοις ἐκ τῶν νήσων πᾶσαν"] * 5
)
TABLE = "\n".join(["µliedro Caras Vértices Aristas Agua Fuego Tierra Aire Elemento"] * 5)


def _lexicon(known):
    """A stand-in for the spelling check's words: ``known`` both by counts and dictionary."""
    return SimpleNamespace(known=known, in_dictionary=known)


def test_the_original_on_facing_pages_is_left_out_but_not_a_lone_table(make_pdf):
    pages = [SPANISH, TABLE, SPANISH, SPANISH]  # a table between Spanish pages: kept
    for _ in range(12):
        pages += [GREEK_AS_LATIN, SPANISH]

    with open_pdf(make_pdf(pages)) as doc:
        language, facing = facing_pages(doc)

    assert language == "es"
    assert facing == set(range(4, 28, 2))


def test_pages_in_greek_letters_are_left_out_without_spanish_neighbours(tmp_path):
    # Split words ("p rin cip io") leave the Spanish pages too few stopwords to count.
    split = "\n".join(["p rin cip io en o rd en to da esa dis po si ción y or ga ni za ción"] * 4)
    doc = pymupdf.open()
    for _ in range(12):
        for text in (GREEK, split):
            page = doc.new_page()
            page.insert_font(fontname="G", fontbuffer=pymupdf.Font("notos").buffer)  # has Greek
            page.insert_text((72, 72), text, fontname="G")
    doc.save(tmp_path / "greek.pdf")

    with open_pdf(tmp_path / "greek.pdf") as doc:
        assert facing_pages(doc)[1] == set(range(0, 24, 2))


def test_greek_paragraphs_are_dropped_quotations_in_a_sentence_kept():
    long_greek = Paragraph(f"{page_mark(7, '8')}{GREEK.replace(chr(10), ' ')}", page=7)
    short = Paragraph("ἑστιατόρων;")
    quote = Paragraph("Platón dice ἔμφρονος y ψυχή en el texto")
    # Greek re-read in a page of Greek read as Latin, and a paragraph all read as Latin.
    mixed = Paragraph("TI ΤΙΜΑΙΟΣ.--᾿Ασθένειά Lá ns aimŀ συνέπεσεν, w Σώκρατες: · ou yap")
    latin = Paragraph("av É KWV T08E QTTEAELTTETO TŁS owouaías .")
    reply = Paragraph("TIM.--Sí.")  # none of the book's words either, but between Spanish
    after = Paragraph("Igualmente, en lo que respecta a la sabiduría")
    dropped = []

    blocks = [quote, short, long_greek, after, reply, after, mixed, latin, mixed, after]
    kept = list(drop_greek(blocks, dropped, "es", True))

    assert dropped == [short, long_greek, mixed, latin, mixed]
    assert kept == [quote, Paragraph(page_mark(7, "8") + after.text), reply, after, after]

    # Not a bilingual edition: the Greek is a quotation, all kept.
    dropped = []
    assert list(drop_greek(blocks, dropped, "es", False)) == blocks
    assert dropped == []


def test_left_out_text_is_listed_as_ignored_once():
    review = Review([], "es")
    review.finish()
    assert review.left_out("greek-dropped", [("8", "ἐπιβατὸν ἐπὶ τὰς ἄλλας")]) == 1
    assert review.left_out("greek-dropped", [("8", "ἐπιβατὸν ἐπὶ τὰς ἄλλας")]) == 0
    (row,) = review.fixes
    assert (row.page, row.kind, row.action, row.status) == (
        "8",
        "greek-dropped",
        "ignore",
        "dropped",
    )


def test_a_few_foreign_pages_are_no_bilingual_edition(make_pdf):
    with open_pdf(make_pdf([SPANISH, GREEK_AS_LATIN, SPANISH, GREEK_AS_LATIN, SPANISH])) as doc:
        assert facing_pages(doc)[1] == set()


def test_garbled_tokens_are_suspect_but_references_and_note_numbers_are_not():
    assert suspect("i(CllQLOµóB") and suspect("Ref>ública") and suspect("conJantipa,")
    assert not suspect("[I7d]") and not suspect("cuerpo615,") and not suspect("(51d-e)")
    assert not suspect("República") and not suspect("http://a.b/c_d")


def test_letters_the_books_language_doesnt_write_are_suspect():
    assert suspect("ōauloii", "es") and suspect("Ćmías,", "es") and suspect("lǽgos", "es")
    assert suspect("sôma", "es") and not suspect("sôma", "fr")
    assert not suspect("ōauloii") and not suspect("ōauloii", "la")  # no rule without letters
    assert not suspect("República,", "es") and not suspect("ἀλήθεια", "es")
    assert not suspect("ﬁnal", "es") and not suspect("Nº18", "es")  # a ligature, "º" is "o"
    assert suspect("daímºn") and suspect("phronimº-")  # but an underlined o read as "º"
    assert not suspect("«Præstet", "es")  # Latin quoted


def test_garbled_words_and_their_unknown_neighbours_are_read_again(monkeypatch):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "dice ka$los mjithos aqui")
    page.insert_text((72, 120), "e$kos", fontname="tiit")  # italic: a transliteration
    page.insert_text((72, 168), "Jérôme")  # "ô" isn't Spanish: read again, but kept
    words = {w[4]: w[:4] for w in page.get_text("words")}
    greek = {"ka$los": ("καλός", 95), "mjithos": ("μῦθος", 90), "e$kos": ("εἰκός", 96)}
    native = {"ka$los": ("kalos", 90), "mjithos": ("mjithos", 30), "e$kos": ("eikos", 90)}
    native["Jérôme"] = ("Jéróme", 95)  # only the accent differs: the model lacks "ô"

    def read(png, tesseract, language, rect, macrons=False):
        reading = greek if language == "grc" else native
        return [(words[old], text, conf) for old, (text, conf) in reading.items()]

    monkeypatch.setattr(bilingual, "_read", read)
    monkeypatch.setattr(fixes, "_words", lambda language: _lexicon({"dice"}.__contains__))

    count, unsure = mark_words(doc, "tesseract", "es", greek=True)

    changed = {old: new for *_, old, new in page_words(doc.load_page(0))}
    assert changed == {"ka$los": "καλός", "mjithos": "μῦθος", "e$kos": "eikos"}  # not "aqui"
    assert count == 3
    # The native reading was as sure; "mjithos" was all Latin letters.
    assert unsure == [
        (0, "greek-unsure", "καλός", "kalos"),
        (0, "greek-unsure", "μῦθος", "mjithos"),
    ]

    # A book without Greek terms: only odd signs are suspect, italics read as Greek too.
    count, unsure = mark_words(doc, "tesseract", "es")

    changed = {old: new for *_, old, new in page_words(doc.load_page(0))}
    assert changed == {"ka$los": "καλός", "e$kos": "εἰκός"}  # no neighbours, no italic rule
    assert [row[1] for row in unsure] == ["greek-unsure"] * 2


def test_a_garbled_word_takes_a_less_sure_clean_reading_with_a_review_row(monkeypatch):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "y Pdskli2n inengendrado9+ daímºn")
    words = {w[4]: w[:4] for w in page.get_text("words")}
    native = {
        "Pdskli2n": ("Páskhōn", 77),
        "inengendrado9+": ("inengendrado”,", 80),  # a glued note number: not a word
        "daímºn": ("daímōn", 90),  # only a macron more: an underlined o
    }

    def read(png, tesseract, language, rect, macrons=False):
        reading = {} if language == "grc" else native
        return [(words[old], text, conf) for old, (text, conf) in reading.items()]

    monkeypatch.setattr(bilingual, "_read", read)
    monkeypatch.setattr(fixes, "_words", lambda language: _lexicon({"y"}.__contains__))

    count, unsure = mark_words(doc, "tesseract", "es", greek=True)

    changed = {old: new for *_, old, new in page_words(doc.load_page(0))}
    assert changed == {"Pdskli2n": "Páskhōn", "daímºn": "daímōn"}
    assert unsure == [(0, "reread-unsure", "Páskhōn", "Pdskli2n")]

    # Without Greek terms no guesses: a garbled word keeps its text.
    other = pymupdf.open()
    other.new_page().insert_text((72, 72), "y Pdskli2n")
    assert mark_words(other, "tesseract", "es") == (0, [])


def test_no_macrons_on_the_books_own_words(monkeypatch):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "dice ¿Qu<é hom>bre daím<ºn")
    words = {w[4]: w[:4] for w in page.get_text("words")}
    # Specks under a scan's letters read as underlines: only the transliteration keeps them.
    native = {"¿Qu<é": ("¿Quḗ", 95), "hom>bre": ("hōmbre", 95), "daím<ºn": ("daímōn", 95)}

    def read(png, tesseract, language, rect, macrons=False):
        reading = {} if language == "grc" else native
        return [(words[old], text, conf) for old, (text, conf) in reading.items()]

    monkeypatch.setattr(bilingual, "_read", read)
    dictionary = {"dice", "Qué", "hombre"}.__contains__
    # Wikipedia's counts have "daímon" too: the dictionary decides.
    lexicon = SimpleNamespace(known=lambda w: dictionary(w) or w == "daímon")
    lexicon.in_dictionary = dictionary
    monkeypatch.setattr(fixes, "_words", lambda language: lexicon)

    mark_words(doc, "tesseract", "es", greek=True)

    changed = {old: new for *_, old, new in page_words(doc.load_page(0))}
    assert changed == {"¿Qu<é": "¿Qué", "hom>bre": "hombre", "daím<ºn": "daímōn"}


def test_a_book_quotes_greek_when_bilingual_or_with_greek_words_on_enough_pages(make_pdf):
    with open_pdf(make_pdf([SPANISH] * 3)) as doc:
        assert not bilingual.quotes_greek(doc, set())
        assert bilingual.quotes_greek(doc, {1})  # facing pages
    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page()
        page.insert_font(fontname="G", fontbuffer=pymupdf.Font("notos").buffer)
        page.insert_text((72, 72), "la verdad, ἀλήθεια", fontname="G")
    assert bilingual.quotes_greek(doc, set())


def test_foreign_names_stay_unless_greek_is_clearly_surer_and_greek_keeps_to_its_line(
    monkeypatch,
):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "dice Hölderlin Molière (f!!ym6s),")
    words = {w[4]: w[:4] for w in page.get_text("words")}
    x0, y0, x1, y1 = words["(f!!ym6s),"]
    h = y1 - y0
    greek = {
        "Hölderlin": [(words["Hölderlin"], "Ὁλδερλιν", 80)],  # not clearly surer: kept
        "Molière": [(words["Molière"], "Μολιερε", 95)],  # clearly surer: taken, with a row
        # The line above reaches into the garbled word's box: not part of its reading.
        "(f!!ym6s),": [
            ((x0, y0 - h / 2, x0 + 5, y0 + h / 4), "κομο", 99),
            ((x0, y0, x1, y1), "(θυμός),", 95),
        ],
    }
    native = {
        "Hölderlin": ("Hólderlin", 70),
        "Molière": ("Moliére", 70),
        "(f!!ym6s),": ("(fym6s),", 40),
    }

    def read(png, tesseract, language, rect, macrons=False):
        if language == "grc":
            return [w for found in greek.values() for w in found]
        return [(words[old], text, conf) for old, (text, conf) in native.items()]

    monkeypatch.setattr(bilingual, "_read", read)
    monkeypatch.setattr(fixes, "_words", lambda language: _lexicon({"dice"}.__contains__))

    _, unsure = mark_words(doc, "tesseract", "es", greek=True)

    changed = {old: new for *_, old, new in page_words(doc.load_page(0))}
    assert changed == {"Molière": "Μολιερε", "(f!!ym6s),": "(θυμός),"}
    assert unsure == [(0, "greek-unsure", "Μολιερε", "Molière")]


def test_a_garbled_words_reading_keeps_to_its_printed_line():
    box = (0, 0, 50, 40)  # a garbled word's box reaching over the line above
    words = [((0, 0, 20, 10), "como", 95), ((0, 25, 40, 35), "(thymós),", 90)]
    words.append(((42, 22, 48, 28), "1582", 60))  # a raised note number stays
    assert bilingual._over_line(words, box, "(f!!ym6s),") == [("(thymós),", 90), ("1582", 60)]


def test_underlined_e_and_o_take_a_macron():
    import numpy as np

    # "daímon" in blocks a letter wide (í narrow, m wide) on a baseline at row 29, a line
    # under the o, and a g-like loop under the d that goes on down.
    gray = np.full((50, 60), 255, np.uint8)
    for x0, x1 in [(0, 9), (10, 19), (20, 24), (25, 39), (40, 49), (50, 59)]:
        gray[16:30, x0:x1] = 0
    gray[32:34, 41:49] = 0  # the underline
    gray[32:42, 1:9] = 0  # a loop below the baseline, not a line
    box = (0, 10, 60, 40)

    assert bilingual._long_vowels(gray, box, "daímon") == "daímōn"
    assert bilingual._long_vowels(gray, box, "drôn") == "drôn"  # long already
    gray[32:34, 41:49] = 255
    assert bilingual._long_vowels(gray, box, "daímon") == "daímon"


def test_greek_wins_when_confident_else_the_books_language():
    assert _choose([("χωρισμός", 96)], [("xweuoós", 0)]) == "χωρισμός"
    assert _choose([("Κερύδιϊιοα", 19)], [("República", 96)]) == "República"
    assert _choose([("ζο5845", 35)], [("c0sas", 40)]) is None


def test_a_re_read_word_replaces_the_whole_token_in_place():
    chars = [{"c": c, "bbox": (i, 0, i + 1, 10)} for i, c in enumerate("ver (ó.>..lÍ&La) x")]
    apply_words(chars, [[4, 0, 16, 10, "(ó.>..lÍ&La)", "(ἀλήθεια)"]])

    assert "".join(c["c"] for c in chars) == "ver (ἀλήθεια) x"

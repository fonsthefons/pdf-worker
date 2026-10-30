from pdf_worker.inline import page_mark, styled
from pdf_worker.structure import Heading, Note, Paragraph
from pdf_worker.tidy import curl_quotes, tidy


def test_curl_quotes():
    assert curl_quotes("""d'Holbach dijo "la canalla". 'Sí', dijo (“no”)""") == (
        "d’Holbach dijo “la canalla”. ‘Sí’, dijo (“no”)"
    )
    mark = page_mark(3, "4")
    assert curl_quotes(mark + '"Hola" —"adiós"') == mark + "“Hola” —“adiós”"


def test_a_space_before_punctuation_goes():
    blocks = [Paragraph("Claro que sí , como dijo ; siglo III a . C . Uno , dos, tres . . . bien")]
    assert list(tidy(blocks, "es"))[0].text == (
        "Claro que sí, como dijo; siglo III a. C. Uno, dos, tres . . . bien"
    )
    french = [Paragraph("Il dit : oui , vraiment ?")]
    assert list(tidy(french, "fr"))[0].text == "Il dit : oui, vraiment ?"


def test_copyright_and_sentence_headings_become_paragraphs():
    blocks = [
        Heading("© 1960: Frederick Copleston", 2),
        Heading("Impreso en España", 2),
        Heading("6. La actividad de Jacobi continuó durante la primera parte del siglo XIX.", 2),
        Heading("Estudios.", 2),
        Heading("KANT.—I: VIDA Y ESCRITOS", 1),
        Note("1", '"Cita".'),
    ]
    out = list(tidy(blocks))
    assert out[0] == Paragraph("© 1960: Frederick Copleston", small=True)
    assert out[1] == Paragraph("Impreso en España", small=True)
    assert isinstance(out[2], Paragraph) and not out[2].small
    assert out[3:5] == blocks[3:5]
    assert out[5] == Note("1", "“Cita”.")


def test_subheadings_under_numbered_headings_go_a_level_down():
    blocks = [
        Heading("Capítulos I-II: La Ilustración", 2),
        Heading("Textos", 2),
        Heading("1. BAYLE", 2),
        Heading(styled("Textos", italic=True), 2),
        Heading("Estudios", 2),
        Heading("2. El comienzo de la comprensión", 2),
        Heading("cristiana", 2),
        Heading("APÉNDICE", 2),
        Heading("Capítulos III-IV: Rousseau", 2),
        Heading("Estudios", 2),
    ]
    out = list(tidy(blocks))
    assert [h.level for h in out] == [2, 2, 2, 3, 3, 2, 2, 2, 2, 2]
    assert out[3].text == "Textos"


def test_a_quote_after_italic_closes():
    text = '"' + styled("Essai", italic=True) + '" y ' + styled('"Nota"', italic=True)
    assert curl_quotes(text) == "“" + styled("Essai", italic=True) + "” y " + styled(
        "“Nota”", italic=True
    )

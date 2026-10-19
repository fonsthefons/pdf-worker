from pdf_worker.inline import page_mark
from pdf_worker.structure import Heading, Note, Paragraph
from pdf_worker.tidy import curl_quotes, tidy


def test_curl_quotes():
    assert curl_quotes("""d'Holbach dijo "la canalla". 'Sí', dijo (“no”)""") == (
        "d’Holbach dijo “la canalla”. ‘Sí’, dijo (“no”)"
    )
    mark = page_mark(3, "4")
    assert curl_quotes(mark + '"Hola" —"adiós"') == mark + "“Hola” —“adiós”"


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

import zipfile

from pdf_worker.epub import write_epub
from pdf_worker.inline import END_ITALIC, ITALIC, plain, styled
from pdf_worker.markdown_export import render_markdown
from pdf_worker.output import Metadata
from pdf_worker.structure import Paragraph
from pdf_worker.styles import apply_layer, markdown_italics, span_text

IT = 2  # MuPDF's italic span flag


def test_words_take_the_style_of_their_text_layer_partners():
    # The layer misreads ("Enciclopedt·a") and drops accents; it still aligns.
    layer = [("La", 0), ("Enciclopedt·a", IT), ("y", 0), ("el", 0), ("Essai", IT), ("sur", IT)]
    layer += [("le", IT), ("merite", IT), ("(1745),", 0), ("de", 0), ("Shaftesbury[^1]", 0)]
    text = "La Enciclopedia y el Essai sur le mérite (1745), de Shaftesbury[^1]"
    assert apply_layer(text, layer) == (
        f"La {ITALIC}Enciclopedia{END_ITALIC} y el "
        f"{ITALIC}Essai sur le mérite{END_ITALIC} (1745), de Shaftesbury[^1]"
    )
    # A layer that hardly matches the block belongs to other text: no styles.
    assert apply_layer(text, [("otra", IT), ("cosa", IT)]) == text


def test_words_take_the_accents_of_their_text_layer_partners():
    layer = [("El", 0), ("imperativo", 0), ("categórico", IT), ("TEOLOGÍA", 0), ("publicó", 0)]
    layer += [("cuestión.", 0), ("Espana", 0), ("compra", 0), ("la", 0), ("conclu-", 0)]
    layer += [("sión.", 0), ("-", 0), ("El", 0)]
    text = "El imperativo categorico[^2] TEOLOGIA público cuestion: España compro la conclusion.—El"
    # Accents Paddle kept stay; a different letter ("compra") is a misreading, not an accent.
    assert apply_layer(text, layer) == (
        f"El imperativo {ITALIC}categórico{END_ITALIC}[^2] TEOLOGÍA público cuestión: España "
        "compro la conclusión.—El"
    )


def test_paddle_markdown_italics_and_italic_spans():
    assert (
        markdown_italics("en *De l'esprit* y 3 * 4")
        == f"en {ITALIC}De l'esprit{END_ITALIC} y 3 * 4"
    )
    span = {"text": " Verum quia factum, ", "flags": IT}
    assert span_text(span) == f" {ITALIC}Verum quia factum{END_ITALIC}, "
    assert span_text({"text": "plain ", "flags": 0}) == "plain "


def test_writers_render_styles(tmp_path):
    text = "la " + styled("Enciclopedia", italic=True) + " y " + styled("Nota", bold=True) + "."
    assert plain(text) == "la Enciclopedia y Nota."
    assert render_markdown(text) == "la *Enciclopedia* y **Nota**."
    # An unpaired marker (left by a text fix) can't break the XHTML.
    blocks = [Paragraph(text), Paragraph(ITALIC + "sin cierre")]
    write_epub(blocks, tmp_path / "b.epub", Metadata("T"))
    with zipfile.ZipFile(tmp_path / "b.epub") as z:
        html = "".join(z.read(n).decode() for n in z.namelist() if n.endswith(".xhtml"))
    assert "la <i>Enciclopedia</i> y <b>Nota</b>." in html and "<i>sin cierre</i>" in html

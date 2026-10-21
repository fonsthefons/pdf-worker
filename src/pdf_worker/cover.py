"""A text cover: the author, title and translator in big type, in place of a scan of
page 1. The reflowed PDF and Word get it as their first page, the EPUB as an image
(Kindle needs one for the library thumbnail).
"""

import re
from collections.abc import Iterable
from html import escape

import pymupdf

from pdf_worker.images import render_cover
from pdf_worker.output import Metadata

PAGE = pymupdf.paper_rect("a5")
_CSS = """\
body { font-family: serif; text-align: center; }
.author { font-size: 16pt; margin-bottom: 40pt; }
h1 { font-size: 28pt; line-height: 1.2; margin: 0 0 40pt 0; }
.translator { font-size: 12pt; font-style: italic; }
"""
TRANSLATED_BY = {
    "es": "Traducción de",
    "fr": "Traduit par",
    "de": "Übersetzt von",
    "it": "Traduzione di",
    "pt": "Tradução de",
}
# "Traducción de MANUEL SACRISTÁN", "TRADUCCIONES, ... Y NOTAS POR M. ÁNGELES DURÁN".
# The name must be capitalised, so "las traducciones de este volumen" is no match.
_TRANSLATOR_RE = re.compile(
    r"(?i:\b(?:traducci[oó]n(?:es)?|traducido|tradução|translat(?:ed|ion)|"
    r"übersetz(?:t|ung)|tradu(?:ction|it)|traduzione))"
    r"[^.:;]{0,60}?\b(?i:de|por|by|von|par|di)\s+([A-ZÀ-Þ][^,;()]{2,80})"
)
_JUNK_RE = re.compile(r"[\^$\\{}]")
_SMALL_WORDS = {"Y", "E", "De", "Del", "La", "And", "Von", "Van", "Und", "Et", "Di"}


def find_translator(texts: Iterable[str]) -> str:
    """The translator named in the first of ``texts`` (title-page blocks) that names one."""
    for text in texts:
        match = _TRANSLATOR_RE.search(" ".join(text.split()))
        if match:
            return name_case(" ".join(_JUNK_RE.sub(" ", match.group(1)).split()).rstrip("."))
    return ""


def name_case(name: str) -> str:
    """ "MANUEL SACRISTÁN" -> "Manuel Sacristán"; names not in capitals stay as they are."""
    if not name.isupper():
        return name
    return " ".join(w.lower() if w in _SMALL_WORDS else w for w in name.title().split())


def add_cover_page(doc: pymupdf.Document, meta: Metadata) -> None:
    """Insert the cover as ``doc``'s first page."""
    page = doc.new_page(0, width=PAGE.width, height=PAGE.height)
    html = ""
    if meta.author:
        html += f'<p class="author">{escape(meta.author)}</p>'
    html += f"<h1>{escape(meta.title)}</h1>"
    if meta.translator:
        html += f'<p class="translator">{escape(translated_by(meta))}</p>'
    page.insert_htmlbox(PAGE + (36, PAGE.height * 0.22, -36, -36), html, css=_CSS)


def cover_jpeg(meta: Metadata) -> bytes:
    with pymupdf.open() as doc:
        add_cover_page(doc, meta)
        return render_cover(doc[0])


def translated_by(meta: Metadata) -> str:
    return f"{TRANSLATED_BY.get(meta.language, 'Translated by')} {meta.translator}"

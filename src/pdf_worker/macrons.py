"""Restore Latin macrons in OCR output.

Tesseract's Latin model has no macrons: it reads a long vowel (``ā``) as a vowel with
some other accent (``à``, ``á``, ``ä``...), and now and then as the plain vowel followed
by the accented one (``Maàrcus``). Classical Latin is written without accents, so in
Latin text every such accent stands for a macron. In a book that mixes Latin with
Spanish, French... the accents of the other language are real, so restoring is done
per paragraph, only where the paragraph reads as Latin (``restore_macrons_if_latin``).
"""

import re
import unicodedata

from pdf_worker.convert import stopword_scores

_VOWELS = "aeiouyAEIOUY"
# Combining marks Tesseract uses where the page has a macron (or a breve).
_STRAY_MARKS = {
    "̀",  # grave
    "́",  # acute
    "̂",  # circumflex
    "̃",  # tilde
    "̆",  # breve
    "̈",  # diaeresis
    "̊",  # ring above (PaddleOCR-VL: "Euröpå")
}
_MACRON = "̄"

# Every precomposed vowel+mark -> vowel with macron, e.g. "à" -> "ā".
_TABLE = {
    unicodedata.normalize("NFC", vowel + mark): unicodedata.normalize("NFC", vowel + _MACRON)
    for vowel in _VOWELS
    for mark in _STRAY_MARKS
}
_TABLE = {char: macron for char, macron in _TABLE.items() if len(char) == 1}
_ACCENTED_RE = re.compile("[" + "".join(_TABLE) + "]")
# A plain vowel followed by its own accented form: one long vowel read twice.
_DOUBLED_RE = re.compile(
    "|".join(re.escape(unicodedata.normalize("NFD", char)[0] + char) for char in sorted(_TABLE))
)

_REPEATED_LONG_RE = re.compile("([" + "".join(sorted(set(_TABLE.values()))) + r"])\1+")


def restore_macrons(text: str) -> str:
    """``"Màrcus et Iülia nón"`` -> ``"Mārcus et Iūlia nōn"``."""
    text = unicodedata.normalize("NFC", text)
    text = _DOUBLED_RE.sub(lambda match: match.group(0)[1], text)
    text = _ACCENTED_RE.sub(lambda match: _TABLE[match.group(0)], text)
    # "nàávis" -> "nāāvis" -> "nāvis": Latin never repeats a long vowel.
    return _REPEATED_LONG_RE.sub(r"\1", text)


def reads_as_latin(text: str, default: bool) -> bool:
    """Whether ``text`` has more Latin stopwords than any other language's; ``default``
    when it is a tie (a heading, a name: too few words to tell)."""
    scores = stopword_scores(text)
    latin = scores.pop("la")
    other = max(scores.values())
    return default if latin == other else latin > other


def restore_macrons_if_latin(text: str, default: bool) -> str:
    """:func:`restore_macrons` if ``text`` reads as Latin, else ``text`` unchanged."""
    return restore_macrons(text) if reads_as_latin(text, default) else text

"""Bilingual editions: the original on facing pages, its words quoted in the translation.

Editions like the Abada Timeo print the Greek on the left-hand pages and the Spanish
on the right, and quote Greek words in the introduction and notes. A text layer made
by a Latin-script OCR reads the Greek as look-alikes ("ἔμφρονος" -> "eµ<j>Qovoi;").

The book is converted in its own language: a page that doesn't read as it, between two
that do, or one set mostly in Greek letters, is a facing page and is left out
(``facing_pages``); so is a Greek paragraph on the other pages, in a bilingual
edition only (``drop_greek``; a few Greek words quoted in a sentence stay). Quoted words
that look garbled (odd signs; in a book with Greek terms, ``quotes_greek``, also letters
the book's language doesn't write, and beside those, words that aren't its own) are read
again, their line at a time, with Tesseract in Greek and in the book's language (as
``pdf_worker.mixed_script`` does): a confident Greek reading replaces the token (in a book
with Greek terms not an italic one: a transliteration), else a confident reading in the
book's language ("Ref>ública" -> "República"). Greek taken over an as confident
reading in the book's language goes to the review file as ``greek-unsure``.
The replacements are stored on the page in memory (``/PdfWorkerWords``) and applied by
``pdf_worker.layout.page_lines``.
"""

import json
import re
import unicodedata
from collections.abc import Callable, Collection, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

import pymupdf

from pdf_worker.consensus import _union
from pdf_worker.inline import PAGE_MARK_RE, plain
from pdf_worker.margin_refs import has_bracketed
from pdf_worker.mixed_script import _DPI, GREEK, _overlap, _tsv

if TYPE_CHECKING:
    import numpy as np

    from pdf_worker.structure import Block, Paragraph

WORDS_KEY = "PdfWorkerWords"
_WORD_RE = re.compile(r"[^\W\d_]+")
# Stopword share of a page's words: below FOREIGN it is in another language, from
# NATIVE it is in the book's (Spanish pages 0.25-0.37, Greek read as Latin 0.00-0.09).
_FOREIGN, _NATIVE = 0.15, 0.25
_MIN_WORDS = 40
_MIN_FACING = 4  # facing pages a bilingual edition has at least
# A token that looks like Greek read as Latin: odd signs, digits or case flips inside.
_ODD_RE = re.compile(r"[µ<>!_|{}\\$%&*+=~^;]")
_DIGIT_IN_WORD_RE = re.compile(r"[^\W\d_]\d+[^\W\d_]")
_ORDINAL_IN_WORD_RE = re.compile(r"[^\W\d_]{2}[ºª]")  # an underlined o: "daímºn", not "Nº"
_CASE_FLIP_RE = re.compile(r"[a-zß-ÿ][A-Z]")
_EDGES = "()[]«»¿?¡!.,;:'\"’‘“”-—–•*"
_GREEK_SHARE = 0.6
# A paragraph this much in Greek letters is Greek (Greek pages are 0.94-0.99); from the
# lower share it is too when it has next to none of the book's words: the rest is Greek
# read as Latin ("TTOU TWV χθὲς μὲν", 0.17-0.84). So is a bibliography entry with a
# Greek title (0.8), which goes too.
_GREEK_PARAGRAPH_SHARE = 0.9
_MIXED_GREEK_SHARE = 0.15
_MIN_GREEK_CONF, _MIN_NATIVE_CONF = 60, 85
_CLEAR_GREEK_CONF, _CLEAR_GREEK_GAP = 85, 15  # Greek over a clean Latin word
_GREEK_WORD_RE = re.compile(r"[Ͱ-Ͽἀ-῿]{2,}")
_GREEK_PAGES = 0.05  # share of pages with Greek words that makes a book quote Greek
_MIN_GUESS_CONF = 70  # a garbled word takes a less sure clean reading, and a review row
# ... made of words only: a note number glued to a word reads as quotes or digits
# ("inengendrado9+" -> "inengendrado”,").
_GUESS_RE = re.compile(r"[(«¿¡]?[^\W\d_]+(?:['’-][^\W\d_]+)*[»)?!.,;:]*")
# Letters a language writes beyond a-z and the Latin quotations' æ, œ ("Præstet"), after
# NFKC ("º" is "o"); any other Latin letter in a word is a misreading ("ōauloii", "Ćmías",
# "ǽ"). No entry: the rule is off (Latin's macrons).
_LETTERS = {
    "en": "",
    "es": "áéíóúüñ",
    "fr": "àâæçéèêëîïôœùûüÿ",
    "de": "äöüß",
    "it": "àèéìíòóùú",
    "pt": "áâãàçéêíóôõú",
}
# A transliteration's long e or o printed with a line under it ("diakosmḗseōs"): placed on
# its letter by the letters' rough widths.
_MACRON, _CIRCUMFLEX = "̄", "̂"
_NARROW, _WIDE = "fijlrt", "mw"


def facing_pages(doc: pymupdf.Document) -> tuple[str, set[int]]:
    """The book's language and the indexes of its facing pages in another language."""
    from pdf_worker.convert import stopword_scores

    pages = []
    totals: dict[str, int] = {}
    for page in doc:
        text = page.get_text()
        scores = stopword_scores(text)
        for language, hits in scores.items():
            totals[language] = totals.get(language, 0) + hits
        pages.append((len(_WORD_RE.findall(text)), scores, _greek_share(text)))
    language = max(totals, key=totals.get) if totals else "en"

    def share(i: int) -> float | None:
        words, scores, _ = pages[i]
        return scores[language] / words if words >= _MIN_WORDS else None

    shares = [share(i) for i in range(len(pages))] + [None, None]  # [-1], [-2]: past the end

    def foreign(i: int) -> bool:
        return shares[i] is not None and shares[i] < _FOREIGN

    def native(i: int) -> bool:
        return shares[i] is not None and shares[i] >= _NATIVE

    # Between pages in the book's language (or a title page with few words)...
    between = {
        i
        for i in range(len(pages))
        if foreign(i)
        and not foreign(i - 1)
        and not foreign(i + 1)
        and (native(i - 1) or native(i + 1))
    }
    # ...and every other page: a lone one is a table or a figure.
    facing = {i for i in between if i - 2 in between or i + 2 in between}
    # Pages set in Greek letters need no neighbours: a split-word text layer ("p rin cip
    # io") leaves the translation's pages too few stopwords to count as its language.
    facing |= {
        i
        for i, (words, _, greek) in enumerate(pages)
        if words >= _MIN_WORDS and greek >= _GREEK_SHARE
    }
    return language, facing if len(facing) >= _MIN_FACING else set()


def quotes_greek(doc: pymupdf.Document, facing: Collection[int]) -> bool:
    """A book with Greek terms: a bilingual edition (``facing`` pages), or one with Greek
    words in its text layer on enough pages (Introducción a la Filosofía 30%; Platón's
    Diálogos 0.5%, its transliterations born digital)."""
    if facing:
        return True
    pages = sum(bool(_GREEK_WORD_RE.search(page.get_text())) for page in doc)
    return pages >= _GREEK_PAGES * doc.page_count


def drop_greek(
    blocks: Iterable["Block"], dropped: list["Paragraph"], language: str, is_bilingual: bool
) -> Iterator["Block"]:
    """Leave out Greek paragraphs of a bilingual edition (any other book quotes Greek
    on purpose: all kept), appending them to ``dropped``: nearly all in Greek
    letters, or partly (the rest Greek read as Latin) with next to none of the words of
    the book's ``language``. A paragraph with neither, between two Greek ones, is Greek
    read as Latin throughout ("av É KWV Tᰶ08E"): left out too. Page marks go on to the
    next block."""
    from pdf_worker.structure import Heading, Note, Paragraph  # it imports layout, which imports us

    if not is_bilingual:
        yield from blocks
        return
    marks, held, after_greek = "", None, False

    def drop(block: "Paragraph") -> None:
        nonlocal marks
        dropped.append(block)
        marks += "".join(m.group() for m in PAGE_MARK_RE.finditer(block.text))

    def keep(block: "Block") -> "Block":
        nonlocal marks
        if marks and isinstance(block, Heading | Paragraph | Note):
            block, marks = replace(block, text=marks + block.text), ""
        return block

    for block in blocks:
        kind = (
            _paragraph_kind(plain(block.text), language) if isinstance(block, Paragraph) else None
        )
        if held is not None:
            if kind == "greek":
                drop(held)
            else:
                yield keep(held)
                after_greek = False
            held = None
        if kind == "greek":
            drop(block)
            after_greek = True
        elif kind == "foreign" and after_greek:
            held = block  # Greek if the next paragraph is
        else:
            after_greek = False
            yield keep(block)
    if held is not None:
        yield keep(held)


def _paragraph_kind(text: str, language: str) -> str | None:
    """ "greek", "foreign" (none of ``language``'s words, no Greek letters) or None."""
    from pdf_worker.convert import stopword_scores

    words = _WORD_RE.findall(text)
    if not words:
        return None
    greek = _greek_share(text)
    native = stopword_scores(text).get(language, 0) >= _FOREIGN * len(words)
    if greek >= _GREEK_PARAGRAPH_SHARE or (greek >= _MIXED_GREEK_SHARE and not native):
        return "greek"
    return "foreign" if not native and not greek else None


def suspect(token: str, language: str = "") -> bool:
    """A token that looks garbled ("i(CllQLOµóB"), or with ``language``, has a Latin letter
    it doesn't write ("ōauloii"); not a reference ("[I7d]") or address."""
    if has_bracketed(token) or "/" in token or "@" in token:
        return False
    core = re.sub(r"\d+$", "", token.strip(_EDGES)).strip(_EDGES)  # a note number
    if sum(c.isalpha() for c in core) < 2:
        return False
    if any(
        r.search(core) for r in (_ODD_RE, _DIGIT_IN_WORD_RE, _CASE_FLIP_RE, _ORDINAL_IN_WORD_RE)
    ):
        return True
    letters = _LETTERS.get(language)
    return letters is not None and any(
        c.isalpha() and not _greek_share(c) and not _written(c, letters)
        for c in unicodedata.normalize("NFC", core)
    )


def _written(char: str, letters: str) -> bool:
    return all(
        c.isascii() or c in letters or c in "æœ"
        for c in unicodedata.normalize("NFKC", char).lower()
    )


def _neighbour(token: str, known: Callable[[str], bool]) -> bool:
    """A word beside a garbled one that isn't one of the book's language (nor Greek
    already): misread too."""
    core = token.strip(_EDGES)
    return (
        len(core) >= 2
        and bool(_WORD_RE.fullmatch(core))
        and not _greek_share(core)
        and not known(core)
    )


def _unaccented(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def mark_words(
    doc: pymupdf.Document,
    tesseract: str,
    language: str,
    skip: Collection[int] = (),
    jobs: int = 4,
    on_line: Callable[[int, int], None] | None = None,
    greek: bool = False,
) -> tuple[int, list[tuple[int, str, str, str]]]:
    """Store re-read words on the pages of ``doc`` (in memory), the book being in
    ``language`` ("es"); returns how many, and the unsure ones: (page index, kind, reading
    taken, other): ``greek-unsure``, Greek taken over an as confident reading in the book's
    language, or ``reread-unsure``, a garbled word ("Pdskli2n") taken as the book language's
    less confident reading ("Páskhōn"; the other is the old text). A reading that only
    changes accents isn't taken: the word was right but for letters the language's model
    lacks ("Jérôme" -> "Jéróme"); unless it adds the macrons of underlined vowels ("daímºn"
    -> "daímōn", ``_long_vowels``).
    Only in a book with Greek terms (``greek``, see ``quotes_greek``): the wider suspect
    rules (``suspect``'s letters, unknown neighbours), italic words (transliterations)
    never read as Greek, readings kept to their printed line, less sure guesses, and
    macrons (not on its dictionary's words: "hombre", not "hōmbre"). Elsewhere those
    misfire on foreign quotations ("causalità"), letter-spaced titles and noisy scans.
    ``on_line(done, total)`` follows the lines read."""
    from pdf_worker.fixes import SPELL_LANGUAGES, _words  # fixes imports layout, which imports us
    from pdf_worker.ocr import TESSERACT_CODES

    code = TESSERACT_CODES[language]

    def known(word: str) -> bool:
        return language not in SPELL_LANGUAGES or _words(language).known(word)

    def in_dictionary(word: str) -> bool:  # not Wikipedia's counts: they have "hos", "tón"
        return language in SPELL_LANGUAGES and _words(language).in_dictionary(word)

    lines = [
        line
        for i in range(doc.page_count)
        if i not in skip
        for line in (_lines(doc, i, language, known) if greek else _lines(doc, i))
    ]

    def read(line: tuple) -> list:
        _, rect, png, _ = line
        return [_read(png, tesseract, GREEK, rect), _read(png, tesseract, code, rect, greek)]

    # Tesseract runs as a subprocess, so threads read lines in parallel (MuPDF stays
    # in this thread: it isn't thread-safe).
    readings = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for reading in pool.map(read, lines):
            readings.append(reading)
            if on_line:
                on_line(len(readings), len(lines))
    words: dict[int, list[list]] = {}
    unsure = []
    for (index, _, _, bad), (greek_words, native) in zip(lines, readings, strict=True):
        for old, box, italic in bad:
            if greek:
                theirs = [
                    (_long_only(t, in_dictionary), c) for t, c in _over_line(native, box, old)
                ]
            else:
                theirs = _over(native, box)
            text, conf = _joined(theirs)
            if italic and greek:
                ours = []
            else:
                ours = _over_line(greek_words, box, old) if greek else _over(greek_words, box)
            new = _choose(ours, theirs)
            g_text, g_conf = _joined(ours)
            latin = g_text != "" and new == g_text and _plain_latin(old)
            if latin and not (g_conf >= _CLEAR_GREEK_CONF and g_conf >= conf + _CLEAR_GREEK_GAP):
                continue  # a foreign name ("Hölderlin"), not Greek read as Latin
            guess = (
                greek
                and not new
                and suspect(old, language)
                and _clean_reading(text, conf, _MIN_GUESS_CONF)
                and all(_GUESS_RE.fullmatch(t) for t in text.split())
            )
            new = new or (text if guess else None)
            if new and (_unaccented(new) != _unaccented(old) or _macrons(new) > _macrons(old)):
                words.setdefault(index, []).append([*box, old, new])
                if guess:
                    unsure.append((index, "reread-unsure", new, old))
                elif latin:
                    unsure.append((index, "greek-unsure", new, old))
                elif new != text and _clean_reading(text, conf):
                    unsure.append((index, "greek-unsure", new, text))
    for index, found in words.items():
        page = doc.load_page(index)
        doc.xref_set_key(page.xref, WORDS_KEY, pymupdf.get_pdf_str(json.dumps(found)))
    return sum(len(found) for found in words.values()), unsure


def page_words(page: pymupdf.Page) -> list[list]:
    kind, value = page.parent.xref_get_key(page.xref, WORDS_KEY)
    return json.loads(value) if kind == "string" else []


def apply_words(chars: list[dict], words: list[list]) -> None:
    """Put re-read words into a line's ``rawdict`` characters: the old token's first
    character takes the new text and the rest go empty, so positions stay the same."""
    for token in _tokens(chars):
        text = "".join(c["c"] for c in token)
        x0, y0, x1, y1 = _union(token)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for fx0, fy0, fx1, fy1, old, new in words:
            if old == text and fx0 <= cx <= fx1 and fy0 <= cy <= fy1:
                token[0]["c"] = new
                for other in token[1:]:
                    other["c"] = ""
                break


def _lines(
    doc: pymupdf.Document,
    index: int,
    language: str = "",
    known: Callable[[str], bool] | None = None,
) -> list[tuple]:
    """(page index, line rect, line image, [(token, box, italic)]) for lines with suspect
    tokens (``suspect``'s ``language``); with ``known``, their neighbours that aren't words
    of the book's language go too."""
    page = doc.load_page(index)
    out = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", ()):
            for span in line["spans"]:
                for c in span["chars"]:
                    c["italic"] = bool(span["flags"] & pymupdf.TEXT_FONT_ITALIC)
            chars = [c for span in line["spans"] for c in span["chars"]]
            texts = [
                ("".join(c["c"] for c in t), _union(t), any(c["italic"] for c in t))
                for t in _tokens(chars)
            ]
            hit = {i for i, (text, _, _) in enumerate(texts) if suspect(text, language)}
            hit |= {
                j
                for i in hit
                for j in (i - 1, i + 1)
                if known and 0 <= j < len(texts) and j not in hit and _neighbour(texts[j][0], known)
            }
            bad = [texts[i] for i in sorted(hit)]
            if bad:
                rect = pymupdf.Rect(line["bbox"]) + (-3, -3, 3, 3)
                pix = page.get_pixmap(dpi=_DPI, clip=rect, colorspace=pymupdf.csGRAY, annots=False)
                out.append((index, rect, pix.tobytes("png"), bad))
    return out


def _choose(greek: list[tuple[str, float]], native: list[tuple[str, float]]) -> str | None:
    """Greek when it reads as Greek, confidently and more so than the book's language;
    else the book's language when it is confident and itself looks clean."""
    g_text, g_conf = _joined(greek)
    n_text, n_conf = _joined(native)
    if g_text and _greek_share(g_text) >= _GREEK_SHARE and g_conf >= max(_MIN_GREEK_CONF, n_conf):
        return g_text
    return n_text if _clean_reading(n_text, n_conf) else None


def _clean_reading(text: str, conf: float, least: float = _MIN_NATIVE_CONF) -> bool:
    """The book language's reading is confident and itself looks clean."""
    return bool(text) and conf >= least and not any(suspect(t) for t in text.split())


def _read(
    png: bytes, tesseract: str, language: str, rect: pymupdf.Rect, macrons: bool = False
) -> list:
    """Tesseract's words in page coordinates: (box, text, confidence); with ``macrons``,
    those of underlined vowels (read in Latin letters)."""
    import cv2
    import numpy as np

    scale = 72 / _DPI
    words = _tsv(png, tesseract, language)
    if macrons and words:
        gray = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        words = [replace(w, text=_long_vowels(gray, w.box, w.text)) for w in words]
    return [
        (
            (
                rect.x0 + w.box[0] * scale,
                rect.y0 + w.box[1] * scale,
                rect.x0 + w.box[2] * scale,
                rect.y0 + w.box[3] * scale,
            ),
            w.text,
            w.conf,
        )
        for w in words
    ]


def _long_vowels(gray: "np.ndarray", box: tuple, text: str) -> str:
    """``text``, a word read in ``box`` of the line image ``gray``, with a macron on each e
    or o printed with a line under it; not on a circumflex one, long already ("drôn")."""
    chars = list(unicodedata.normalize("NFD", text))
    for share in _underlines(gray, box):
        bases = [i for i, c in enumerate(chars) if not unicodedata.combining(c)]
        widths = [
            0.5
            if not chars[i].isalpha() or chars[i].lower() in _NARROW
            else 1.5
            if chars[i].lower() in _WIDE
            else 1.0
            for i in bases
        ]
        centres = [(sum(widths[:k]) + w / 2) / sum(widths) for k, w in enumerate(widths)]
        vowels = [k for k, i in enumerate(bases) if chars[i] in "eoEO"]
        if not vowels:
            continue
        k = min(vowels, key=lambda k: abs(centres[k] - share))
        end = bases[k + 1] if k + 1 < len(bases) else len(chars)
        marks = chars[bases[k] + 1 : end]
        if abs(centres[k] - share) < 1.5 / len(bases) and not {_MACRON, _CIRCUMFLEX} & set(marks):
            chars.insert(bases[k] + 1, _MACRON)
    return unicodedata.normalize("NFC", "".join(chars))


def _underlines(gray: "np.ndarray", box: tuple) -> list[float]:
    """The middle of each line under the word in ``box``, as a share of its width: a run of
    ink a letter wide just under the baseline, with nothing below it (a g's loop goes on)."""
    import cv2
    import numpy as np

    x0, y0, x1, y1 = box
    height = y1 - y0
    ink = gray[y0 : y1 + height // 4, x0:x1] < 128
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8))
    bottoms = [y + h - 1 for _, y, _, h, _ in stats[1:] if h >= 0.25 * height]
    if not bottoms:
        return []
    base = int(np.median(bottoms))  # letters stand on it; descenders and underlines are few
    spans: list[list[int]] = []
    for row in range(base + 2, min(len(ink), base + 2 + max(3, int(0.12 * height)))):
        edges = np.flatnonzero(np.diff(np.concatenate([[0], ink[row].astype(np.int8), [0]])))
        for start, end in zip(edges[::2], edges[1::2], strict=True):
            below = ink[row + 3 : row + 3 + max(3, int(0.2 * height)), start:end]
            if max(6, 0.25 * height) <= end - start <= 1.2 * height and not below.any():
                for span in spans:
                    if start < span[1] and span[0] < end:
                        span[:] = [min(span[0], start), max(span[1], end)]
                        break
                else:
                    spans.append([start, end])
    return [(start + end) / 2 / (x1 - x0) for start, end in spans]


def _macrons(text: str) -> int:
    return unicodedata.normalize("NFD", text).count(_MACRON)


def _long_only(text: str, known: Callable[[str], bool]) -> str:
    """``text`` without the macrons of the words that, without them, are ``known`` words of
    the book's language (its dictionary's): a scan's specks under "hombre" or "que", no
    transliteration."""

    def plain(word: str) -> str:
        return unicodedata.normalize("NFC", unicodedata.normalize("NFD", word).replace(_MACRON, ""))

    return " ".join(
        plain(w) if _macrons(w) and known(plain(w).strip(_EDGES)) else w for w in text.split(" ")
    )


def _plain_latin(token: str) -> bool:
    """A word of Latin letters only (accents too) with no sign of misreading: a name
    ("Molière") rather than Greek read as Latin."""
    core = token.strip(_EDGES)
    return (
        bool(_WORD_RE.fullmatch(core))
        and not _greek_share(core)
        and not any(r.search(core) for r in (_ODD_RE, _CASE_FLIP_RE, _ORDINAL_IN_WORD_RE))
    )


def _over(words: list, box: tuple) -> list[tuple[str, float]]:
    return [(text, conf) for b, text, conf in words if _overlap(b, box) >= 0.5]


def _over_line(words: list, box: tuple, old: str) -> list[tuple[str, float]]:
    """The words over ``box`` on one printed line, that of the one most like ``old``: a
    garbled word's box can reach over the lines around it ("(f!!ym6s)," over "como Las
    partes (thymós),")."""
    over = [w for w in words if _overlap(w[0], box) >= 0.5]
    if len(over) > 1:
        best = max(over, key=lambda w: SequenceMatcher(None, w[1], old).ratio())[0]
        over = [w for w in over if w[0][1] < best[3] and best[1] < w[0][3]]  # note numbers stay
    return [(text, conf) for _, text, conf in over]


def _joined(words: list[tuple[str, float]]) -> tuple[str, float]:
    if not words:
        return "", 0.0
    return " ".join(t for t, _ in words), sum(c for _, c in words) / len(words)


def _greek_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    greek = sum("GREEK" in unicodedata.name(c, "") for c in letters)
    return greek / len(letters) if letters else 0.0


def _tokens(chars: list[dict]) -> list[list[dict]]:
    """Runs of characters between spaces."""
    runs: list[list[dict]] = [[]]
    for char in chars:
        if char["c"].isspace():
            runs.append([])
        else:
            runs[-1].append(char)
    return [run for run in runs if run]

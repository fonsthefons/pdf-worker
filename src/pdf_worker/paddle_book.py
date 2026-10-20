"""Build a book's blocks straight from PaddleOCR-VL's page blocks.

``convert --ocr redo --ocr-engine paddle`` used to write Paddle's text into the PDF as
an invisible layer and then read that layer back, guessing paragraphs, notes and
headings from type sizes; the guess undid what Paddle already knew. Here Paddle's labels
decide: titles become headings, text blocks paragraphs (joined across pages when a block
goes on with the sentence), footnotes notes, pictures images; running heads, page numbers
and footers are dropped. The cleaning is the OCR path's (``paddle_ocr.prepare_blocks``:
note numbers, references, margin references from Tesseract).

Notes are labelled per part (``c<part>-<n>``): a count that starts again from 1 (the
introduction's notes, then the dialogue's) is a new part, as in the printed book.
"""

import bisect
import contextlib
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator

import pymupdf

from pdf_worker import missing_refs, styles
from pdf_worker.images import _render
from pdf_worker.inline import MARGIN_REF_RE, margin_ref, page_mark, plain
from pdf_worker.layout import _roman
from pdf_worker.margin_refs import assign_labels, in_book
from pdf_worker.note_numbers import SUPERSCRIPT_RE, from_sup, left_open
from pdf_worker.ocr import DEFAULT_LANGUAGE, TESSERACT_CODES, OcrEngineMissingError, tesseract_path
from pdf_worker.paddle_ocr import (
    clean_text,
    mixed_reader,
    page_scanner,
    prepare_blocks,
    text_settings,
)
from pdf_worker.structure import Block, Gloss, Heading, Image, Note, Paragraph

_SENTENCE_END = tuple('.!?»"”’)]:;')
_LEADING_REFS_RE = re.compile(f"(?:{MARGIN_REF_RE.pattern})*")
# Paddle keeps a line-break hyphen with a space: "Pro- tarco".
# shortcut: also joins a real "físico- químico"; rare in prose, check on other books.
_BROKEN_WORD_RE = re.compile(r"(\w)- (?=[a-záéíóúñü])")
# A speech: "SÓC.—", "Sóc. —", "PROTARCO. —" (Paddle varies case, accents and spacing).
_SPEAKER_RE = re.compile(
    rf"^((?:{MARGIN_REF_RE.pattern})*)"
    r"([A-ZÁÉÍÓÚÑỐ][A-Za-záéíóúñốÁÉÍÓÚÑỐ]{1,11})\s*\.?\s*[—–-]\s*"
)
# The model's second reading of a note's own number: "³⁵ 5 ¿Eco", "²⁷ ? Sobre".
_NOTE_JUNK_RE = re.compile(r"^(?:\d{1,3}[.)]?|[?*'])\s+")
# Front matter: the leading pages with fewer words than this (title pages, credits).
_FRONT_WORDS = 60
_HEAD_ZONE = 0.15  # a "header" lower on the page is a centred line (dramatis personae)
_PICTURE_LABELS = {"image", "figure", "chart"}
_MIN_PICTURE_SHARE = 0.02  # of the page area: smaller ones are ornaments or specks
_DROP = {"header", "number", "footer", "formula_number"}
# Spanish "¿" misread as a letter or digit glued to the question's first word ("iY
# bien?", "lPor qué?", "2El qué?", "ipodrías ...?"), or apart ("L Cómo no?"): group 1
# is the misread mark, group 2 that word.
_LOST_QUESTION_RE = re.compile(r"(?<![\w¿¡])([iIlℓ12|!ủé]|[iIlLℓ12] )(?=(\w+)[^.!?¿]*\?)")
# The same for "¡" ("jtú!", "ivenga!", ";Tendría que ver!", "iY si es un ladrón!").
_LOST_EXCLAMATION_RE = re.compile(r"(?<![\w¿¡])([iIlj;1|]|[iIl] )(?=(\w+)[^.?!¿¡]*!)")
# Vietnamese letters in a Spanish book are misreads of Spanish ones ("Sốc." "Sị"):
# only an acute, a tilde or a diaeresis are kept.
_VIETNAMESE_RE = re.compile(r"[Ạ-ỹ]")
_SPANISH_MARKS = {"́", "̃", "̈"}
_COMMON = 3  # a word seen this often in the book is a real one
# shortcut: Spanish's one-letter words are vowels and "y"; set per language if a
# book in another language uses margin references.
_LONE_CONSONANT_RE = re.compile(r"[b-df-hj-np-tv-xzB-DF-HJ-NP-TV-XZ]")
# Printed page numbers further apart than this: pages are missing from the scan (a
# misread page number rarely jumps forward by little).
_PAGE_JUMP = 1


def _is_mark_word(word: str, label: str) -> bool:
    """A margin mark read into the text: its letter or number, or a lone consonant."""
    return word in (label[-1], label[:-1]) or bool(_LONE_CONSONANT_RE.fullmatch(word))


def restore_question_marks(text: str, counts: Counter) -> str:
    """Put back the "¿" that Paddle read as "i", "l", "2" ... before a question's
    first word. Before a capital it can't be anything else; before a lowercase word
    only when the book (``counts``: its words, lowercase) knows the word without it
    and hardly with it ("ipor" -> "¿por", but "idea" stays). The same for "¡"."""

    def fixer(opening: str) -> Callable[[re.Match], str]:
        def fix(match: re.Match) -> str:
            mark, word = match.groups()
            if word[0].isupper():
                return opening
            glued = (mark + word).lower()
            if " " not in mark and counts[glued] <= 1 and counts[word.lower()] >= _COMMON:
                return opening
            return mark

        return fix

    text = _LOST_QUESTION_RE.sub(fixer("¿"), text)
    return _LOST_EXCLAMATION_RE.sub(fixer("¡"), text)


def spanish_letters(text: str) -> str:
    """ "Sốc." -> "Sóc.", "Sị" -> "Sí": a Vietnamese letter keeps its Spanish accent."""

    def fix(match: re.Match) -> str:
        parts = unicodedata.normalize("NFD", match.group())
        kept = parts[0] + "".join(c for c in parts[1:] if c in _SPANISH_MARKS)
        return unicodedata.normalize("NFC", kept)

    return _VIETNAMESE_RE.sub(fix, text)


def printed_labels(readings: list[tuple[int, str]]) -> dict[int, str]:
    """Each page's printed number from Paddle's ``(page, reading)``, in page order. A
    reading counts when the reading before or after agrees with it; other pages (chapter
    openings print none, some are misread) count on from the last one that counts.
    Pages before printed page 1 get lower-case Roman numerals."""
    numbers = [(page, int(n)) for page, n in readings if n.isdigit()]
    agreed = [
        (page, n)
        for k, (page, n) in enumerate(numbers)
        if any(
            0 <= j < len(numbers) and numbers[j][1] - n == numbers[j][0] - page
            for j in (k - 1, k + 1)
        )
    ]
    labels = {}
    for page, _ in readings:
        k = bisect.bisect_right(agreed, (page, math.inf)) - 1
        known, n = agreed[max(k, 0)] if agreed else (page, page + 1)
        number = n + page - known
        labels[page] = str(number) if number >= 1 else _roman(page + 1).lower()
    return labels


def text_sample(rows: list[dict]) -> str:
    return " ".join(b.get("text", "") for row in rows for b in row["blocks"])[:20_000]


def iter_paddle_blocks(
    doc: pymupdf.Document,
    rows: list[dict],
    images: bool = True,
    latin_macrons: bool | None = None,
    restored: list[str] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    margin_refs: bool | None = None,
) -> Iterator[Block]:
    """The book's blocks from Paddle's ``rows`` (one per page, as ``paddle_pages``
    returns them) for the scanned ``doc``. References put back by
    ``pdf_worker.missing_refs`` are told in ``restored``, one line each.
    ``on_page(done, total)`` is called after each page. With ``margin_refs`` False no
    margin mark is labelled; with None only when labels are on enough pages
    (``margin_refs.in_book``)."""
    language, macrons, latin_default, rivals = text_settings(rows, latin_macrons)
    scan_of = page_scanner(language)
    read_mixed = mixed_reader(language)
    clips = missing_refs.PaddleClips()
    tries = [("text layer", missing_refs.text_layer)]
    with contextlib.suppress(OcrEngineMissingError):  # no Tesseract: skip that try
        code = TESSERACT_CODES.get(language, DEFAULT_LANGUAGE)
        tries.append(("Tesseract", missing_refs.tesseract_try(tesseract_path(), code)))
    tries.append(("Paddle crop", clips))
    # Pages are prepared first and the book is built after: margin marks are labelled
    # all at once (``assign_labels``), which needs every reading.
    prepared = []  # (page mark, row, blocks, anchors); blocks None for front matter
    last_note, last_open = None, False
    printed = None  # the previous page's printed number
    front = True
    rows = sorted(rows, key=lambda r: r["page"])
    numbers = [
        next((b["text"].strip() for b in row["blocks"] if b.get("label") == "number"), "")
        for row in rows
    ]
    labels = printed_labels([(row["page"], n) for row, n in zip(rows, numbers, strict=True)])
    try:
        for done, (row, number) in enumerate(zip(rows, numbers, strict=True)):
            if on_page:
                on_page(done, len(rows))
            page = doc.load_page(row["page"])
            label = labels[row["page"]]
            mark = page_mark(row["page"], label)
            if front:
                words = sum(
                    len(b.get("text", "").split())
                    for b in row["blocks"]
                    if b.get("label") in ("text", "footnote")
                )
                if words < _FRONT_WORDS:
                    # title pages: the cover and the metadata stand for them
                    prepared.append((mark, row, None, None))
                    continue
                front = False
            if any(b.get("label") == "content" for b in row["blocks"]):
                # A printed table of contents ("ROUSSEAU.—I ..... 6"): the book's own
                # navigation stands for it, as in the text-layer path.
                prepared.append((mark, row, None, None))
                continue
            if number.isdigit() and printed is not None and int(number) - printed > _PAGE_JUMP:
                # Pages missing from the scan (279 -> 282): their notes are gone too, so
                # the count goes on from this page's first reference, not from the last.
                refs = [
                    from_sup(r)
                    for b in row["blocks"]
                    if b.get("label") != "footnote"
                    for r in SUPERSCRIPT_RE.findall(clean_text(b.get("text", "")))
                ]
                if refs and last_note is not None and min(refs) > last_note:
                    last_note, last_open = min(refs) - 1, False
            printed = int(number) if number.isdigit() else None
            blocks, anchors, last_note = prepare_blocks(
                page,
                row,
                macrons,
                latin_default,
                rivals,
                scan_of(page),
                last_note,
                last_open,
                read_mixed,
            )
            last_open = left_open(blocks)
            for n, source in missing_refs.restore(page, blocks, tries):
                if restored is not None:
                    restored.append(f"note {n} reference restored from {source}, page {label}")
            layer = styles.layer_words(page)
            for block in blocks:
                text = styles.markdown_italics(block[2])
                block[2] = styles.apply_layer(text, styles.words_in(layer, block[1]))
            prepared.append((mark, row, blocks, anchors))
        if on_page:
            on_page(len(rows), len(rows))
    finally:
        clips.close()

    def build(book: _Book, pictures: bool) -> Iterator[Block]:
        for mark, row, blocks, anchors in prepared:
            book.marks.append(mark)
            book.page = row["page"]
            if blocks is not None:
                yield from book.add_page(doc.load_page(row["page"]), row, blocks, anchors, pictures)
        yield from book.flush()

    book = _Book(lambda reading: None)
    if margin_refs is not False:
        readings: list[tuple[int, str | None]] = []
        dry = _Book(lambda reading: readings.append((dry.page, reading)))
        for block in build(dry, False):
            if isinstance(block, Heading):
                readings.append((dry.page, None))  # a new section: the marks count anew
        found = assign_labels(readings)
        marks = [page for page, reading in readings if reading is not None]
        labelled = {page for page, label in zip(marks, found, strict=True) if label}
        if margin_refs or in_book(len(labelled), len(rows)):
            labels = iter(found)
            book = _Book(lambda reading: next(labels))
    if language == "es":
        book.counts = Counter(
            w.lower() for row in rows for b in row["blocks"] for w in re.findall(r"\w+", b["text"])
        )
    yield from build(book, images)


class _Book:
    def __init__(self, label_of: Callable[[str], str | None]) -> None:
        self.label_of = label_of  # a margin mark's reading -> its label (None: no mark)
        self.page = 0  # the page being added (0-based)
        self.counts: Counter | None = None  # a Spanish book's words: "¿" is put back
        self.para: str | None = None  # the paragraph in progress (may run on a page)
        self.pending: list[Block] = []  # notes, glosses and pictures after it
        self.marks: list[str] = []  # page starts not yet placed in the text
        self.part = 0
        self.notes_seen = False
        self.last_note: str | None = None

    def flush(self) -> Iterator[Block]:
        if self.para is not None:
            yield Paragraph(self.para.strip())
            self.para = None
        yield from self.pending
        self.pending = []

    def add_page(self, page, row, blocks, anchors, images) -> Iterator[Block]:
        notes = [b for b in blocks if b[0] == "footnote"]
        # A note count starting again from 1: the next part (introduction -> dialogue).
        if any(n[2].startswith("¹ ") for n in notes) and self.notes_seen:
            self.part += 1
        self.notes_seen = self.notes_seen or bool(notes)
        first_text = True
        for i, (label, rect, text) in enumerate(blocks):
            if label == "header" and rect.y0 > page.rect.height * _HEAD_ZONE:
                yield from self.flush()  # "SÓCRATES, PROTARCO, FILEBO" under the title
                yield Paragraph(" ".join(text.split()), small=True)
                continue
            if label in _DROP:
                continue
            if label == "footnote":
                self._add_note(text)
                continue
            if label == "aside_text":
                self.pending.append(Gloss(tuple(text.splitlines())))
                continue
            if label == "algorithm":  # a table of variants: one small line each
                yield from self.flush()
                for line in text.splitlines():
                    yield Paragraph(line, small=True)
                continue
            if label in ("doc_title", "paragraph_title"):
                yield from self.flush()
                yield Heading(" ".join(text.split()), 1 if label == "doc_title" else 2)
                continue
            text = self._body_text(text, anchors.get(i, []))
            lead = "".join(self.marks)
            self.marks = []
            # The page's first text block goes on with the previous page's paragraph
            # when that one ended mid-sentence or this one starts in lowercase.
            plain_start = plain(text).lstrip()
            continues = (
                self.para is not None
                and first_text
                and (plain_start[:1].islower() or not self.para.rstrip().endswith(_SENTENCE_END))
            )
            first_text = False
            if continues:
                end = self.para.rstrip()
                if re.search(r"\w-$", end) and plain_start[:1].islower():
                    # The page mark (and a margin reference) goes before the whole word
                    # ("some-" + "tieron").
                    refs = _LEADING_REFS_RE.match(text).group()
                    cut = end.rfind(" ") + 1
                    self.para = end[:cut] + lead + refs + end[cut:-1] + text[len(refs) :]
                else:
                    self.para = end + " " + lead + text
                continue
            yield from self.flush()
            self.para = lead + text
        if images:
            self.pending += _pictures(page, row)

    def _body_text(self, text: str, marks: list[tuple[int, str]]) -> str:
        """Margin references at their words, note references as ``[^label]``."""
        words = text.split()
        for k, reading in sorted(marks):
            label = self.label_of(reading)
            if label and k < len(words):
                # The mark itself read as a word beside its line's first: "[26b] b SÓC.",
                # "niño. b [17b] PRO.", "26 [26a]" (a lone consonant is no word).
                if k > 0 and _is_mark_word(words[k - 1], label):
                    words[k - 1] = ""
                if _is_mark_word(words[k], label) and k + 1 < len(words):
                    words[k], k = "", k + 1
                if k > 0 and re.search(r"\w-$", words[k - 1]):  # before "invo- car"
                    k -= 1
                words[k] = margin_ref(label) + words[k]
        text = _BROKEN_WORD_RE.sub(r"\1", " ".join(w for w in words if w))
        if self.counts is not None:
            text = spanish_letters(restore_question_marks(text, self.counts))
        text = _SPEAKER_RE.sub(
            lambda m: m.group(1) + m.group(3).upper().replace("Ố", "Ó") + ". — ", text
        )
        return SUPERSCRIPT_RE.sub(lambda m: f"[^c{self.part}-{from_sup(m.group())}]", text)

    def _add_note(self, text: str) -> None:
        if self.counts is not None:
            text = spanish_letters(text)
        match = SUPERSCRIPT_RE.match(text)
        if match:
            self.last_note = f"c{self.part}-{from_sup(match.group())}"
            body = _NOTE_JUNK_RE.sub("", text[match.end() :].strip())
            self.pending.append(Note(self.last_note, body))
        elif self.last_note:  # the previous page's note going on
            self.pending.append(Note(self.last_note, text.strip(), continued=True))


def _pictures(page: pymupdf.Page, row: dict) -> list[Image]:
    sx = page.rect.width / (row.get("width") or page.rect.width)
    sy = page.rect.height / (row.get("height") or page.rect.height)
    out = []
    for block in row["blocks"]:
        if block.get("label") not in _PICTURE_LABELS or len(block.get("bbox", [])) != 4:
            continue
        x0, y0, x1, y1 = block["bbox"]
        rect = pymupdf.Rect(x0 * sx, y0 * sy, x1 * sx, y1 * sy) & page.rect
        if rect.width * rect.height < page.rect.width * page.rect.height * _MIN_PICTURE_SHARE:
            continue
        picture = _render(page, rect)
        out.append(Image(picture.data, picture.width, picture.height))
    return out

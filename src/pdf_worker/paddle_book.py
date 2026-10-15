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

import contextlib
import re
from collections.abc import Callable, Iterator

import pymupdf

from pdf_worker import missing_refs
from pdf_worker.images import _render
from pdf_worker.inline import MARGIN_REF_RE, margin_ref, page_mark, plain
from pdf_worker.margin_refs import assign_labels
from pdf_worker.note_numbers import SUPERSCRIPT_RE, from_sup, left_open
from pdf_worker.ocr import DEFAULT_LANGUAGE, TESSERACT_CODES, OcrEngineMissingError, tesseract_path
from pdf_worker.paddle_ocr import page_scanner, prepare_blocks, text_settings
from pdf_worker.structure import Block, Gloss, Heading, Image, Note, Paragraph

_SENTENCE_END = tuple('.!?»"”’)]:;')
# Paddle keeps a line-break hyphen with a space: "Pro- tarco".
# shortcut: also joins a real "físico- químico"; rare in prose, check on other books.
_BROKEN_WORD_RE = re.compile(r"(\w)- (?=[a-záéíóúñü])")
# A speech: "SÓC.—", "Sóc. —", "PROTARCO. —" (Paddle varies case, accents and spacing).
_SPEAKER_RE = re.compile(
    rf"^((?:{MARGIN_REF_RE.pattern})*)"
    r"([A-ZÁÉÍÓÚÑỐ][A-Za-záéíóúñốÁÉÍÓÚÑỐ]{1,11})\s*\.?\s*[—–-]\s*"
)
# The model's second reading of a note's own number: "³⁵ 5 ¿Eco", "²⁷ ? Sobre".
_NOTE_JUNK_RE = re.compile(r"^(?:\d{1,3}\)?|[?*'])\s+")
# Front matter: the leading pages with fewer words than this (title pages, credits).
_FRONT_WORDS = 60
_HEAD_ZONE = 0.15  # a "header" lower on the page is a centred line (dramatis personae)
_PICTURE_LABELS = {"image", "figure", "chart"}
_MIN_PICTURE_SHARE = 0.02  # of the page area: smaller ones are ornaments or specks
_DROP = {"header", "number", "footer", "formula_number"}


def text_sample(rows: list[dict]) -> str:
    return " ".join(b.get("text", "") for row in rows for b in row["blocks"])[:20_000]


def iter_paddle_blocks(
    doc: pymupdf.Document,
    rows: list[dict],
    images: bool = True,
    latin_macrons: bool | None = None,
    restored: list[str] | None = None,
    on_page: Callable[[int, int], None] | None = None,
) -> Iterator[Block]:
    """The book's blocks from Paddle's ``rows`` (one per page, as ``paddle_pages``
    returns them) for the scanned ``doc``. References put back by
    ``pdf_worker.missing_refs`` are told in ``restored``, one line each.
    ``on_page(done, total)`` is called after each page."""
    language, macrons, latin_default, rivals = text_settings(rows, latin_macrons)
    scan_of = page_scanner(language)
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
    front = True
    try:
        for done, row in enumerate(sorted(rows, key=lambda r: r["page"])):
            if on_page:
                on_page(done, len(rows))
            page = doc.load_page(row["page"])
            number = next(
                (b["text"].strip() for b in row["blocks"] if b.get("label") == "number"), ""
            )
            label = number if number.isdigit() else str(row["page"] + 1)
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
            blocks, anchors, last_note = prepare_blocks(
                page, row, macrons, latin_default, rivals, scan_of(page), last_note, last_open
            )
            last_open = left_open(blocks)
            for n, source in missing_refs.restore(page, blocks, tries):
                if restored is not None:
                    restored.append(f"note {n} reference restored from {source}, page {label}")
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

    readings: list[tuple[int, str]] = []
    dry = _Book(lambda reading: readings.append((dry.page, reading)))
    for _ in build(dry, False):
        pass
    labels = iter(assign_labels(readings))
    yield from build(_Book(lambda reading: next(labels)), images)


class _Book:
    def __init__(self, label_of: Callable[[str], str | None]) -> None:
        self.label_of = label_of  # a margin mark's reading -> its label (None: no mark)
        self.page = 0  # the page being added (0-based)
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
            if label in ("doc_title", "paragraph_title"):
                yield from self.flush()
                yield Heading(" ".join(text.split()), 1 if label == "doc_title" else 2)
                continue
            text = self._body_text(text, anchors.get(i, []))
            if self.marks:
                text = "".join(self.marks) + text
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
                    self.para = end[:-1] + text
                else:
                    self.para = end + " " + text
                continue
            yield from self.flush()
            self.para = text
        if images:
            self.pending += _pictures(page, row)

    def _body_text(self, text: str, marks: list[tuple[int, str]]) -> str:
        """Margin references at their words, note references as ``[^label]``."""
        words = text.split()
        for k, reading in sorted(marks):
            label = self.label_of(reading)
            if label and k < len(words):
                words[k] = margin_ref(label) + words[k]
        text = _BROKEN_WORD_RE.sub(r"\1", " ".join(words))
        text = _SPEAKER_RE.sub(
            lambda m: m.group(1) + m.group(3).upper().replace("Ố", "Ó") + ". — ", text
        )
        return SUPERSCRIPT_RE.sub(lambda m: f"[^c{self.part}-{from_sup(m.group())}]", text)

    def _add_note(self, text: str) -> None:
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

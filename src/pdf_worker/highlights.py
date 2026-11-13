"""Draw a book's Kindle highlights onto a PDF of the same text (an EPUB, FB2 or MOBI is
laid out as a PDF first). Highlights are found by their words, not by position."""

import os
import re
import tempfile
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from pdf_worker.document import open_pdf
from pdf_worker.ebook_to_pdf import ebook_to_pdf
from pdf_worker.errors import PdfOpenError, PdfWorkerError
from pdf_worker.kindle_positions import Highlight, read_kindle_db

EBOOK_SUFFIXES = {".epub", ".fb2", ".mobi"}
FUZZY_MIN = 8  # tokens; shorter highlights must match exactly
_EDGE = 4  # tokens that must match at each end of a fuzzy span
_NON_WORD = re.compile(r"\W+")

Box = tuple[int, int, pymupdf.Rect]  # block, line, word rect
Token = tuple[str, list[Box]]
Span = tuple[int, int]  # global token start, end


@dataclass
class HighlightReport:
    output_path: Path
    title: str
    highlighted: int
    notes_attached: int
    unmatched: list[str]
    notes_unattached: int


def highlight_book(
    input_path: str | Path,
    kindle_db: str | Path,
    azw3: str | Path,
    output_path: str | Path | None = None,
) -> HighlightReport:
    """Write a copy of the book with its Kindle highlights; the input is never changed."""
    input_path = Path(input_path)
    output_path = Path(output_path or input_path.with_name(f"{input_path.stem}.highlighted.pdf"))
    suffix = input_path.suffix.lower()
    if suffix not in EBOOK_SUFFIXES | {".pdf"}:
        raise PdfWorkerError(f"Not a PDF, EPUB, FB2 or MOBI: {input_path}")
    if not input_path.is_file():
        raise PdfOpenError(f"File not found: {input_path}")
    if output_path.resolve() == input_path.resolve():
        raise PdfWorkerError(f"The output would overwrite the input: {input_path}")
    highlights = read_kindle_db(kindle_db, azw3)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_path.parent, prefix=".highlights.") as tmp:
        pdf = input_path
        if suffix in EBOOK_SUFFIXES:
            pdf = Path(tmp) / "book.pdf"
            ebook_to_pdf(input_path, pdf)
        with open_pdf(pdf) as doc:
            title = doc.metadata.get("title") or input_path.stem
            kept = _drop_contained(highlights)
            found = _candidates(doc, [tokens for _, tokens in kept])
            chosen, unmatched = [], []
            prev_end = 0
            for (highlight, _), spans in zip(kept, found, strict=True):
                if not spans:
                    unmatched.append(highlight.text)
                    continue
                span = next((s for s in spans if s[0] >= prev_end), spans[0])
                chosen.append((span, highlight))
                prev_end = span[1]
            noted = _draw(doc, chosen)
            doc.save(Path(tmp) / "out.pdf", garbage=3, deflate=True)
        os.replace(Path(tmp) / "out.pdf", output_path)
    notes = sum(1 for h in highlights if h.note)
    return HighlightReport(output_path, title, len(chosen), noted, unmatched, notes - noted)


def normalize(word: str) -> str:
    return _NON_WORD.sub("", unicodedata.normalize("NFKC", word).casefold())


def text_tokens(text: str) -> list[str]:
    return [token for token in map(normalize, text.split()) if token]


def page_tokens(page: pymupdf.Page) -> list[Token]:
    """The page's words as tokens; a word hyphenated over two lines is one token."""
    # shortcut: a word hyphenated over a page break stays two tokens; rare enough so far.
    words = page.get_text("words")
    tokens, text, boxes = [], "", []
    for i, (x0, y0, x1, y1, word, block, line, _) in enumerate(words):
        text += word
        boxes.append((block, line, pymupdf.Rect(x0, y0, x1, y1)))
        last_on_line = i + 1 == len(words) or tuple(words[i + 1][5:7]) != (block, line)
        if last_on_line and word.endswith(("-", "­")) and i + 1 < len(words):
            continue
        if token := normalize(text):
            tokens.append((token, boxes))
        text, boxes = "", []
    return tokens


def _drop_contained(highlights: list[Highlight]) -> list[tuple[Highlight, list[str]]]:
    """Highlights in Kindle order with their tokens, minus any that another one contains."""
    items = [(h, text_tokens(h.text)) for h in sorted(highlights, key=lambda h: h.start)]
    joined = [f" {' '.join(tokens)} " for _, tokens in items]
    return [
        item
        for i, item in enumerate(items)
        if not any(
            j != i and joined[i] in joined[j] and (joined[i] != joined[j] or j < i)
            for j in range(len(items))
        )
        or not item[1]
    ]


def _candidates(doc: pymupdf.Document, wanted: list[list[str]]) -> list[list[Span]]:
    """Every exact occurrence of each token list, or else its fuzzy ones; pages streamed."""
    exact: list[list[Span]] = [[] for _ in wanted]
    fuzzy: list[list[Span]] = [[] for _ in wanted]
    by_first, by_head = defaultdict(list), defaultdict(list)
    for i, tokens in enumerate(wanted):
        if tokens:
            by_first[tokens[0]].append(i)
        if len(tokens) >= FUZZY_MIN:
            by_head[tuple(tokens[:_EDGE])].append(i)
    reach = max((_longest(len(t)) for t in wanted), default=0)
    buf: list[str] = []  # buf[k] is token number base + k
    base = 0

    def scan(starts: int) -> None:
        for p in range(starts):
            for i in by_first.get(buf[p], ()):
                n = len(wanted[i])
                if buf[p : p + n] == wanted[i]:
                    exact[i].append((base + p, base + p + n))
            for i in by_head.get(tuple(buf[p : p + _EDGE]), ()):
                tail, n = wanted[i][-_EDGE:], len(wanted[i])
                lengths = range(max(_EDGE, int(0.8 * n) - 3), _longest(n) + 1)
                for size in sorted(lengths, key=lambda size: abs(size - n)):
                    if buf[p + size - _EDGE : p + size] == tail:
                        fuzzy[i].append((base + p, base + p + size))
                        break

    for page in doc:
        buf += [token for token, _ in page_tokens(page)]
        ready = len(buf) - reach  # starts whose longest possible span is all in buf
        if ready > 0:
            scan(ready)
            base += ready
            del buf[:ready]
    scan(len(buf))
    return [e or f for e, f in zip(exact, fuzzy, strict=True)]


def _longest(n: int) -> int:
    return int(1.2 * n) + 3 if n >= FUZZY_MIN else n


def _draw(doc: pymupdf.Document, chosen: list[tuple[Span, Highlight]]) -> int:
    """One highlight annotation per span per page; a note goes on its span's first one."""
    noted: set[int] = set()
    first = 0
    for page in doc:
        tokens = page_tokens(page)
        last = first + len(tokens)
        for k, ((start, end), highlight) in enumerate(chosen):
            if start >= last or end <= first:
                continue
            lines: dict[tuple[int, int], pymupdf.Rect] = {}
            for _, boxes in tokens[max(start, first) - first : min(end, last) - first]:
                for block, line, rect in boxes:
                    key = (block, line)
                    lines[key] = lines[key] | rect if key in lines else rect
            annot = page.add_highlight_annot(quads=[rect.quad for rect in lines.values()])
            if highlight.note and k not in noted:
                annot.set_info(content=highlight.note)
                annot.update()
                noted.add(k)
        first = last
    return len(noted)

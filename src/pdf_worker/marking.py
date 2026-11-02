"""The marking page (``pdf-worker mark``): a local web page where a person marks a book's
lines (``pdf_worker.marks``), served with the standard library only.

The page shows the lines the pipeline sees: ``page_lines`` after ``convert_pdf``'s
preparation for a text layer, or, for a scan built from PaddleOCR-VL's rows (cached rows
only: no model runs here), the rows' blocks, one line per printed line they keep. Blocks
are the layout model's boxes when its rows are cached, else MuPDF's.

The kinds view (``/labels/N.json``, ``/doubtful.json``) shows each line's kind by the
book's style sheet (``pdf_worker.style_sheet``), matched again after every save.
"""

import json
import re
from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

import pymupdf

from pdf_worker import bilingual, font_sizes, glued_refs, marks, style_sheet
from pdf_worker.document import TEXT_FLAGS
from pdf_worker.layout import page_lines
from pdf_worker.paddle_ocr import cached_rows, clean_text

PAGE_HTML = Path(__file__).with_name("marking.html")
DPI = 150
_PAGE_RE = re.compile(r"^/(page|labels)/(\d+)\.(png|json)$")


class ViewLine(NamedTuple):
    bbox: tuple[float, float, float, float]
    text: str
    block: int = -1  # a scan's line: the index of its Paddle block in the row


class Book:
    """A PDF opened for marking: its pages' lines, words and blocks, and its marks."""

    def __init__(self, doc: pymupdf.Document, pdf_path: str | Path, marks_path: str | Path):
        self.doc = doc
        self.path = Path(marks_path)
        self.info = marks.pdf_info(pdf_path)
        rows = cached_rows(pdf_path)
        # Paddle reads only the books converted from its rows (scans); a half is a round
        # share that leaves out a few pages read for a test.
        self.paddle = rows if len(rows) >= doc.page_count / 2 else None
        self.layout = {} if self.paddle else cached_rows(pdf_path, layout=True)
        if not self.paddle:
            # convert_pdf's preparation (but for re-reading garbled words: OCR).
            font_sizes.mark_misreporting(doc)
            glued_refs.mark_glued_refs(doc, skip=bilingual.facing_pages(doc)[1])
        self.marks = marks.load(self.path, None) if self.path.exists() else marks.Marks(self.info)
        marks.check_pdf(self.marks, self.info)
        self._views: dict[int, dict] = {}
        self._lines: dict[int, list] = {}  # the lines each view was made from
        self._measures: style_sheet.Measures | None = None
        self._classified: tuple[marks.Marks, style_sheet.Classification] | None = None

    def summary(self) -> dict:
        return {
            "name": self.info.name,
            "pages": self.info.pages,
            "source": "paddle rows" if self.paddle else "text layer",
            "blocks": "layout model" if self.paddle or self.layout else "MuPDF",
            "marks_file": str(self.path),
        }

    def view(self, number: int) -> dict:
        """Page ``number`` (1-based): its size, lines, words and blocks, in points."""
        if number not in self._views:
            page = self.doc.load_page(number - 1)
            if self.paddle:
                lines, words, blocks = paddle_view(page, self.paddle.get(number - 1))
            else:
                lines, words, blocks = _text_view(page, self.layout.get(number - 1))
            self._lines[number] = lines
            self._views[number] = {
                "width": page.rect.width,
                "height": page.rect.height,
                "lines": [{"bbox": _round(line.bbox), "text": line.text} for line in lines],
                "words": [[*_round(w[:4]), w[4]] for w in words],
                "blocks": blocks,
            }
        return self._views[number]

    def pages(self) -> list[style_sheet.PageLines]:
        """Every page's lines, as the page shows them (read once: about 15 s for a
        450-page text layer)."""
        found = []
        for number in range(1, self.info.pages + 1):
            view = self.view(number)
            found.append(style_sheet.PageLines(view["width"], view["height"], self._lines[number]))
        return found

    def classified(self) -> style_sheet.Classification:
        """Every line's kind by the current marks (measured once, matched again after
        the marks change)."""
        if self._classified is None or self._classified[0] is not self.marks:
            pages = self.pages()
            self._measures = self._measures or style_sheet.measure(pages)
            found = style_sheet.classify(pages, self.marks, self._measures)
            self._classified = (self.marks, found)
        return self._classified[1]

    def labels(self, number: int) -> dict:
        """Page ``number``'s lines' kinds, and the note numbers found in its text."""
        found = self.classified()
        return {
            "lines": [asdict(label) for label in found.labels[number - 1]],
            "refs": [_round(box) for box in found.refs[number - 1]],
        }

    def png(self, number: int) -> bytes:
        return self.doc.load_page(number - 1).get_pixmap(dpi=DPI, annots=False).tobytes("png")

    def texts(self, mark: marks.Mark) -> list[str]:
        """The texts ``mark``'s shape takes on its page now (words for a note reference)."""
        view = self.view(mark.page)
        if mark.kind == "note-ref":
            return [w[4] for w in marks.words_in(mark.shape, view["words"])]
        lines = [ViewLine(tuple(line["bbox"]), line["text"]) for line in view["lines"]]
        return [line.text for line in marks.lines_in(mark.shape, lines)]

    def stale(self) -> list[dict]:
        """The marks whose ``texts`` no longer match the lines they take."""
        found = []
        for mark in self.marks.marks:
            now = self.texts(mark)
            if now != mark.texts:
                found.append({"id": mark.id, "page": mark.page, "kind": mark.kind, "now": now})
        return found

    def missing(self) -> list[str]:
        """``marks.missing`` with each mark's texts as its shape takes them now (marks
        saved by an older page may hold none)."""
        now = [replace(mark, texts=self.texts(mark)) for mark in self.marks.marks]
        found = marks.missing(replace(self.marks, marks=now))
        # A scan's lines and words are placed by estimate (and OCR merges margin letters
        # into the text): a mark taking none of them still says where the thing is.
        return [item for item in found if not (self.paddle and item.endswith("takes no text."))]

    def save(self, data: object) -> None:
        new = marks.from_dict(data)
        marks.check_pdf(new, self.info)
        marks.save(self.path, new)
        self.marks = new


def _round(box) -> list[float]:
    return [round(c, 2) for c in box]


def _text_view(page: pymupdf.Page, row: dict | None):
    lines = page_lines(page)
    words = _span_words(lines)
    if row and row.get("width"):
        scale = page.rect.width / row["width"]
        blocks = [
            {"bbox": _round(c * scale for c in b["bbox"]), "label": b.get("label", "")}
            for b in row["blocks"]
            if len(b.get("bbox", [])) == 4
        ]
    else:
        blocks = [
            {"bbox": _round(b[:4]), "label": ""}
            for b in page.get_text("blocks", flags=TEXT_FLAGS)
            if b[6] == 0  # text, not an image
        ]
    return lines, words, blocks


def _span_words(lines) -> list[tuple]:
    """Words split at span edges too: MuPDF's words glue a note's number to its word
    ("secular1"), whose middle a shape drawn round the number leaves out."""
    words = []
    for line in lines:
        for span in line.spans:
            x0, y0, x1, y1 = span["bbox"]
            # shortcut: letters share the span's width evenly; exact enough to hit a word.
            step = (x1 - x0) / max(len(span["text"]), 1)
            for match in re.finditer(r"\S+", span["text"]):
                start, end = match.span()
                words.append((x0 + start * step, y0, x0 + end * step, y1, match[0]))
    return words


def paddle_view(page: pymupdf.Page, row: dict | None):
    """Lines, words and blocks from a page's Paddle row: each block's printed lines share
    its height evenly, and a line's words its width by their letters."""
    # shortcut: lines and words are placed by share, not found on the scan; enough to
    # mark them, upgrade if a phase needs their real boxes.
    if not row:
        return [], [], []
    sx = page.rect.width / (row.get("width") or page.rect.width)
    sy = page.rect.height / (row.get("height") or page.rect.height)
    lines, words, blocks = [], [], []
    for index, block in enumerate(row["blocks"]):
        if len(block.get("bbox", [])) != 4:
            continue
        x0, y0, x1, y1 = block["bbox"]
        x0, y0, x1, y1 = x0 * sx, y0 * sy, x1 * sx, y1 * sy
        blocks.append({"bbox": _round((x0, y0, x1, y1)), "label": block.get("label", "")})
        texts = [t.strip() for t in clean_text(block.get("text", "")).splitlines() if t.strip()]
        step = (y1 - y0) / max(len(texts), 1)
        for k, text in enumerate(texts):
            top, bottom = y0 + k * step, y0 + (k + 1) * step
            lines.append(ViewLine((x0, top, x1, bottom), text, index))
            left, width = x0, (x1 - x0) / len(text)
            for match in re.finditer(r"\S+", text):
                start, end = match.span()
                words.append((left + start * width, top, left + end * width, bottom, match[0]))
    return lines, words, blocks


def serve(book: Book, port: int = 0) -> HTTPServer:
    """A server on 127.0.0.1 (``port`` 0: a free one) for ``book``'s marking page. Call
    ``serve_forever()`` on it. One request at a time: the PDF is not shared between
    threads."""
    page_html = PAGE_HTML.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._reply(page_html, "text/html; charset=utf-8")
            elif path == "/book.json":
                self._json(book.summary())
            elif path == "/marks.json":
                self._json(marks.to_dict(book.marks))
            elif path == "/stale.json":
                self._json(book.stale())
            elif path == "/check.json":
                self._json(book.missing())
            elif path == "/doubtful.json":
                after = parse_qs(urlsplit(self.path).query).get("after", ["0"])[0]
                after = int(after) if after.isdigit() else 0
                self._json({"page": book.classified().next_doubtful(after)})
            elif (match := _PAGE_RE.match(path)) and 1 <= int(match[2]) <= book.info.pages:
                number = int(match[2])
                if match[1] == "labels" and match[3] == "json":
                    self._json(book.labels(number))
                elif match[1] == "labels":
                    self.send_error(404)
                elif match[3] == "png":
                    self._reply(book.png(number), "image/png")
                else:
                    self._json(book.view(number))
            else:
                self.send_error(404)

        def do_POST(self):
            size = int(self.headers.get("Content-Length") or 0)
            if self.path != "/marks.json" or not 0 < size < 50_000_000:
                self.send_error(400)
                return
            try:
                book.save(json.loads(self.rfile.read(size).decode("utf-8")))
            except (ValueError, marks.MarksError) as exc:  # JSONDecodeError is a ValueError
                self._json({"error": str(exc)}, 400)
                return
            except OSError as exc:
                self._json({"error": f"Not saved: {exc}"}, 500)
                return
            self._json({"saved": str(book.path), "stale": book.stale()})

        def _json(self, data, status: int = 200):
            self._reply(
                json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json", status
            )

        def _reply(self, body: bytes, kind: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return HTTPServer(("127.0.0.1", port), Handler)

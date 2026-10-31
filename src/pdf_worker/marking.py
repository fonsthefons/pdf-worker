"""The marking page (``pdf-worker mark``): a local web page where a person marks a book's
lines (``pdf_worker.marks``), served with the standard library only.

The page shows the lines the pipeline sees: ``page_lines`` after ``convert_pdf``'s
preparation for a text layer, or, for a scan built from PaddleOCR-VL's rows (cached rows
only: no model runs here), the rows' blocks, one line per printed line they keep. Blocks
are the layout model's boxes when its rows are cached, else MuPDF's.
"""

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import NamedTuple

import pymupdf

from pdf_worker import bilingual, font_sizes, glued_refs, marks
from pdf_worker.document import TEXT_FLAGS
from pdf_worker.layout import page_lines
from pdf_worker.paddle_ocr import cached_rows, clean_text

PAGE_HTML = Path(__file__).with_name("marking.html")
DPI = 150
_PAGE_RE = re.compile(r"^/page/(\d+)\.(png|json)$")


class ViewLine(NamedTuple):
    bbox: tuple[float, float, float, float]
    text: str


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
                lines, words, blocks = _paddle_view(page, self.paddle.get(number - 1))
            else:
                lines, words, blocks = _text_view(page, self.layout.get(number - 1))
            self._views[number] = {
                "width": page.rect.width,
                "height": page.rect.height,
                "lines": [{"bbox": _round(line.bbox), "text": line.text} for line in lines],
                "words": [[*_round(w[:4]), w[4]] for w in words],
                "blocks": blocks,
            }
        return self._views[number]

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

    def save(self, data: object) -> None:
        new = marks.from_dict(data)
        marks.check_pdf(new, self.info)
        marks.save(self.path, new)
        self.marks = new


def _round(box) -> list[float]:
    return [round(c, 2) for c in box]


def _text_view(page: pymupdf.Page, row: dict | None):
    lines = page_lines(page)
    words = page.get_text("words", flags=TEXT_FLAGS)
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


def _paddle_view(page: pymupdf.Page, row: dict | None):
    """Lines, words and blocks from a page's Paddle row: each block's printed lines share
    its height evenly, and a line's words its width by their letters."""
    # shortcut: lines and words are placed by share, not found on the scan; enough to
    # mark them, upgrade if a phase needs their real boxes.
    if not row:
        return [], [], []
    sx = page.rect.width / (row.get("width") or page.rect.width)
    sy = page.rect.height / (row.get("height") or page.rect.height)
    lines, words, blocks = [], [], []
    for block in row["blocks"]:
        if len(block.get("bbox", [])) != 4:
            continue
        x0, y0, x1, y1 = block["bbox"]
        x0, y0, x1, y1 = x0 * sx, y0 * sy, x1 * sx, y1 * sy
        blocks.append({"bbox": _round((x0, y0, x1, y1)), "label": block.get("label", "")})
        texts = [t.strip() for t in clean_text(block.get("text", "")).splitlines() if t.strip()]
        step = (y1 - y0) / max(len(texts), 1)
        for k, text in enumerate(texts):
            top, bottom = y0 + k * step, y0 + (k + 1) * step
            lines.append(ViewLine((x0, top, x1, bottom), text))
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
            elif (match := _PAGE_RE.match(path)) and 1 <= int(match[1]) <= book.info.pages:
                number = int(match[1])
                if match[2] == "png":
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

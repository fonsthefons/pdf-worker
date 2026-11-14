"""Read a book's Kindle highlights: positions from the Kindle's annotation database, text
from the book's AZW3 (a highlight's positions are byte offsets in its text stream).

Notes are not read: the Kindle's ``ksdk_annotation_v1.db`` keeps highlights (dataset 1),
bookmarks, reading positions and popular highlights, but no dataset with typed notes was
found in it, so ``Highlight.note`` is always None here.
"""

import html
import json
import re
import sqlite3
import struct
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from pdf_worker.errors import PdfWorkerError

# The Kindle cuts the title in a book id ("...-EBOK-Lecciones_preliminares_de_filos:36B66A99-0").
_ID_TITLE_LEN = 31
# The database's positions fall 16 bytes before the text they mark (measured on one book's
# four highlights; the cause is unknown). shortcut: constant, revisit if another book differs.
_OFFSET = 16
_REACH = 2000  # most bytes a highlight is widened by on each side
_CLOSERS = rb"(?:\xc2\xbb|\xe2\x80[\x99\x9d]|[\"')\]])*"
_STOP = rb"(?:[.?!]|\xe2\x80\xa6)" + _CLOSERS + rb"(?=[\s<]|$)|</(?:p|h\d|div|li)>"
_SENTENCE_END = re.compile(_STOP + rb"\s*")
_SENTENCE_END_NOSPACE = re.compile(_STOP)
_CUT_TAG = re.compile(r"^[^<]*>|<[^>]*$")
_TAG = re.compile(r"<[^>]*>")
_BREAKS = b" \t\r\n<>"  # what ends a word, as the PDF's words go


@dataclass(frozen=True)
class Highlight:
    text: str
    start: int
    end: int
    note: str | None = None


def read_kindle_db(db_path: str | Path, azw3_path: str | Path) -> list[Highlight]:
    """The highlights of the book in ``azw3_path``, in Kindle-location order."""
    title, stream = read_azw3(azw3_path)
    return highlights_from_db(db_path, title, stream)


def palmdoc(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        c = data[i]
        i += 1
        if c == 0 or 9 <= c <= 0x7F:
            out.append(c)
        elif c <= 8:
            out += data[i : i + c]
            i += c
        elif c >= 0xC0:
            out += b" "
            out.append(c ^ 0x80)
        else:
            c = (c << 8) | data[i]
            i += 1
            dist, n = (c >> 3) & 0x7FF, (c & 7) + 3
            for _ in range(n):
                out.append(out[-dist])
    return bytes(out)


def trailing_size(rec: bytes, flags: int) -> int:
    """How many bytes at the end of a text record are trailing entries, not text."""

    def entry(size: int) -> int:
        shift = result = 0
        while size > 0:
            v = rec[size - 1]
            result |= (v & 0x7F) << shift
            shift += 7
            size -= 1
            if v & 0x80 or shift >= 28:
                break
        return result

    num = 0
    rest = flags >> 1
    while rest:
        if rest & 1:
            num += entry(len(rec) - num)
        rest >>= 1
    if flags & 1:
        num += (rec[len(rec) - num - 1] & 3) + 1
    return num


def read_azw3(path: str | Path) -> tuple[str, bytes]:
    """The book's full name and its decompressed text stream."""
    # shortcut: reads record 0's book; a joint MOBI/KF8 file's KF8 half is not looked for.
    path = Path(path)
    if not path.is_file():
        raise PdfWorkerError(f"File not found: {path}")
    data = path.read_bytes()
    if data[60:68] != b"BOOKMOBI":
        raise PdfWorkerError(f"{path} is not an AZW3 book")
    try:
        count = struct.unpack(">H", data[76:78])[0]
        offsets = [struct.unpack(">I", data[78 + 8 * i : 82 + 8 * i])[0] for i in range(count)]
        offsets.append(len(data))
        rec0 = data[offsets[0] : offsets[1]]
        compression, _, _, records = struct.unpack(">HHIH", rec0[:10])
        header_len, encoding = struct.unpack(">II", rec0[20:28])[0], rec0[28:32]
        name_at, name_len = struct.unpack(">II", rec0[84:92])
        flags = struct.unpack(">H", rec0[0xF2:0xF4])[0] if header_len >= 0xE4 else 0
        codec = "utf-8" if struct.unpack(">I", encoding)[0] == 65001 else "cp1252"
        title = rec0[name_at : name_at + name_len].decode(codec, "replace")
        if compression not in (1, 2):
            raise PdfWorkerError(f"{path}: compression {compression} is not handled")
        parts = []
        for i in range(1, records + 1):
            rec = data[offsets[i] : offsets[i + 1]]
            rec = rec[: len(rec) - trailing_size(rec, flags)]
            parts.append(rec if compression == 1 else palmdoc(rec))
    except (struct.error, IndexError) as exc:
        raise PdfWorkerError(f"{path} is not a readable AZW3 book: {exc}") from exc
    return title, b"".join(parts)


def span_text(stream: bytes, start: int, end: int) -> str:
    """The whole sentences the two positions touch, without markup (the positions run a
    little off, so the highlight is widened to sentence ends rather than trusted)."""
    start = max(0, min(start, len(stream)))
    end = max(start, min(end, len(stream)))
    before = [m.end() for m in _SENTENCE_END.finditer(stream, max(0, start - _REACH), start)]
    start = before[-1] if before else max(0, start - _REACH)
    after = _SENTENCE_END_NOSPACE.search(stream, max(start, end - 1), end + _REACH)
    end = after.end() if after else min(len(stream), end + _REACH)
    text = stream[start:end].decode("utf-8", "replace")
    text = _TAG.sub("", _CUT_TAG.sub("", text))
    return " ".join(html.unescape(text).split())


def title_key(title: str) -> str:
    """Accents, case, spaces and punctuation dropped: "La distinción:" -> "ladistincion"."""
    return "".join(c for c in unicodedata.normalize("NFKD", title).casefold() if c.isalnum())


def highlights_from_db(db_path: str | Path, title: str, stream: bytes) -> list[Highlight]:
    """The highlights of the database's book whose id names ``title``; text from ``stream``."""
    db_path = Path(db_path)
    if not db_path.is_file():
        raise PdfWorkerError(f"File not found: {db_path}")
    try:
        with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as con:
            rows = con.execute(
                "select book_id, start_position, end_position from nonsyncable_annotations "
                "where dataset = 1"
            ).fetchall()
    except sqlite3.Error as exc:
        raise PdfWorkerError(f"Could not read Kindle highlights from {db_path}: {exc}") from exc
    books = sorted({row[0] for row in rows})
    want = title_key(title)
    matches = [b for b in books if _names(_id_title(b), want)]
    if not matches:
        names = ", ".join(sorted({_id_title(b) or b for b in books})) or "none"
        raise PdfWorkerError(
            f"No book with highlights in {db_path} matches {title!r}; those with some: {names}"
        )
    if len(matches) > 1:
        raise PdfWorkerError(f"Several books in {db_path} match {title!r}: {', '.join(matches)}")
    highlights = []
    for book_id, start, end in rows:
        if book_id == matches[0]:
            s = json.loads(start)["shortPosition"] + _OFFSET
            e = json.loads(end)["shortPosition"] + _OFFSET
            highlights.append(Highlight(span_text(stream, s, e), s, e))
    return sorted(highlights, key=lambda h: (h.start, h.end))


def _id_title(book_id: str) -> str:
    if "-EBOK-" not in book_id:
        return ""
    return book_id.split("-EBOK-", 1)[1].rsplit("-", 1)[0].rsplit(":", 1)[0]


def _names(id_title: str, want: str) -> bool:
    key = title_key(id_title)
    return bool(key) and (key == want or (len(id_title) >= _ID_TITLE_LEN and want.startswith(key)))

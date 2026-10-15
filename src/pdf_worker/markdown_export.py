"""Write structure blocks as Markdown (Pandoc/GFM footnote syntax).

The body is streamed to the output file; notes are streamed to a temporary file and
appended at the end, so memory use stays flat.
"""

import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path

from pdf_worker.inline import LinkClose, LinkOpen, MarginRef, pieces, plain
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import REF_RE, Block, Gloss, Heading, Image, Note, Paragraph, Table

# Characters that would otherwise start Markdown formatting.
_INLINE_SPECIAL_RE = re.compile(r"([\\`*_<])")
_LINE_START_RE = re.compile(r"^([#>+\-=|])")
# "12. Text" at the start of a paragraph would become an ordered list.
_LIST_NUMBER_RE = re.compile(r"^(\d{1,9})([.)])(\s)")


def escape_markdown(text: str, line_start: bool = True) -> str:
    """Escape Markdown syntax in plain text, leaving ``[^label]`` references intact.

    ``line_start`` also escapes characters that only matter at the start of a block
    (``#`` headings, ``>`` quotes, ``-`` lists).
    """
    pieces = []
    last = 0
    for match in REF_RE.finditer(text):
        pieces.append(_INLINE_SPECIAL_RE.sub(r"\\\1", text[last : match.start()]))
        pieces.append(match.group(0))
        last = match.end()
    pieces.append(_INLINE_SPECIAL_RE.sub(r"\\\1", text[last:]))
    escaped = "".join(pieces)
    if not line_start:
        return escaped
    return _LIST_NUMBER_RE.sub(r"\1\\\2\3", _LINE_START_RE.sub(r"\\\1", escaped))


def render_markdown(text: str, line_start: bool = True) -> str:
    """Escape block text for Markdown and render its inline markers: web links become
    ``[text](url)``; links within the book and page starts are dropped."""
    out: list[str] = []
    targets: list[str | None] = []
    first = True
    for piece in pieces(text):
        if isinstance(piece, str):
            out.append(escape_markdown(piece, line_start=line_start and first))
            first = False
        elif isinstance(piece, LinkOpen):
            uri = piece.target[2:] if piece.target.startswith("u:") else None
            targets.append(uri)
            if uri:
                out.append("[")
        elif isinstance(piece, LinkClose):
            uri = targets.pop() if targets else None
            if uri:
                out.append(f"](<{uri}>)")
        elif isinstance(piece, MarginRef):
            out.append(f"**\\[{piece.label}\\]** ")  # bold in Word too (via Pandoc)
            first = False
    return "".join(out)


def _yaml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_markdown(blocks: Iterable[Block], output_path: Path, meta: Metadata) -> WriteStats:
    stats = WriteStats(chapters=1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, body_name = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.")
    nfd, notes_name = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.n.")
    try:
        with (
            os.fdopen(fd, "w", encoding="utf-8", newline="\n") as body,
            os.fdopen(nfd, "w+", encoding="utf-8", newline="\n") as notes,
        ):
            body.write(f"---\ntitle: {_yaml(meta.title)}\n")
            if meta.author:
                body.write(f"author: {_yaml(meta.author)}\n")
            body.write(f"lang: {meta.language}\n---\n\n")
            open_note: Note | None = None
            for block in blocks:
                if isinstance(block, Heading):
                    stats.headings += 1
                    level = min(block.level, 6)
                    text = render_markdown(block.text, line_start=False)
                    body.write("#" * level + " " + text + "\n\n")
                elif isinstance(block, Paragraph):
                    stats.paragraphs += 1
                    body.write(render_markdown(block.text) + "\n\n")
                elif isinstance(block, Table):
                    stats.tables += 1
                    body.write(_table(block) + "\n")
                elif isinstance(block, Image):
                    # Pictures go to a folder next to the .md file: book_images/img1.jpg.
                    stats.images += 1
                    folder = output_path.parent / f"{output_path.stem}_images"
                    folder.mkdir(exist_ok=True)
                    name = f"img{stats.images}.jpg"
                    (folder / name).write_bytes(block.data)
                    body.write(f"![](<{folder.name}/{name}>)\n\n")
                elif isinstance(block, Gloss):
                    stats.glosses += 1
                    # A blockquote, one margin line per line (backslash = hard break).
                    lines = [render_markdown(line) for line in block.lines]
                    body.write("> " + "\\\n> ".join(lines) + "\n\n")
                elif isinstance(block, Note):
                    if block.continued and open_note and open_note.label == block.label:
                        open_note = Note(block.label, f"{open_note.text} {block.text}")
                        continue
                    if open_note:
                        _write_note(notes, open_note)
                    open_note = block
                    stats.notes += 1
            if open_note:
                _write_note(notes, open_note)
            notes.seek(0)
            for chunk in iter(lambda: notes.read(1 << 16), ""):
                body.write(chunk)
        os.replace(body_name, output_path)
    except BaseException:
        Path(body_name).unlink(missing_ok=True)
        raise
    finally:
        Path(notes_name).unlink(missing_ok=True)
    return stats


def _table(table: Table) -> str:
    """A pipe table; its first row is the header row (Markdown tables need one)."""

    def cell(text: str) -> str:
        return render_markdown(text, line_start=False).replace("|", "\\|") or " "

    rows = ["| " + " | ".join(cell(c) for c in row) + " |" for row in table.rows]
    rule = "|" + "|".join(" --- " for _ in table.rows[0]) + "|"
    return "\n".join([rows[0], rule, *rows[1:]]) + "\n"


def _write_note(out, note: Note) -> None:
    # Later paragraphs of a note are indented by four spaces (Pandoc footnote syntax).
    paragraphs = [render_markdown(p) for p in note.text.split("\n\n") if plain(p).strip()]
    out.write(f"[^{note.label}]: " + "\n\n    ".join(paragraphs) + "\n\n")

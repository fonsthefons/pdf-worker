"""Write the book as clean plain text: reflowed paragraphs, notes at the end.

Unlike ``extract-text`` (the PDF's text layer, page by page), this is the rebuilt book:
no page breaks, running heads or line numbers; one paragraph per line; headings set off
by blank lines; footnote references as ``[n]`` with the notes listed at the end.
"""

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from pdf_worker.footnotes import display_marker
from pdf_worker.inline import plain
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import REF_RE, Block, Gloss, Heading, Image, Note, Paragraph, Table


def write_text(blocks: Iterable[Block], output_path: Path, meta: Metadata) -> WriteStats:
    stats = WriteStats(chapters=1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, body_name = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.")
    nfd, notes_name = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.n.")
    try:
        with (
            os.fdopen(fd, "w", encoding="utf-8", newline="\n") as body,
            os.fdopen(nfd, "w+", encoding="utf-8", newline="\n") as notes,
        ):
            body.write(meta.title + "\n")
            if meta.author:
                body.write(meta.author + "\n")
            body.write("\n")
            open_note: Note | None = None
            for block in blocks:
                if isinstance(block, Heading):
                    stats.headings += 1
                    body.write(f"\n{_text(block.text)}\n\n")
                elif isinstance(block, Paragraph):
                    stats.paragraphs += 1
                    body.write(_text(block.text) + "\n\n")
                elif isinstance(block, Gloss):
                    stats.glosses += 1
                    body.write("".join(f"    {_text(line)}\n" for line in block.lines) + "\n")
                elif isinstance(block, Table):
                    stats.tables += 1
                    rows = ("\t".join(_text(cell) for cell in row) for row in block.rows)
                    body.write("\n".join(rows) + "\n\n")
                elif isinstance(block, Image):
                    stats.images += 1
                    body.write("[picture]\n\n")
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
            if stats.notes:
                body.write("\nNotes\n\n")
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


def _text(text: str) -> str:
    """Block text with markers removed and references as ``[n]``."""
    return REF_RE.sub(lambda m: f"[{display_marker(m.group(1))}]", plain(text)).strip()


def _write_note(out, note: Note) -> None:
    paragraphs = [_text(p) for p in note.text.split("\n\n") if plain(p).strip()]
    out.write(f"[{display_marker(note.label)}] " + "\n    ".join(paragraphs) + "\n\n")

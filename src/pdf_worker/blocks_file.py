"""A book's structure (``pdf_worker.structure``'s blocks) saved as JSON Lines.

``convert_pdf`` builds the blocks once, saves them here and writes every format from the
file. Line 1 is ``{"metadata": {...}}`` (``output.Metadata``); then one block per line,
``{"type": "Paragraph", "text": ..., "page": ..., ...}`` with the dataclass's fields
(an ``Image``'s ``data`` is base64). Written and read as a stream.
"""

import base64
import json
import os
import tempfile
import typing
from collections.abc import Iterable, Iterator
from dataclasses import asdict, fields
from pathlib import Path

from pdf_worker.output import Metadata
from pdf_worker.structure import Block, Gloss, Image, Table

TYPES = {cls.__name__: cls for cls in typing.get_args(Block)}


def write_blocks(blocks: Iterable[Block], meta: Metadata, path: str | Path) -> None:
    """Save ``meta`` and ``blocks`` to ``path`` (atomically)."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(_line({"metadata": asdict(meta)}))
            for block in blocks:
                row = {f.name: getattr(block, f.name) for f in fields(block)}
                if isinstance(block, Image):
                    row["data"] = base64.b64encode(block.data).decode("ascii")
                out.write(_line({"type": type(block).__name__, **row}))
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _line(row: dict) -> str:
    # U+2028/2029 (structure.PARAGRAPH_BREAK) end a line for many readers: escaped.
    text = json.dumps(row, ensure_ascii=False)
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029") + "\n"


def read_metadata(path: str | Path) -> Metadata:
    with open(path, encoding="utf-8") as lines:
        return Metadata(**json.loads(next(lines))["metadata"])


def read_blocks(path: str | Path) -> Iterator[Block]:
    """The blocks saved in ``path``, one at a time."""
    with open(path, encoding="utf-8") as lines:
        next(lines)  # the metadata
        for line in lines:
            row = json.loads(line)
            cls = TYPES[row.pop("type")]
            if cls is Image:
                row["data"] = base64.b64decode(row["data"])
            elif cls is Gloss:
                row["lines"] = tuple(row["lines"])
            elif cls is Table:
                row["rows"] = tuple(tuple(cells) for cells in row["rows"])
            yield cls(**row)

"""Compare two blocks files (``pdf_worker.blocks_file``), streaming both.

Prints each heading whose level changed (PDF page, old -> new, text), then every other
difference: their count and the first 20. Exit 1 when anything but a heading's
``level``/``source`` differs.

  .venv/bin/python tools/blocks_diff.py BEFORE.jsonl AFTER.jsonl
  .venv/bin/python tools/blocks_diff.py selftest
"""

import json
import sys
from itertools import zip_longest
from pathlib import Path

from pdf_worker.blocks_file import write_blocks
from pdf_worker.inline import plain
from pdf_worker.output import Metadata
from pdf_worker.structure import Heading, Paragraph

ROOT = Path(__file__).resolve().parent.parent
_LEVEL_FIELDS = ("level", "source")
_SHOWN = 20


def _rest(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in _LEVEL_FIELDS}


def diff(before: Path, after: Path) -> tuple[list[tuple], int, list[tuple]]:
    """(heading level changes as (page, old, new, text), count of other differences,
    the first 20 of them as (line number, before line, after line))."""
    changes, count, others = [], 0, []
    with open(before, encoding="utf-8") as a, open(after, encoding="utf-8") as b:
        for number, (x, y) in enumerate(zip_longest(a, b), 1):
            if x == y:
                continue
            old, new = (json.loads(line) if line else None for line in (x, y))
            heading = old and new and old.get("type") == new.get("type") == "Heading"
            if heading and _rest(old) == _rest(new):
                if old["level"] != new["level"]:
                    changes.append((new["page"], old["level"], new["level"], new["text"]))
                continue
            count += 1
            if len(others) < _SHOWN:
                others.append((number, x, y))
    return changes, count, others


def main(before: Path, after: Path) -> int:
    changes, count, others = diff(before, after)
    print(f"{len(changes)} heading levels changed")
    for page, old, new, text in changes:
        print(f"  p{page + 1}: {old} -> {new}  {plain(text)}")
    print(f"{count} other differences")
    for number, x, y in others:
        print(f"  line {number}:\n    - {(x or '').rstrip()}\n    + {(y or '').rstrip()}")
    return 1 if count else 0


def selftest() -> None:
    work = ROOT / "scratch" / "blocks_diff_selftest"
    work.mkdir(parents=True, exist_ok=True)
    meta = Metadata(title="T", author="A", language="es")
    blocks = [Heading("I. Uno", 3, 0), Paragraph("texto", page=0), Heading("1. Dos", 3, 1)]
    write_blocks(blocks, meta, work / "before.jsonl")
    leveled = [Heading("I. Uno", 1, 0, source="tags"), blocks[1], Heading("1. Dos", 2, 1)]
    write_blocks(leveled, meta, work / "levels.jsonl")
    changes, count, _ = diff(work / "before.jsonl", work / "levels.jsonl")
    assert changes == [(0, 3, 1, "I. Uno"), (1, 3, 2, "1. Dos")] and count == 0, changes
    changed = [*leveled[:2], Heading("1. Tres", 2, 1), Paragraph("más")]
    write_blocks(changed, meta, work / "other.jsonl")
    changes, count, others = diff(work / "before.jsonl", work / "other.jsonl")
    assert changes == [(0, 3, 1, "I. Uno")] and count == 2, (changes, count)
    assert [n for n, _, _ in others] == [4, 5] and others[1][1] is None, others
    assert main(work / "before.jsonl", work / "levels.jsonl") == 0
    print("ok")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["selftest"]:
        selftest()
    elif len(args) == 2:
        sys.exit(main(Path(args[0]), Path(args[1])))
    else:
        sys.exit(__doc__)

"""Write structure blocks as Markdown (Pandoc/GFM footnote syntax).

The body is streamed to the output file; notes are streamed to a temporary file and
appended at the end, so memory use stays flat.
"""

import json
import os
import re
import tempfile
from collections.abc import Iterable
from functools import partial
from pathlib import Path

from pdf_worker.inline import LinkClose, LinkOpen, MarginRef, Style, pieces, plain
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import (
    REF_RE,
    Block,
    Gloss,
    Heading,
    Image,
    ListItem,
    Note,
    Paragraph,
    Table,
)

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


def render_markdown(text: str, line_start: bool = True, typst: bool = False) -> str:
    """Escape block text for Markdown and render its inline markers: web links become
    ``[text](url)``, italic and bold ``*text*`` and ``**text**``; links within the book
    and page starts are dropped. Margin references are bold ``[34b]``, or with ``typst``
    raw Typst calls ``#mref("34b")`` (``pdf_worker.typst_export``'s template)."""
    out: list[str] = []
    targets: list[str | None] = []
    first = True
    styles = {True: False, False: False}  # italic, bold: on at this point
    for piece in pieces(text):
        if isinstance(piece, str):
            escaped = escape_markdown(piece, line_start=line_start and first)
            core = escaped.strip()
            # Emphasis must hug its text: spaces go outside the asterisks.
            mark = "*" * styles[True] + "**" * styles[False]
            if mark and core:
                lead = escaped[: len(escaped) - len(escaped.lstrip())]
                trail = escaped[len(escaped.rstrip()) :]
                escaped = f"{lead}{mark}{core}{mark[::-1]}{trail}"
            out.append(escaped)
            first = False
        elif isinstance(piece, Style):
            styles[piece.italic] = piece.on
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
            if typst:
                # ";" ends the call, so a following "(" or "." isn't read as part of it.
                # shortcut: a label with a backtick would end the code span; OCR labels have none.
                out.append(f"`#mref({json.dumps(piece.label, ensure_ascii=False)});`{{=typst}}")
            else:
                out.append(f"**\\[{piece.label}\\]** ")  # bold in Word too (via Pandoc)
            first = False
    return "".join(out)


def _yaml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_markdown(
    blocks: Iterable[Block], output_path: Path, meta: Metadata, typst: bool = False
) -> WriteStats:
    """``typst``: margin references as raw Typst (see ``render_markdown``)."""
    render = partial(render_markdown, typst=typst)
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
            if meta.publisher:
                body.write(f"publisher: {_yaml(meta.publisher)}\n")
            if meta.year:
                body.write(f"date: {_yaml(meta.year)}\n")
            body.write(f"lang: {meta.language}\n---\n\n")
            open_note: Note | None = None
            listing: dict[int, str] = {}  # open list depths -> the label that comes next
            for block in blocks:
                if listing and not isinstance(block, ListItem):
                    body.write("\n")  # a blank line ends the list
                    listing.clear()
                if isinstance(block, Heading):
                    stats.headings += 1
                    level = min(block.level, 6)
                    text = render(block.text, line_start=False)
                    body.write("#" * level + " " + text + "\n\n")
                elif isinstance(block, Paragraph):
                    stats.paragraphs += 1
                    body.write(render(block.text) + "\n\n")
                elif isinstance(block, ListItem):
                    stats.paragraphs += 1
                    body.write(_list_item(block, listing, render))
                elif isinstance(block, Table):
                    stats.tables += 1
                    body.write(_table(block, render) + "\n")
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
                    lines = [render(line) for line in block.lines]
                    body.write("> " + "\\\n> ".join(lines) + "\n\n")
                elif isinstance(block, Note):
                    if block.continued and open_note and open_note.label == block.label:
                        open_note = Note(block.label, f"{open_note.text} {block.text}")
                        continue
                    if open_note:
                        _write_note(notes, open_note, render)
                    open_note = block
                    stats.notes += 1
            if open_note:
                _write_note(notes, open_note, render)
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


def _next_label(label: str) -> str:
    """The label Pandoc gives the next item of a list: "a)" -> "b)", "9." -> "10."."""
    number, mark = label[:-1], label[-1]
    return (str(int(number) + 1) if number.isdigit() else chr(ord(number) + 1)) + mark


def _list_item(item: ListItem, listing: dict[int, str], render) -> str:
    """One item as Pandoc list syntax (``fancy_lists``): "a) text" starts a list at "a)" and
    Pandoc numbers on from there, so the printed label survives only while each is the one
    after the item before, or starts a list of another kind ("1." then "a)": a blank line
    between); any other label (or one Pandoc reads as a name, like "A.") is escaped text
    in a paragraph of its own. ``listing`` holds the open depths (see ``_next_label``).
    shortcut: a second list restarting at "1." after the first is a paragraph at its
    first item; add a separator comment if books need it."""
    depth = min(item.depth, max(listing, default=0) + 1)
    for deeper in [d for d in listing if d > depth]:
        del listing[deeper]
    label = item.label
    # Any one-sign label ("•", "–", "*", U+F0B7) or Word's "o" (a nested list's) is a bullet.
    bullet = label in ("", "o") or (len(label) == 1 and not label.isalnum())
    marker = "-" if bullet else label
    want = listing.get(depth, marker)
    kind = lambda m: (m[:-1].isdigit(), m[-1])  # noqa: E731 - digits or letters, "." or ")"
    if (bullet or re.fullmatch(r"\d{1,3}[.)]|[a-zA-Z]\)", label)) and (
        want == marker or kind(want) != kind(marker)
    ):
        listing[depth] = marker if bullet else _next_label(label)
        new_list = "\n" if want != marker else ""
        return new_list + "    " * (depth - 1) + f"{marker} {render(item.text, line_start=False)}\n"
    out = "\n" if listing else ""
    listing.clear()
    escaped = re.sub(r"[.)(]", r"\\\g<0>", escape_markdown(label, line_start=False))
    return out + f"{escaped} {render(item.text, line_start=False)}".lstrip() + "\n\n"


def _table(table: Table, render=render_markdown) -> str:
    """A pipe table; its first row is the header row (Markdown tables need one)."""

    def cell(text: str) -> str:
        return render(text, line_start=False).replace("|", "\\|") or " "

    rows = ["| " + " | ".join(cell(c) for c in row) + " |" for row in table.rows]
    rule = "|" + "|".join(" --- " for _ in table.rows[0]) + "|"
    return "\n".join([rows[0], rule, *rows[1:]]) + "\n"


def _write_note(out, note: Note, render=render_markdown) -> None:
    # Later paragraphs of a note are indented by four spaces (Pandoc footnote syntax).
    paragraphs = [render(p) for p in note.text.split("\n\n") if plain(p).strip()]
    out.write(f"[^{note.label}]: " + "\n\n    ".join(paragraphs) + "\n\n")

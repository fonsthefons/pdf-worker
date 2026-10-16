"""Write the book as a freshly typeset, reflowed PDF (A5 pages, like an e-book).

The book is rendered to HTML (``pdf_worker.html_export``) and laid out by MuPDF's
Story engine onto new pages, with working links for contents and footnotes.

Footnotes go to the bottom of the page that first refers to them. Story has no
footnotes, so the book is laid out again with room kept for each page's notes until
every page's notes fit (a reference pushed to the next page takes its note along).
Notes too long for a page stay at the end of the book.

Margin references (Stephanus "22b", see ``pdf_worker.margin_refs``) are set in the right
margin, level with the line of the word they precede.
"""

import os
import re
import tempfile
from collections.abc import Iterable
from html import unescape as html_unescape
from pathlib import Path

import pymupdf

from pdf_worker.cover import add_cover_page
from pdf_worker.html_export import write_html
from pdf_worker.inline import ESTIMATED
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import Block

PAGE = pymupdf.paper_rect("a5")
MARGIN = 42  # points
FRAME = PAGE + (MARGIN, MARGIN, -MARGIN, -MARGIN)
_CSS = """\
body { font-family: serif; font-size: 11pt; line-height: 1.35; }
h1, h2, h3, h4, h5, h6 { font-family: sans-serif; }
p { margin: 0 0 0.3em 0; text-align: justify; }
img { max-width: 100%; }
"""
# Same column as the body (``body { margin: 0 5% }`` from the EPUB CSS), smaller type.
_NOTE_CSS = """\
body { margin: 0 5%; font-family: serif; font-size: 9pt; line-height: 1.25; }
p { margin: 0 0 2pt 0; text-align: justify; }
sup { font-size: 0.75em; line-height: 0; }
"""
_RULE = 10  # points kept above a page's notes for the separating rule
_MAX_NOTE = 0.4  # a note taller than this share of the text frame stays at the end
_EXACT_PASSES = 3  # then room for notes only grows, so the layout settles
_MAX_PASSES = 12

_NOTES_RE = re.compile(r'<section id="notes" class="notes">\n(.*?)</section>\n', re.DOTALL)
_ASIDE_RE = re.compile(r'<aside class="note" id="(n\d+)"[^>]*>(.*?)</aside>\n?', re.DOTALL)
_TOC_NOTES_RE = re.compile(r'\n?<li><a href="#notes">[^<]*</a>(?:</li>)?')
_LINK_TAG_RE = re.compile(r"</?a\b[^>]*>")
_BACK_RE = re.compile(r' <a class="back"[^>]*>[^<]*</a>')
_REF_ID_RE = re.compile(r"r(\d+)(?:-\d+)?")
# A margin reference from the EPUB writer, and the word after it.
_MREF_RE = re.compile(r'<span class="mref[^"]*" id="(m\d+)">([^<]*)</span>(\s*)([^\s<]*)')
_MREF_ID_RE = re.compile(r"m\d+")
_MREF_GAP = 6  # points between the text column and a margin reference
_MREF_SIZE = 7.5
_MREF_COLOR = (0.18, 0.49, 0.2)  # green, as in the EPUB
_MREF_ESTIMATED_COLOR = (0.85, 0.11, 0.38)  # pink, as in the EPUB
_FOLIO_SIZE = 9


def write_pdf(
    blocks: Iterable[Block],
    output_path: Path,
    meta: Metadata,
    notes_at: str = "page",
    cover: bool = False,
) -> WriteStats:
    """Lay the book out as an A5 PDF. ``notes_at``: "page" sets each footnote at the foot
    of the page that refers to it, "end" keeps them all in the notes section. ``cover``
    adds a text cover (``pdf_worker.cover``) as page 1. Pages are numbered at the foot
    with the PDF's own page numbers, the cover unnumbered."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=output_path.parent, prefix=f".{output_path.name}.w."))
    fd, tmp_name = tempfile.mkstemp(dir=output_path.parent, prefix=f".{output_path.name}.")
    os.close(fd)
    try:
        page_html = work / "book.html"
        stats = write_html(blocks, page_html, meta, images_dir=work / "images", css=_CSS)
        html = page_html.read_text(encoding="utf-8")
        html, notes = _split_notes(html) if notes_at == "page" else (html, {})
        html, labels = _margin_refs(html)
        archive = pymupdf.Archive(str(work))
        reserve: dict[int, float] = {}
        for passes in range(1, _MAX_PASSES + 1):
            doc, refs, marks = _typeset(html, archive, reserve)
            need = _room_needed(refs, notes)
            fits = all(height <= reserve.get(page, 0) for page, height in need.items())
            if fits or passes == _MAX_PASSES:
                break
            doc.close()
            if passes >= _EXACT_PASSES:
                need = {p: max(h, reserve.get(p, 0)) for p, h in (reserve | need).items()}
            reserve = need
        with doc:
            _place_notes(doc, refs, notes)
            _place_margin_refs(doc, marks, labels)
            _number_pages(doc, first=2 if cover else 1)
            if cover:
                add_cover_page(doc, meta)
            doc.set_metadata({"title": meta.title, "author": meta.author, "producer": "pdf-worker"})
            doc.save(tmp_name, garbage=3, deflate=True)
            stats.chapters = doc.page_count  # pages, for the summary
        os.replace(tmp_name, output_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    finally:
        for path in sorted(work.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        work.rmdir()
    return stats


def _split_notes(html: str) -> tuple[str, dict[str, tuple[str, float]]]:
    """Take the notes that fit on a page, and are referred to, out of the end section.

    Returns the book without them and ``{note id: (note HTML, height)}``.
    """
    section = _NOTES_RE.search(html)
    if not section:
        return html, {}
    notes = {}
    with pymupdf.open() as scratch:
        page = scratch.new_page(width=PAGE.width, height=PAGE.height * 4)
        for note_id, body in _ASIDE_RE.findall(section.group(1)):
            if f'<a class="noteref" id="r{note_id[1:]}"' not in html:
                continue  # no page to put it under
            body = _BACK_RE.sub("", body)  # under its reference, the note needs no way back
            body = _LINK_TAG_RE.sub("", body)  # links are added once the note is placed
            height = _height(page, body)
            if height <= FRAME.height * _MAX_NOTE:
                notes[note_id] = (body, height)
    if not notes:
        return html, {}
    rest = _ASIDE_RE.sub(lambda m: m.group(0) if m.group(1) not in notes else "", section.group(1))
    if _ASIDE_RE.search(rest):
        html = html.replace(section.group(1), rest)
    else:  # every note moved: drop the section and its contents entry
        html = _TOC_NOTES_RE.sub("", html.replace(section.group(0), ""))
    # A reference to a note at the foot of the page is linked once the page is laid out.
    for note_id in notes:
        html = re.sub(
            rf'(<a class="noteref" id="r{note_id[1:]}(?:-\d+)?") href="#{note_id}"', r"\1", html
        )
    return html, notes


def _height(page: pymupdf.Page, body: str) -> float:
    rect = pymupdf.Rect(FRAME.x0, 0, FRAME.x1, page.rect.height)
    spare, _ = page.insert_htmlbox(rect, body, css=_NOTE_CSS)
    return rect.height - spare + 1  # 1 pt so it fits again at the foot of the page


def _typeset(html: str, archive, reserve: dict[int, float]):
    """Lay the book out, the text of each page ending above its ``reserve``.

    Returns the document, the references to notes: ``[(page, note id, rect)]``, and
    where the margin references go: ``[(page, id, rect)]``.
    """
    story = pymupdf.Story(html=html, archive=archive)
    refs = []
    marks: dict[str, tuple[int, str, pymupdf.Rect]] = {}
    seen = set()

    def rect_fn(rect_num, filled):
        return PAGE, FRAME + (0, 0, 0, -reserve.get(rect_num, 0)), None

    def position_fn(position):
        if not position.id:
            return
        rect = pymupdf.Rect(position.rect)
        if _MREF_ID_RE.fullmatch(position.id):
            # Reported twice: first at the space before the word (maybe the line
            # before), then at the word itself.
            if position.id not in marks or rect.width > 0:
                marks[position.id] = (position.page_num - 1, position.id, rect)
            return
        match = _REF_ID_RE.fullmatch(position.id)
        if match and position.id not in seen:
            seen.add(position.id)
            refs.append((position.page_num - 1, f"n{match.group(1)}", rect))

    return story.write_with_links(rect_fn, position_fn), refs, list(marks.values())


def _margin_refs(html: str) -> tuple[str, dict[str, str]]:
    """Take the margin references out of the text; the word after each one carries its
    id, so the label can be set in the margin beside that word's line.

    Returns the book and ``{id: label}``."""
    labels = {}

    def lift(match: re.Match) -> str:
        labels[match.group(1)] = html_unescape(match.group(2))
        if match.group(4):
            return f'{match.group(3)}<span id="{match.group(1)}">{match.group(4)}</span>'
        return f'{match.group(3)}<span id="{match.group(1)}"></span>'  # a tag follows

    return _MREF_RE.sub(lift, html), labels


def _place_margin_refs(doc: pymupdf.Document, marks, labels: dict[str, str]) -> None:
    """Set each margin reference in the right margin, level with its line."""
    x = FRAME.x1 - FRAME.width * 0.05 + _MREF_GAP  # the text column ends at 5% in
    last = (-1, 0.0, 0.0)  # page, baseline and right end of the last one set
    for page_no, mark_id, rect in marks:
        label = labels.get(mark_id)
        if not label:
            continue
        baseline = rect.y1 - rect.height * 0.25
        start = x
        if last[0] == page_no and abs(last[1] - baseline) < 2:
            start = last[2] + 3  # two on one line: side by side
        page = doc[page_no]
        color = _MREF_ESTIMATED_COLOR if label.startswith(ESTIMATED) else _MREF_COLOR
        page.insert_text(
            (start, baseline), label, fontname="hebo", fontsize=_MREF_SIZE, color=color
        )
        width = pymupdf.get_text_length(label, fontname="hebo", fontsize=_MREF_SIZE)
        last = (page_no, baseline, start + width)


def _number_pages(doc: pymupdf.Document, first: int) -> None:
    for number, page in enumerate(doc, first):
        label = str(number)
        width = pymupdf.get_text_length(label, fontname="tiro", fontsize=_FOLIO_SIZE)
        page.insert_text(
            ((PAGE.width - width) / 2, PAGE.height - MARGIN / 2),
            label,
            fontname="tiro",
            fontsize=_FOLIO_SIZE,
        )


def _page_notes(refs, notes) -> dict[int, list[str]]:
    """The notes at the foot of each page: those first referred to there."""
    pages: dict[int, list[str]] = {}
    placed = set()
    for page, note_id, _ in refs:
        if note_id in notes and note_id not in placed:
            placed.add(note_id)
            pages.setdefault(page, []).append(note_id)
    return pages


def _room_needed(refs, notes) -> dict[int, float]:
    """Room to keep at the foot of each page for its notes.

    A reference too low for its note to fit under it goes to the next page with its
    line (the page's text ends above that line), else the two would push each other
    back and forth between the pages.
    """
    room: dict[int, float] = {}
    full = set()
    placed = set()
    for page, note_id, rect in refs:
        if note_id not in notes or note_id in placed or page in full:
            continue
        before = room.get(page, _RULE)
        after = before + notes[note_id][1]
        if rect.y1 <= FRAME.y1 - after:
            placed.add(note_id)
            room[page] = after
        else:
            room[page] = max(before, FRAME.y1 - rect.y0 + 0.5)
            full.add(page)
    return room


def _place_notes(doc: pymupdf.Document, refs, notes) -> None:
    where = {}  # note id -> (page, rect)
    for page_no, ids in _page_notes(refs, notes).items():
        page = doc[page_no]
        y = FRAME.y1 - sum(notes[n][1] for n in ids)
        left = FRAME.x0 + FRAME.width * 0.05
        page.draw_line((left, y - _RULE / 2), (left + FRAME.width * 0.3, y - _RULE / 2), width=0.5)
        for note_id in ids:
            body, height = notes[note_id]
            rect = pymupdf.Rect(FRAME.x0, y, FRAME.x1, y + height)
            page.insert_htmlbox(rect, body, css=_NOTE_CSS)
            where[note_id] = (page_no, rect)
            y += height
    first_ref = {}
    for page_no, note_id, rect in refs:
        if note_id not in where:
            continue
        first_ref.setdefault(note_id, (page_no, rect))
        note_page, note_rect = where[note_id]
        _link(
            doc[page_no], pymupdf.Rect(rect.x0, rect.y0, rect.x0 + 8, rect.y1), note_page, note_rect
        )
    for note_id, (page_no, rect) in where.items():
        marker = pymupdf.Rect(rect.x0, rect.y0, rect.x0 + FRAME.width * 0.05 + 12, rect.y0 + 11)
        _link(doc[page_no], marker, *first_ref[note_id])


def _link(page: pymupdf.Page, source: pymupdf.Rect, target_page: int, target: pymupdf.Rect):
    page.insert_link(
        {"kind": pymupdf.LINK_GOTO, "from": source, "page": target_page, "to": target.tl}
    )

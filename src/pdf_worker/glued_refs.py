"""Note references flattened onto the line: "inteligentes74• Puesto que".

The Timeo's OCR redraw (ClearScan-style, see ``pdf_worker.font_sizes``) sets the printed
"inteligentes⁷⁴." in body-size digits on the baseline, glued to the word, and reads the
period after it as "•"; a few it flags as superscript. Digits glued to a word are also
misread old-style figures ("x999" for 1999), so only those that count up through the
book as notes do (1, 2, 3 ..., with gaps where OCR lost some) are taken. Their places
are stored on the pages (in memory, ``/PdfWorkerGluedRefs``) and
``pdf_worker.layout.page_lines`` writes them as superscript digits, to be matched with
their notes as any others.
"""

import json
import re
from collections.abc import Collection

import pymupdf

from pdf_worker.consensus import _union
from pdf_worker.endnotes import LOSSY_MIN_RUN, LOSSY_STEP, sequences

REFS_KEY = "PdfWorkerGluedRefs"
_SUPERSCRIPT = 1  # MuPDF span flag
_TO_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_NUMBER_RE = re.compile(r"(?<!\d)\d{1,3}(?!\d)")
# A number glued after a word's letter or closing quote, ending the word:
# "inteligentes74•", "«generado»17.", "(46d)28".
_GLUED_RE = re.compile(r"(?:(?<=[^\W\d_]|[»”)])|(?<=[^\W\d_] ))\d{1,3}(?=•?[.,;:?!»”)]*(?:\s|$))")


def mark_glued_refs(doc: pymupdf.Document, skip: Collection[int] = ()) -> int:
    """Store the places of ``doc``'s glued references on its pages (in memory);
    returns how many."""
    boxes: dict[int, list] = {}
    for run in sequences(_candidates(doc, skip), LOSSY_STEP, LOSSY_STEP):
        if len(run.items) >= LOSSY_MIN_RUN:
            for _, (index, box) in run.items:
                boxes.setdefault(index, []).append(box)
    for index, page_boxes in boxes.items():
        doc.xref_set_key(
            doc.load_page(index).xref, REFS_KEY, pymupdf.get_pdf_str(json.dumps(page_boxes))
        )
    return sum(len(page_boxes) for page_boxes in boxes.values())


def _candidates(doc: pymupdf.Document, skip: Collection[int]) -> list[tuple[int, tuple]]:
    """Numbers glued to a word or flagged as superscript: ``(number, (page, box))``."""
    found = []
    for page in doc:
        if page.number in skip:
            continue
        for block in page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
            for line in block.get("lines", ()):
                chars, raised = [], []
                for span in line["spans"]:
                    raised += [bool(span["flags"] & _SUPERSCRIPT)] * len(span["chars"])
                    chars += span["chars"]
                text = "".join(c["c"] for c in chars)
                if len(text) != len(chars):
                    continue  # a glyph of several characters: offsets don't hold
                for match in _NUMBER_RE.finditer(text):
                    start, end = match.span()
                    if _GLUED_RE.match(text, start) or all(raised[start:end]):
                        box = _union(chars[start:end])
                        found.append((int(match.group()), (page.number, box)))
    return found


def page_refs(page: pymupdf.Page) -> list[list[float]]:
    kind, value = page.parent.xref_get_key(page.xref, REFS_KEY)
    return json.loads(value) if kind == "string" else []


def apply_refs(chars: list[dict], boxes: list[list[float]]) -> None:
    """Write the glued references in a line's ``rawdict`` characters as superscript
    digits, and a "•" right after one as the period it is."""
    for i, char in enumerate(chars):
        x0, y0, x1, y1 = char["bbox"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if char["c"].isdigit() and any(
            bx0 <= cx <= bx1 and by0 <= cy <= by1 for bx0, by0, bx1, by1 in boxes
        ):
            char["c"] = char["c"].translate(_TO_SUP)
            after = [c["c"] for c in chars[i + 1 : i + 3]]
            if after[:1] == ["•"]:
                chars[i + 1]["c"] = "."
            elif after == [" ", "•"]:  # "exactitud188 •": the period moves up
                chars[i + 1]["c"], chars[i + 2]["c"] = ".", ""

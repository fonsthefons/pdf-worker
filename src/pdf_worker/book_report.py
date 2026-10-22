"""A quality report for one built book: what is wrong, what may be wrong, and a grade.

Nothing here is a measured probability. The grade sums up counts the pipeline already
has (the review file, the OCR and convert reports, words kept), against the fixed
thresholds below, which the report prints so the grade can be checked by hand.
"""

import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pdf_worker.document import open_pdf
from pdf_worker.fixes import SPELL_LANGUAGES, SPELLING_TYPES, Fix

KIND_LABELS = {
    "chars": "odd characters (look-alike letters, stray symbols)",
    "note-no-ref": "notes whose reference wasn't found in the text",
    "ref-no-note": "note references with no note",
    "margin-est": "margin references placed by estimate",
    "margin-missing": "margin references missing",
    "greek-dropped": "Greek passages left out (bilingual edition)",
}
FOUND_KINDS = ("chars", "note-no-ref", "ref-no-note")
SPELLING_LABELS = {
    "accent": "accent probably lost",
    "swap": "letters OCR often confuses (b/h, c/e...)",
    "ocr1": "one letter from a known word",
    "name": "close to a name used elsewhere in the book",
    "unknown": "not in the dictionary",
}

# Grade thresholds. Kept words = the book's words / the words of the PDF it was built
# from (letters only, so page numbers don't count; running heads make it a bit under 1).
KEPT_D, KEPT_C = 0.70, 0.85
EMPTY_D = 0.10  # share of pages with no text at all
OPEN_C, OPEN_B = 5.0, 0.5  # open review rows per 1,000 words of the book
GRADE_RULES = [
    f"D: under {KEPT_D:.0%} of the words kept, or over {EMPTY_D:.0%} of pages without text",
    f"C: under {KEPT_C:.0%} of the words kept, or over {OPEN_C:g} open rows per 1,000 words",
    f"B: over {OPEN_B:g} open rows per 1,000 words, or OCR'd text with spelling rows open "
    f"or in a language the spelling check doesn't know (it knows {', '.join(SPELL_LANGUAGES)})",
    "A: none of the above",
]

_WORD = re.compile(r"[^\W\d_]+")
_TAG = re.compile(r"<[^>]+>")


@dataclass
class BookReport:
    name: str
    how: str  # where the text came from
    ocr: bool  # the text was read by OCR (now or in an earlier layer)
    language: str = ""
    notes: list[str] = field(default_factory=list)
    corrected: dict[str, int] = field(default_factory=dict)  # fixed automatically
    pages: int = 0
    empty_pages: int = 0
    source_words: int | None = None  # None: no text layer to compare with
    book_words: int = 0
    found: Counter = field(default_factory=Counter)  # label -> open rows
    possible: Counter = field(default_factory=Counter)
    left_out: Counter = field(default_factory=Counter)
    open_spelling: int = 0
    decided: int = 0  # review rows with a decision

    @property
    def open_rows(self) -> int:
        return sum(self.found.values()) + sum(self.possible.values())

    @property
    def kept(self) -> float | None:
        return self.book_words / self.source_words if self.source_words else None

    @property
    def spelling_unchecked(self) -> bool:
        return self.ocr and self.language not in SPELL_LANGUAGES

    @property
    def grade(self) -> str:
        per_k = self.open_rows / max(self.book_words / 1000, 1)
        kept = self.kept
        if (kept is not None and kept < KEPT_D) or self.empty_pages > EMPTY_D * self.pages:
            return "D"
        if (kept is not None and kept < KEPT_C) or per_k > OPEN_C:
            return "C"
        if per_k > OPEN_B or (self.ocr and self.open_spelling) or self.spelling_unchecked:
            return "B"
        return "A"


def count_rows(report: BookReport, fixes: list[Fix]) -> None:
    """Sort the review file's rows into found, possible, left out and decided."""
    for fix in fixes:
        if fix.action == "replace" and fix.status == "stale":
            report.found["review fixes that no longer apply"] += 1
        elif fix.action:
            report.decided += 1
        elif fix.status == "stale":
            continue  # the text it was about is gone
        elif fix.kind == "greek-dropped":
            report.left_out[KIND_LABELS[fix.kind]] += 1
        elif fix.kind == "spelling":
            label = SPELLING_LABELS.get(fix.type, SPELLING_LABELS["unknown"])
            report.possible[f"spelling: {label}"] += 1
            report.open_spelling += 1
        elif fix.kind in FOUND_KINDS:
            report.found[KIND_LABELS[fix.kind]] += 1
        else:
            report.possible[KIND_LABELS.get(fix.kind, fix.kind)] += 1


def count_words(report: BookReport, pdf: Path, epub: Path, compare: bool = True) -> None:
    """Pages, empty pages and words of the source ``pdf`` (page by page), and the
    words of the built ``epub`` (file by file). ``compare=False``: the PDF's text layer
    isn't what the book was built from, so no words-kept share."""
    words = 0
    with open_pdf(pdf) as doc:
        report.pages = doc.page_count
        for page in doc:
            n = len(_WORD.findall(page.get_text()))
            words += n
            report.empty_pages += not n
    report.source_words = words if compare else None
    with zipfile.ZipFile(epub) as z:
        for name in z.namelist():
            if name.endswith((".xhtml", ".html")) and not name.endswith("nav.xhtml"):
                text = _TAG.sub(" ", z.read(name).decode("utf-8", "replace"))
                report.book_words += len(_WORD.findall(text))


def markdown(report: BookReport, state: str) -> str:
    kept = report.kept
    lines = [
        f"# {report.name}",
        "",
        f"**Grade {report.grade}** ({state}). Open review rows: {report.open_rows}"
        f" ({report.open_rows / max(report.book_words / 1000, 1):.1f} per 1,000 words);"
        f" decided: {report.decided}.",
        "",
        "## Reliability",
        "",
        f"- Text: {report.how}",
        *(f"- {note}" for note in report.notes),
        *(
            [f"- OCR'd text in '{report.language}': no spelling check for it"]
            if report.spelling_unchecked
            else []
        ),
        f"- Pages: {report.pages}, without any text: {report.empty_pages}",
        f"- Words in the book: {report.book_words:,}"
        + (
            f" of {report.source_words:,} in the PDF it was built from ({kept:.0%} kept)"
            if kept is not None
            else " (no text layer to compare with)"
        ),
    ]
    for title, counts in [
        ("Errors found (open)", report.found),
        ("Possible errors (open)", report.possible),
        ("Fixed automatically", report.corrected),
        ("Left out", report.left_out),
    ]:
        lines += ["", f"## {title}", ""]
        # Automatic fixes show 0 too: it says the check ran.
        rows = [(label, n) for label, n in counts.items() if n or counts is report.corrected]
        lines += [f"- {label}: {n}" for label, n in rows] or ["- none"]
    lines += ["", "## How the grade is set", "", *(f"- {rule}" for rule in GRADE_RULES)]
    return "\n".join(lines) + "\n"


assert tuple(SPELLING_LABELS) == SPELLING_TYPES

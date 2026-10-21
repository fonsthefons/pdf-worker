"""Endnotes referenced by superscript numbers, with the notes collected elsewhere.

Many books number notes per chapter (superscripts 1, 2, 3 ... restarting in every
chapter) and print them together: at the end of each chapter or in a "Notes" section at
the back (``1. Text of the note``). The analysis pass records every superscript number
and every numbered line; this module turns them into runs and groups and pairs each
chapter's run of references with its group of notes, in document order.

Labels are ``c<group>-<number>`` (``[^c3-12]``); readers see just the number.
"""

import bisect
import re
from dataclasses import dataclass, field

from pdf_worker.margin_refs import OCR_DIGITS

# Numbers may skip a little within a run (a missed superscript, an OCR'd note).
_MAX_STEP = 3
# ... in OCR that loses or garbles numbers in a row ("todos'º5" for 105, "l!IO" for 120).
LOSSY_STEP = 15
# ... where only long runs are trusted (the Timeo's shorter ones were stray numbers): a
# few a page, so a few pages of a book are tested as the book is.
LOSSY_MIN_RUN = 20
_LOSSY_RUN_PER_PAGE = 2
_LOSSY_MIN_RUN_FLOOR = 4
# A run and a group pair up when their highest numbers are this close.
_MAX_COUNT_DIFF = 2
_MAX_COUNT_RATIO = 0.15
# Keep the DP small on huge documents.
_MAX_ALIGN = 3000

Position = tuple[int, int]  # (page index, line index)


@dataclass
class _Sequence:
    """Numbers 1, 2, 3 ... in document order, with where each one occurs."""

    items: list[tuple[int, tuple]] = field(default_factory=list)  # (number, key)

    @property
    def last(self) -> int:
        return self.items[-1][0]

    @property
    def start(self) -> tuple:
        return self.items[0][1]


@dataclass
class ChapterNotes:
    # (page index, line index) -> {span index of a superscript: label}
    refs: dict[Position, dict[int, str]] = field(default_factory=dict)
    # (page index, line index) of a note's first line -> label
    defs: dict[Position, str] = field(default_factory=dict)
    # Labels of the last note in each group (the notes area may end after them).
    last_in_group: set[str] = field(default_factory=set)
    # Last notes after which the notes section goes on with the next chapter's notes.
    section_continues: set[str] = field(default_factory=set)
    # Pages holding notes: no bottom-of-page footnote detection there.
    note_pages: set[int] = field(default_factory=set)


def sequences(
    entries: list[tuple[int, tuple]], max_step: int = _MAX_STEP, resume_step: int = 1
) -> list[_Sequence]:
    """Split numbers into sequences that start at 1 and climb by at most ``max_step``;
    strays are ignored, and a sequence after a stray "1" resumes by ``resume_step``."""
    out: list[_Sequence] = []
    for number, key in entries:
        current = out[-1] if out else None
        previous = out[-2] if len(out) > 1 else None
        if current and number == current.last + 1:
            current.items.append((number, key))
        elif (
            previous
            and previous.last < number <= previous.last + resume_step
            and len(previous.items) > len(current.items)
        ):
            # The previous sequence resumes: the latest one was a numbered list inside
            # a note ("107. ... 1. ... 10." then "108."), or a stray "1", not a group of
            # its own.
            out.pop()
            previous.items.append((number, key))
        elif current and current.last < number <= current.last + max_step:
            current.items.append((number, key))
        elif number == 1 and current and len(current.items) == 1:
            current.items[0] = (number, key)  # a "1" after a lone "1": one of them a stray
        elif number == 1:
            out.append(_Sequence([(number, key)]))
    return out


def lossy_min_run(pages: int) -> int:
    """The length from which a lossy run is trusted, in a document of ``pages``."""
    return max(_LOSSY_MIN_RUN_FLOOR, min(LOSSY_MIN_RUN, _LOSSY_RUN_PER_PAGE * pages))


def runs_from_anywhere(entries: list[tuple[int, tuple]]) -> list[_Sequence]:
    """Runs climbing by at most ``LOSSY_STEP`` from any number (OCR loses note 1 as any
    other, and a part of a book starts where it starts); each number joins the longest
    run it can continue, so a stray starts a run nothing follows."""
    runs: list[_Sequence] = []
    for item in entries:
        fits = [run for run in runs if run.last < item[0] <= run.last + LOSSY_STEP]
        if fits:
            max(fits, key=lambda run: len(run.items)).items.append(item)
        else:
            runs.append(_Sequence([item]))
    return runs


def _fill_gaps(
    defined: dict[int, tuple], marks: list[tuple], readings: dict[tuple, str] | None = None
) -> None:
    """Notes a group skips (their numbers misread): where as many unclaimed marks lie
    between the notes found around the gap as numbers are missing, they are those notes,
    in order. Then, by what a mark was read as (``readings``), a mark whose last digits
    are a missing number's (".i,57" for 457, "H7" for 447) is that note, in order; and
    the gaps left are counted again."""
    _fill_counted(defined, marks)
    if readings:
        _fill_read(defined, marks, readings)
        _fill_counted(defined, marks)


def _gaps(defined: dict[int, tuple], marks: list[tuple]):
    """Each gap in the numbers found: (lower, upper, the unclaimed marks between)."""
    used = set(defined.values())
    numbers = sorted(defined)
    for lo, hi in zip(numbers, numbers[1:], strict=False):
        if hi - lo >= 2:
            between = (m for m in marks if defined[lo] < m < defined[hi] and m not in used)
            yield lo, hi, sorted(between)


def _fill_counted(defined: dict[int, tuple], marks: list[tuple]) -> None:
    for lo, hi, between in list(_gaps(defined, marks)):
        if len(between) == hi - lo - 1:
            defined.update(zip(range(lo + 1, hi), between, strict=True))


def _fill_read(defined: dict[int, tuple], marks: list[tuple], readings: dict[tuple, str]) -> None:
    for lo, hi, between in list(_gaps(defined, marks)):
        last = lo
        for mark in between:
            digits = re.sub(r"\D", "", readings.get(mark, "").translate(OCR_DIGITS))
            if not digits:
                continue
            fits = [
                n
                for n in range(last + 1, hi)
                if n not in defined and str(n).endswith(digits[-len(str(n)) :])
            ]
            if len(fits) == 1:  # "H7" with both 447 and 457 missing: either
                defined[fits[0]] = mark
                last = fits[0]


def _refs_end(run: _Sequence, group: _Sequence) -> tuple:
    """Where a lossy run's references end and its notes begin: the reference after
    which the most of the run's numbers have their note. A stray superscript read among
    the notes ("111" after 101) joins the run, and ending there would lose every note
    before it. The earliest such reference wins."""
    best, end = -1, run.items[-1][1]
    for _, at in run.items:
        noted = {number for number, key in group.items if key > at}
        score = sum(1 for number, key in run.items if key <= at and number in noted)
        if score > best:
            best, end = score, at
    return end


def _compatible(a: int, b: int) -> bool:
    return abs(a - b) <= max(_MAX_COUNT_DIFF, _MAX_COUNT_RATIO * max(a, b))


def _align(
    runs: list[_Sequence], groups: list[_Sequence], after_refs: bool = False
) -> list[tuple[int, int]]:
    """Pair runs with groups in order (a longest common subsequence on note counts).

    A group must start after its run starts (notes come after their references), or
    with ``after_refs`` lie after the run's last reference (from its middle on: its
    first number may be a stray). With ``after_refs`` (lossy OCR) a run also fits a
    group that holds its numbers: the last references or notes may be lost.
    """
    runs, groups = runs[:_MAX_ALIGN], groups[:_MAX_ALIGN]
    n, m = len(runs), len(groups)

    def fits(i: int, j: int) -> bool:
        run, group = runs[i], groups[j]
        holds = group.items[0][0] <= run.items[0][0] <= run.last <= group.last + LOSSY_STEP
        if not _compatible(run.last, group.last) and not (after_refs and holds):
            return False
        if after_refs:
            return groups[j].items[len(groups[j].items) // 2][1] > runs[i].items[-1][1]
        return groups[j].start > runs[i].start

    best = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            skip = max(best[i + 1][j], best[i][j + 1])
            match = 1 + best[i + 1][j + 1] if fits(i, j) else 0
            best[i][j] = max(skip, match)
    pairs = []
    i = j = 0
    while i < n and j < m:
        if fits(i, j) and best[i][j] == 1 + best[i + 1][j + 1]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif best[i + 1][j] >= best[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def match_chapter_notes(
    refs: list[tuple[int, tuple[int, int, int]]],
    defs: list[tuple[int, Position]],
    lossy: bool = False,
    least: int = LOSSY_MIN_RUN,
    marks: list[Position] = (),
    readings: dict[Position, str] | None = None,
) -> ChapterNotes:
    """Pair superscript references with numbered notes.

    ``refs`` are ``(number, (page, line, span))`` and ``defs`` ``(number, (page, line))``,
    both in document order. ``lossy``: OCR lost or garbled many numbers, so they may
    skip by ``LOSSY_STEP`` and start anywhere, only runs and groups of ``least`` are
    trusted, and a group of notes must come after all of its references (not footnotes
    beside them). ``marks``: first lines of notes whose number may be misread beyond
    reading ("n" for 11), to fill a group's gaps; ``readings``: what each was read as.
    """
    result = ChapterNotes()
    if lossy:
        runs = [run for run in runs_from_anywhere(refs) if len(run.items) >= least]
        groups = [g for g in runs_from_anywhere(defs) if len(g.items) >= least]
    else:
        runs = sequences(refs)
        groups = [g for g in sequences(defs) if len(g.items) >= 2]
    pairs = _align(runs, groups, after_refs=lossy)
    ref_positions = sorted(key[:2] for _, key in refs)
    for chapter, (i, j) in enumerate(pairs, start=1):
        end = _refs_end(runs[i], groups[j]) if lossy else runs[i].items[-1][1]
        defined = {number: key for number, key in groups[j].items if not lossy or key > end}
        _fill_gaps(defined, [m for m in marks if m > end], readings)
        for number, key in sorted(defined.items()):
            result.defs[key] = f"c{chapter}-{number}"
            result.note_pages.add(key[0])
        last_label = f"c{chapter}-{groups[j].last}"
        result.last_in_group.add(last_label)
        if chapter < len(pairs):
            # No references between this group and the next: one notes section, whose
            # per-chapter subheadings must not end it.
            after, before = groups[j].items[-1][1], groups[pairs[chapter][1]].start
            at = bisect.bisect_right(ref_positions, after)
            if at == len(ref_positions) or ref_positions[at] >= before:
                result.section_continues.add(last_label)
        for number, (page, line, span) in runs[i].items:
            if number in defined and (page, line, span) <= end:
                result.refs.setdefault((page, line), {})[span] = f"c{chapter}-{number}"
    return result

"""Endnotes referenced by superscript numbers, with the notes collected elsewhere.

Many books number notes per chapter (superscripts 1, 2, 3 ... restarting in every
chapter) and print them together: at the end of each chapter or in a "Notes" section at
the back (``1. Text of the note``). The analysis pass records every superscript number
and every numbered line; this module turns them into runs and groups and pairs each
chapter's run of references with its group of notes, in document order.

Labels are ``c<group>-<number>`` (``[^c3-12]``); readers see just the number.
"""

import bisect
from dataclasses import dataclass, field

# Numbers may skip a little within a run (a missed superscript, an OCR'd note).
_MAX_STEP = 3
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


def _sequences(entries: list[tuple[int, tuple]]) -> list[_Sequence]:
    """Split numbers into sequences that start at 1 and climb; strays are ignored."""
    out: list[_Sequence] = []
    for number, key in entries:
        current = out[-1] if out else None
        previous = out[-2] if len(out) > 1 else None
        if current and number == current.last + 1:
            current.items.append((number, key))
        elif previous and number == previous.last + 1:
            # The previous sequence resumes: the latest one was a numbered list inside
            # a note ("107. ... 1. ... 10." then "108."), not a group of its own.
            out.pop()
            previous.items.append((number, key))
        elif current and current.last < number <= current.last + _MAX_STEP:
            current.items.append((number, key))
        elif number == 1:
            out.append(_Sequence([(number, key)]))
    return out


def _compatible(a: int, b: int) -> bool:
    return abs(a - b) <= max(_MAX_COUNT_DIFF, _MAX_COUNT_RATIO * max(a, b))


def _align(runs: list[_Sequence], groups: list[_Sequence]) -> list[tuple[int, int]]:
    """Pair runs with groups in order (a longest common subsequence on note counts).

    A group must start after its run starts: notes come after their references.
    """
    runs, groups = runs[:_MAX_ALIGN], groups[:_MAX_ALIGN]
    n, m = len(runs), len(groups)
    best = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            skip = max(best[i + 1][j], best[i][j + 1])
            match = 0
            if _compatible(runs[i].last, groups[j].last) and groups[j].start > runs[i].start:
                match = 1 + best[i + 1][j + 1]
            best[i][j] = max(skip, match)
    pairs = []
    i = j = 0
    while i < n and j < m:
        if (
            _compatible(runs[i].last, groups[j].last)
            and groups[j].start > runs[i].start
            and best[i][j] == 1 + best[i + 1][j + 1]
        ):
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
) -> ChapterNotes:
    """Pair superscript references with numbered notes.

    ``refs`` are ``(number, (page, line, span))`` and ``defs`` ``(number, (page, line))``,
    both in document order.
    """
    result = ChapterNotes()
    runs = _sequences(refs)
    groups = [g for g in _sequences(defs) if len(g.items) >= 2]
    pairs = _align(runs, groups)
    ref_positions = sorted(key[:2] for _, key in refs)
    for chapter, (i, j) in enumerate(pairs, start=1):
        defined = {number: key for number, key in groups[j].items}
        for number, key in defined.items():
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
            if number in defined:
                result.refs.setdefault((page, line), {})[span] = f"c{chapter}-{number}"
    return result

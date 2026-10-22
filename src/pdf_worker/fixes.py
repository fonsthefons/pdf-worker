"""The review file: OCR errors fixed by hand in a TSV and applied on every build.

``<pdf stem>.fixes.tsv`` (next to the PDF) has the columns ``id, page, kind, type, find,
context, action, value, status``. ``page`` is the printed page label (``*``: the whole
book); ``find`` is exact text on that page. Each build applies the rows that have an
action to the blocks before any writer sees them, then appends what looks wrong with an
empty action, keeps every row the user wrote, and sets ``status``: ``applied``,
``ambiguous`` (``find`` occurs twice on the page: only the first was changed), or
``stale`` (``find`` is gone, or a flagged item is no longer found).

Actions (``value`` in brackets):
- ``replace`` [new text]: ``find`` becomes the value, on that page (``*``: everywhere);
- ``ignore``: never flagged again;
- ``attach`` [word]: note ``find`` gets a reference after the first ``word`` on the page;
- ``drop``: the reference to note ``find`` is removed;
- ``accept``: estimated margin reference ``find`` ("~21b") becomes a found one;
- ``move`` [word]: ... and goes before the first ``word`` on the page;
- ``add`` [``21d before pero``]: a margin reference the scan lost.

Kinds flagged: ``spelling`` (Spanish and English books, body text only: not notes,
small print, bibliographies or indexes; words found at most twice in the book (a
capitalised one only once, unless a more frequent name is one or two edits away: then
it is flagged with that name as a guess, ``name: Bohatec?``). The words themselves are
checked by ai-client's ``check.text``, on the body text without page marks, margin and
note references or styles: see its README), ``chars`` (odd letters: macrons outside
Latin, Cyrillic look-alikes, stray ``$``; not in bibliographies, indexes or ALL CAPS
words), ``note-no-ref``, ``ref-no-note``, ``margin-est`` (estimated margin references)
and ``margin-missing`` (labels missing between two found ones). Text the build left out
is listed too, set to ``ignore`` with status ``dropped``: ``greek-dropped`` (a Greek
paragraph in a bilingual edition, ``bilingual.drop_greek``).

A spelling row's ``type`` is its likely error, most reliable first (new rows are sorted
so): ``accent`` (one accent off; the fix is pre-filled as ``value``, set the action to
confirm it), ``swap`` (b read for h or c for e, "becho", "comcr": pre-filled too),
``seen: <word>?`` (corrected so before, in another book or to more than one word),
``ocr1: <word>?`` (one letter off: a guess), ``near: <word>?`` (close to a common
word), ``name`` / ``name: <name>?`` (capitalised) or ``unknown``.

Two kinds of check flags are applied without review, each written as a ``replace`` row
of type ``auto: split`` or ``auto: learned`` (set it to ``ignore`` to undo it): words
split in two ("inmor-talidad", "por ciones") and corrections learned from earlier
decisions. Every word row you decide (``replace``, ``ignore``) is recorded once in
ai-client's decisions on the next build, under the book's ``source`` (``check.record``).
"""

import csv
import os
import re
import tempfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path

from ai_client import check

from pdf_worker.inline import ESTIMATED, MARGIN_REF_RE, PAGE_MARK_RE, STYLE_RE, margin_ref, plain
from pdf_worker.margin_estimates import label_value, value_label
from pdf_worker.structure import REF_RE, Block, Heading, Note, Paragraph

SPELL_LANGUAGES = tuple(check.config.LANGUAGES)
WORD_KINDS = ("spelling", "chars")  # rows about a word: their decisions are recorded
AUTO = ("split", "learned")  # check flags applied without review
_MAX_SPELLING_COUNT = 2
_MAX_MISSING = 10  # more margin labels lost in a row: the found ones are suspect
_CONTEXT = 30  # characters each side
_FIND_CHARS = 60  # a left-out paragraph's row: its start
_SPLIT_RE = re.compile(f"({PAGE_MARK_RE.pattern})")
_MARKS_RE = re.compile(f"{PAGE_MARK_RE.pattern}|{MARGIN_REF_RE.pattern}|{STYLE_RE.pattern}")
# What the check never sees: page marks, margin and note references, styles.
_HIDDEN_RE = re.compile(f"{_MARKS_RE.pattern}|{REF_RE.pattern}")
_COUNT_RE = re.compile(r"^×\d+ ")  # a row's context starts with its count in the book
_WORD_RE = re.compile(r"[^\W\d_]+")
_MACRON_RE = re.compile("[āēīōūȳĀĒĪŌŪȲ]")
_CYRILLIC_RE = re.compile("[Ѐ-ӿ]")
_DOLLAR_RE = re.compile(r"\S*\$\S*")
_BACK_MATTER_RE = re.compile(r"bibliograf|[íi]ndice|\bindex\b|referencias|references", re.I)
_AUTHOR_ENTRY_RE = re.compile(r"[A-ZÀ-Þ][A-ZÀ-Þ'\- ]{2,},\s+[A-ZÀ-Þ][a-zà-ÿ]?\.")
_YEAR_RE = re.compile(r"\b1[5-9]\d\d\b")
# Whole word: a bibliography's "Capítulos I-II: ..." groups entries, it isn't a chapter.
_CHAPTER_RE = re.compile(r"(?:cap[íi]tulo|chapter|parte|part|libro|book)\b", re.I)
_MAX_REFERENCE = 300  # characters
_ADD_RE = re.compile(r"(\S+)\s+before\s+(.+)")


@dataclass
class Fix:
    id: str
    page: str
    kind: str
    find: str
    context: str = ""
    action: str = ""
    value: str = ""
    status: str = ""
    type: str = ""  # a spelling row's likely error: accent, ocr1 (with a guess), name...


COLUMNS = ("id", "page", "kind", "type", "find", "context", "action", "value", "status")
# Most reliable first.
SPELLING_TYPES = ("accent", "swap", "seen", "ocr1", "near", "name", "unknown")


def default_fixes_path(pdf_path: str | Path) -> Path:
    """``book.pdf`` and ``book.ocr.pdf`` -> ``book.fixes.tsv``."""
    pdf_path = Path(pdf_path)
    stem = re.sub(r"(?:\.ocr)+$", "", pdf_path.stem, flags=re.I)
    return pdf_path.with_name(f"{stem}.fixes.tsv")


def read_fixes(path: Path) -> list[Fix]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return [Fix(**{c: (row.get(c) or "").strip() for c in COLUMNS}) for row in rows]


def write_fixes(path: Path, fixes: list[Fix]) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(COLUMNS)
            writer.writerows([getattr(fix, c) for c in COLUMNS] for fix in fixes)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class Review:
    """Applies ``fixes`` to a stream of blocks and collects what looks wrong in it."""

    def __init__(self, fixes: list[Fix], language: str, spelling: bool = True, source: str = ""):
        """``spelling=False``: no word check. ``source`` names the book in ai-client's
        decisions (the review file's stem): without it, decisions are used but not recorded."""
        self.fixes = fixes
        self.lexicon = _words(language) if spelling and language in SPELL_LANGUAGES else None
        self.decisions = check.Decisions(language) if self.lexicon else None
        self.source = source
        self.language = language
        self.check_chars = language != "la"  # macrons are Latin
        self.page = ""
        self.hits = [0] * len(fixes)  # occurrences of each fix's target on its page
        self.done = [False] * len(fixes)
        self.known: set[str] = set()  # lowercase words never flagged: the user's own
        self.kept = {f.find for f in fixes if f.action == "ignore"}  # never flagged again
        self.by_page: dict[str, list[int]] = {}  # rows with an action, by page
        for i, fix in enumerate(fixes):
            if fix.action:
                self.by_page.setdefault(fix.page, []).append(i)
            if fix.action == "replace":  # the user's own words are right
                self.known.update(w.lower() for w in _WORD_RE.findall(fix.value))
        self.auto: list[Fix] = []  # check flags applied without review
        # (kind, key) -> [count, page, find, context, type, value]
        self.words: dict[tuple[str, str], list] = {}
        self.refs: dict[str, str] = {}  # note label -> page of its first reference
        self.notes: dict[str, str] = {}
        self.labels: list[tuple[str, str] | None] = []  # margin labels; None: a heading
        self.back: int | None = None  # level of the bibliography/index heading we're under
        self.body = True  # spelling is checked in the body text only
        self.reference = False  # bibliography/index: nothing is checked

    def apply(self, blocks: Iterable[Block]) -> Iterator[Block]:
        for block in blocks:
            if isinstance(block, Heading | Paragraph | Note):
                if isinstance(block, Heading):
                    self.labels.append(None)
                    self._section(block)
                self.reference = self.back is not None or _is_reference(block)
                self.body = not self.reference and not isinstance(block, Note)
                self.body = self.body and not getattr(block, "small", False)
                # Checked before the review file's rows apply, as those were written on
                # the checked text (split words already joined).
                text = self._check(block.text) if self.body and self.lexicon else block.text
                text = self._text(self._across_pages(text))
                if isinstance(block, Note):
                    self.notes.setdefault(block.label, self.page)
                if text != block.text:
                    block = replace(block, text=text)
            yield block

    def _across_pages(self, text: str) -> str:
        """A two-word find split by a page break ("def <page>niciones"), on the row's page
        or the one before: replaced here, as the pages are fixed one at a time later. The
        marks go before the new text."""
        if not PAGE_MARK_RE.search(text):
            return text
        for rows in self.by_page.values():
            for i in rows:
                fix = self.fixes[i]
                if fix.action != "replace" or " " not in fix.find or self.done[i]:
                    continue
                for m in _word_pattern(fix.find, pages=True).finditer(text):
                    mark = PAGE_MARK_RE.search(m.group())
                    before = PAGE_MARK_RE.findall(text[: m.start()])
                    if mark and fix.page in (
                        "*",
                        mark.group(1),
                        before[-1] if before else self.page,
                    ):
                        self.hits[i] += 1
                        self.done[i] = True
                        text = text[: m.start()] + _marks(m) + fix.value + text[m.end() :]
                        break
        return text

    def _check(self, text: str) -> str:
        """ai-client's check on a body block's words: split and learned flags applied (as
        ``auto`` rows), the others kept for review. Marks inside a fixed span go before it."""
        clean, at = _clean(text)
        flags = check.text(clean, self.lexicon, source=self.source, decisions=self.decisions)
        auto = []
        for flag in flags:
            find = flag.find
            if find in self.kept or find.lower() in self.known:
                continue
            if self.check_chars and (_MACRON_RE.search(find) or _CYRILLIC_RE.search(find)):
                continue  # a "chars" row
            page = _page_at(text, at[flag.start], self.page)
            context = " ".join(flag.context.split())
            if flag.kind in AUTO and flag.value:
                auto.append(flag)
                self.auto.append(
                    Fix(
                        "",
                        page,
                        "spelling",
                        find,
                        context,
                        "replace",
                        flag.value,
                        "applied",
                        f"auto: {flag.kind}",
                    )
                )
            elif flag.kind != "context":
                kind, value = _row_type(flag)
                entry = self.words.get(("spelling", find.lower()))
                if entry:
                    entry[0] += 1
                else:
                    self.words[("spelling", find.lower())] = [1, page, find, context, kind, value]
        for flag in sorted(auto, key=lambda f: f.start, reverse=True):
            start, end = at[flag.start], at[flag.end - 1] + 1
            marks = "".join(m.group() for m in _HIDDEN_RE.finditer(text, start, end))
            text = text[:start] + marks + flag.value + text[end:]
        return text

    def _section(self, heading: Heading) -> None:
        """A bibliography or index lasts until a higher heading, or one of its level that
        starts a chapter: OCR gives its subheadings ("Textos", "Estudios") the same level."""
        text = plain(heading.text)
        if _BACK_MATTER_RE.search(text):
            self.back = heading.level if self.back is None else min(self.back, heading.level)
        elif self.back is not None and (
            heading.level < self.back
            or (heading.level == self.back and (self.back == 1 or _CHAPTER_RE.match(text)))
        ):
            self.back = None

    def _text(self, text: str) -> str:
        parts = _SPLIT_RE.split(text)  # text, mark, label, text, mark, label, ...
        out = []
        for i in range(0, len(parts), 3):
            if i:
                out.append(parts[i - 2])
                self.page = parts[i - 1]
            segment = self._fix(parts[i])
            self._scan(segment)
            out.append(segment)
        return "".join(out)

    def _fix(self, text: str) -> str:
        for i in self.by_page.get(self.page, []) + self.by_page.get("*", []):
            if text:
                text = self._apply(i, self.fixes[i], text)
        return text

    def _apply(self, i: int, fix: Fix, text: str) -> str:
        everywhere = fix.page == "*"
        action = fix.action
        if action in ("replace", "ignore"):
            pattern = _word_pattern(fix.find)
            found = len(pattern.findall(text))
            self.hits[i] += found
            if action == "ignore" or not found or (self.done[i] and not everywhere):
                self.done[i] = self.done[i] or bool(found)
                return text
            self.done[i] = True
            # Margin references inside a two-word find go before the new text.
            return pattern.sub(lambda m: _marks(m) + fix.value, text, count=0 if everywhere else 1)
        if action == "drop":
            return self._remove(i, text, f"[^{fix.find}]", "", everywhere)
        if action == "accept":
            new = margin_ref(fix.find.removeprefix(ESTIMATED))
            return self._remove(i, text, margin_ref(fix.find), new, everywhere)
        if action == "attach":
            return self._insert(i, text, fix.value, f"[^{fix.find}]", after=True)
        if action == "move":
            label = fix.find.removeprefix(ESTIMATED)
            text = text.replace(margin_ref(fix.find), "")
            return self._insert(i, text, fix.value, margin_ref(label), after=False)
        if action == "add" and (match := _ADD_RE.fullmatch(fix.value.strip('"'))):
            return self._insert(i, text, match.group(2), margin_ref(match.group(1)), after=False)
        return text

    def _remove(self, i: int, text: str, old: str, new: str, everywhere: bool) -> str:
        found = text.count(old)
        self.hits[i] += found
        if not found or (self.done[i] and not everywhere):
            return text
        self.done[i] = True
        return text.replace(old, new, -1 if everywhere else 1)

    def _insert(self, i: int, text: str, word: str, mark: str, after: bool) -> str:
        matches = list(_word_pattern(word).finditer(text)) if word else []
        self.hits[i] += len(matches)
        if not matches or self.done[i]:
            return text
        self.done[i] = True
        at = matches[0].end() if after else matches[0].start()
        return text[:at] + mark + text[at:]

    def _scan(self, text: str) -> None:
        for match in REF_RE.finditer(text):
            self.refs.setdefault(match.group(1), self.page)
        for label in MARGIN_REF_RE.findall(text):
            self.labels.append((label, self.page))
        words = REF_RE.sub("", plain(text))
        for match in _DOLLAR_RE.finditer(words if not self.reference else ""):
            self._flag("chars", match.group(), words, match)
        for match in _WORD_RE.finditer(words):
            word = match.group()
            if self.reference or (len(word) > 1 and word.isupper()):
                continue  # ALL CAPS (headings, small caps) is never flagged: user's choice
            if self.check_chars and (_MACRON_RE.search(word) or _CYRILLIC_RE.search(word)):
                self._flag("chars", word, words, match)

    def _flag(self, kind: str, find: str, text: str, match: re.Match) -> None:
        entry = self.words.get((kind, find))
        if entry:
            entry[0] += 1
            return
        context = text[max(0, match.start() - _CONTEXT) : match.end() + _CONTEXT]
        self.words[(kind, find)] = [1, self.page, find, " ".join(context.split()), "", ""]

    def finish(self, on_word: Callable[[int, int], None] | None = None) -> dict[str, int]:
        """Set each row's status and append what was found; returns new rows per kind.
        ``on_word(done, total)`` follows the words flagged."""
        found = self._found(on_word)
        keys = {(f.kind, f.find, f.page) for f in found}
        for i, fix in enumerate(self.fixes):
            if not fix.action:
                fix.status = "" if (fix.kind, fix.find, fix.page) in keys else "stale"
            elif not self.done[i]:
                fix.status = "stale"
            else:
                ambiguous = fix.page != "*" and self.hits[i] > 1
                fix.status = "ambiguous" if ambiguous else "applied"
        self._record()
        covered = {(f.kind, f.find, f.page) for f in self.fixes}
        next_id = max((int(f.id) for f in self.fixes if f.id.isdigit()), default=0) + 1
        added: dict[str, int] = {}
        for fix in found + self.auto:
            if {(fix.kind, fix.find, fix.page), (fix.kind, fix.find, "*")} & covered:
                continue
            covered.add((fix.kind, fix.find, fix.page))
            fix.id = str(next_id)
            next_id += 1
            self.fixes.append(fix)
            kind = fix.type if fix.type.startswith("auto") else fix.kind
            added[kind] = added.get(kind, 0) + 1
        return added

    def _record(self) -> None:
        """Each word row the user decided, recorded once in ai-client's decisions for
        this book: ``replace`` as accepted, ``ignore`` as kept (the text was right)."""
        if self.decisions is None or not self.source:
            return
        for fix in self.fixes:
            accepted = fix.action == "replace"
            if (
                fix.kind not in WORD_KINDS
                or fix.action not in ("replace", "ignore")
                or fix.type.startswith("auto")
                or (accepted and not fix.value)
            ):
                continue
            value = fix.value if accepted else fix.find
            history = self.decisions.history[fix.find]
            if history[self.source, value]:
                continue
            history[self.source, value] += 1
            context = _COUNT_RE.sub("", fix.context)
            flag = check.Flag(fix.kind, 0, len(fix.find), fix.find, fix.value, context, "")
            check.record(
                flag, accepted, self.source, self.language, value=fix.value if accepted else None
            )

    def left_out(self, kind: str, items: list[tuple[str, str]]) -> int:
        """List text the build left out, ``(page, text)``, as rows set to ``ignore``: there
        to check, never sent for review. Call after ``finish``; returns the new rows."""
        rows = {(kind, text[:_FIND_CHARS], page): text for page, text in items}
        for fix in self.fixes:
            if (fix.kind, fix.find, fix.page) in rows:
                fix.status = "dropped"
                del rows[(fix.kind, fix.find, fix.page)]
        next_id = max((int(f.id) for f in self.fixes if f.id.isdigit()), default=0) + 1
        for n, ((_, find, page), text) in enumerate(rows.items()):
            context = text[: 2 * _CONTEXT]
            self.fixes.append(
                Fix(str(next_id + n), page, kind, find, context, "ignore", "", "dropped")
            )
        return len(rows)

    def _found(self, on_word: Callable[[int, int], None] | None = None) -> list[Fix]:
        found = []
        # Capitalised flagged words with their count over the whole book.
        names = {
            e[2]: e[0]
            for (kind, _), e in self.words.items()
            if kind == "spelling" and _is_name(e[2])
        }
        for i, ((kind, _), (count, page, find, context, type_, value)) in enumerate(
            self.words.items()
        ):
            if on_word:
                on_word(i, len(self.words))
            if kind == "spelling" and count > _MAX_SPELLING_COUNT:
                continue
            near = _near_name(find, count, names) if find in names else ""
            if find in names and count > 1 and not near and type_ != "accent":
                continue  # a name the book repeats is spelled as printed
            if near and type_.split(":")[0] in ("name", "unknown"):
                type_ = f"name: {near}?"
            context = f"×{count} {context}" if count > 1 else context
            found.append(Fix("", page, kind, find, context, value=value, type=type_))
        if on_word:
            on_word(len(self.words), len(self.words))
        # A reference whose note wasn't found ("o168-1") has a stand-in note: it is a
        # reference with no note, and its stand-in alone (its reference dropped with a
        # running head) is nothing.
        found += [
            Fix("", p, "note-no-ref", n)
            for n, p in self.notes.items()
            if n not in self.refs and not n.startswith("o")
        ]
        found += [
            Fix("", p, "ref-no-note", r)
            for r, p in self.refs.items()
            if r not in self.notes or r.startswith("o")
        ]
        found += [
            Fix("", page, "margin-est", label)
            for label, page in filter(None, self.labels)
            if label.startswith(ESTIMATED)
        ]
        previous = None
        for entry in self.labels:
            value = label_value(entry[0].removeprefix(ESTIMATED)) if entry else None
            if entry is None or value is None:
                previous = None if entry is None else previous
                continue
            if previous and 0 < value - previous[0] - 1 <= _MAX_MISSING:
                first, last = value_label(previous[0] + 1), value_label(value - 1)
                span = first if first == last else f"{first}..{last}"
                found.append(Fix("", previous[1], "margin-missing", span))
            previous = (value, entry[1])
        # Spelling rows last, the likeliest errors first; page order within each.
        return sorted(
            found, key=lambda f: SPELLING_TYPES.index(f.type.split(":")[0]) + 1 if f.type else 0
        )


def _is_reference(block: Block) -> bool:
    """A bibliography entry: "MAIGRON, L., Le roman ...", or a short line with a year and
    several commas ("Gesammelte Schriften, 6 vols., Halle, 1775")."""
    if not isinstance(block, Paragraph):
        return False
    text = plain(block.text).strip()
    if _AUTHOR_ENTRY_RE.match(text):
        return True
    return len(text) < _MAX_REFERENCE and bool(_YEAR_RE.search(text)) and text.count(",") >= 3


@cache
def _words(language: str) -> check.Words:
    """Loaded once per language (a few seconds), for all the books of a run."""
    return check.Words(language)


def _clean(text: str) -> tuple[str, list[int]]:
    """``text`` without the marks the check mustn't see, and where each of its characters
    is in ``text``."""
    at: list[int] = []
    last = 0
    for match in _HIDDEN_RE.finditer(text):
        at += range(last, match.start())
        last = match.end()
    at += range(last, len(text))
    return "".join(text[i] for i in at), at


def _page_at(text: str, index: int, page: str) -> str:
    """The page at ``index`` of a block: its last page mark before it, else ``page``."""
    marks = PAGE_MARK_RE.findall(text, 0, index)
    return marks[-1] if marks else page


def _row_type(flag: check.Flag) -> tuple[str, str]:
    """A check flag's row ``(type, value)``: a likely fix (accent, swap) is pre-filled, a
    guess is given in the type only."""
    if flag.kind == "seen":
        return f"seen: {flag.value}?", ""
    if flag.how in ("accent", "swap"):
        return flag.how, flag.value
    if flag.how == "edit":
        return f"ocr1: {flag.value}?", ""
    if flag.how == "near":
        return f"{'name' if flag.kind == 'name' else 'near'}: {flag.value}?", ""
    return ("name" if _is_name(flag.find) else "unknown"), ""


def _is_name(word: str) -> bool:
    return word[0].isupper() and word[1:].islower()


def _near_name(word: str, count: int, names: dict[str, int]) -> str:
    """A more frequent name one edit away (two from 5 letters): "Bohatcc" -> "Bohatec"."""
    most = 1 if len(word) < 5 else 2
    # shortcut: same first letter only (keeps this fast), misses a misread first letter.
    near = [
        n
        for n, c in names.items()
        if c > count
        and n[0] == word[0]
        and abs(len(n) - len(word)) <= most
        and _distance(word, n) <= most
    ]
    return max(near, key=names.get, default="")


def _distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def _word_pattern(text: str, pages: bool = False) -> re.Pattern:
    """``text`` as written, not inside a longer word. A margin reference (or with
    ``pages``, a page mark) may sit between two words ("def <21a>niciones")."""
    start = r"(?<!\w)" if text[:1].isalnum() else ""
    end = r"(?!\w)" if text[-1:].isalnum() else ""
    marks = _MARKS_RE.pattern if pages else f"{MARGIN_REF_RE.pattern}|{STYLE_RE.pattern}"
    gap = f"(?: |{marks})+"
    return re.compile(start + gap.join(map(re.escape, text.split(" "))) + end)


def _marks(match: re.Match) -> str:
    """The page marks and margin references inside a match, to keep before new text."""
    return "".join(m.group() for m in _MARKS_RE.finditer(match.group()))

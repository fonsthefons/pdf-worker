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
small print, bibliographies or indexes; words found at most twice in the book, unknown
to the Hunspell dictionary (and to ``dictionaries/es.extra.txt``), and not
English/German/French/Italian/Latin words of 5+ letters), ``chars`` (odd letters:
macrons outside Latin, Cyrillic look-alikes, stray ``$``), ``note-no-ref``,
``ref-no-note``, ``margin-est`` (estimated margin references) and ``margin-missing``
(labels missing between two found ones).

A spelling row's ``type`` is its likely error, most reliable first (new rows are sorted
so): ``accent`` (one accent off; the fix is pre-filled as ``value``, set the action to
confirm it), ``ocr1: <word>?`` (one letter off: a guess), ``name`` (capitalised) or
``unknown``. Words split at a line break ("inmor-talidad", "por ciones") are joined
before the check when the joined word is known.
"""

import csv
import os
import re
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path

from pdf_worker.inline import ESTIMATED, MARGIN_REF_RE, PAGE_MARK_RE, margin_ref, plain
from pdf_worker.margin_estimates import label_value, value_label
from pdf_worker.structure import REF_RE, Block, Heading, Note, Paragraph

SPELL_LANGUAGES = ("es", "en")
# Words these know are never flagged in a book of another language.
FOREIGN_LANGUAGES = ("en", "de", "fr", "it", "la")
# Hunspell dictionaries, read by spylls: es_ES and en_US from LibreOffice; de, fr, it,
# la from wooorm/dictionaries (licence files alongside).
_DICTIONARIES = Path(__file__).parent / "dictionaries"
_MAX_SPELLING_COUNT = 2
_MIN_FOREIGN = 5  # letters: shorter words aren't excused by the foreign dictionaries
_MAX_MISSING = 10  # more margin labels lost in a row: the found ones are suspect
_CONTEXT = 30  # characters each side
_SPLIT_RE = re.compile(f"({PAGE_MARK_RE.pattern})")
# A word, a line-break hyphen or space, marks; the next word is only looked at, so it can
# pair with the one after it in turn.
_SPLIT_WORD_RE = re.compile(
    r"(?<![\w-])(?P<first>[^\W\d_]+)(?:- ?| )"
    f"(?P<marks>(?:{PAGE_MARK_RE.pattern}|{MARGIN_REF_RE.pattern})*)"
    r"(?=(?P<second>[^\W\d_]+)(?![\w-]))"
)
_WORD_RE = re.compile(r"[^\W\d_]+")
_LATIN_RE = re.compile(r"[A-Za-zÀ-ɏ]+")
_MACRON_RE = re.compile("[āēīōūȳĀĒĪŌŪȲ]")
_CYRILLIC_RE = re.compile("[Ѐ-ӿ]")
_DOLLAR_RE = re.compile(r"\S*\$\S*")
_BACK_MATTER_RE = re.compile(r"bibliograf|[íi]ndice|\bindex\b|referencias|references", re.I)
_AUTHOR_ENTRY_RE = re.compile(r"[A-ZÀ-Þ][A-ZÀ-Þ'\- ]{2,},\s+[A-ZÀ-Þ][a-zà-ÿ]?\.")
_YEAR_RE = re.compile(r"\b1[5-9]\d\d\b")
_MAX_REFERENCE = 300  # characters
_ADD_RE = re.compile(r"(\S+)\s+before\s+(.+)")
# Infinitive or gerund + one or two pronouns: basarlo, evitarle, basándoselo.
_ENCLITIC_RE = re.compile(r"(.+(?:r|ndo))(?:[mts]e|nos|os|l[aeo]s?){1,2}")
_UNACCENT = str.maketrans("áéíóú", "aeiou")
_SUPERLATIVE_RE = re.compile(r"(.+)ísim[oa]s?")
# Words es_ES lacks that books use (lowercase, one per line).
_SPANISH_EXTRA = set((_DICTIONARIES / "es.extra.txt").read_text(encoding="utf-8").lower().split())
_ACCENTS = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "úü", "n": "ñ"}
_ACCENTS |= {v: k for k, vs in _ACCENTS.items() for v in vs}  # and back
_LETTERS = "abcdefghijklmnopqrstuvwxyzáéíóúüñ"
# OCR misreadings of letter shapes ("rn" for "m"), tried before the one-letter edits.
_CONFUSIONS = (("rn", "m"), ("m", "rn"), ("cl", "d"), ("li", "h"), ("ni", "m"), ("in", "m"))


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
SPELLING_TYPES = ("accent", "ocr1", "name", "unknown")  # most reliable first


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

    def __init__(self, fixes: list[Fix], language: str):
        self.fixes = fixes
        self.spell = None
        if language in SPELL_LANGUAGES:
            from spylls.hunspell import Dictionary

            self.spell = Dictionary.from_files(str(_DICTIONARIES / language))
        self.language = language
        self.spanish = language == "es"
        self.check_chars = language != "la"  # macrons are Latin
        self.page = ""
        self.hits = [0] * len(fixes)  # occurrences of each fix's target on its page
        self.done = [False] * len(fixes)
        self.known: dict[str, bool] = {}  # lowercase word -> not to be flagged
        self.spelled: dict[str, bool] = {}  # word -> in the book's dictionary
        self.by_page: dict[str, list[int]] = {}  # rows with an action, by page
        for i, fix in enumerate(fixes):
            if fix.action:
                self.by_page.setdefault(fix.page, []).append(i)
            if fix.action == "replace":  # the user's own words are right
                self.known.update((w.lower(), True) for w in _WORD_RE.findall(fix.value))
        self.words: dict[tuple[str, str], list] = {}  # (kind, key) -> [count, page, find, ctx]
        self.refs: dict[str, str] = {}  # note label -> page of its first reference
        self.notes: dict[str, str] = {}
        self.labels: list[tuple[str, str] | None] = []  # margin labels; None: a heading
        self.back: int | None = None  # level of the bibliography/index heading we're under
        self.body = True  # spelling is checked in the body text only

    def apply(self, blocks: Iterable[Block]) -> Iterator[Block]:
        for block in blocks:
            if isinstance(block, Heading | Paragraph | Note):
                if isinstance(block, Heading):
                    self.labels.append(None)
                    self._section(block)
                self.body = self.back is None and not isinstance(block, Note)
                self.body = self.body and not getattr(block, "small", False)
                self.body = self.body and not _is_reference(block)
                text = self._text(self._join_split(block.text) if self.spell else block.text)
                if isinstance(block, Note):
                    self.notes.setdefault(block.label, self.page)
                if text != block.text:
                    block = replace(block, text=text)
            yield block

    def _join_split(self, text: str) -> str:
        """Join a word the OCR split at a line break ("inmor-talidad", "invo- car",
        "por ciones"): when the joined word is known and a part is not ("cosa-en-sí",
        "físico-químico" stay). Page marks and margin references go before it."""

        def join(match: re.Match) -> str:
            first, second = match["first"], match["second"]
            if (
                second[0].islower()
                and not (self._spelled(first) and self._spelled(second))
                and self._spelled(first + second)
            ):
                return match["marks"] + first
            return match.group()

        return _SPLIT_WORD_RE.sub(join, text)

    def _spelled(self, word: str) -> bool:
        if word not in self.spelled:
            self.spelled[word] = _knows(self.spell, word, self.spanish)
        return self.spelled[word]

    def _section(self, heading: Heading) -> None:
        """A bibliography or index lasts until a heading of its level or higher."""
        if _BACK_MATTER_RE.search(plain(heading.text)):
            self.back = heading.level if self.back is None else min(self.back, heading.level)
        elif self.back is not None and heading.level <= self.back:
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
            return pattern.sub(lambda _: fix.value, text, count=0 if everywhere else 1)
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
        for match in _DOLLAR_RE.finditer(words):
            self._flag("chars", match.group(), words, match)
        for match in _WORD_RE.finditer(words):
            word = match.group()
            if self.check_chars and (_MACRON_RE.search(word) or _CYRILLIC_RE.search(word)):
                self._flag("chars", word, words, match)
            elif self.body and self.spell and len(word) > 2 and _LATIN_RE.fullmatch(word):
                key = word.lower()
                if key not in self.known:
                    self.known[key] = self._spelled(word) or (
                        len(word) >= _MIN_FOREIGN and any(_knows(d, word) for d in self.foreign)
                    )
                if not self.known[key]:
                    self._flag("spelling", word, words, match, key)

    @cached_property
    def foreign(self) -> list:
        """Quoted foreign titles and phrases are common; short words stay checked, they
        may be misreadings ("ban" for "han"). Loaded on first use (a few seconds)."""
        from spylls.hunspell import Dictionary

        return [
            Dictionary.from_files(str(_DICTIONARIES / other))
            for other in FOREIGN_LANGUAGES
            if other != self.language
        ]

    def _flag(self, kind: str, find: str, text: str, match: re.Match, key: str = "") -> None:
        entry = self.words.get((kind, key or find))
        if entry:
            entry[0] += 1
            return
        context = text[max(0, match.start() - _CONTEXT) : match.end() + _CONTEXT]
        self.words[(kind, key or find)] = [1, self.page, find, " ".join(context.split())]

    def finish(self) -> dict[str, int]:
        """Set each row's status and append what was found; returns new rows per kind."""
        found = self._found()
        keys = {(f.kind, f.find, f.page) for f in found}
        for i, fix in enumerate(self.fixes):
            if not fix.action:
                fix.status = "" if (fix.kind, fix.find, fix.page) in keys else "stale"
            elif not self.done[i]:
                fix.status = "stale"
            else:
                ambiguous = fix.page != "*" and self.hits[i] > 1
                fix.status = "ambiguous" if ambiguous else "applied"
        covered = {(f.kind, f.find, f.page) for f in self.fixes}
        next_id = max((int(f.id) for f in self.fixes if f.id.isdigit()), default=0) + 1
        added: dict[str, int] = {}
        for fix in found:
            if {(fix.kind, fix.find, fix.page), (fix.kind, fix.find, "*")} & covered:
                continue
            fix.id = str(next_id)
            next_id += 1
            self.fixes.append(fix)
            added[fix.kind] = added.get(fix.kind, 0) + 1
        return added

    def _found(self) -> list[Fix]:
        found = []
        for (kind, _), (count, page, find, context) in self.words.items():
            if kind == "spelling" and count > _MAX_SPELLING_COUNT:
                continue
            fix = Fix("", page, kind, find, f"×{count} {context}" if count > 1 else context)
            if kind == "spelling":
                fix.type, fix.value = self._spelling_type(find)
            found.append(fix)
        found += [Fix("", p, "note-no-ref", n) for n, p in self.notes.items() if n not in self.refs]
        found += [Fix("", p, "ref-no-note", r) for r, p in self.refs.items() if r not in self.notes]
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

    def _spelling_type(self, word: str) -> tuple[str, str]:
        """``(type, value)``: a one-accent fix is pre-filled as the value (the user still
        sets the action); a one-edit word is only a guess, given in the type."""
        low = word.lower()
        fix = next((w for w in _accent_variants(low) if self._spelled(w)), "")
        if fix:
            return "accent", fix[0].upper() + fix[1:] if word[0].isupper() else fix
        # Plain lookups: this tries hundreds of words.
        fix = next((w for w in _one_edits(low) if self.spell.lookup(w)), "")
        if fix:
            return f"ocr1: {fix}?", ""
        if word[0].isupper() and word[1:].islower():
            return "name", ""
        return "unknown", ""


def _is_reference(block: Block) -> bool:
    """A bibliography entry: "MAIGRON, L., Le roman ...", or a short line with a year and
    several commas ("Gesammelte Schriften, 6 vols., Halle, 1775")."""
    if not isinstance(block, Paragraph):
        return False
    text = plain(block.text).strip()
    if _AUTHOR_ENTRY_RE.match(text):
        return True
    return len(text) < _MAX_REFERENCE and bool(_YEAR_RE.search(text)) and text.count(",") >= 3


def _knows(dictionary, word: str, spanish: bool = False) -> bool:
    if dictionary.lookup(word) or dictionary.lookup(word.lower()):
        return True
    if not spanish:
        return False
    low = word.lower()
    if low in _SPANISH_EXTRA:
        return True
    # es_ES lists which pronouns each verb takes ("basarlo" is missing); books needn't agree.
    verb = _ENCLITIC_RE.fullmatch(low)
    if verb and any(dictionary.lookup(v) for v in (verb[1], verb[1].translate(_UNACCENT))):
        return True
    # Superlatives: correctísima, larguísimo, riquísimos.
    stem = (match := _SUPERLATIVE_RE.fullmatch(low)) and match[1]
    if not stem:
        return False
    stem = stem[:-2] + "c" if stem.endswith("qu") else stem[:-1] if stem.endswith("gu") else stem
    return any(dictionary.lookup(stem + end) for end in ("o", "e", ""))


def _accent_variants(word: str) -> Iterator[str]:
    """``word`` with one accent added or taken away (pudieramos -> pudiéramos)."""
    for i, c in enumerate(word):
        for alt in _ACCENTS.get(c, ""):
            yield word[:i] + alt + word[i + 1 :]


def _one_edits(word: str) -> Iterator[str]:
    """``word`` with one letter dropped, changed or added, or a common misreading undone."""
    for x, y in _CONFUSIONS:
        if x in word:
            yield word.replace(x, y, 1)
    for i in range(len(word) + 1):
        a, b = word[:i], word[i:]
        if b:
            yield a + b[1:]
            yield from (a + c + b[1:] for c in _LETTERS if c != b[0])
        yield from (a + c + b for c in _LETTERS)


def _word_pattern(text: str) -> re.Pattern:
    """``text`` as written, not inside a longer word."""
    start = r"(?<!\w)" if text[:1].isalnum() else ""
    end = r"(?!\w)" if text[-1:].isalnum() else ""
    return re.compile(start + re.escape(text) + end)

"""Score a whole converted book (our Markdown) against a reference of the same text
(docs/quality-plan.md, Phase 1).

Usage:
  .venv/bin/python tools/book_score.py REFERENCE OURS.md [--collected]
  (REFERENCE: .epub or .txt; --collected: it holds more than our book)
  .venv/bin/python tools/book_score.py selftest

The two are aligned as word sequences (lower case, punctuation off): anchors are word
5-grams that occur once in each, kept in order (longest increasing run), and ``difflib``
between anchors (a gap too big for it gets anchors of its own, unique within the gap).
When the reference marks its notes, its body is aligned with our text without our
``[^n]:`` notes, then each reference note on its own with the words of ours left over,
so a note counts wherever we put it. Only the reference between its first and last
anchor counts (another edition may add front or back matter), and only our words between
our first and last anchor. A stretch of over 1,000 of our words with under a tenth of
that in the reference is left out too (an index the reference lacks), and the same the
other way round with ``--collected`` (the rest of a collected edition). A note
counts when an anchor finds it in ours or it sits inside the counted body.

Measures (``score`` returns the counts; ``tools/quality.py`` turns them into rates):
- words: reference words matched and missing, our extra words;
- headings (references with ``h1``-``h6``): a reference heading is found when 80% of its
  words align into our ``#`` lines; one whose words align nowhere doesn't count. Ours is
  real when 80% of its words align into reference headings. Levels: pairs of found
  headings ranked as in the reference (as ``headings_test.py``);
- breaks: each body paragraph's first word aligned into the other's body; a reference
  break is found when its partner starts one of our paragraphs, ours is real when its
  partner starts a reference paragraph. Headings and notes left out;
- notes (references that mark notes: ``aside``, ``epub:type`` note, or the target of a
  link reading "1", "[1]", "*"): reference note words aligned into our text rather than
  our ``[^n]:`` notes;
- leftovers: runs of our extra words with nothing missing in the reference there (pure
  insertions) that are a bare number (page numbers) or, 5 letters or more, repeat 3 or
  more times (running heads), counted per run.
"""

import json
import posixpath
import re
import sys
import unicodedata
import zipfile
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from html.parser import HTMLParser
from itertools import combinations
from pathlib import Path
from xml.etree import ElementTree

from regression import _blocks, _write_atomic

ROOT = Path(__file__).resolve().parent.parent
BODY, HEADING, NOTE = 0, 1, 2
N = 5  # anchor length in words
GAP_LIMIT = 2_000_000  # len(a) * len(b) above which a gap gets anchors of its own
EDGE_GAP, EDGE_WORDS = 1000, 200  # words: see _trim
FOUND = 0.8  # share of a heading's words that must align
HEAD_LETTERS = 5  # a repeated insertion shorter than this is a stray word, not a head
_WORD_RE = re.compile(r"[^\W_]+")
_MARKER_RE = re.compile(r"^\s*[\[(]?\s*(?:\d{1,4}|[*†‡§]+)\s*[\])]?\s*$")
_LINK_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S | re.I)
_NOTE_TYPES = {"footnote", "endnote", "rearnote", "note", "footnotes", "endnotes", "rearnotes"}
_SKIP_TYPES = {"pagebreak", "toc", "landmarks", "page-list"}
_BLOCKS = {
    "p", "div", "li", "blockquote", "aside", "td", "th", "dd", "dt", "pre", "section",
    "article", "table", "tr", "ul", "ol", "body", "figure", "figcaption", "header",
    "footer", "nav", "h1", "h2", "h3", "h4", "h5", "h6",
}  # fmt: skip
_VOID = {"br", "img", "hr", "meta", "link", "input", "col", "area", "base", "wbr", "source"}
_MD_NOTE_RE = re.compile(r"^\[\^[^\]]+\]:")
_MD_NOTEREF_RE = re.compile(r"\[\^[^\]]+\]")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\]\([^)]*\)")


def words(text: str) -> list[str]:
    return _WORD_RE.findall(unicodedata.normalize("NFKC", text).lower())


@dataclass
class Text:
    """A book as words: each word's kind (BODY, HEADING, NOTE), its block (paragraph,
    heading or note; -1 for none) and its heading's index in ``headings`` (-1)."""

    words: list[str] = field(default_factory=list)
    kind: list[int] = field(default_factory=list)
    block: list[int] = field(default_factory=list)
    head: list[int] = field(default_factory=list)
    headings: list[tuple[int, str]] = field(default_factory=list)  # (level, text)
    blocks: int = 0

    def add(self, ws: list[str], kind: int, block: int, head: int = -1) -> None:
        self.words += ws
        self.kind += [kind] * len(ws)
        self.block += [block] * len(ws)
        self.head += [head] * len(ws)


# --- reading ---------------------------------------------------------------------------


def read_markdown(path: Path) -> Text:
    out = Text()
    current = None  # (kind, block, head) of the open paragraph or note
    for block in _blocks(path):
        current = None
        for line in block.split("\n"):
            if line.startswith("!["):
                continue
            text = _MD_LINK_RE.sub("]", _MD_IMAGE_RE.sub(" ", line))
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                out.headings.append((level, line.lstrip("#").strip()))
                current = (HEADING, out.blocks, len(out.headings) - 1)
                out.blocks += 1
                text = text.lstrip("#")
                out.add(words(_MD_NOTEREF_RE.sub(" ", text)), *current)
                current = None  # a heading is one line
                continue
            if _MD_NOTE_RE.match(line):
                current = (NOTE, out.blocks, -1)
                out.blocks += 1
                text = _MD_NOTE_RE.sub(" ", text)
            elif current is None:
                current = (BODY, out.blocks, -1)
                out.blocks += 1
            out.add(words(_MD_NOTEREF_RE.sub(" ", text.lstrip("> "))), *current)
    return out


def read_txt(path: Path) -> Text:
    out = Text()
    paragraph: list[str] = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in [*f, ""]:
            if line.strip():
                paragraph.append(line)
            elif paragraph:
                out.add(words(" ".join(paragraph)), BODY, out.blocks)
                out.blocks += 1
                paragraph = []
    return out


def _spine(z: zipfile.ZipFile) -> list[str]:
    container = ElementTree.fromstring(z.read("META-INF/container.xml"))
    opf = next(e.get("full-path") for e in container.iter() if e.tag.endswith("rootfile"))
    root = ElementTree.fromstring(z.read(opf))
    base = posixpath.dirname(opf)
    items = {
        e.get("id"): (e.get("href"), e.get("properties") or "")
        for e in root.iter()
        if e.tag.endswith("}item") or e.tag == "item"
    }
    docs = []
    for e in root.iter():
        if e.tag.endswith("itemref") and e.get("idref") in items:
            href, props = items[e.get("idref")]
            if "nav" not in props.split():
                docs.append(posixpath.normpath(posixpath.join(base, href)))
    return docs


def _target(doc: str, href: str) -> str | None:
    if "#" not in href:
        return None
    file, _, anchor = href.partition("#")
    file = posixpath.normpath(posixpath.join(posixpath.dirname(doc), file)) if file else doc
    return f"{file}#{anchor}"


def _note_targets(z: zipfile.ZipFile, docs: list[str]) -> set[str]:
    """``doc#id`` of every note: targets of links marked noteref or reading like a
    note marker ("1", "[1]", "*")."""
    targets = set()
    for doc in docs:
        html = z.read(doc).decode("utf-8", "replace")
        for attrs, text in _LINK_RE.findall(html):
            href = re.search(r'href="([^"]*)"', attrs)
            marker = "noteref" in attrs or _MARKER_RE.match(re.sub(r"<[^>]+>", "", text))
            if href and marker and (target := _target(doc, href.group(1))):
                targets.add(target)
    return targets


class _Html(HTMLParser):
    def __init__(self, doc: str, targets: set[str], out: Text):
        super().__init__(convert_charrefs=True)
        self.doc, self.targets, self.out = doc, targets, out
        self.stack: list[list] = []  # [tag, note, skip, heading index or -1]
        self.text: list[str] = []  # the open block's text, inline tags joined
        self.link: tuple[int, str] | None = None  # (len(self.text) before it, its text)

    def flush(self) -> None:
        """The text since the last block tag, as one block; read as the stack is now,
        so a note anchor found inside a paragraph makes all of it a note."""
        text, self.text = "".join(self.text), []
        ws = words(text)
        if not ws:
            return
        heads = [entry[3] for entry in self.stack if entry[3] >= 0]
        kind = NOTE if any(e[1] for e in self.stack) else HEADING if heads else BODY
        head = heads[-1] if kind == HEADING else -1
        if head >= 0:
            level, old = self.out.headings[head]
            self.out.headings[head] = (level, " ".join(f"{old} {text}".split()))
        self.out.add(ws, kind, self.out.blocks, head)
        self.out.blocks += 1

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCKS:
            self.flush()
        elif tag == "br":
            self.text.append(" ")
        a = {k: v or "" for k, v in attrs}
        types = set(a.get("epub:type", "").split())
        note = tag == "aside" or bool(types & _NOTE_TYPES)
        skip = (
            bool(types & _SKIP_TYPES)
            or "pagenum" in a.get("class", "")
            or tag in ("script", "style", "head")
        )
        # (A link's own id is where a note's back link points: the marker, not a note.)
        target = not (tag == "a" and a.get("href"))
        if target and a.get("id") and f"{self.doc}#{a['id']}" in self.targets:
            if tag in _BLOCKS:
                note = True
            else:  # the note's anchor inside it: its paragraph is the note
                for entry in reversed(self.stack):
                    if entry[0] in _BLOCKS:
                        entry[1] = True
                        break
        if tag == "a" and "#" in a.get("href", ""):
            self.link = (len(self.text), "")
        head = -1
        if re.fullmatch(r"h[1-6]", tag):
            self.out.headings.append((int(tag[1]), ""))
            head = len(self.out.headings) - 1
        if tag not in _VOID:
            self.stack.append([tag, note, skip, head])

    def handle_endtag(self, tag):
        if tag == "a" and self.link:
            start, text = self.link
            if _MARKER_RE.match(text) or not words(text):  # a note marker or a back link
                del self.text[start:]
            self.link = None
        if tag in _BLOCKS:
            self.flush()
        if any(entry[0] == tag for entry in self.stack):
            while self.stack.pop()[0] != tag:
                pass

    def handle_data(self, data):
        if self.link:
            self.link = (self.link[0], self.link[1] + data)
        if not any(entry[2] for entry in self.stack):
            self.text.append(data)


def read_epub(path: Path) -> Text:
    out = Text()
    with zipfile.ZipFile(path) as z:
        docs = _spine(z)
        targets = _note_targets(z, docs)
        for doc in docs:
            parser = _Html(doc, targets, out)
            parser.feed(z.read(doc).decode("utf-8", "replace"))
            parser.close()
            parser.flush()
    return out


def read_reference(path: Path) -> Text:
    return read_txt(path) if path.suffix.lower() == ".txt" else read_epub(path)


# --- alignment -------------------------------------------------------------------------


def _unique(ws: list[str], n: int) -> dict[tuple, int]:
    seen: dict[tuple, int] = {}
    for i in range(len(ws) - n + 1):
        gram = tuple(ws[i : i + n])
        seen[gram] = -1 if gram in seen else i
    return seen


def _increasing(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The longest run of ``pairs`` (sorted by their first) increasing in their second."""
    tails: list[int] = []  # second value ending the best run of each length
    ends: list[int] = []  # index in pairs of that end
    back = [-1] * len(pairs)
    for k, (_, j) in enumerate(pairs):
        pos = bisect_left(tails, j)
        if pos == len(tails):
            tails.append(j)
            ends.append(k)
        else:
            tails[pos], ends[pos] = j, k
        back[k] = ends[pos - 1] if pos else -1
    run, k = [], ends[-1] if ends else -1
    while k >= 0:
        run.append(pairs[k])
        k = back[k]
    return run[::-1]


def _anchors(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    ua, ub = _unique(a, N), _unique(b, N)
    pairs = sorted((i, ub[g]) for g, i in ua.items() if i >= 0 and ub.get(g, -1) >= 0)
    return _increasing(pairs)


def _trim(anchors: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Without the anchors of the first or last ``EDGE_WORDS`` reference words when a
    gap of over ``EDGE_GAP`` words cuts them off from the rest: a title or a colophon
    that one text has at the other end (with an index between, say)."""

    def cut(k: int) -> bool:  # a long gap before anchors[k]
        (i0, j0), (i1, j1) = anchors[k - 1], anchors[k]
        return i1 - i0 > EDGE_GAP or j1 - j0 > EDGE_GAP

    n = len(anchors)
    if not n:
        return anchors
    first, last = anchors[0][0], anchors[-1][0]
    head = [k for k in range(1, n) if anchors[k - 1][0] - first < EDGE_WORDS]
    tail = [k for k in range(n - 1, 0, -1) if last - anchors[k][0] < EDGE_WORDS]
    lo = max((k for k in head if cut(k)), default=0)
    hi = min((k for k in tail if cut(k)), default=n)
    return anchors[lo:hi] if lo < hi else anchors


def _difflib(a, b, oa, ob, out):
    for m in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        out.extend((oa + m.a + k, ob + m.b + k) for k in range(m.size))


def _align(a, b, oa, ob, out, top=False) -> tuple[int, int, int, int] | None:
    """Matched (index in a + oa, index in b + ob) pairs into ``out``. At the top, words
    before the first anchor and after the last stay unmatched, and the span between
    them is returned (start and end in a, then in b)."""
    anchors = _anchors(a, b)
    if top:
        anchors = _trim(anchors)
    if not anchors:
        if not top and len(a) * len(b) <= GAP_LIMIT:
            _difflib(a, b, oa, ob, out)
        return None
    return _walk(a, b, anchors, oa, ob, out, top)


def _walk(a, b, anchors, oa, ob, out, top) -> tuple[int, int, int, int]:
    pa = pb = 0
    first = None
    for i, j in anchors:
        if i < pa or j < pb:
            if first is not None and i - j == pa - pb:  # the same run, one word on
                out.extend((oa + i + k, ob + j + k) for k in range(pa - i, N))
                pa, pb = i + N, j + N
            continue  # else it overlaps the anchor before it differently in a and b
        if first is None:
            first = (i, j)
            if top:
                pa, pb = i, j
        _gap(a[pa:i], b[pb:j], oa + pa, ob + pb, out)
        out.extend((oa + i + k, ob + j + k) for k in range(N))
        pa, pb = i + N, j + N
    if not top:
        _gap(a[pa:], b[pb:], oa + pa, ob + pb, out)
    return first[0], pa, first[1], pb


def _gap(a, b, oa, ob, out):
    if not a or not b:
        return
    if len(a) * len(b) <= GAP_LIMIT:
        _difflib(a, b, oa, ob, out)
    else:
        _align(a, b, oa, ob, out)


def align(ref: list[str], ours: list[str], ref_at: list[int], ours_at: list[int]):
    """Align the words of ``ref`` at positions ``ref_at`` with ours at ``ours_at``: the
    matched (ref position, our position) pairs and the span (ref start, ref end, our
    start, our end; positions), or None when no anchor is found."""
    a, b = [ref[i] for i in ref_at], [ours[j] for j in ours_at]
    pairs: list[tuple[int, int]] = []
    span = _align(a, b, 0, 0, pairs, top=True)
    matched = [(ref_at[i], ours_at[j]) for i, j in pairs]
    if span is None:
        return matched, None
    i0, i1, j0, j1 = span
    return matched, (ref_at[i0], ref_at[i1 - 1] + 1, ours_at[j0], ours_at[j1 - 1] + 1)


def _absent(pairs: list[tuple[int, int]], n_a: int, n_b: int) -> tuple[list[bool], list[bool]]:
    """Gaps between matched words (positions in a and b) of over ``EDGE_GAP`` words in
    one text and under a tenth of that in the other: text the other edition doesn't
    have (the rest of a collected edition, an index), to be left out of the counts."""
    out_a, out_b = [False] * n_a, [False] * n_b
    for (i0, j0), (i1, j1) in zip(pairs, pairs[1:], strict=False):
        da, db = i1 - i0 - 1, j1 - j0 - 1
        if da > EDGE_GAP and db * 10 < da:
            out_a[i0 + 1 : i1] = [True] * da
        if db > EDGE_GAP and da * 10 < db:
            out_b[j0 + 1 : j1] = [True] * db
    return out_a, out_b


def _align_notes(ref: Text, ours: Text, note_at: list[int], free: list[int]):
    """Each reference note aligned on its own with the words of ours at ``free`` (notes
    may sit in any order in ours): (ref position, our position) pairs, and the notes
    (reference blocks) that have an anchor."""
    notes: dict[int, list[int]] = {}
    for i in note_at:
        notes.setdefault(ref.block[i], []).append(i)
    b = [ours.words[j] for j in free]
    ub = _unique(b, N)
    grams = Counter()
    for at in notes.values():
        ws = [ref.words[i] for i in at]
        grams.update(tuple(ws[k : k + N]) for k in range(len(ws) - N + 1))
    pairs, anchored = [], set()
    for block, at in notes.items():
        ws = [ref.words[i] for i in at]
        found = []
        for k in range(len(ws) - N + 1):
            gram = tuple(ws[k : k + N])
            if grams[gram] == 1 and ub.get(gram, -1) >= 0:
                found.append((k, ub[gram]))
        run = _increasing(found)
        if run:
            anchored.add(block)
            local: list[tuple[int, int]] = []
            _walk(ws, b, run, 0, 0, local, top=True)
            pairs += [(at[k], free[j]) for k, j in local]
    return pairs, anchored


# --- scoring ---------------------------------------------------------------------------


def score(ref: Text, ours: Text, collected: bool = False) -> dict:
    """``collected``: the reference holds more than our book (a collected edition), so
    its long stretches ours lacks don't count; otherwise they are missing words."""
    n_ref, n_ours = len(ref.words), len(ours.words)
    body_at = [i for i in range(n_ref) if ref.kind[i] != NOTE]
    # Our notes meet the reference's notes only, when it marks them.
    marks = len(body_at) < n_ref
    ours_at = [j for j in range(n_ours) if not (marks and ours.kind[j] == NOTE)]
    pairs, span = align(ref.words, ours.words, body_at, ours_at)
    if span is None:
        return {"error": "no anchors: not the same text"}
    r0, r1, o0, o1 = span
    partner = [-1] * n_ref  # our word for each reference word
    rank = {i: k for k, i in enumerate(body_at)}
    body_back = [-1] * n_ours  # for each of ours, its reference word's place in body_at
    pairs.sort()
    for i, j in pairs:
        partner[i] = j
        body_back[j] = rank[i]
    absent_a, absent_ours = _absent([(rank[i], j) for i, j in pairs], len(body_at), n_ours)
    if not collected:  # else a stretch we lost would not count
        absent_a = [False] * len(body_at)
    counted = [False] * n_ref  # reference words that count
    for k, i in enumerate(body_at):
        counted[i] = r0 <= i < r1 and not absent_a[k]
    mine = [o0 <= j < o1 and not absent_ours[j] for j in range(n_ours)]  # ours that count

    notes = None
    note_at = [i for i in range(n_ref) if ref.kind[i] == NOTE]
    if note_at:
        used = set(partner) - {-1}
        free = [j for j in range(n_ours) if j not in used]
        note_pairs, anchored = _align_notes(ref, ours, note_at, free)
        for i, j in note_pairs:
            partner[i] = j
        notes = {"words": 0, "in_notes": 0, "in_body": 0}
        for i in note_at:
            # A note counts when found in ours, or inside the counted body (a note by its
            # paragraph); endnotes found nowhere may be another edition's.
            k = bisect_left(body_at, i) - 1  # the body word before it
            if ref.block[i] in anchored or (r0 <= i < r1 and not absent_a[max(k, 0)]):
                counted[i] = True
                notes["words"] += 1
                if partner[i] >= 0:
                    notes["in_notes" if ours.kind[partner[i]] == NOTE else "in_body"] += 1

    back = [-1] * n_ours  # the reference word for each of ours
    for i in range(n_ref):
        if partner[i] >= 0:
            back[partner[i]] = i
    ref_words = sum(counted)
    matched = sum(1 for i in range(n_ref) if counted[i] and partner[i] >= 0)
    extra = sum(1 for j in range(n_ours) if mine[j] and back[j] < 0)
    return {
        "ref_words": ref_words,
        # The share of the reference's body the span covers: text lost at either end
        # shrinks the span rather than counting as missing.
        "ref_body": len(body_at),
        "coverage": sum(counted[i] for i in body_at),
        "matched": matched,
        "missing": ref_words - matched,
        "extra": extra,
        "headings": _headings(ref, ours, partner, back, counted, mine),
        "breaks": _breaks(ref, ours, partner, back, counted, mine),
        "notes": notes,
        **_leftovers(ours, back, body_back, mine),
    }


def _headings(ref, ours, partner, back, counted, mine) -> dict | None:
    if HEADING not in ref.kind:
        return None
    out = {"ref": 0, "found": 0, "ours": 0, "real": 0, "pairs": 0, "agree": 0}
    out.update(missed=[], wrong=[])
    words_of: dict[int, list[int]] = {}
    for i, h in enumerate(ref.head):
        if h >= 0 and counted[i]:
            words_of.setdefault(h, []).append(i)
    levels = []  # (reference level, our level) of each found heading
    for h, at in words_of.items():
        ours_heads = [ours.head[partner[i]] for i in at if partner[i] >= 0]
        if not ours_heads:
            continue  # its words are nowhere in ours: another edition's heading
        out["ref"] += 1
        in_heads = [g for g in ours_heads if g >= 0]
        if len(in_heads) >= FOUND * len(at):
            out["found"] += 1
            best = Counter(in_heads).most_common(1)[0][0]
            levels.append((ref.headings[h][0], ours.headings[best][0]))
        else:
            out["missed"].append(ref.headings[h][1])
    our_words: dict[int, list[int]] = {}
    for j, g in enumerate(ours.head):
        if g >= 0 and mine[j]:
            our_words.setdefault(g, []).append(j)
    for g, at in our_words.items():
        out["ours"] += 1
        real = sum(back[j] >= 0 and ref.head[back[j]] >= 0 for j in at)
        if real >= FOUND * len(at):
            out["real"] += 1
        else:
            out["wrong"].append(ours.headings[g][1])
    for (t1, f1), (t2, f2) in combinations(levels, 2):
        out["pairs"] += 1
        out["agree"] += (t1 > t2) - (t1 < t2) == (f1 > f2) - (f1 < f2)
    return out


def _starts(text: Text, other: Text, link: list[int], keep) -> dict[int, int]:
    """Each body block's first word aligned into the other's body: word -> partner."""
    starts: dict[int, int] = {}
    seen = set()
    for i, j in enumerate(link):
        if j < 0 or not keep(i) or text.kind[i] != BODY or other.kind[j] != BODY:
            continue
        if text.block[i] not in seen:
            seen.add(text.block[i])
            starts[i] = j
    return starts


def _breaks(ref, ours, partner, back, counted, mine) -> dict:
    ref_starts = _starts(ref, ours, partner, lambda i: counted[i])
    our_starts = _starts(ours, ref, back, lambda j: mine[j])
    return {
        "ref": len(ref_starts),
        "found": sum(j in our_starts for j in ref_starts.values()),
        "ours": len(our_starts),
        "real": sum(i in ref_starts for i in our_starts.values()),
    }


def _leftovers(ours, back, body_back, mine) -> dict:
    """Runs of our extra words, inside one block, with no reference body word missing
    between the body words around them (pure insertions)."""
    runs: list[list[str]] = []
    n, j = len(mine), 0
    while j < n:
        if back[j] >= 0 or not mine[j]:
            j += 1
            continue
        k = j
        while k < n and mine[k] and back[k] < 0 and ours.block[k] == ours.block[j]:
            k += 1
        before = next((body_back[x] for x in range(j - 1, -1, -1) if body_back[x] >= 0), None)
        after = next((body_back[x] for x in range(k, n) if body_back[x] >= 0), None)
        if before is not None and after is not None and after == before + 1:
            runs.append(ours.words[j:k])
        j = k
    keys = Counter(" ".join(w for w in run if not w.isdigit()) for run in runs)
    left = Counter()
    for key, n in keys.items():
        # A bare number (page numbers), or words repeated (running heads).
        if not key or (n >= 3 and len(key.replace(" ", "")) >= HEAD_LETTERS):
            left[key or "(number)"] = n
    return {"leftovers": left.total(), "leftover_kinds": dict(left.most_common(10))}


def score_files(reference: Path, md: Path, collected: bool = False) -> dict:
    return score(read_reference(Path(reference)), read_markdown(Path(md)), collected)


# --- selftest --------------------------------------------------------------------------


def selftest() -> None:
    def para(stem: str, n: int = 12) -> str:
        return " ".join(f"{stem}{k}" for k in range(n))

    p1, p2a, p2b, p3, p4 = para("uno"), para("dos"), para("tres"), para("cuatro"), para("cinco")
    note = para("nota", 8)
    xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>t</title></head><body>
<h1>Capítulo primero</h1>
<p>{p1}<a epub:type="noteref" href="#n1"><sup>1</sup></a></p>
<p>{p2a} {p2b}</p>
<h2>La sección dos</h2>
<p>{p3}</p>
<h2>Otra sección</h2>
<p>{p4}</p>
<aside epub:type="footnote" id="n1"><p><a href="#r1">1</a> {note}</p></aside>
</body></html>"""
    opf = """<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">
<manifest><item id="c" href="c.xhtml" media-type="application/xhtml+xml"/></manifest>
<spine><itemref idref="c"/></spine></package>"""
    container = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>"""
    md = f"""---
title: t
---

# Capítulo primero

{p1}[^1]

{note}

Historia breve

{p2a}

Historia breve

{p2b}

La sección dos

{p3}

Historia breve

### Otra sección

{p4}
"""
    work = ROOT / "scratch" / "book_score_selftest"
    work.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(work / "ref.epub", "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/c.xhtml", xhtml)
    _write_atomic(work / "ours.md", md)
    s = score_files(work / "ref.epub", work / "ours.md")
    body = 2 + 5 * 12 + 3 + 2  # the headings' words and the paragraphs'
    assert s["ref_words"] == body + 8 and s["matched"] == body + 8, s
    assert (s["missing"], s["extra"]) == (0, 6), s  # three running heads of two words
    h = s["headings"]
    assert (h["ref"], h["found"], h["ours"], h["real"]) == (3, 2, 2, 2), h
    assert (h["pairs"], h["agree"]) == (1, 1) and h["missed"] == ["La sección dos"], h
    # p1, p2, p3, p4 in the reference; p2 split in two in ours: one break not real.
    assert s["breaks"] == {"ref": 4, "found": 4, "ours": 5, "real": 4}, s["breaks"]
    assert s["notes"] == {"words": 8, "in_notes": 0, "in_body": 8}, s["notes"]
    assert s["leftovers"] == 3 and s["leftover_kinds"] == {"historia breve": 3}, s
    print("selftest passed")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["selftest"]:
        selftest()
    elif len(args) in (2, 3) and args[2:] in ([], ["--collected"]):
        s = score_files(Path(args[0]), Path(args[1]), len(args) == 3)
        print(json.dumps(s, ensure_ascii=False, indent=1))
    else:
        sys.exit(__doc__)

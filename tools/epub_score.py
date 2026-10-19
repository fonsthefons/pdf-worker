"""Score a built EPUB against a reference EPUB of the same edition.

Usage: .venv/bin/python tools/epub_score.py REFERENCE.epub OURS.epub

Prints one line per measure, reference value beside ours where both have one. Run it
after each change to the pipeline (see PROGRESS.md, "EPUB QUALITY PLAN"); the numbers
are counts, so compare runs of the same book only.
"""

import re
import sys
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass, field

_WORD_RE = re.compile(r"[^\W\d_]+")
_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"<(h[1-6])[^>]*>(.*?)</\1>", re.S)
_BAD_HEADING_RE = re.compile(r"©|\b(impreso|printed|isbn|copyright)\b", re.I)
_LONG_HEADING = 100  # characters: longer "headings" are body sentences


@dataclass
class Book:
    docs: int = 0
    words: Counter = field(default_factory=Counter)
    tokens: list[str] = field(default_factory=list)
    tags: Counter = field(default_factory=Counter)
    bad_headings: int = 0
    straight_quotes: int = 0
    curly_quotes: int = 0


def read(path: str) -> Book:
    book = Book()
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith((".xhtml", ".html", ".htm")) or "nav" in name.lower():
                continue
            html = z.read(name).decode("utf-8", "replace").split("<body", 1)[-1]
            book.docs += 1
            book.tags.update(
                t.lower() for t in re.findall(r"<(h[1-6]|i|em|b|strong|sup)[\s>]", html)
            )
            book.tags["noteref"] += html.count('epub:type="noteref"')
            for _, heading in _HEADING_RE.findall(html):
                heading = " ".join(_TAG_RE.sub(" ", heading).split())
                book.bad_headings += (
                    bool(_BAD_HEADING_RE.search(heading)) or len(heading) > _LONG_HEADING
                )
            text = _TAG_RE.sub(" ", html).replace("&nbsp;", " ")
            book.straight_quotes += text.count("'") + text.count('"') + text.count("&quot;")
            book.curly_quotes += sum(text.count(c) for c in "‘’“”")
            tokens = _WORD_RE.findall(text)
            book.tokens += tokens
            book.words.update(tokens)
    return book


def plain(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word) if not unicodedata.combining(c))


def lost_accents(ref: Book, ours: Book) -> Counter:
    """Our unaccented words that the reference only ever prints with an accent."""
    accented = {plain(w) for w in ref.words if plain(w) != w}
    return Counter(
        {
            w: n
            for w, n in ours.words.items()
            if w not in ref.words and plain(w) == w and w in accented
        }
    )


def split_words(ref: Book, ours: Book) -> Counter:
    """Our word pairs, neither in the reference, that join into a reference word ("leza")."""
    pairs = Counter()
    for a, b in zip(ours.tokens, ours.tokens[1:], strict=False):
        if (a not in ref.words or b not in ref.words) and (a + b) in ref.words and len(a + b) > 4:
            pairs[f"{a} {b}"] += 1
    return pairs


def main(ref_path: str, ours_path: str) -> None:
    ref, ours = read(ref_path), read(ours_path)
    rows = [
        ("words", ref.words.total(), ours.words.total()),
        ("documents", ref.docs, ours.docs),
        *((tag, ref.tags[tag], ours.tags[tag]) for tag in ("h1", "h2", "h3")),
        ("italic (i/em)", ref.tags["i"] + ref.tags["em"], ours.tags["i"] + ours.tags["em"]),
        (
            "bold (b/strong)",
            ref.tags["b"] + ref.tags["strong"],
            ours.tags["b"] + ours.tags["strong"],
        ),
        ("sup", ref.tags["sup"], ours.tags["sup"]),
        ("noteref links", ref.tags["noteref"], ours.tags["noteref"]),
        ("bad headings (©, >100 chars)", ref.bad_headings, ours.bad_headings),
        ("straight quotes", ref.straight_quotes, ours.straight_quotes),
        ("curly quotes", ref.curly_quotes, ours.curly_quotes),
    ]
    width = max(len(name) for name, *_ in rows)
    print(f"{'':{width}}  {'reference':>10}  {'ours':>10}")
    for name, a, b in rows:
        print(f"{name:{width}}  {a:>10}  {b:>10}")
    lost, split = lost_accents(ref, ours), split_words(ref, ours)
    unknown = Counter({w: n for w, n in ours.words.items() if w not in ref.words})
    print(
        f"lost accents: {lost.total()} ({len(lost)} words)",
        f"e.g. {[w for w, _ in lost.most_common(8)]}",
    )
    print(f"split words: {split.total()} e.g. {[p for p, _ in split.most_common(6)]}")
    print(f"words not in reference: {unknown.total()} ({len(unknown)} distinct)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])

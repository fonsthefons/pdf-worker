"""Greek terms of the test books found in a converted book (our Markdown).

Usage:
  .venv/bin/python tools/greek_score.py OUT.md...
  .venv/bin/python tools/greek_score.py selftest

The truth is ``test_pdfs/greek_truth.json`` (else its copy ``tests/data/greek_truth.json``):
each term {book, page (1-based), kind: "greek" (Greek letters) or "translit" (in Latin
letters, long vowels with macrons), text} as printed. ``OUT.md`` is scored against the
terms of the book named by its stem ("timeo.md": book "timeo"). A term is found when it
occurs in one of the book's paragraphs, both NFC, emphasis marks and escapes left out,
spaces collapsed. Prints per kind the terms found and the misses (page and text).
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

from regression import _blocks, _write_atomic

ROOT = Path(__file__).resolve().parent.parent
TRUTH = ROOT / "test_pdfs" / "greek_truth.json"
_MARKS_RE = re.compile(r"[*\\]")


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def load_truth() -> list[dict]:
    path = TRUTH if TRUTH.exists() else ROOT / "tests" / "data" / "greek_truth.json"
    return json.loads(path.read_text(encoding="utf-8"))


def score(terms: list[dict], md: Path) -> dict[str, dict]:
    """Per kind: {"found": n, "missing": [term, ...]} for ``terms`` (one book's)."""
    left = {i: _norm(t["text"]) for i, t in enumerate(terms)}
    for block in _blocks(md):
        text = _norm(_MARKS_RE.sub("", block))
        for i in [i for i, term in left.items() if term in text]:
            del left[i]
    out: dict[str, dict] = {}
    for i, t in enumerate(terms):
        kind = out.setdefault(t["kind"], {"found": 0, "missing": []})
        if i in left:
            kind["missing"].append(t)
        else:
            kind["found"] += 1
    return out


def report(md: Path, truth: list[dict]) -> None:
    terms = [t for t in truth if t["book"] == md.stem]
    if not terms:
        print(f"{md.stem}: no terms in the truth")
        return
    for kind, s in score(terms, md).items():
        total = s["found"] + len(s["missing"])
        print(f"{md.stem} {kind}: {s['found']}/{total} found, {len(s['missing'])} missing")
        for t in s["missing"]:
            print(f"  p.{t['page']}: {t['text']}")


def selftest() -> None:
    work = ROOT / "scratch" / "greek_score_selftest"
    work.mkdir(parents=True, exist_ok=True)
    md = work / "book.md"
    # "eudaímōn" decomposed (o + macron) in ours; "lógos" split over two lines.
    decomposed = unicodedata.normalize("NFD", "eudaímōn")
    _write_atomic(md, f"---\ntitle: t\n---\n\nEl *{decomposed}* y el\n*ló\\*gos* aquí\n\nἀλήθεια\n")
    terms = [
        {"book": "book", "page": 1, "kind": "translit", "text": "eudaímōn"},
        {"book": "book", "page": 1, "kind": "translit", "text": "y el lógos"},
        {"book": "book", "page": 2, "kind": "translit", "text": "daímōn hoi"},
        {"book": "book", "page": 2, "kind": "greek", "text": "ἀλήθεια"},
        {"book": "book", "page": 3, "kind": "greek", "text": "λόγος"},
    ]
    s = score(terms, md)
    assert s["translit"]["found"] == 2 and [t["page"] for t in s["translit"]["missing"]] == [2], s
    assert s["greek"]["found"] == 1 and [t["text"] for t in s["greek"]["missing"]] == ["λόγος"], s
    assert all(t["book"] in ("timeo", "if", "philosophy") for t in load_truth())
    print("selftest passed")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["selftest"]:
        selftest()
    elif args and "selftest" not in args:
        truth = load_truth()
        for arg in args:
            report(Path(arg), truth)
    else:
        sys.exit(__doc__)

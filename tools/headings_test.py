"""Heading rules against the real headings of the new test books (docs/layout-plan.md,
Phase 5 headings: which of the options (a)-(d) to keep).

Usage:
  .venv/bin/python tools/headings_test.py run OUT_DIR     (heavy: runs the layout model)
  .venv/bin/python tools/headings_test.py score OUT_DIR   (re-score OUT_DIR/headings.json)
  .venv/bin/python tools/headings_test.py selftest        (the scoring, on a made-up page)

``run`` takes the books of test_pdfs/book_tests_pdfs/manifest.json one at a time: the
layout model's rows for its pages (``paddle_ocr.layout_pages``, cached in
scratch/paddle-home, so a second run is quick), then its headings under each variant's
rules (``structure.HEADING_RULES``), saved to OUT_DIR/headings.json after each book.
The headings come from ``structure.iter_blocks`` and ``tidy``, as in ``convert_pdf``;
the word re-reading (Tesseract) and the review's word check are left out: they don't
make headings. Then ``score``: each variant against truth.json, in OUT_DIR/report.md.

Scoring, page by page: a heading found is correct when most of it (80%) is text of the
page's real headings; a bare number ("1.", "V.") is correct only when it is a whole real
heading. A real heading is found when most of it (60%) is text of the headings found (so a
heading split in two, or two joined, still counts). Levels: for two real headings found
in a book, is one above the other, or level with it, as in the book (pairs agreeing).
"""

import json
import os
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

from regression import _write_atomic

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "test_pdfs" / "book_tests_pdfs"
# (a) is the PR's rule: a line in a title box is a heading. (b), (c), (d) are on top of it.
VARIANTS = {
    "old (main)": {"no_titles", "size", "implicit"},
    "a": set(),
    "a+b": {"implicit"},
    "a+c": {"larger"},
    "a+d": {"number"},
    "a+c+d": {"larger", "number"},
    "a+b+c+d": {"implicit", "larger", "number"},
}
_NUMBER_RE = re.compile(r"^(?:\d{1,3}|[ivxlc]{1,6})$")
FOUND, CORRECT = 0.6, 0.8


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c if c.isalnum() else " " for c in text if not unicodedata.combining(c))
    return " ".join(text.split())


def _matched(a: str, b: str) -> int:
    return sum(m.size for m in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())


def score_book(truth: list[dict], found: list[list]) -> dict:
    """``truth``: {"page", "text", "level"}; ``found``: [page, level, text]."""
    out = {"truth": len(truth), "found": 0, "headings": len(found), "correct": 0}
    out.update(pairs=0, agree=0, missed=[], extra=[], levels={})
    levels = []  # (truth level, found level) of each real heading found
    for page in sorted({t["page"] for t in truth} | {f[0] for f in found}):
        real = [t for t in truth if t["page"] == page]
        got = [f for f in found if f[0] == page]
        real_text = " ".join(_norm(t["text"]) for t in real)
        got_text = " ".join(_norm(f[2]) for f in got)
        for _, level, text in got:
            norm = _norm(text)
            if _NUMBER_RE.match(norm):
                ok = any(_norm(t["text"]) == norm for t in real)
            else:
                ok = bool(norm) and _matched(norm, real_text) >= CORRECT * len(norm)
            out["correct"] += ok
            if not ok:
                out["extra"].append(f"p. {page}: {text!r} (level {level})")
        for t in real:
            norm = _norm(t["text"])
            if norm and _matched(norm, got_text) >= FOUND * len(norm):
                out["found"] += 1
                best = max(got, key=lambda f: _matched(_norm(f[2]), norm))
                levels.append((t["level"], best[1]))
            else:
                out["missed"].append(f"p. {page}: {t['text']!r} (level {t['level']})")
    for (t1, f1), (t2, f2) in combinations(levels, 2):
        out["pairs"] += 1
        out["agree"] += (t1 > t2) - (t1 < t2) == (f1 > f2) - (f1 < f2)
    for t, f in levels:
        out["levels"].setdefault(t, set()).add(f)
    return out


def _share(n: int, total: int) -> str:
    return f"{n / total:.0%}" if total else "-"


def score(out: Path) -> None:
    truth = json.loads((TESTS / "truth.json").read_text(encoding="utf-8"))
    built = json.loads((out / "headings.json").read_text(encoding="utf-8"))
    books = [b for b in built if b in truth]
    lines = [
        "# Heading rules on the new test books",
        "",
        f"{len(books)} books, {sum(len(truth[b]['headings']) for b in books)} real headings"
        " (test_pdfs/book_tests_pdfs/truth.json). Recall: real headings found. Precision:"
        " headings found that are real. Levels: pairs of real headings found ranked as in"
        " the book. (a) title boxes only (the PR); b keeps the all-caps/bold rule, c the size"
        " test for lines larger than any title box on the page, d joins a bare number to the"
        " next line; old = main's rules (size test and all-caps/bold, no title boxes).",
        "",
        "| Variant | Recall | Precision | F1 | Levels | Missed | Extra |",
        "|---|---|---|---|---|---|---|",
    ]
    scores = {
        v: {b: score_book(truth[b]["headings"], built[b][v]) for b in books} for v in VARIANTS
    }
    for variant, by_book in scores.items():
        t = {
            k: sum(s[k] for s in by_book.values())
            for k in ("truth", "found", "headings", "correct", "pairs", "agree")
        }
        recall, precision = t["found"] / (t["truth"] or 1), t["correct"] / (t["headings"] or 1)
        f1 = 2 * recall * precision / ((recall + precision) or 1)
        lines.append(
            f"| {variant} | {recall:.0%} | {precision:.0%} | {f1:.0%}"
            f" | {_share(t['agree'], t['pairs'])}"
            f" | {t['truth'] - t['found']} | {t['headings'] - t['correct']} |"
        )
    lines += ["", "## By book (recall / precision)", ""]
    lines.append("| Book | " + " | ".join(VARIANTS) + " |")
    lines.append("|---|" + "---|" * len(VARIANTS))
    for book in books:
        cells = [
            f"{_share(s['found'], s['truth'])} / {_share(s['correct'], s['headings'])}"
            for s in (scores[v][book] for v in VARIANTS)
        ]
        lines.append(f"| {book} | " + " | ".join(cells) + " |")
    for variant, by_book in scores.items():
        lines += ["", f"## Errors: {variant}"]
        for book, s in by_book.items():
            if not (s["missed"] or s["extra"]):
                continue
            levels = ", ".join(f"{t}: {sorted(f)}" for t, f in sorted(s["levels"].items()))
            lines += ["", f"### {book} (real level: levels found, {levels})", ""]
            lines += [f"- missed {m}" for m in s["missed"]] + [f"- extra {e}" for e in s["extra"]]
    _write_atomic(out / "report.md", "\n".join(lines) + "\n")
    print("\n".join(lines[:16]))
    print(f"\nreport: {out / 'report.md'}")


def run(out: Path) -> None:
    # The layout model's rows, cached as regression.py caches them.
    os.environ.setdefault("PDF_WORKER_PADDLE_CACHE", str(ROOT / "scratch" / "paddle-home"))
    from pdf_worker import font_sizes, glued_refs, structure
    from pdf_worker.convert import guess_language
    from pdf_worker.document import open_pdf
    from pdf_worker.inline import plain
    from pdf_worker.layout import analyze_document
    from pdf_worker.paddle_ocr import layout_pages
    from pdf_worker.structure import Heading, iter_blocks
    from pdf_worker.tidy import tidy

    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((TESTS / "manifest.json").read_text(encoding="utf-8"))
    saved = out / "headings.json"
    built = json.loads(saved.read_text(encoding="utf-8")) if saved.exists() else {}
    for label, book in manifest.items():
        if label in built:
            print(f"{label}: done before", flush=True)
            continue
        pdf = TESTS / book["file"]
        print(f"{label}: layout model ({len(book['pages'])} pages)", flush=True)
        rows = layout_pages(pdf)
        built[label] = {}
        for variant, rules in VARIANTS.items():
            structure.HEADING_RULES = frozenset(rules)
            with open_pdf(pdf) as doc:
                font_sizes.mark_misreporting(doc)
                glued_refs.mark_glued_refs(doc)
                profile = analyze_document(doc)
                profile.layout = rows
                blocks = tidy(
                    iter_blocks(doc, profile, images=False), guess_language(profile.text_sample)
                )
                built[label][variant] = [
                    [b.page + 1, b.level, plain(b.text)] for b in blocks if isinstance(b, Heading)
                ]
        structure.HEADING_RULES = frozenset()
        _write_atomic(saved, json.dumps(built, ensure_ascii=False, indent=1))
        print(f"  {', '.join(f'{v} {len(h)}' for v, h in built[label].items())}", flush=True)
    score(out)


def selftest() -> None:
    truth = [
        {"page": 1, "text": "CAPÍTULO PRIMERO La vida", "level": 1},
        {"page": 1, "text": "1. Noción de ente", "level": 2},
        {"page": 2, "text": "V. Este es el corazón", "level": 2},
    ]
    found = [
        [1, 1, "CAPITULO PRIMERO"],  # half of a heading split in two...
        [1, 1, "LA VIDA"],  # ...and its other half: found, both correct
        [1, 2, "1."],  # a bare number split from its title: extra
        [1, 2, "Noción de ente"],
        [2, 3, "V."],  # its title left as text: missed, and the number extra
        [2, 2, "98 MIGUEL DE UNAMUNO"],  # a running head: extra
    ]
    s = score_book(truth, found)
    assert (s["found"], s["truth"], s["correct"], s["headings"]) == (2, 3, 3, 6), s
    assert (s["agree"], s["pairs"]) == (1, 1), s
    assert len(s["missed"]) == 1 and "corazón" in s["missed"][0], s
    assert s["levels"] == {1: {1}, 2: {2}}, s
    print("selftest passed")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0] in ("run", "score"):
        (run if args[0] == "run" else score)(Path(args[1]))
    elif args == ["selftest"]:
        selftest()
    else:
        sys.exit(__doc__)

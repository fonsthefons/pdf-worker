"""Whole books against reference editions, and both headings page sets
(docs/quality-plan.md, Phase 1).

Usage:
  .venv/bin/python tools/quality.py build OUT_DIR    (heavy: converts every book)
  .venv/bin/python tools/quality.py score OUT_DIR    (re-score a build: no conversion)
  .venv/bin/python tools/quality.py compare BEFORE_DIR AFTER_DIR

``build`` converts each book of ``PAIRS`` to ``OUT_DIR/<label>.md`` one at a time, as
``tools/regression.py`` does (title and author given, the review file in OUT_DIR, cached
model rows), then runs ``tools/headings_test.py run`` on both page sets
(``OUT_DIR/headings``, ``OUT_DIR/headings_heldout``) and ``score``. ``score`` scores each
book against its reference (``tools/book_score.py``) and writes ``OUT_DIR/quality.json``
and ``OUT_DIR/report.md``: a working and a held-out table (one row per book, a total row)
and the error kinds ranked by their rate per 10,000 reference words. Held-out books show
numbers only (the plan's rule 4): their missed headings and such are not written.
``compare`` prints every measure before -> after, working and held-out apart, marking a
change beyond the tolerance (1 point for percentages, 1 per 10,000 reference words for
rates) as better or WORSE.
"""

import json
import sys
from pathlib import Path

import book_score
import headings_test
from regression import _write_atomic, convert_book

ROOT = Path(__file__).resolve().parent.parent
P = ROOT / "test_pdfs"
NEW = P / "new_test_books"
# label, PDF, reference, held out, built from PaddleOCR-VL's rows (a scan). The pairs
# and the same-text check that chose them: docs/quality-plan.md, "Reference pairs".
PAIRS = [
    ("philosophy", P / "philosophy.pdf", P / "philosophy_epub_good.epub", False, True),
    (
        "copleston",
        NEW / "copleston" / "Historia de la Filosofía Tomo 1 - Copleston.pdf",
        NEW / "copleston" / "1 - Grecia y Roma Frederick Copleston.epub",
        False,
        False,
    ),
    (
        "ratzinger",
        NEW / "Introduction to Christianity by Ratzinger.pdf",
        NEW / "Introduction to Christianity by Ratzinger.epub",
        False,
        False,
    ),
    (
        "lugones",
        P / "lugones_imperio_jesuitico_1904.pdf",
        P / "refs" / "lugones_imperio_jesuitico_wikisource.epub",
        False,
        False,
    ),
    (
        "platon_bad",
        P / "platon_dialogos_vi_bad.pdf",
        P / "Dialogos Completos Platon.epub",
        False,
        True,
    ),
    (
        "dialogos",
        P / "platon_dialogos_vi_good.pdf",
        P / "Dialogos Completos Platon.epub",
        False,
        False,
    ),
    ("niebla", P / "niebla_1914.pdf", P / "refs" / "pg49836.txt", False, False),
    ("pepita", P / "pepita_1901.pdf", P / "refs" / "pg17223.txt", True, False),
    ("marianela", P / "marianela_1888.pdf", P / "refs" / "pg17340.txt", True, False),
    ("gaviota", P / "gaviota_1856.pdf", P / "refs" / "pg23600.txt", True, False),
]
# References whose heading tags don't mark the book's divisions (Wikisource's mark the
# title page only): no heading measures.
NO_HEADINGS = {"lugones"}
# References that hold more than the PDF (the complete dialogues; both volumes of La
# gaviota, the PDF is volume 1): only what aligns counts.
COLLECTED = {"platon_bad", "dialogos", "gaviota"}
SETS = ("working", "heldout")
PAGE_SETS = {"working": "headings", "heldout": "headings_heldout"}
PAGE_TESTS = {"working": headings_test.TESTS, "heldout": headings_test.TESTS / "heldout"}
_PAGE_KEYS = ("truth", "found", "headings", "correct", "pairs", "agree")


# --- measures --------------------------------------------------------------------------


def _pct(n, d):
    return 100 * n / d if d else None


def _rate(n, d):
    return 10_000 * n / d if d else None


def _sum(scores: list[dict]) -> dict:
    """The counts of several books' scores added up (headings and notes over the books
    that have them, with the reference words of those books)."""
    total = {k: sum(s[k] for s in scores) for k in ("ref_words", "matched", "missing", "extra")}
    total["leftovers"] = sum(s["leftovers"] for s in scores)
    for k in ("coverage", "ref_body"):  # books whose reference isn't a collected edition
        total[k] = sum(s[k] for s in scores if s["coverage"] is not None)
    total["breaks"] = {k: sum(s["breaks"][k] for s in scores) for k in scores[0]["breaks"]}
    for part, keys in (
        ("headings", ("ref", "found", "ours", "real", "pairs", "agree")),
        ("notes", ("words", "in_notes", "in_body")),
    ):
        having = [s for s in scores if s[part]]
        total[part] = (
            {k: sum(s[part][k] for s in having) for k in keys}
            | {"ref_words": sum(s["ref_words"] for s in having)}
            if having
            else None
        )
    return total


def measures(s: dict) -> dict:
    """A score's measures: (value, unit "%" or "/10k", higher is better)."""
    w, h, b, n = s["ref_words"], s["headings"], s["breaks"], s["notes"]
    nw = n.get("ref_words", w) if n else 0
    cover = _pct(s["coverage"], s["ref_body"]) if s["coverage"] is not None else None
    return {
        "covered": (cover, "%", True),
        "matched": (_pct(s["matched"], w), "%", True),
        "missing": (_rate(s["missing"], w), "/10k", False),
        "extra": (_rate(s["extra"], w), "/10k", False),
        "headings found": (_pct(h["found"], h["ref"]) if h else None, "%", True),
        "headings real": (_pct(h["real"], h["ours"]) if h else None, "%", True),
        "levels": (_pct(h["agree"], h["pairs"]) if h else None, "%", True),
        "breaks found": (_pct(b["found"], b["ref"]), "%", True),
        "breaks real": (_pct(b["real"], b["ours"]), "%", True),
        "notes in body": (_rate(n["in_body"], nw) if n else None, "/10k", False),
        "leftovers": (_rate(s["leftovers"], w), "/10k", False),
    }


def error_kinds(s: dict) -> dict:
    """Each error kind's rate per 10,000 reference words (for ranking). A level error is
    a found heading times the share of pairs ranked otherwise than in the reference."""
    w, h, b, n = s["ref_words"], s["headings"], s["breaks"], s["notes"]
    kinds = {
        "notes in the body": _rate(n["in_body"], n.get("ref_words", w)) if n else None,
        "missing words": _rate(s["missing"], w),
        "reference body not covered (lost at the ends)": (
            _rate(s["ref_body"] - s["coverage"], s["ref_body"])
            if s["coverage"] is not None
            else None
        ),
        "extra words": _rate(s["extra"], w),
        "paragraph breaks missed": _rate(b["ref"] - b["found"], w),
        "extra paragraph breaks": _rate(b["ours"] - b["real"], w),
        "leftovers (running heads, page numbers)": _rate(s["leftovers"], w),
    }
    if h:
        hw = h.get("ref_words", w)
        kinds["headings missed"] = _rate(h["ref"] - h["found"], hw)
        kinds["wrong headings"] = _rate(h["ours"] - h["real"], hw)
        wrong_rank = h["found"] * (1 - h["agree"] / h["pairs"]) if h["pairs"] else 0
        kinds["level disagreement"] = _rate(wrong_rank, hw)
    return kinds


def page_measures(t: dict) -> dict:
    return {
        "pages: headings found": (_pct(t["found"], t["truth"]), "%", True),
        "pages: headings real": (_pct(t["correct"], t["headings"]), "%", True),
        "pages: levels": (_pct(t["agree"], t["pairs"]), "%", True),
    }


# --- build and score -------------------------------------------------------------------


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for label, pdf, _, _, paddle in PAIRS:
        print(f"{label}: {pdf.name}", flush=True)
        convert_book(label, pdf, out, paddle)
    for which, folder in PAGE_SETS.items():
        print(f"headings test pages: {which}", flush=True)
        headings_test.run(out / folder, PAGE_TESTS[which])
    score(out)


def _pages(out: Path, which: str) -> dict | None:
    built = out / PAGE_SETS[which] / "headings.json"
    if not built.exists():
        return None
    truth = json.loads((PAGE_TESTS[which] / "truth.json").read_text(encoding="utf-8"))
    found = json.loads(built.read_text(encoding="utf-8"))
    total = dict.fromkeys(_PAGE_KEYS, 0)
    for book, variants in found.items():
        if book in truth:
            s = headings_test.score_book(truth[book]["headings"], variants["current"])
            for k in _PAGE_KEYS:
                total[k] += s[k]
    return total


def score(out: Path) -> None:
    books = {}
    for label, _, ref, held_out, _ in PAIRS:
        md = out / f"{label}.md"
        if not md.exists():
            print(f"{label}: not built")
            continue
        s = book_score.score_files(ref, md, label in COLLECTED)
        if "error" in s:
            print(f"{label}: {s['error']}")
            continue
        if label in NO_HEADINGS:
            s["headings"] = None
        if label in COLLECTED:  # it holds more: what it covers says nothing
            s["coverage"] = None
        if held_out:  # numbers only (rule 4)
            for part in ("headings",):
                if s[part]:
                    s[part] = {k: v for k, v in s[part].items() if not isinstance(v, list)}
            s.pop("leftover_kinds")
        books[label] = {"set": SETS[held_out], "reference": ref.name} | s
        print(f"{label}: {s['ref_words']} reference words", flush=True)
    result = {"books": books, "pages": {which: _pages(out, which) for which in SETS}}
    _write_atomic(out / "quality.json", json.dumps(result, ensure_ascii=False, indent=1))
    _write_atomic(out / "report.md", report(result))
    print(f"report: {out / 'report.md'}")


def _fmt(value, unit) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}%" if unit == "%" else f"{value:.1f}"


def _totals(result: dict, which: str) -> dict | None:
    scores = [b for b in result["books"].values() if b["set"] == which]
    return _sum(scores) if scores else None


def report(result: dict) -> str:
    names = list(measures(next(iter(result["books"].values()))))
    lines = [
        "# Quality: whole books against reference editions",
        "",
        "Percentages: higher is better. Rates: per 10,000 reference words, lower is"
        " better. Counted: the reference between its first and last anchor, without long"
        " stretches ours doesn't have (see tools/book_score.py).",
    ]
    for which in SETS:
        lines += ["", f"## {which.capitalize()} books", ""]
        lines.append("| Book | Reference words | " + " | ".join(names) + " |")
        lines.append("|---|---|" + "---|" * len(names))
        rows = [(k, b) for k, b in result["books"].items() if b["set"] == which]
        total = _totals(result, which)
        for label, s in rows + ([("**total**", total)] if total else []):
            cells = [_fmt(*measures(s)[name][:2]) for name in names]
            lines.append(f"| {label} | {s['ref_words']:,} | " + " | ".join(cells) + " |")
    lines += ["", "## Headings test pages", "", "| Set | Real headings | Found | Real | Levels |"]
    lines.append("|---|---|---|---|---|")
    for which in SETS:
        t = result["pages"][which]
        if t:
            cells = [_fmt(*m[:2]) for m in page_measures(t).values()]
            lines.append(f"| {which} | {t['truth']} | " + " | ".join(cells) + " |")
    lines += ["", "## Error kinds by rate per 10,000 reference words", ""]
    lines += ["| Kind | Working | Held-out |", "|---|---|---|"]
    kinds = {w: error_kinds(t) for w in SETS if (t := _totals(result, w))}
    working = kinds.get("working", {})
    for kind in sorted(working, key=lambda k: -(working[k] or 0)):
        held = kinds.get("heldout", {}).get(kind)
        lines.append(f"| {kind} | {_fmt(working[kind], '')} | {_fmt(held, '')} |")
    lines += ["", "## Working books: headings missed and wrong, leftovers", ""]
    for label, s in result["books"].items():
        if s["set"] != "working":
            continue
        lines.append(f"### {label}")
        if s["headings"]:
            lines.append(
                f"- missed ({len(s['headings']['missed'])}): {s['headings']['missed'][:20]}"
            )
            lines.append(f"- wrong ({len(s['headings']['wrong'])}): {s['headings']['wrong'][:20]}")
        lines.append(f"- leftovers: {s['leftover_kinds']}")
        lines.append("")
    return "\n".join(lines) + "\n"


# --- compare ---------------------------------------------------------------------------


def _change(before, after, unit, higher) -> str:
    if before is None or after is None:
        return "-" if before == after else f"{_fmt(before, unit)} -> {_fmt(after, unit)}"
    text = f"{_fmt(before, unit)} -> {_fmt(after, unit)}"
    gain = (after - before) if higher else (before - after)
    if gain < -1:  # the tolerance: 1 point, or 1 per 10,000 reference words
        return f"{text} WORSE"
    if gain > 1:
        return f"{text} better"
    return text if before != after else text.split(" -> ")[0]


def compare(before: Path, after: Path) -> None:
    a = json.loads((before / "quality.json").read_text(encoding="utf-8"))
    b = json.loads((after / "quality.json").read_text(encoding="utf-8"))
    worse = 0
    for which in SETS:
        print(f"== {which}")
        rows = [(k, a["books"].get(k), b["books"].get(k)) for k in b["books"]]
        rows = [(k, x, y) for k, x, y in rows if y["set"] == which]
        ta, tb = _totals(a, which), _totals(b, which)
        for label, x, y in rows + ([("total", ta, tb)] if ta and tb else []):
            if x is None:
                print(f"{label}: not in {before}")
                continue
            ma, mb = measures(x), measures(y)
            changes = [f"{name} {_change(ma[name][0], mb[name][0], *mb[name][1:])}" for name in mb]
            worse += sum(c.endswith("WORSE") for c in changes)
            print(f"{label}: " + "; ".join(changes))
        pa, pb = a["pages"].get(which), b["pages"].get(which)
        if pa and pb:
            ma, mb = page_measures(pa), page_measures(pb)
            changes = [f"{name} {_change(ma[name][0], mb[name][0], *mb[name][1:])}" for name in mb]
            worse += sum(c.endswith("WORSE") for c in changes)
            print("; ".join(changes))
    print(f"changes beyond the tolerance for the worse: {worse}")


def main(argv: list[str]) -> None:
    if len(argv) == 2 and argv[0] in ("build", "score"):
        (build if argv[0] == "build" else score)(Path(argv[1]))
    elif len(argv) == 3 and argv[0] == "compare":
        compare(Path(argv[1]), Path(argv[2]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

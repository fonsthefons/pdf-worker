"""Run engines.py on three quality books, one at a time, and score them (step S7).

  .venv/bin/python docs/experiments/drop-in/engines_run.py [ENGINE ...]

Per engine and book: convert with a 2 h limit (over it: again, first 150 pages only),
score with tools/book_score.py against the quality reference, and write
scratch/drop-in/engines/{scores.json,scores.md} (beside q-base and q-nomarks) and
scratch/drop-in/results/S7.md.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import book_score  # noqa: E402
import quality  # noqa: E402

DROP = ROOT / "scratch" / "drop-in"
OUT = DROP / "engines"
PY = DROP / "venv-engines" / "bin" / "python"
SCRIPT = ROOT / "docs" / "experiments" / "drop-in" / "engines.py"
LIMIT = 7200  # seconds per book
BOOKS = ["philosophy", "copleston", "ratzinger"]
PAIRS = {label: (pdf, ref) for label, pdf, ref, _, _ in quality.PAIRS}
COLUMNS = [
    "matched",
    "missing",
    "extra",
    "headings found",
    "headings real",
    "breaks found",
    "breaks real",
    "notes in body",
    "leftovers",
]


def convert(engine: str, label: str) -> dict:
    md = OUT / f"{engine}-{label}.md"
    note = ""
    for pages in (None, "1-150"):
        command = [str(PY), str(SCRIPT), engine, str(PAIRS[label][0]), str(md)]
        if pages:
            command += ["--pages", pages]
            note = "over 2 h: first 150 pages only"
        log = (OUT / f"{engine}-{label}.log").open("w")
        start = time.time()
        try:
            done = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=LIMIT)
        except subprocess.TimeoutExpired:
            if engine == "mineru":  # the server outlives its killed client
                subprocess.run([str(PY.parent / "mineru"), "server", "stop"], env=os.environ)
            continue
        minutes = round((time.time() - start) / 60, 1)
        if done.returncode:
            return {"error": f"exit {done.returncode}, see {log.name}", "minutes": minutes}
        return {"minutes": minutes, "note": note if pages else "", "md": str(md)}
    return {"error": "over 2 h, and over 2 h on the first 150 pages", "minutes": None}


def scored(entry: dict, label: str) -> dict:
    if "md" in entry:
        s = book_score.score_files(PAIRS[label][1], Path(entry["md"]), False)
        entry["score"] = {k: s[k] for k in s if k != "leftover_kinds"} if "error" not in s else None
        entry["error"] = s.get("error")
    return entry


def baseline(name: str, label: str) -> dict:
    result = json.loads((DROP / name / "quality.json").read_text(encoding="utf-8"))
    return {"minutes": None, "score": result["books"][label]}


def fmt(entry: dict) -> str:
    if not entry.get("score"):
        return f"not run: {entry.get('error')}"
    m = quality.measures(entry["score"])
    return " | ".join(quality._fmt(*m[k][:2]) for k in COLUMNS)


def render(results: dict) -> str:
    lines = [
        "# S7: Docling and MinerU against q-base and q-nomarks",
        "",
        "Cells: " + ", ".join(COLUMNS) + " (% or per 10,000 reference words).",
        "",
        "| book | engine | minutes | " + " | ".join(COLUMNS) + " | note |",
        "|---|---|---|" + "---|" * len(COLUMNS) + "---|",
    ]
    for label in BOOKS:
        rows = [("q-base", baseline("q-base", label)), ("q-nomarks", baseline("q-nomarks", label))]
        rows += [(e, results[e][label]) for e in results if label in results[e]]
        for name, entry in rows:
            cells = fmt(entry)
            if not entry.get("score"):
                cells = cells + " |" * (len(COLUMNS) - 1)
            minutes, note = entry.get("minutes") or "-", entry.get("note", "")
            lines.append(f"| {label} | {name} | {minutes} | {cells} | {note} |")
    return "\n".join(lines) + "\n"


def main(engines: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (DROP / "results").mkdir(exist_ok=True)
    path = OUT / "scores.json"
    results = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for engine in engines:
        for label in BOOKS:
            results.setdefault(engine, {})[label] = scored(convert(engine, label), label)
            path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
            (OUT / "scores.md").write_text(render(results), encoding="utf-8")
            (DROP / "results" / "S7.md").write_text(render(results), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:] or ["docling", "mineru"])

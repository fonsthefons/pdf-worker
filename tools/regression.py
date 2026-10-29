"""Before/after numbers for the test books (docs/layout-plan.md, Phase 0).

Usage:
  .venv/bin/python tools/regression.py build OUT_DIR
  .venv/bin/python tools/regression.py compare BEFORE_DIR AFTER_DIR

``build`` converts each book of ``BOOKS`` to ``OUT_DIR/<label>.md`` and writes its numbers
to ``OUT_DIR/<label>.json``. ``compare`` prints each number before -> after, the headings
lost and added, and writes ``AFTER_DIR/<label>.diff`` (the two .md files, 2 lines of
context). Build each run into a new folder: the review file (``<label>.fixes.tsv``) is
kept there, and a second build would start from the first one's decisions.
"""

import difflib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDFS = ROOT / "test_pdfs"
BOOKS = [
    ("kant", PDFS / "Critica de la Razon Pura - Immanuel Kant.pdf"),
    ("timeo_web", PDFS / "Platon - Timeo.pdf"),
    ("metafisica", PDFS / "metafisica_bad1.pdf"),
    ("lugones", PDFS / "lugones_imperio_jesuitico_1904.pdf"),
    ("dilexit", PDFS / "dilexit_nos.pdf"),
    ("dialogos", PDFS / "platon_dialogos_vi_good.pdf"),
    ("timeo_greek", PDFS / "Timeo_by_Platón_no_intro.pdf"),
    ("niebla", PDFS / "niebla_1914.pdf"),
]
NUMBERS = ["paragraphs", "headings", "notes", "splits"]

_SENTENCE_END_RE = re.compile(r"[.:;!?»”\"')\]]$")
_LETTER_ITEM_RE = re.compile(r"\w\)")  # "a)": a list item, not a split sentence
_NOT_PARAGRAPH = ("#", "[^", "    ", "![", "> ", "|")  # headings, notes, images, glosses, tables


def _blocks(md: Path):
    """The Markdown body's blocks (separated by blank lines), front matter skipped."""
    with md.open(encoding="utf-8") as f:
        if f.readline().rstrip("\n") == "---":
            for line in f:
                if line.rstrip("\n") == "---":
                    break
        block: list[str] = []
        for line in f:
            if line.strip():
                block.append(line.rstrip("\n"))
            elif block:
                yield "\n".join(block)
                block = []
        if block:
            yield "\n".join(block)


def numbers(md: Path, stats) -> dict:
    headings: list[str] = []
    splits = 0
    last = ""  # the paragraph before, its emphasis marks and escapes stripped
    for block in _blocks(md):
        if block.startswith("#"):
            headings.append(block.lstrip("#").strip())
        if block.startswith(_NOT_PARAGRAPH):
            continue
        text = block.strip("*_\\ ")
        if last and text and not _SENTENCE_END_RE.search(last):
            splits += text[0].islower() and not _LETTER_ITEM_RE.match(text)
        last = text
    return {
        "paragraphs": stats.paragraphs,
        "headings": headings,
        "notes": stats.notes,
        "splits": splits,
    }


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def build(out: Path) -> None:
    # The layout model's rows, as the inbox passes them (cached in scratch/paddle-home).
    os.environ.setdefault("PDF_WORKER_PADDLE_CACHE", str(ROOT / "scratch" / "paddle-home"))
    from pdf_worker.convert import convert_pdf
    from pdf_worker.paddle_ocr import layout_pages

    out.mkdir(parents=True, exist_ok=True)
    for label, pdf in BOOKS:
        print(f"{label}: {pdf.name}", flush=True)
        md = out / f"{label}.md"
        report = convert_pdf(
            pdf,
            md,
            "md",
            title=label,
            author="-",
            cover=False,
            fixes_path=out / f"{label}.fixes.tsv",
            layout_rows=layout_pages(pdf),
        )
        result = numbers(md, report.stats)
        _write_atomic(out / f"{label}.json", json.dumps(result, ensure_ascii=False, indent=1))
        print(f"  {', '.join(f'{k} {_count(result[k])}' for k in NUMBERS)}", flush=True)


def _count(value) -> int:
    return len(value) if isinstance(value, list) else value


def compare(before: Path, after: Path) -> None:
    for label, _ in BOOKS:
        a_json, b_json = before / f"{label}.json", after / f"{label}.json"
        if not (a_json.exists() and b_json.exists()):
            print(f"{label}: missing in {before if not a_json.exists() else after}")
            continue
        a, b = json.loads(a_json.read_text()), json.loads(b_json.read_text())
        changes = [
            f"{k} {_count(a[k])} -> {_count(b[k])}" for k in NUMBERS if _count(a[k]) != _count(b[k])
        ]
        print(f"{label}: {', '.join(changes) or 'same numbers'}")
        # Multisets, so a heading that appears once more or less counts too.
        lost = list(a["headings"])
        added = []
        for heading in b["headings"]:
            if heading in lost:
                lost.remove(heading)
            else:
                added.append(heading)
        for heading in lost:
            print(f"  - heading: {heading}")
        for heading in added:
            print(f"  + heading: {heading}")
        a_md, b_md = before / f"{label}.md", after / f"{label}.md"
        diff = list(
            difflib.unified_diff(
                a_md.read_text(encoding="utf-8").splitlines(keepends=True),
                b_md.read_text(encoding="utf-8").splitlines(keepends=True),
                str(a_md),
                str(b_md),
                n=2,
            )
        )
        _write_atomic(after / f"{label}.diff", "".join(diff))
        removed = sum(line.startswith("-") and not line.startswith("---") for line in diff)
        inserted = sum(line.startswith("+") and not line.startswith("+++") for line in diff)
        print(f"  diff: {len(diff)} lines (-{removed} +{inserted}) in {after / f'{label}.diff'}")


def main(argv: list[str]) -> None:
    if len(argv) == 2 and argv[0] == "build":
        build(Path(argv[1]))
    elif len(argv) == 3 and argv[0] == "compare":
        compare(Path(argv[1]), Path(argv[2]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

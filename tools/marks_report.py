"""What a marked book's style sheet says (docs/marks-plan.md, Phase 1): lines per how-sure
class, each kind's lines, the conflicts' most common pairs, the doubtful pages.

Usage:
  .venv/bin/python tools/marks_report.py [--paddle-cache DIR] BOOK.pdf...

Reads each book's marks file (never writes it); runs no model (cached Paddle rows only).
"""

import argparse
import os
import time
from collections import Counter
from pathlib import Path

from pdf_worker import marking, marks
from pdf_worker.document import open_pdf


def report(pdf: Path) -> None:
    start = time.monotonic()
    with open_pdf(pdf) as doc:
        book = marking.Book(doc, pdf, marks.default_marks_path(pdf))
        found = book.classified()
        pages = book.pages()
    labels = [  # blank lines (a text layer's spaces) left out
        label
        for page, page_labels in zip(pages, found.labels, strict=True)
        for line, label in zip(page.lines, page_labels, strict=True)
        if line.text.strip()
    ]
    sure = Counter(label.sure for label in labels)
    kinds = Counter(
        label.agree[0] if label.sure == "matched" else f"{label.kind} (marked)"
        for label in labels
        if label.sure in ("marked", "matched")
    )
    pairs = Counter(" / ".join(sorted(label.agree)) for label in labels if label.sure == "conflict")
    doubtful = [page for page in range(1, len(found.labels) + 1) if found.doubtful(page)]
    print(f"## {pdf.name} ({len(found.labels)} pages, {time.monotonic() - start:.0f} s)")
    print(
        "lines: " + ", ".join(f"{k} {sure[k]}" for k in ("marked", "matched", "conflict", "rules"))
    )
    print(f"odd (matched, placed or sized like no example): {sum(label.odd for label in labels)}")
    print("kinds: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
    print("conflicts: " + (", ".join(f"{k} {n}" for k, n in pairs.most_common(5)) or "none"))
    print(f"note numbers found: {sum(len(refs) for refs in found.refs)}")
    print(f"doubtful pages: {len(doubtful)} (first: {', '.join(map(str, doubtful[:10]))})")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--paddle-cache", type=Path, help="PaddleOCR-VL's cache folder.")
    args = parser.parse_args()
    if args.paddle_cache:
        os.environ["PDF_WORKER_PADDLE_CACHE"] = str(args.paddle_cache)
    for pdf in args.pdfs:
        report(pdf)


if __name__ == "__main__":
    main()

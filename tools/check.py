"""A quick check of the pipeline on sample pages of the test books: a few minutes, not an hour.

Usage:
  .venv/bin/python tools/check.py pick                    (choose the sample pages once)
  .venv/bin/python tools/check.py build OUT_DIR [--full]
  .venv/bin/python tools/check.py compare BEFORE_DIR AFTER_DIR

``pick`` writes ``tools/check_pages.json`` (commit it): for each book of ``regression.BOOKS``
and ``quality.PAIRS``, a few windows of consecutive pages, the first window and those with
the most titles and footnotes in the cached model rows. ``build`` cuts those pages out of
each book (``scratch/check-pdfs``), gives the cut PDF the original's cached rows, remapped
to the new page numbers (a page without cached rows is read by the model, once), converts
it as ``regression.convert_book`` does, books in parallel, and runs both headings page sets
(``headings_test.run``). A book's marks and PDF tags are not carried into the cut. ``compare``
is ``regression.compare`` for these books plus the page sets' scores
(``quality.page_measures``). ``--full`` is ``regression.build`` plus ``quality.build``: every
book whole, an hour. Build each run into a new folder.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import headings_test
import pymupdf
import quality
import regression

ROOT = Path(__file__).resolve().parent.parent
PAGES = Path(__file__).with_name("check_pages.json")
CUTS = ROOT / "scratch" / "check-pdfs"
WINDOWS, WIDTH = 4, 8  # sample pages per book: up to this many windows of this many pages
WORKERS = 6
# The model rows are cached in scratch/paddle-home, as in regression.py (read before convert_book).
os.environ.setdefault("PDF_WORKER_PADDLE_CACHE", str(ROOT / "scratch" / "paddle-home"))


def books() -> dict[str, tuple[Path, bool]]:
    """Each unique book: label -> (PDF, built from PaddleOCR-VL's rows)."""
    found = {label: (pdf, False) for label, pdf in regression.BOOKS}
    for label, pdf, _, _, paddle in quality.PAIRS:
        found.setdefault(label, (pdf, paddle))
    return found


def _score(row: dict) -> int:
    labels = [b.get("label") for b in row["blocks"]]
    return 3 * sum(x in ("doc_title", "paragraph_title") for x in labels) + 2 * (
        "footnote" in labels
    )


def pick_pages(rows: dict[int, dict], page_count: int) -> list[int]:
    """The first window of pages, then the windows with the most titles and footnotes
    (``_score``); every page of a book that fits in the windows."""
    if page_count <= WINDOWS * WIDTH:
        return list(range(page_count))
    score = [_score(rows.get(i, {"blocks": []})) for i in range(page_count)]
    starts = [0]
    for _ in range(WINDOWS - 1):
        free = [
            s for s in range(page_count - WIDTH + 1) if all(abs(s - t) >= WIDTH for t in starts)
        ]
        starts.append(max(free, key=lambda s: (sum(score[s : s + WIDTH]), -s)))
    return sorted(p for s in starts for p in range(s, s + WIDTH))


def remap(rows: dict[int, dict], pages: list[int]) -> dict[int, dict]:
    """The rows of the original's ``pages``, numbered as in the cut (uncached pages left out)."""
    return {new: {**rows[old], "page": new} for new, old in enumerate(pages) if old in rows}


def cut(pdf: Path, pages: list[int], label: str) -> Path:
    """``pdf``'s ``pages`` as a PDF in ``CUTS`` (kept: its cache key is its bytes' hash)."""
    digest = hashlib.sha1(json.dumps(pages).encode()).hexdigest()[:8]
    out = CUTS / f"{label}-{digest}.pdf"
    if not out.exists():
        CUTS.mkdir(parents=True, exist_ok=True)
        # insert_pdf, not select: select fails on some books' structure trees.
        with pymupdf.open(pdf) as doc, pymupdf.open() as sub:
            for page in pages:
                sub.insert_pdf(doc, from_page=page, to_page=page)
            sub.save(out.with_name(f".{out.name}.tmp"), garbage=3, deflate=True)
        os.replace(out.with_name(f".{out.name}.tmp"), out)
    return out


def _give_rows(pdf: Path, sub: Path, pages: list[int], paddle: bool) -> int:
    """Cache the original's rows, remapped, as the cut's; returns the pages left to the model."""
    from pdf_worker.paddle_ocr import LAYOUT_MODEL, _pages_cache, _read_rows, cached_rows

    cache = _pages_cache(sub, LAYOUT_MODEL, "layout") if not paddle else _pages_cache(sub)
    have = _read_rows(cache)
    new = {
        k: v for k, v in remap(cached_rows(pdf, layout=not paddle), pages).items() if k not in have
    }
    if new:
        cache.parent.mkdir(parents=True, exist_ok=True)
        with cache.open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in new.values())
    return len(pages) - len(have) - len(new)


def _build_book(label: str, pdf: Path, paddle: bool, pages: list[int], out: Path) -> str:
    try:
        return _convert_cut(label, pdf, paddle, pages, out)
    except Exception:  # pymupdf's errors can't cross the process boundary
        raise RuntimeError(f"{label}:\n{traceback.format_exc()}") from None


def _convert_cut(label: str, pdf: Path, paddle: bool, pages: list[int], out: Path) -> str:
    sub = cut(pdf, pages, label)
    unread = _give_rows(pdf, sub, pages, paddle)
    note = f", {unread} pages' rows not cached: read by the model" if unread else ""
    result = regression.convert_book(label, sub, out, paddle)
    numbers = ", ".join(f"{k} {regression._count(result[k])}" for k in regression.NUMBERS)
    return f"{label}: {len(pages)} pages{note}; {numbers}"


def _headings(out: Path, which: str) -> str:
    headings_test.run(out / quality.PAGE_SETS[which], quality.PAGE_TESTS[which])
    return f"headings test pages: {which}"


def build(out: Path, full: bool = False) -> None:
    if full:
        regression.build(out)
        quality.build(out)
        return
    out.mkdir(parents=True, exist_ok=True)
    picked = json.loads(PAGES.read_text(encoding="utf-8"))
    start = time.time()
    with ProcessPoolExecutor(WORKERS) as pool:
        jobs = [pool.submit(_headings, out, which) for which in quality.SETS]
        jobs += [
            pool.submit(_build_book, label, pdf, paddle, picked[label], out)
            for label, (pdf, paddle) in books().items()
        ]
        for job in jobs:
            print(job.result(), flush=True)
    print(f"done in {time.time() - start:.0f} s")


def pick() -> None:
    from pdf_worker.document import open_pdf
    from pdf_worker.paddle_ocr import cached_rows

    picked = {}
    for label, (pdf, paddle) in books().items():
        with open_pdf(pdf) as doc:
            count = doc.page_count
        picked[label] = pick_pages(cached_rows(pdf, layout=not paddle), count)
        print(f"{label}: {len(picked[label])} of {count} pages", flush=True)
    regression._write_atomic(PAGES, json.dumps(picked, indent=1) + "\n")


def compare(before: Path, after: Path) -> None:
    regression.compare(before, after, list(books()))
    for which in quality.SETS:
        pa, pb = quality._pages(before, which), quality._pages(after, which)
        if pa and pb:
            ma, mb = quality.page_measures(pa), quality.page_measures(pb)
            changes = [f"{n} {quality._change(ma[n][0], mb[n][0], *mb[n][1:])}" for n in mb]
            print(f"headings test pages, {which}: " + "; ".join(changes))


def main(argv: list[str]) -> None:
    options = argparse.ArgumentParser(prog="check.py")
    options.add_argument("command", choices=["pick", "build", "compare"])
    options.add_argument("dirs", nargs="*", type=Path)
    options.add_argument("--full", action="store_true")
    args = options.parse_args(argv)
    if args.command == "pick" and not args.dirs:
        pick()
    elif args.command == "build" and len(args.dirs) == 1:
        build(args.dirs[0], args.full)
    elif args.command == "compare" and len(args.dirs) == 2:
        compare(*args.dirs)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

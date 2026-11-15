"""Variant D of the drop-in experiment (scratch/drop-in/results/S4.md, "Extra variant"): cut
each two-page spread of a scan into its two pages before the book is dropped in.

Usage (repo root, .venv/bin/python):
  split_spreads.py detect [BOOK.pdf...]            no books: the experiment's twenty PDFs
  split_spreads.py split BOOK.pdf OUT.pdf [--sheets A-B]
  split_spreads.py order BOOK.pdf OURS [--pages N...]
  split_spreads.py selftest

``detect``: a sheet is a spread when it is wider than high and, of its text layer's lines
(``layout.page_lines``, lines under four characters left out), none crosses the band around
its middle (``BAND``) and each side holds at least a third. "By the rule alone" counts the
sheets without the wider-than-high test (the brief's rule: it took 40 two-column pages of
three upright books for spreads). Confirmed: two page numbers at the same height, the right
one the left one's plus one, or the top line of both sides at the same height and short. In
a book where most sheets with text are spreads, a wider-than-high sheet with no crossing
line is cut too, at the book's gutter ("by the book": a page that ends a chapter beside a
full one). A sheet without text is never cut. The twenty: a source without a text layer is
judged on the PDF the baseline built from it (scratch/drop-in/audit-base/file_work).

``split``: each spread becomes two pages, left then right (the sheet twice, each with its
half as MediaBox: picture and text layer kept, the other half outside the page); other
sheets are copied. ``--sheets`` keeps only those. ``OUT.pages.json``: new page -> sheet, side.

``order``: how much of the printed order our text keeps. OURS is an EPUB or a ``.md``
(``audit.read_output``). Per printed page of BOOK.pdf (a sheet's half where ``detect`` says
spread), for each line and the next: the join is the last three words of the one and the
first three of the next (lower-cased, no punctuation; lines ending in a hyphen or with under
three words have none). Figures: joins found in ours, lines whose first four words are found
(the line after a hyphen-ended one left out: it starts with half a word), lines whose last
four are found (hyphen-ended ones left out), and the sheets (of ten joins or more) with
under half their joins found: the woven ones. Running heads and page numbers are lines too,
so no book reaches 100%: compare with books that are not woven. The lines are the text
layer's: a page the OCR garbled is compared with its garbled lines, and scores well when
ours repeats them. ``--pages`` prints the
figures of single sheets and, for an EPUB, our lines between that page's mark and the next.
"""

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(Path(__file__).parent), str(ROOT / "tools")]

from book_score import words  # noqa: E402
from regression import _write_atomic  # noqa: E402

from pdf_worker.document import open_pdf  # noqa: E402
from pdf_worker.layout import page_lines  # noqa: E402

BAND = 0.03  # of the sheet's width, each side of its middle
SHARE = 1 / 3  # of the lines, on each side
MIN_CHARS = 4
LEVEL = 4.0  # points: "at the same height"
HYPHENS = ("-", "‐", "¬", "–")
SHOWN = 12  # doubtful sheets printed per book
OUR_LINES = 150  # of ours, per sheet of --pages
MIN_JOINS = 10  # a sheet with fewer isn't counted as woven or not


@dataclass
class Sheet:
    width: float
    lines: int = 0  # of four characters or more
    left: int = 0
    right: int = 0
    crossing: int = 0
    gutter: float = 0.0  # where to cut
    confirmed: str = ""  # "numbers", "heads"
    landscape: bool = False
    by_book: bool = False

    @property
    def rule(self) -> bool:
        """The brief's rule alone: it also takes two-column pages (indexes, tables)."""
        return not self.crossing and min(self.left, self.right) >= max(1, self.lines * SHARE)

    @property
    def spread(self) -> bool:
        return self.rule and self.landscape

    @property
    def cut(self) -> bool:
        return self.spread or self.by_book

    def numbers(self) -> str:
        return f"lines {self.lines} left {self.left} right {self.right} crossing {self.crossing}"


def _rows(page) -> list[tuple[float, float, float, str]]:
    """(x0, x1, baseline, text) of the page's lines, in ``page_lines`` order."""
    return [(ln.bbox[0], ln.bbox[2], ln.baseline, ln.text.strip()) for ln in page_lines(page)]


def judge(rows, width: float, height: float) -> Sheet:
    mid = width / 2
    long = [r for r in rows if len(r[3]) >= MIN_CHARS]
    sheet = Sheet(width, len(long), gutter=mid, landscape=width > height)
    sheet.crossing = sum(x0 < mid - BAND * width and x1 > mid + BAND * width for x0, x1, *_ in long)
    left = [r for r in long if r[0] + r[1] < width]
    right = [r for r in long if r[0] + r[1] >= width]
    sheet.left, sheet.right = len(left), len(right)
    if left and right and max(r[1] for r in left) < min(r[0] for r in right):
        sheet.gutter = (max(r[1] for r in left) + min(r[0] for r in right)) / 2
    numbers = [r for r in rows if r[3].isdigit()]
    if any(
        a[1] < mid < b[0] and abs(a[2] - b[2]) <= LEVEL and int(b[3]) == int(a[3]) + 1
        for a in numbers
        for b in numbers
    ):
        sheet.confirmed = "numbers"
    elif left and right:
        tops = [min(side, key=lambda r: r[2]) for side in (left, right)]
        widest = [max(r[1] - r[0] for r in side) for side in (left, right)]
        short = all(t[1] - t[0] < 0.6 * w for t, w in zip(tops, widest, strict=True))
        if short and abs(tops[0][2] - tops[1][2]) <= LEVEL:
            sheet.confirmed = "heads"
    return sheet


def judge_book(doc) -> list[Sheet]:
    sheets = [judge(_rows(page), page.rect.width, page.rect.height) for page in doc]
    spreads = [s for s in sheets if s.spread]
    if spreads and 2 * len(spreads) > sum(s.lines > 0 for s in sheets):
        gutter = statistics.median(s.gutter / s.width for s in spreads)
        for s in sheets:
            if not s.spread and s.lines and not s.crossing and s.landscape:
                s.by_book, s.gutter = True, gutter * s.width
    return sheets


def _twenty() -> list[tuple[str, Path]]:
    import quality

    manifest = json.loads((Path(__file__).parent / "books_sd.json").read_text(encoding="utf-8"))
    sd = [ROOT / b["path"] for b in manifest if b["path"].endswith(".pdf")]
    return [(label, pdf) for label, pdf, *_ in quality.PAIRS] + [(p.stem, p) for p in sd]


def detect(books: list[tuple[str, Path]]) -> None:
    for label, pdf in books:
        with open_pdf(pdf) as doc:
            sheets = judge_book(doc)
        built = ROOT / "scratch/drop-in/audit-base/file_work" / pdf.name / pdf.name
        if 2 * sum(s.lines > 0 for s in sheets) < len(sheets) and built.exists():
            label += " (the baseline's OCR)"
            with open_pdf(built) as doc:
                sheets = judge_book(doc)
        spreads = [s for s in sheets if s.spread]
        mostly = 2 * len(spreads) > sum(s.lines > 0 for s in sheets)
        print(
            f"{label}: sheets {len(sheets)}, with text {sum(s.lines > 0 for s in sheets)}, "
            f"spreads {len(spreads)} (confirmed {sum(bool(s.confirmed) for s in spreads)}, "
            f"landscape {sum(s.landscape for s in spreads)}), "
            f"by the book {sum(s.by_book for s in sheets)}, "
            f"landscape sheets {sum(s.landscape for s in sheets)}, "
            f"by the rule alone {sum(s.rule for s in sheets)}"
        )
        # Doubtful: a landscape sheet that goes against the book's other sheets.
        doubtful = [(n, s) for n, s in enumerate(sheets, 1) if s.landscape and s.spread != mostly]
        for n, s in doubtful[:SHOWN]:
            what = "spread" if s.spread else "cut by the book" if s.by_book else "not cut"
            print(f"  sheet {n}: {what}; {s.numbers()} confirmed {s.confirmed or 'no'}")
        if len(doubtful) > SHOWN:
            print(f"  ... and {len(doubtful) - SHOWN} more doubtful sheets")


def _half(page, sheet: Sheet, side: int) -> pymupdf.Rect:
    """The left (0) or right (1) half of the page, as a MediaBox (PDF coordinates)."""
    r = page.rect
    clip = pymupdf.Rect(r.x0, r.y0, sheet.gutter, r.y1)
    if side:
        clip = pymupdf.Rect(sheet.gutter, r.y0, r.x1, r.y1)
    box = clip * page.derotation_matrix * ~page.transformation_matrix
    return box.normalize()


def split(src: Path, out: Path, keep: range | None = None) -> list[dict]:
    with open_pdf(src) as doc:
        sheets = judge_book(doc)
        kept = [n for n in range(len(sheets)) if keep is None or n + 1 in keep]
        doc.select(kept)
        for k in reversed(range(len(kept))):  # from the end: a copy moves what follows it
            if sheets[kept[k]].cut:
                boxes = [_half(doc[k], sheets[kept[k]], side) for side in (0, 1)]
                # A full copy: a page listed twice by select() is one object, one MediaBox.
                doc.fullcopy_page(k, k + 1 if k + 1 < doc.page_count else -1)
                for side in (0, 1):
                    doc[k + side].set_mediabox(boxes[side])
        pages = [
            {"page": 0, "sheet": n + 1, "side": side}
            for n in kept
            for side in (("left", "right") if sheets[n].cut else ("whole",))
        ]
        for number, entry in enumerate(pages, 1):
            entry["page"] = number
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f".{out.name}.tmp")
        doc.save(tmp, garbage=3, deflate=True)
        os.replace(tmp, out)
    _write_atomic(out.with_suffix(".pages.json"), json.dumps(pages, indent=1) + "\n")
    return pages


def count(lines: list[str], grams: dict[int, set[tuple]]) -> Counter:
    """The three figures' counts for one printed page's lines against ours' word runs."""
    c: Counter = Counter()
    ws = [words(text) for text in lines]
    hyphen = [text.rstrip().endswith(HYPHENS) for text in lines]
    for k, w in enumerate(ws):
        if len(w) >= 4 and not (k and hyphen[k - 1]):
            c["starts"] += 1
            c["starts_found"] += tuple(w[:4]) in grams[4]
        if len(w) >= 4 and not hyphen[k]:
            c["ends"] += 1
            c["ends_found"] += tuple(w[-4:]) in grams[4]
        if k + 1 < len(ws) and not hyphen[k] and len(w) >= 3 and len(ws[k + 1]) >= 3:
            c["joins"] += 1
            c["joins_found"] += tuple(w[-3:] + ws[k + 1][:3]) in grams[6]
    return c


def figures(c: Counter) -> str:
    def pct(key):
        return f"{c[key + '_found'] / c[key]:.1%} ({c[key + '_found']}/{c[key]})" if c[key] else "-"

    return f"joins {pct('joins')}, line starts {pct('starts')}, line ends {pct('ends')}"


def order(pdf: Path, ours_path: Path, show: list[int] = (), only: range | None = None) -> Counter:
    """``only``: count those sheets alone (a book of which ours holds a part)."""
    import audit

    ours = audit.read_output(ours_path)
    runs = [[w for line in ours.lines for w in words(audit._plain(line))]]
    runs += [words(audit._plain(note)) for note in ours.notes.values()]
    grams = {n: {tuple(r[k : k + n]) for r in runs for k in range(len(r) - n + 1)} for n in (4, 6)}
    slices = audit._slices(ours, [], True) if ours.pages else {}
    total: Counter = Counter()
    with open_pdf(pdf) as doc:
        sheets = judge_book(doc)
        for n, (page, sheet) in enumerate(zip(doc, sheets, strict=True), 1):
            if only is not None and n not in only:
                continue
            rows = _rows(page)
            sides = [rows]
            if sheet.cut:
                sides = [
                    [r for r in rows if (r[0] + r[1] >= 2 * sheet.gutter) == s] for s in (0, 1)
                ]
            here: Counter = Counter()
            for side in sides:
                here += count([r[3] for r in side], grams)
                total["printed pages"] += 1
            total += here
            total["sheets"] += here["joins"] >= MIN_JOINS
            total["woven"] += here["joins"] >= MIN_JOINS and 2 * here["joins_found"] < here["joins"]
            if n in show:
                print(f"sheet {n} ({len(sides)} printed page(s)): {figures(here)}")
                a, b = slices.get(n - 1, (0, 0))
                print(
                    f"our lines {a + 1}-{b} (at most {OUR_LINES})",
                    *ours.lines[a:b][:OUR_LINES],
                    sep="\n",
                )
    print(
        f"{pdf.stem} / {ours_path.name}: printed pages {total['printed pages']}, {figures(total)}, "
        f"sheets with under half their joins {total['woven']} of {total['sheets']}"
    )
    return total


def selftest() -> None:
    work = ROOT / "scratch" / "drop-in" / "spreads_selftest"
    work.mkdir(parents=True, exist_ok=True)
    sides = [
        [f"{side} línea {k} " + " ".join(f"{side[0]}{k}p{j}" for j in range(6)) for k in range(12)]
        for side in ("izquierda", "derecha")
    ]
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=560)
    for x, lines, number in ((60, sides[0], "68"), (460, sides[1], "69")):
        for k, line in enumerate(lines):
            page.insert_text((x, 80 + 14 * k), line, fontsize=9)
        page.insert_text((x + 140, 520), number, fontsize=9)
    doc.save(work / "spread.pdf")
    doc = pymupdf.open()
    page = doc.new_page()
    for k, line in enumerate(sides[0]):
        page.insert_text((72, 80 + 14 * k), line, fontsize=11)
    doc.save(work / "single.pdf")

    with open_pdf(work / "spread.pdf") as doc:
        (sheet,) = judge_book(doc)
    assert sheet.spread and sheet.confirmed == "numbers" and (sheet.left, sheet.right) == (12, 12)
    assert 330 < sheet.gutter < 460, sheet
    pages = split(work / "spread.pdf", work / "spread.split.pdf")
    assert [(p["sheet"], p["side"]) for p in pages] == [(1, "left"), (1, "right")], pages
    assert json.loads((work / "spread.split.pages.json").read_text()) == pages
    with open_pdf(work / "spread.split.pdf") as doc:
        got = [[row[3] for row in _rows(page)] for page in doc]
        assert not any(s.cut for s in judge_book(doc))
    assert got == [sides[0] + ["68"], sides[1] + ["69"]], got
    assert [p["side"] for p in split(work / "single.pdf", work / "single.split.pdf")] == ["whole"]
    with open_pdf(work / "single.split.pdf") as doc:
        assert doc.page_count == 1 and [row[3] for row in _rows(doc[0])] == sides[0]
    # A crossing title makes a sheet one page; a short last page is cut by the book.
    rows = [(60.0, 340.0, 80.0 + k, "texto de la línea") for k in range(9)]
    both = rows + [(x0 + 400, x1 + 400, y, t) for x0, x1, y, t in rows]
    assert judge(both, 800, 560).spread
    assert not judge(both + [(200.0, 600.0, 40.0, "un título ancho")], 800, 560).spread
    assert not judge(both + rows + rows, 800, 560).spread  # 27 lines left, 9 right
    # An upright page in two columns.
    columns = judge([(x0 * 0.7, x1 * 0.7, y, t) for x0, x1, y, t in both], 560, 800)
    assert columns.rule and not columns.spread

    straight = work / "straight.md"
    _write_atomic(
        straight, "---\ntitle: t\n---\n\n" + "\n\n".join(" ".join(s) for s in sides) + "\n"
    )
    woven = work / "woven.md"
    pairs = [line for pair in zip(*sides, strict=True) for line in pair]
    _write_atomic(woven, "---\ntitle: t\n---\n\n" + " ".join(pairs) + "\n")
    for pdf in ("spread.pdf", "spread.split.pdf"):
        c = order(work / pdf, straight)
        assert c["joins"] == 22 == c["joins_found"] and c["printed pages"] == 2, c
        assert c["woven"] == 0 < c["sheets"], c
        c = order(work / pdf, woven)
        assert c["joins_found"] < 0.5 * c["joins"] and c["starts_found"] == c["starts"] == 24, c
        assert c["woven"] == c["sheets"] > 0, c
    none = count(["uno dos tres cua-", "tro cinco seis siete", "a b c d"], {4: set(), 6: set()})
    assert (none["starts"], none["ends"], none["joins"], none.total()) == (2, 2, 1, 5), none
    print("ok")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("detect").add_argument("books", type=Path, nargs="*")
    p = sub.add_parser("split")
    p.add_argument("book", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--sheets", help="A-B: only those sheets")
    p = sub.add_parser("order")
    p.add_argument("book", type=Path)
    p.add_argument("ours", type=Path)
    p.add_argument("--pages", type=int, nargs="+", default=[])
    sub.add_parser("selftest")
    args = parser.parse_args(argv)
    if args.command == "detect":
        detect([(b.stem, b) for b in args.books] or _twenty())
    elif args.command == "split":
        first, _, last = (args.sheets or "").partition("-")
        keep = range(int(first), int(last or first) + 1) if first else None
        pages = split(args.book, args.out, keep)
        cut = sum(p["side"] == "left" for p in pages)
        print(f"{args.out}: {len(pages)} pages from {len(pages) - cut} sheets, {cut} cut")
    elif args.command == "order":
        order(args.book, args.ours, args.pages)
    else:
        selftest()


if __name__ == "__main__":
    main(sys.argv[1:])

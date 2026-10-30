"""Today's rules against the layout model, part by part (docs/layout-plan.md, Phase 4).

Usage: .venv/bin/python tools/parts_report.py OUT_DIR [LABEL...] [--show PAGE...]

Converts each test book (``regression.BOOKS``, or the LABELs given) to Markdown in
OUT_DIR as ``regression.py build`` does, watching the pipeline's decisions on the way,
and compares them with the layout model's labels (``paddle_ocr.layout_pages``, cached
in scratch/paddle-home). For each part it counts the lines (pages, for contents) both
call that part, only the rule, only the model, with the 5 pages (1-based) holding most
of each. Furniture (running heads, page numbers) is left out of every count.

- footnote region: lines of the page's footnote region (``footnotes._find_region``) /
  ``footnote``, ``vision_footnote``.
- footnotes: the lines of that region kept as notes (``_collect_footnotes`` drops a
  region whose markers it can't match) / the same labels.
- contents (pages): ``structure._is_contents_page`` / more than half the page's lines in
  ``content`` boxes.
- bibliography: lines of blocks the review takes for references (``fixes.Review``: under
  a bibliography or index heading, or ``_is_reference``) / ``reference``,
  ``reference_content``.
- margins: lines of the margin column ``margins.split_columns`` found / ``aside_text``.
- paragraph starts: among lines of the pipeline's paragraphs inside a ``text`` box, the
  first line of a paragraph / the first line of its box. Of the model's own starts, those
  in the page's first text box are counted apart (often a paragraph from the page before).
- headings: lines of headings / ``doc_title``, ``paragraph_title``.
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from regression import BOOKS

from pdf_worker import fixes, footnotes, margins, structure
from pdf_worker.convert import convert_pdf
from pdf_worker.layout import box_labels
from pdf_worker.paddle_ocr import layout_pages
from pdf_worker.structure import Heading, Paragraph

os.environ.setdefault(
    "PDF_WORKER_PADDLE_CACHE", str(Path(__file__).resolve().parents[1] / "scratch" / "paddle-home")
)

MODEL = {
    "footnote region": {"footnote", "vision_footnote"},
    "footnotes": {"footnote", "vision_footnote"},
    "bibliography": {"reference", "reference_content"},
    "margins": {"aside_text"},
    "headings": {"doc_title", "paragraph_title"},
}
PARTS = [
    "footnote region",
    "footnotes",
    "contents",
    "bibliography",
    "margins",
    "paragraph starts",
    "headings",
]
KINDS = ["both", "rule", "model"]
TOP = "model, first box of the page"  # paragraph starts only: part of "model"


class Watch:
    """The pipeline's decisions on one book, page by page."""

    def __init__(self, rows: dict[int, dict]):
        self.rows = rows
        self.pages: dict[int, dict] = {}
        self.page = -1
        self.blocks: dict[tuple[int, float], tuple[str, list]] = {}  # (page, top) -> kind, lines
        self.references: set[tuple[int, float]] = set()

    def start_page(self, page, index, profile, layout, lines) -> None:
        self.page = index
        furniture = {_key(line) for line in layout.furniture}
        body = {_key(bl.line) for bl in layout.lines}
        row = self.rows.get(index)
        labels, boxes = [""] * len(lines), [""] * len(lines)
        if row:
            labels = box_labels(page, row, lines)
            numbered = [{**block, "label": str(n)} for n, block in enumerate(row["blocks"])]
            boxes = box_labels(page, {**row, "blocks": numbered}, lines)
        texts = {i for i, ln in enumerate(lines) if ln.text.strip() and _key(ln) not in furniture}
        # A page of chapter endnotes has no footnotes; the lines the body leaves there are
        # the notes' hung numbers.
        notes = set() if index in profile.chapter_notes.note_pages else texts
        self.pages[index] = {
            "lines": lines,
            "spans": {id(span): i for i, line in enumerate(lines) for span in line.spans},
            "labels": labels,
            "boxes": boxes,
            "texts": texts,
            "contents": False,
            "footnote region": set(REGION),
            "footnotes": {i for i in notes if _key(lines[i]) not in body},
            "margins": set(),
            "bibliography": set(),
            "headings": set(),
            "para": set(),
            "start": set(),
        }

    def find(self, page: int, line) -> list[int]:
        """The page's lines that ``line`` is: the pipeline trims and joins lines but keeps
        their spans (the same objects)."""
        spans = self.pages[page]["spans"]
        return sorted({spans[id(span)] for span in line.spans if id(span) in spans})

    def finish(self) -> None:
        for (page, top), (kind, seen) in self.blocks.items():
            first = True
            for line_page, line in seen:
                if line_page not in self.pages:
                    continue
                found = self.find(line_page, line)
                parts = self.pages[line_page]
                if kind == "heading":
                    parts["headings"].update(found)
                else:
                    parts["para"].update(found)
                    if first and found:
                        parts["start"].add(min(found, key=lambda i: parts["lines"][i].bbox[1::-1]))
                if (page, top) in self.references:
                    parts["bibliography"].update(found)
                first = False

    def show(self, page: int) -> None:
        """Each line of a page (1-based) with the rule's parts and the model's label."""
        parts = self.pages.get(page - 1)
        if parts is None:
            print(f"p. {page}: not built")
            return
        print(f"p. {page}" + (" (contents page)" if parts["contents"] else ""))
        flags = [
            ("footnote region", "R"),
            ("footnotes", "F"),
            ("bibliography", "B"),
            ("margins", "M"),
            ("headings", "H"),
            ("para", "P"),
            ("start", "S"),
        ]
        for i, line in enumerate(parts["lines"]):
            rule = "".join(f for name, f in flags if i in parts[name])
            rule = rule if i in parts["texts"] else "furn"
            label = parts["labels"][i] or "-"
            print(f"  {rule:6} {label:17} s{line.size:5.1f} {line.text[:90]!r}")

    def counts(self) -> dict[str, dict[str, Counter]]:
        """part -> kind -> {page: count}."""
        out = {part: {kind: Counter() for kind in KINDS} for part in PARTS}
        for page, parts in self.pages.items():
            labels, texts = parts["labels"], parts["texts"]
            for part in PARTS:
                if part == "contents":
                    content = sum(labels[i] == "content" for i in texts)
                    rule, model = {0} if parts["contents"] else set(), set()
                    if content > 0.5 * len(texts):
                        model = {0}
                elif part == "paragraph starts":
                    inside = {i for i in parts["para"] & texts if labels[i] == "text"}
                    rule = parts["start"] & inside
                    model = {i for i in inside if _first_of_box(parts, i)}
                else:
                    rule = parts[part] & texts
                    model = {i for i in texts if labels[i] in MODEL[part]}
                for kind, found in zip(
                    KINDS, (rule & model, rule - model, model - rule), strict=True
                ):
                    if found:
                        out[part][kind][page] = len(found)
                if part == "paragraph starts" and model - rule:
                    # The page's first text box: often a paragraph running on from the page
                    # before, which Phase 5 would not start anew.
                    lines = parts["lines"]
                    first = min(model, key=lambda i: lines[i].bbox[1::-1])
                    if first not in rule:
                        out[part].setdefault(TOP, Counter())[page] = 1
        return out


def _first_of_box(parts: dict, i: int) -> bool:
    lines, boxes = parts["lines"], parts["boxes"]
    same = [j for j in parts["texts"] if boxes[j] == boxes[i]]
    return i == min(same, key=lambda j: lines[j].bbox[1::-1])


def _key(line) -> tuple:
    return line.bbox, line.text


WATCH: Watch | None = None
LINES: list = []  # the lines ``layout_page`` read last
REGION: list[int] = []  # and the footnote region it found among them
_page_lines = footnotes.page_lines
_find_region = footnotes._find_region
_layout_page = structure.layout_page
_is_contents_page = structure._is_contents_page
_is_margin_column = margins._is_margin_column
_add = structure._Builder.add
_add_line = structure._State._add_line
_flush = structure._State._flush
_apply = fixes.Review.apply


def _watch_page_lines(page):
    LINES[:] = _page_lines(page)
    return LINES[:]


def _watch_find_region(*args, **kwargs):
    region = _find_region(*args, **kwargs)
    REGION[:] = region or []
    return region


def _watch_layout_page(page, index, profile, previous_label=None):
    REGION.clear()  # pages of chapter notes don't look for one
    layout = _layout_page(page, index, profile, previous_label)
    WATCH.start_page(page, index, profile, layout, LINES[:])
    return layout


def _watch_contents(lines):
    found = _is_contents_page(lines)
    WATCH.pages[WATCH.page]["contents"] = found
    return found


def _watch_margin(margin, body, left, right):
    found = _is_margin_column(margin, body, left, right)
    if found:
        page = WATCH.pages[WATCH.page]
        for bl in margin:
            page["margins"].update(WATCH.find(WATCH.page, bl.line))
    return found


def _watch_add(self, text, line, page):
    vars(self).setdefault("seen", []).append((page, line))
    _add(self, text, line, page)


def _watch_add_line(self, body_line, margins, new_page):
    yield from _add_line(self, body_line, margins, new_page)
    if self.current.kind == "table":  # a table's rows don't go through ``add``
        vars(self.current).setdefault("seen", []).append((self.page_index, body_line.line))


def _watch_flush(self):
    builder = self.current
    for block in _flush(self):
        if isinstance(block, Heading | Paragraph) and (block.page, block.top) == (
            builder.page,
            builder.top,
        ):
            kind = "heading" if isinstance(block, Heading) else "para"
            WATCH.blocks[(block.page, block.top)] = (kind, vars(builder).get("seen", []))
        yield block


def _watch_apply(self, blocks):
    for block in _apply(self, blocks):
        if self.reference and isinstance(block, Heading | Paragraph):
            WATCH.references.add((block.page, block.top))
        yield block


# Watching, not changing: each wrapper returns what the pipeline's own function does.
footnotes.page_lines = _watch_page_lines
footnotes._find_region = _watch_find_region
structure.layout_page = _watch_layout_page
structure._is_contents_page = _watch_contents
margins._is_margin_column = _watch_margin
structure._Builder.add = _watch_add
structure._State._add_line = _watch_add_line
structure._State._flush = _watch_flush
fixes.Review.apply = _watch_apply


def _examples(pages: Counter) -> str:
    return ", ".join(str(page + 1) for page, _ in pages.most_common(5))


def report(out: Path, labels: list[str], show: list[int]) -> None:
    global WATCH
    out.mkdir(parents=True, exist_ok=True)
    totals = {part: Counter() for part in PARTS}
    for label, pdf in BOOKS:
        if labels and label not in labels:
            continue
        rows = layout_pages(pdf)
        WATCH = Watch(rows)
        convert_pdf(
            pdf,
            out / f"{label}.md",
            "md",
            title=label,
            author="-",
            cover=False,
            fixes_path=out / f"{label}.fixes.tsv",
            layout_rows=rows,
        )
        WATCH.finish()
        seen = Counter(
            parts["labels"][i] or "-" for parts in WATCH.pages.values() for i in parts["texts"]
        )
        print(f"\n## {label} ({len(WATCH.pages)} pages, {sum(seen.values())} lines)")
        print("model labels: " + ", ".join(f"{name} {n}" for name, n in seen.most_common()))
        for part, kinds in WATCH.counts().items():
            unit = "pages" if part == "contents" else "lines"
            print(f"{part} ({unit}):")
            for kind, pages in kinds.items():
                total = sum(pages.values())
                totals[part][kind] += total
                print(f"  {kind:5} {total:6}  p. {_examples(pages) or '-'}")
        for page in show:
            WATCH.show(page)
        sys.stdout.flush()
    print("\n## All books\n\n| Part | Both | Only the rule | Only the model |\n|---|---|---|---|")
    for part in PARTS:
        print(f"| {part} | " + " | ".join(f"{totals[part][kind]:,}" for kind in KINDS) + " |")
    print(f"\nparagraph starts, {TOP}: {totals['paragraph starts'][TOP]:,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("labels", nargs="*", help="books to build (default: all)")
    parser.add_argument(
        "--show",
        type=int,
        nargs="+",
        default=[],
        help="pages (1-based) to print line by line: R footnote region, F footnote kept, "
        "B bibliography, M margin, "
        "H heading, P paragraph, S paragraph start (the rule's); then the model's label",
    )
    args = parser.parse_args()
    report(args.out, args.labels, args.show)

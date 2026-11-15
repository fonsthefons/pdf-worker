"""Marks made without the user (drop-in experiment, step S5): can a book be converted the
marks way (docs/marks-plan.md) with marks nobody drew?

  automarks.py make BOOK.pdf OUT.marks.json --mode rules|local|cloud
  automarks.py score AUTO.marks.json HAND.marks.json
  automarks.py build OUT_DIR       (heavy: converts each book with OUT_DIR/<label>.marks.json)
  automarks.py report DIR...       (the four hand-marked books' measures in each build folder)
  automarks.py selftest

``make``, ``rules``: a few examples per kind (running heads, page numbers, headings per
level, footnotes, note numbers, contents, margin references, body text) taken where
today's rules and the layout model's cached rows (``scratch/paddle-home``) call a line the
same; sections and the notes setting from those lines; no model call. On a text layer the
rules are the pipeline's own decisions (``tools/parts_report.py`` watches a conversion
without marks); on a scan built from PaddleOCR-VL's rows, the furniture rule
(``paddle_book.furniture``) and plain rules on each block's place and words against
Paddle's labels. Margin references count before headings (priority 2): a scan with them
gets no heading examples. A line one side calls a footnote and the other not, below the page's
body, is marked ``ignore`` there (``here``): an unsure note is dropped, never put in the
body (priority 1). ``local`` and ``cloud``: as rules, then the doubtful pages of the
style sheet those marks make (``marks_report.py``'s list, at most 20, spread over the
book) are asked of a vision model, one page per request (page image at 100 dpi and its
numbered lines, a JSON answer); what it says becomes ``here`` marks on that page. A failed
or late call leaves the rules' answer. local: LM Studio's model (``ai_client.lmstudio``);
cloud: a free OpenRouter vision model, stopping when ``requests_left()`` is 0.

``score``: every line's kind by each marks file (``style_sheet.classify``, followed as
``convert`` does: ``follow_marks._kind`` / ``_scan_kind``), per kind of the hand marks:
the same, left to today's rules, dropped, another kind; margin references first, then
footnotes, then headings (the README's priorities). The PDF is the hand marks' own
(``book.marks.json`` -> ``book.pdf``).

``build``: copies each PDF with its marks into ``OUT_DIR/books/`` (``convert`` reads the
marks file beside the PDF; the Paddle cache is keyed by content) and converts it as
``tools/quality.py build`` does, then ``quality.score``.
"""

import argparse
import base64
import contextlib
import json
import os
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / "scratch" / "drop-in" / "automarks-work"
os.environ.setdefault("PDF_WORKER_PADDLE_CACHE", str(ROOT / "scratch" / "paddle-home"))
sys.path.insert(0, str(ROOT / "tools"))

from pdf_worker import marking, style_sheet  # noqa: E402
from pdf_worker import marks as marks_mod  # noqa: E402
from pdf_worker.document import open_pdf  # noqa: E402
from pdf_worker.follow_marks import _kind, _scan_kind  # noqa: E402
from pdf_worker.layout import PAGE_NUMBER_RE, is_superscript_number  # noqa: E402
from pdf_worker.margin_refs import is_mark  # noqa: E402

LABELS = ("philosophy", "copleston", "ratzinger", "platon_bad")  # the hand-marked books
# Examples per kind: round numbers chosen before the results, about what the hand marks hold.
EXAMPLES = {
    "running-head": 10,
    "page-number": 10,
    "footnote": 12,
    "body": 15,
    "contents": 3,
    "margin-ref": 15,
    "note-ref": 10,
}
PER_LEVEL = 3  # heading examples per level, up to 4 levels
MAX_PAGES = 20  # doubtful pages asked of a model, a book
DPI = 100
TIMEOUT = {"local": 180, "cloud": 120}  # seconds: a later answer is a failed call
CLOUD_MODEL = "nvidia/nemotron-3.5-super-vl:free"  # ai-client's free vision model
# LM Studio's model (ai-client's, qwen3.5-9b) loaded with room for one page: an image of
# about 1,500 tokens, 50 numbered lines and the answer; the default 32,768 needs more memory.
LOCAL_CONTEXT = 8192
UNSURE = "unsure-footnote"
IN_BODY = ("body", "caption", "contents", "heading")  # kinds whose text stays in the book
MODEL_KINDS = {
    "footnote": "footnote",
    "vision_footnote": "footnote",
    "doc_title": "heading",
    "paragraph_title": "heading",
    "text": "body",
    "content": "contents",
}
ANSWER_KINDS = (
    "running-head",
    "page-number",
    "body",
    "footnote",
    "margin-ref",
    "contents",
    "caption",
    "other",
)
ROW_ORDER = ("margin-ref", "footnote", "heading", "heading 1", "heading 2", "heading 3")
ROW_ORDER += ("heading 4", "body", "running-head", "page-number", "contents", "note-ref")
_NOTE_START = re.compile(r"^\s*(?:\d{1,3}|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|\*)(?:[\s.)]|$)")
_PAGE_AT_END = re.compile(r"(?:\.{3,}|…|\s)\s*\d{1,3}\s*$")


# --- small parts (selftest) ---------------------------------------------------------------


def spread(items: list, n: int) -> list:
    """``n`` of ``items`` spread evenly over the list (all of them when it holds n or fewer)."""
    if len(items) <= n:
        return list(items)
    if n == 1:
        return [items[len(items) // 2]]
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def rect(box, pad: float = 0.5) -> list[list[float]]:
    x0, y0, x1, y1 = box
    return [[x0 - pad, y0 - pad], [x1 + pad, y0 - pad], [x1 + pad, y1 + pad], [x0 - pad, y1 + pad]]


def model_kind(label: str | None, text: str) -> str | None:
    """The kind the layout model's label says."""
    if label in ("header", "footer", "number"):
        return "page-number" if PAGE_NUMBER_RE.match(text) else "running-head"
    if label == "aside_text":
        return "margin-ref" if is_mark(text.strip()) else None
    return MODEL_KINDS.get(label or "")


def agreed(rule: str | None, model: str | None, foot: bool) -> str | None:
    """A line's kind for an example: the one both sides give; ``UNSURE`` when one calls it
    a footnote and the other not, at the page's foot (``foot``: below its body)."""
    if rule and rule == model:
        return rule
    edges = {"running-head", "page-number", "margin-ref"}
    if foot and (rule == "footnote") != (model == "footnote") and not edges & {rule, model}:
        return UNSURE
    return None


def heading_levels(found: list[tuple[tuple, int]]) -> dict[tuple, int]:
    """(style, page) of the agreed headings -> level of each style: the 4 styles seen on
    the most pages (two at least), largest (then bold, capitals) first."""
    pages = defaultdict(set)
    for style, page in found:
        pages[style].add(page)
    styles = sorted(
        (s for s, seen in pages.items() if len(seen) >= 2), key=lambda s: -len(pages[s])
    )
    styles = sorted(styles[:4], key=lambda s: (-s[0], not s[1], not s[2]))
    return {style: level for level, style in enumerate(styles, 1)}


def parse_answer(text: str) -> dict[int, tuple[str, int | None]]:
    """A model's JSON answer {"1": "body", "2": "heading-2"...} -> line -> (kind, level)."""
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(match[0]) if match else {}
    except json.JSONDecodeError:
        return {}
    found = {}
    for key, value in data.items() if isinstance(data, dict) else ():
        value = str(value).strip().lower().replace("_", "-")
        heading = re.fullmatch(r"heading(?:[- ]?([1-4]))?", value)
        if not str(key).strip().isdigit():
            continue
        if heading:
            found[int(key)] = ("heading", int(heading[1]) if heading[1] else None)
        elif value in ANSWER_KINDS:
            found[int(key)] = (value, None)
    return found


def merge(current: str | None, answer: tuple[str, int | None] | None, text: str) -> str | None:
    """A line's kind after a model's answer. Margin references first (priority 2): a mark
    the model calls a heading is a margin reference, and one never becomes a note. A line
    one calls a footnote and the other something else is dropped (priority 1)."""
    if answer is None or answer[0] == "other":
        return current
    kind, level = answer
    if current == "margin-ref" or (kind == "heading" and is_mark(text.strip())):
        return "margin-ref"
    if kind == "margin-ref" or current == "ignore":  # the rules were unsure: it stays dropped
        return "margin-ref" if kind == "margin-ref" else current
    if current and (kind == "footnote") != (current == "footnote"):
        return "ignore"
    if current is None and kind in IN_BODY:
        # Left to today's rules (on a scan: Paddle's label, its footnotes included), a line
        # the model calls body, caption, contents or heading may be a note, and so marked it
        # stays in the body whatever the rules say (platon_bad, local model: 25.7 notes in
        # the body per 10,000 words with body marks, 11.9 with captions and headings).
        return current
    if kind == "heading":
        if current and current.startswith("heading "):
            return current  # the style sheet's level: the model doesn't see the book's
        return f"heading {level or 2}"
    return kind


def tally(hand: list[str | None], auto: list[str | None]) -> dict[str, Counter]:
    """Per kind of the hand marks (and "heading", all levels): lines, the same by the auto
    marks, left to today's rules, dropped, another kind; and the lines the auto marks give
    that kind which the hand marks give another (``extra``) or leave to the rules."""
    rows: dict[str, Counter] = defaultdict(Counter)

    def keys(kind):
        return [kind, "heading"] if kind and kind.startswith("heading ") else [kind]

    for h, a in zip(hand, auto, strict=True):
        if h:
            for k in keys(h):
                rows[k]["lines"] += 1
                same = a == h or (k == "heading" and a and a.startswith("heading "))
                where = (
                    "same"
                    if same
                    else "rules"
                    if a is None
                    else "dropped"
                    if a in marks_mod.DROPPED_KINDS
                    else "other"
                )
                rows[k][where] += 1
        if a:
            for k in keys(a):
                if h is None:
                    rows[k]["auto, hand left to rules"] += 1
                elif not (h == a or (k == "heading" and h.startswith("heading "))):
                    rows[k]["extra"] += 1
    return rows


# --- make ---------------------------------------------------------------------------------


def _key(box) -> tuple:
    return tuple(round(c) for c in box)


def _text_lines(pdf: Path) -> dict[int, list]:
    """Page index -> (bbox, text, rule's kind, model's kind) of each line, from a
    conversion without marks watched by ``tools/parts_report.py``."""
    import parts_report  # its wrappers watch: each returns what the pipeline's own does

    from pdf_worker import structure
    from pdf_worker.convert import convert_pdf
    from pdf_worker.paddle_ocr import layout_pages

    def watch_add(self, text, line, page, *rest):  # parts_report's predates ``emphasized``
        vars(self).setdefault("seen", []).append((page, line))
        parts_report._add(self, text, line, page, *rest)

    structure._Builder.add = watch_add

    rows = layout_pages(pdf)
    parts_report.WATCH = parts_report.Watch(rows)
    fixes = WORK / "rules.fixes.tsv"
    fixes.unlink(missing_ok=True)  # a review file would carry the last book's decisions
    convert_pdf(
        pdf,
        WORK / "rules.md",
        "md",
        title="-",
        author="-",
        cover=False,
        fixes_path=fixes,
        layout_rows=rows,
        marks=False,
    )
    parts_report.WATCH.finish()
    found = {}
    for index, parts in parts_report.WATCH.pages.items():
        lines = []
        for i, line in enumerate(parts["lines"]):
            text = line.text.strip()
            if not text:
                continue
            if i not in parts["texts"]:
                rule = "page-number" if PAGE_NUMBER_RE.match(text) else "running-head"
            elif i in parts["footnote region"] and i in parts["footnotes"]:
                rule = "footnote"
            elif i in parts["margins"]:
                rule = "margin-ref" if is_mark(text) else None
            elif i in parts["headings"]:
                rule = "heading"
            elif i in parts["para"]:
                rule = "contents" if parts["contents"] else "body"
            else:
                rule = None
            lines.append((list(line.bbox), text, rule, model_kind(parts["labels"][i], text)))
        found[index] = lines
    return found


def _scan_lines(book: marking.Book, pages: list) -> dict[int, list]:
    """The same for a scan's lines (``marking.paddle_view``): rules on each Paddle block's
    place and words against its label."""
    from pdf_worker.paddle_book import furniture
    from pdf_worker.paddle_ocr import relabel

    rows = book.paddle
    furn = furniture([rows[k] for k in sorted(rows)])
    found = {}
    for index, page in enumerate(pages):
        row = rows.get(index)
        if not row:
            continue
        sx = page.width / (row.get("width") or page.width)
        sy = page.height / (row.get("height") or page.height)
        texts = [line.text.strip() for line in page.lines]
        contents_page = sum(bool(_PAGE_AT_END.search(t)) for t in texts) >= 5
        lines = []
        for line, text in zip(page.lines, texts, strict=True):
            if not text:
                continue
            block = row["blocks"][line.block]
            whole = block.get("text", "")
            x0, y0, x1, _ = block["bbox"]
            words = len(whole.split())
            if line.block in furn.get(index, ()):
                rule = "page-number" if PAGE_NUMBER_RE.match(text) else "running-head"
            elif y0 * sy > page.height / 2 and _NOTE_START.match(whole):
                rule = "footnote"
            elif (x1 - x0) * sx < 0.12 * page.width and is_mark(text):
                rule = "margin-ref"
            elif contents_page and _PAGE_AT_END.search(text):
                rule = "contents"
            elif (
                words <= 12
                and sum(c.isalpha() for c in whole) >= 2
                and whole.rstrip()[-1:] not in ".,;:"
            ):
                rule = "heading"
            elif words >= 15:
                rule = "body"
            else:
                rule = None
            lines.append((list(line.bbox), text, rule, model_kind(relabel(block, whole), text)))
        found[index] = lines
    return found


def _found(book: marking.Book, pdf: Path, pages: list) -> dict[int, list]:
    """``_text_lines`` / ``_scan_lines``, kept in WORK by the PDF's hash (a text layer's
    takes a whole conversion)."""
    WORK.mkdir(parents=True, exist_ok=True)
    cache = WORK / f"{book.info.sha256[:16]}.lines.json"
    if cache.exists():
        return {int(k): v for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}
    found = _scan_lines(book, pages) if book.paddle else _text_lines(pdf)
    tmp = cache.with_name(f".{cache.name}.tmp")
    tmp.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, cache)
    return found


def auto_marks(
    book: marking.Book, pages: list, measures, found: dict[int, list]
) -> marks_mod.Marks:
    """The rules' marks: examples where rule and model agree, ``ignore`` on unsure notes."""
    features = {
        (index, _key(line.bbox)): f
        for index, page in enumerate(pages)
        for line, f in zip(page.lines, measures.features[index], strict=True)
    }
    by_kind: dict[str, list] = defaultdict(list)
    headings, unsure = [], []
    body_keys: dict[int, set] = defaultdict(set)
    counts: dict[str, Counter] = defaultdict(Counter)  # kind -> page -> lines
    first_notes = {}  # page -> the first footnote line's text
    for index in sorted(found):
        lines = found[index]
        bodies = [box[3] for box, _, rule, model in lines if rule == model == "body"]
        bottom = max(bodies, default=None)
        for box, text, rule, model in lines:
            kind = agreed(rule, model, bottom is not None and box[1] > bottom)
            if kind is None:
                continue
            counts[kind][index + 1] += 1
            if kind == UNSURE:
                unsure.append((index + 1, box, text))
            elif kind == "heading":
                f = features.get((index, _key(box)))
                if f and f.size and not is_mark(text):
                    style = (round(f.size / measures.size_tol), bool(f.bold), bool(f.caps))
                    headings.append((style, index + 1, box, text))
            elif kind == "body" and len(text) < 40:
                continue  # a paragraph's short last line: no example of the body's lines
            else:
                by_kind[kind].append((index + 1, box, text))
                if kind == "body":
                    body_keys[index].add(_key(box))
                if kind == "footnote":
                    first_notes.setdefault(index + 1, text)
    if not book.paddle:  # note numbers: superscript numbers in agreed body lines
        for index, keys in body_keys.items():
            if index + 1 not in first_notes:
                continue
            for line in pages[index].lines:
                if _key(line.bbox) in keys:
                    by_kind["note-ref"] += [
                        (index + 1, span["bbox"], span["text"])
                        for span in line.spans
                        if is_superscript_number(span, line)
                    ]
    made: list[marks_mod.Mark] = []

    def add(page, kind, box, text, level=None, scope="style"):
        made.append(
            marks_mod.Mark(
                f"a{len(made) + 1}",
                page,
                kind,
                [tuple(p) for p in rect(box)],
                [text],
                level,
                scope,
            )
        )

    # A book with margin references: agreed ones on 5% of its pages (set after seeing the
    # counts: platon_bad 30 of 293 pages, philosophy 1 of 462). Fewer are stray ink.
    margins = len({page for page, _, _ in by_kind["margin-ref"]}) >= 0.05 * len(pages)
    if not margins:
        by_kind.pop("margin-ref")
    for kind, n in EXAMPLES.items():
        for page, box, text in spread(by_kind[kind], n):
            add(page, kind, box, text)
    # Margin references before headings (priority 2): on a scan the style sheet matches a
    # heading by estimated size and place only, which takes margin labels (platon_bad:
    # 639 references with heading marks, 700 without); its headings are left to the rules.
    if book.paddle and margins:
        headings = []
    levels = heading_levels([(style, page) for style, page, _, _ in headings])
    for style, level in levels.items():
        for _, page, box, text in spread([h for h in headings if h[0] == style], PER_LEVEL):
            add(page, "heading", box, text, level)
    for page, box, text in unsure:
        add(page, "ignore", box, text, scope="here")
    count = len(pages)
    notes = sorted(first_notes)
    # Round shares chosen before the results: notes on 2% of the pages make a book with
    # footnotes; 4 in 5 of them starting at 1 make numbering by page.
    settings = marks_mod.Settings(
        "page" if len(notes) >= max(3, 0.02 * count) else None,
        "page"
        if notes
        and sum(re.match(r"\s*1\b", first_notes[p]) is not None for p in notes) >= 0.8 * len(notes)
        else None,
    )
    body_pages = sorted(p for p, n in counts["body"].items() if n >= 5)
    contents_pages = {p for p, n in counts["contents"].items() if n >= 3}
    return marks_mod.Marks(book.info, settings, sections(body_pages, contents_pages, count), made)


def sections(
    body_pages: list[int], contents_pages: set[int], count: int
) -> list[marks_mod.Section]:
    """Front matter from page 1, the main text from the first page after it with body
    text, a contents section over each run of contents pages, then main text again."""
    starts = {1: "front"}
    main = next((p for p in body_pages if p > 1), None)
    if main:
        starts[main] = "main"
    for p in sorted(contents_pages):
        if p - 1 not in contents_pages:
            starts[p] = "contents"
        if p + 1 not in contents_pages and p < count:
            starts.setdefault(p + 1, "main" if main and p + 1 >= main else "front")
    return [marks_mod.Section(p, kind) for p, kind in sorted(starts.items())]


def _ask(mode: str, png: bytes, lines: list[str]) -> str:
    from ai_client import get_client

    numbered = "\n".join(f"{n}. {text[:100]}" for n, text in enumerate(lines, 1))
    prompt = (
        "This is a page of a book, and below are its lines as read, numbered from the top. "
        "Say what each line is: running-head, page-number, heading-1 (a part or chapter "
        "title), heading-2, heading-3, heading-4 (smaller section titles), body, footnote, "
        "margin-ref (a section number printed in the margin, like 17a or 402a5), contents (a "
        "line of the table of contents), caption, or other. Answer with JSON only, one entry "
        'per line: {"1": "running-head", "2": "body", ...}\n\n' + numbered
    )
    image = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image}},
            ],
        }
    ]
    if mode == "cloud":
        return get_client("openrouter").chat(
            messages=messages,
            model=CLOUD_MODEL,
            fallbacks=False,
            thinking=False,
            timeout=TIMEOUT[mode],
            retries=0,
            max_tokens=3000,
        )
    client = get_client("lmstudio")
    client.context_length = LOCAL_CONTEXT  # as ``ask``'s session loaded it
    return client.chat(messages=messages, thinking=False, timeout=TIMEOUT[mode], retries=0)


def ask(book: marking.Book, pages: list, measures, auto: marks_mod.Marks, mode: str) -> dict:
    """``auto`` with ``here`` marks from a model's answers on its doubtful pages."""
    book.marks, book._measures = auto, measures
    found = book.classified()
    doubtful = [p for p in range(1, len(found.labels) + 1) if found.doubtful(p)]
    asked = spread(doubtful, MAX_PAGES)
    follow = _scan_kind if book.paddle else _kind
    stats = {"doubtful": len(doubtful), "asked": 0, "answered": 0, "changed": 0, "errors": []}
    if mode == "local":
        from ai_client import lmstudio

        session = lmstudio.session(context_length=LOCAL_CONTEXT)
    else:
        session = contextlib.nullcontext()
    start = time.monotonic()
    try:
        with session:
            for page in asked:
                if mode == "cloud":
                    from ai_client import get_client

                    left = get_client("openrouter").requests_left()
                    if left is not None and left <= 0:
                        stats["errors"].append("no free requests left")
                        break
                lines = [
                    (i, line) for i, line in enumerate(pages[page - 1].lines) if line.text.strip()
                ]
                png = book.doc.load_page(page - 1).get_pixmap(dpi=DPI).tobytes("png")
                stats["asked"] += 1
                try:
                    answer = parse_answer(_ask(mode, png, [line.text.strip() for _, line in lines]))
                except Exception as exc:  # noqa: BLE001 - a failed or late call keeps the rules' answer
                    stats["errors"].append(f"p{page}: {type(exc).__name__}: {str(exc)[:160]}")
                    continue
                stats["answered"] += bool(answer)
                for n, (i, line) in enumerate(lines, 1):
                    current = follow(found.labels[page - 1][i])
                    kind = merge(current, answer.get(n), line.text)
                    if kind and kind != current:
                        name, _, level = kind.partition(" ")
                        auto.marks.append(
                            marks_mod.Mark(
                                f"m{len(auto.marks) + 1}",
                                page,
                                name,
                                [tuple(p) for p in rect(line.bbox)],
                                [line.text],
                                int(level) if level else None,
                                "here",
                            )
                        )
                        stats["changed"] += 1
    except Exception as exc:  # noqa: BLE001 - the model can't be reached: the rules' marks stay
        stats["errors"].append(f"session: {type(exc).__name__}: {str(exc)[:300]}")
    stats["seconds"] = round(time.monotonic() - start)
    return stats


def make(pdf: Path, out: Path, mode: str) -> None:
    start = time.monotonic()
    absent = WORK / "absent.marks.json"  # never written: the Book starts with no marks
    with open_pdf(pdf) as doc:
        book = marking.Book(doc, pdf, absent)
        pages = book.pages()
        measures = style_sheet.measure(pages)
        auto = auto_marks(book, pages, measures, _found(book, pdf, pages))
        stats = ask(book, pages, measures, auto, mode) if mode != "rules" else {}
    auto = marks_mod.from_dict(marks_mod.to_dict(auto))  # checked as a hand-made file is
    out.parent.mkdir(parents=True, exist_ok=True)
    marks_mod.save(out, auto)
    kinds = Counter(
        m.kind + (f" {m.level}" if m.level else "") + (" (here)" if m.scope == "here" else "")
        for m in auto.marks
    )
    print(f"{pdf.name} -> {out} ({mode}, {time.monotonic() - start:.0f} s)")
    print(
        f"  settings {marks_mod.to_dict(auto)['settings']}; sections "
        + ", ".join(f"{s.page} {s.kind}" for s in auto.sections)
    )
    print("  marks: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
    if stats:
        errors = stats.pop("errors")
        print("  model: " + json.dumps(stats) + f"; errors {len(errors)}")
        for error in errors[:5]:
            print(f"    {error}")


# --- score, build, report -----------------------------------------------------------------


def score(auto_path: Path, hand_path: Path) -> None:
    pdf = hand_path.with_name(hand_path.name.removesuffix(".marks.json") + ".pdf")
    with open_pdf(pdf) as doc:
        book = marking.Book(doc, pdf, hand_path)
        hand = book.classified()
        book.marks = marks_mod.load(auto_path, None)
        marks_mod.check_pdf(book.marks, book.info)
        auto = book.classified()
        follow = _scan_kind if book.paddle else _kind
    flat = lambda found: [follow(label) for page in found.labels for label in page]  # noqa: E731
    rows = tally(flat(hand), flat(auto))
    if not book.paddle:  # note numbers found in the text by each style sheet
        h = {(p, _key(b)) for p, boxes in enumerate(hand.refs) for b in boxes}
        a = {(p, _key(b)) for p, boxes in enumerate(auto.refs) for b in boxes}
        rows["note-ref"] = Counter(lines=len(h), same=len(h & a), extra=len(a - h))
    print(f"## {pdf.name}: {auto_path.name} against the hand marks")
    print(
        "| kind | hand lines | same | left to rules | dropped | another kind"
        " | auto: hand another kind | auto: hand left to rules |"
    )
    print("|---|---|---|---|---|---|---|---|")
    pct = lambda n, d: f"{100 * n / d:.1f}%" if d else "-"  # noqa: E731
    for kind in [*ROW_ORDER, *sorted(set(rows) - set(ROW_ORDER))]:
        r = rows.get(kind)
        if not r:
            continue
        n = r["lines"]
        print(
            f"| {kind} | {n} | {pct(r['same'], n)} | {pct(r['rules'], n)} | {pct(r['dropped'], n)}"
            f" | {pct(r['other'], n)} | {r['extra']} | {r['auto, hand left to rules']} |"
        )


def build(out: Path) -> None:
    import quality
    from regression import convert_book

    books = out / "books"
    books.mkdir(parents=True, exist_ok=True)
    for label, pdf, _, _, paddle in quality.PAIRS:
        auto = out / f"{label}.marks.json"
        if not auto.exists():
            continue
        copy = books / pdf.name
        if not copy.exists():
            tmp = copy.with_name(f".{copy.name}.tmp")
            shutil.copyfile(pdf, tmp)
            os.replace(tmp, copy)
        shutil.copyfile(auto, marks_mod.default_marks_path(copy))
        start = time.monotonic()
        print(f"{label}: {copy}", flush=True)
        convert_book(label, copy, out, paddle, True)
        print(f"  {time.monotonic() - start:.0f} s", flush=True)
    quality.score(out)


def report(folders: list[Path]) -> None:
    import quality
    from rank_checks import is_main

    names = ("covered", "missing", "extra", "headings found", "headings real", "levels")
    names += ("breaks real", "notes in body", "leftovers")
    print("| book | build | " + " | ".join(names) + " | main missed | main wrong | margin refs |")
    print("|---|---|" + "---|" * (len(names) + 3))
    for label in LABELS:
        for folder in folders:
            path = folder / "quality.json"
            book = (
                json.loads(path.read_text(encoding="utf-8"))["books"].get(label)
                if path.exists()
                else None
            )
            if not book:
                print(f"| {label} | {folder.name} | not built |")
                continue
            m = quality.measures(book)
            h = book.get("headings") or {}
            mains = [sum(map(is_main, h.get(k, []))) for k in ("missed", "wrong")]
            cells = [quality._fmt(*m[name][:2]) for name in names]
            # rank_checks.refs' count: bracketed margin references ("[17a]") in the book
            text = (folder / f"{label}.md").read_text(encoding="utf-8")
            refs = len(re.findall(r"\[\d{1,3}[a-e]\\?\]", text))
            print(
                f"| {label} | {folder.name} | "
                + " | ".join(cells)
                + f" | {mains[0]} | {mains[1]} | {refs} |"
            )


def selftest() -> None:
    assert spread(list(range(10)), 3) == [0, 4, 9] and spread([1, 2], 5) == [1, 2]
    assert marks_mod.inside((5, 5), rect((0, 0, 10, 10))) and not marks_mod.inside(
        (11, 5), rect((0, 0, 10, 10))
    )
    assert (
        model_kind("number", "12") == "page-number"
        and model_kind("header", "CAPÍTULO I") == "running-head"
    )
    assert (
        model_kind("aside_text", "17a") == "margin-ref" and model_kind("aside_text", "Nota") is None
    )
    assert agreed("body", "body", False) == "body" and agreed("footnote", "body", False) is None
    assert agreed("footnote", "body", True) == UNSURE and agreed(None, "footnote", True) == UNSURE
    assert agreed("page-number", "footnote", True) is None
    assert heading_levels(
        [
            ((30, True, True), 3),
            ((30, True, True), 9),
            ((24, True, False), 4),
            ((24, True, False), 8),
            ((40, True, True), 1),
        ]
    ) == {(30, True, True): 1, (24, True, False): 2}
    many = [((s, False, False), p) for s in (10, 20, 30, 40, 50) for p in range(s // 10 + 1)]
    assert heading_levels(many) == {
        (50, False, False): 1,
        (40, False, False): 2,
        (30, False, False): 3,
        (20, False, False): 4,
    }
    assert parse_answer(
        'ok {"1": "Heading-2", "2": "footnote", "3": "nonsense", "x": "body"} .'
    ) == {1: ("heading", 2), 2: ("footnote", None)}
    assert parse_answer("no json") == {}
    assert merge("body", ("footnote", None), "Cf. Platón") == "ignore"
    assert merge("footnote", ("body", None), "y así") == "ignore"
    assert merge(None, ("footnote", None), "1 Cf.") == "footnote"
    assert merge("heading 2", ("heading", 1), "17a") == "margin-ref"
    assert merge("margin-ref", ("footnote", None), "17a") == "margin-ref"
    assert merge("heading 3", ("heading", 1), "Capítulo") == "heading 3"
    assert merge(None, ("heading", None), "Capítulo") is None and merge("body", None, "x") == "body"
    assert merge("contents", ("heading", None), "Capítulo") == "heading 2"
    assert merge(None, ("caption", None), "32 En el Fedro") is None
    assert merge("ignore", ("body", None), "y así") == "ignore"
    assert merge(None, ("body", None), "32 En el Fedro") is None
    assert merge("heading 2", ("body", None), "y así") == "body"
    rows = tally(
        ["footnote", "footnote", "footnote", "heading 1", None],
        ["footnote", "ignore", "body", "heading 2", "body"],
    )
    assert rows["footnote"] == Counter(lines=3, same=1, dropped=1, other=1)
    assert rows["heading"]["same"] == 1 and rows["heading 1"]["other"] == 1
    assert rows["body"] == Counter(extra=1, **{"auto, hand left to rules": 1})
    assert [s.kind for s in sections([1, 3, 20], {5, 6, 30}, 30)] == [
        "front",
        "main",
        "contents",
        "main",
        "contents",
    ]
    print("ok")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("make")
    p.add_argument("pdf", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--mode", choices=("rules", "local", "cloud"), default="rules")
    p = sub.add_parser("score")
    p.add_argument("auto", type=Path)
    p.add_argument("hand", type=Path)
    sub.add_parser("build").add_argument("out", type=Path)
    sub.add_parser("report").add_argument("folders", type=Path, nargs="+")
    sub.add_parser("selftest")
    args = parser.parse_args(argv)
    if args.command == "make":
        make(args.pdf, args.out, args.mode)
    elif args.command == "score":
        score(args.auto, args.hand)
    elif args.command == "build":
        build(args.out)
    elif args.command == "report":
        report(args.folders)
    else:
        selftest()


if __name__ == "__main__":
    main(sys.argv[1:])

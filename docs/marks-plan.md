# Plan: a person marks a few examples, the pipeline follows them

Written 2026-10-31, after the quality plan's Phase 5. One phase per PR, each at the
effort at the end of its heading (low, medium or high). Read this whole file and the top
of `PROGRESS.md` first.

## Why

The layout and quality plans found every role of a line (heading, footnote, running
head...) with general rules and the layout model. The last phases each moved the
numbers a point or two and missed the merge gate, and each general rule meets a book it
breaks: Copleston's chapter-numbered footnotes taken for chapter notes (quality Phase 5),
Magnifica Humanitas losing its headings to the contents rule (quality Phase 4). A person
sees in seconds what the rules guess at, and a book is typeset the same way throughout,
so a few marked examples say what every line of the book is.

The new route: before converting a book, a person marks examples of each kind of line
(a chapter heading, a section heading, a footnote, a running head, a page number, a
note reference...), where sections start (introduction, main text, notes, bibliography)
and two settings (where notes are printed, where their numbers start again). The
pipeline turns the examples into the book's own style sheet, labels every line by it,
and shows its decisions page by page so the person fixes the few it got wrong. Books
without marks convert exactly as today.

## Rules for every phase

1. **Without a marks file nothing changes**: the eight regression books (no marks)
   convert byte for byte as before (`tools/regression.py compare`: 0 diff lines).
2. **Marks are the person's work.** Never edit, rewrite, regenerate or delete a marks
   file; phases only read them. Never look at a book's reference EPUB while writing
   matching code, and never tune a number to make one book's score come out right.
3. **Code stays general**: no book's words, pages or sizes in code. Numbers the matching
   needs come from the book (its body size, line spacing, the examples themselves) or
   are round values chosen before looking at the results, written in a one-line comment
   and in the phase's `PROGRESS.md` entry.
4. **A mark wins over the style sheet, the style sheet wins over today's rules**; a kind
   nobody marked is left to today's rules.
5. **Measure** with `tools/quality.py`: build with marks, and with `--no-marks` (Phase 2
   adds it) for the before side. A phase's own measure gets better on the marked books,
   and no measure gets worse beyond the quality plan's tolerance (1 point for
   percentages, 1 per 10,000 reference words).

## The proof-of-concept books

Copleston, Ratzinger, platon_bad and philosophy (`tools/quality.py` `PAIRS`; all four
have reference EPUBs). Copleston and Ratzinger have a text layer (fonts known);
platon_bad and philosophy are scans built from PaddleOCR-VL's rows (fonts unknown, pages
may be skewed). The user marks them after Phase 0; `tools/run_plan.py` waits until all
four marks files exist.

## The marks file

`<book>.marks.json` next to the PDF (`book.pdf` and `book.ocr.pdf` -> `book.marks.json`,
as `fixes.default_fixes_path` does), written atomically; the version before the last
save is kept as `<book>.marks.prev.json`. Coordinates are PDF points in the space of
`layout.page_lines`' boxes; pages are 1-based.

```json
{
  "version": 1,
  "pdf": {"name": "book.pdf", "pages": 612, "sha256": "..."},
  "settings": {"notes": "page", "numbering": "chapter"},
  "sections": [
    {"page": 1, "kind": "front", "keep": false},
    {"page": 9, "kind": "contents", "keep": true},
    {"page": 13, "kind": "introduction", "keep": true},
    {"page": 41, "kind": "main", "keep": true}
  ],
  "marks": [
    {"id": "m1", "page": 41, "kind": "heading", "level": 1, "scope": "style",
     "shape": [[72.0, 90.5], [523.1, 88.0], [523.6, 131.2], [72.4, 133.9]],
     "texts": ["CAPÍTULO I", "LOS ORÍGENES"]}
  ]
}
```

- **settings.notes**, where a note's text is printed: `page` (foot of the page),
  `chapter` (after each chapter), `book` (a notes section at the end), `none`.
  **settings.numbering**, where note numbers start again at 1: `page`, `chapter`, `book`.
  Missing: today's rules decide.
- **sections**: each runs from its page to the next section's. Kinds: `front` (title
  page, copyright, dedication), `contents`, `introduction`, `main`, `notes`,
  `bibliography`, `index`, `appendix`, `back`. `keep: false` leaves it out of the book.
- **marks**: `kind` is one of `title` (title-page lines), `heading` (with `level` 1-4),
  `body`, `running-head`, `page-number`, `footnote`, `note-ref` (a note's number in the
  text), `endnote`, `contents`, `bibliography`, `index`, `caption`, `ignore`. `scope`:
  `style` (an example: teach the style sheet) or `here` (this place only, e.g. a
  correction made in review). `shape`: the polygon the person drew (3 or more corners,
  any angle: a skewed scan's lines don't fit an upright rectangle). `texts`: the texts
  of the lines it took when it was made, to find them again and to warn when the
  pipeline's lines have changed.
- A line belongs to a shape when the middle of its box lies inside the polygon; a word
  (for `note-ref`) when its middle does.

## Effort and fan

| Phase | Effort | Heavy work (fan) |
|---|---|---|
| 0: marks file and marking page | medium | none (page images on demand) |
| (the user marks the four books) | - | - |
| 1: style sheet and review view | high | none (labels for the four books' pages, no conversion) |
| 2: page furniture and notes from marks | medium | two builds of the four books, the regression set |
| 3: headings and levels from marks | medium | same |
| 4: proof-of-concept verdict | low | one whole yardstick run; stops for the user |
| 5: sections, and the contents as links | medium | two builds of the four books, the regression set |
| 6: final report and the marks-first workflow | low | one whole yardstick run |

Run heavy builds one at a time: two Paddle builds at once collide on the shared crop
cache.

---

## Phase 0: marks file and marking page (medium)

Goal: `pdf-worker mark BOOK.pdf` opens a page in the browser where the user marks a book
quickly, and the marks file of the format above.

1. `src/pdf_worker/marks.py`: the format (dataclasses), `default_marks_path`, load with
   checks (unknown kind or version, a PDF whose page count or hash differs: a
   `PdfWorkerError` subclass), atomic save keeping the `.prev` copy, and
   `lines_in(shape, lines)` / `words_in(shape, words)` by point-in-polygon. Unit tests
   with `make_pdf`, including a skewed (rotated) shape that takes a slanted line and
   leaves its neighbours.
2. **The lines the page shows are the lines the pipeline sees**: `page_lines` after the
   same preparation as `convert_pdf` (`tools/page_parts.py` does it), and for a book
   built from PaddleOCR-VL's rows, the lines made from those rows (find how
   `tools/regression.py` `convert_book(paddle=True)` passes them, and reuse that path;
   cached rows in `scratch/paddle-home`). Text blocks: the layout model's boxes when its
   rows are cached (`profile.layout`), else MuPDF's blocks.
3. A local server with the standard library only (`http.server`, bound to 127.0.0.1, a
   free port, opens the browser unless `--no-browser`): the page as a PNG rendered on
   request (150 dpi), the page's lines, words and blocks as JSON, the marks file read
   and saved. Only kinds and fields of the format are accepted on save. One HTML file
   with plain JS, no framework, no download from the internet.
4. The page, in this order of importance:
   - The page image with each line's box drawn faintly and the blocks dashed; zoom and
     pan (scans need it); page number box, previous/next keys.
   - Select: click a line; shift-click adds lines; click a block's edge (or alt-click
     inside) takes the block's lines; drag on an empty spot draws a rectangle whose
     **four corners then drag freely** into any four-sided shape; clicking an edge's
     middle adds a corner. The selected lines light up as the shape changes.
   - Assign: a key or button per kind (headings ask for the level 1-4); `here` instead
     of `style` with a modifier key. Marks are drawn in their kind's colour, with a
     legend; click a mark to change or delete it.
   - The page's section start (kind, keep) and the book's two settings, in a side
     panel.
   - Every change saves at once; reopening resumes where the user left off.
   - Marks whose `texts` no longer match their lines are listed with their page.
5. CLI: `_add_mark_command` (`pdf-worker mark BOOK.pdf [--port N] [--no-browser]`).
   `convert` doesn't read marks yet.
6. Check it in a real browser: the run skill or Claude in Chrome on Ratzinger and
   platon_bad (a scan): draw a shape, drag a corner, mark a block, set a section,
   reload, see the marks back; screenshots into `scratch/marks/`. Record in
   `PROGRESS.md` how to use the page (one short list the user reads before marking).

PR: "Marks: the marks file and the marking page".

## Phase 1: style sheet and review view (high)

Goal: every line of a marked book gets a kind and how sure it is, and the user sees it.
Start by checking the four marks files load; read them, never change them.

1. Features of a line (`marks.py` or a new `style_sheet.py`): size against the body
   size, font family (text layer only), bold, italic, all capitals, alignment in its
   column (centred, flush left, indented, flush right), place on the page (share of the
   page height from the top and from the bottom), the gap above and below in body line
   spacings, the numbering it starts with (roman, arabic, letter, a division word from
   the existing Spanish/English list, none) and its length. For `note-ref`: the
   number's size and rise against its line, and whether it is glued to a word.
2. The style sheet: per kind (and heading level), the examples' features. A line takes
   a kind when its features agree with an example's: the same font family and bold /
   capitals where known, size within a round tolerance, the same numbering class, and
   for `running-head` / `page-number` the same page edge. Scans have no fonts: size,
   place, capitals and numbering only. One kind agrees: `matched`; a mark covers it:
   `marked`; two kinds agree: `conflict` (today's rules decide, the review lists it);
   none: `rules`.
3. `classify(doc, marks)` -> per page, per line: kind, level, how sure. Fast: no model
   runs (cached rows only).
4. Review view in the marking page: a toggle colours each line by its kind (solid for
   `marked`, outlined for `matched`, hatched for `conflict`), and a "next doubtful
   page" key jumps to the next page with a conflict, or a line placed or sized like no
   example of its kind. A correction made there is a mark with `scope: here` unless the
   user chooses `style`.
5. Write in `PROGRESS.md`, per book: lines per how-sure class, kinds' counts, the
   conflicts' most common pairs. Don't score against the references yet.

PR: "Marks: style sheet and review view".

## Phase 2: page furniture and notes from marks (medium)

Goal: `convert` follows the marks for running heads, page numbers, footnotes, note
references and the notes settings.

1. `convert` reads the book's marks file when there is one; `--no-marks` ignores it.
   `tools/quality.py build` gets `--no-marks` and `--only LABEL,...` (the four books).
2. The seams (read the code first): `DocumentProfile.furniture` (running heads, page
   numbers), `footnotes._find_region` (which lines are the page's footnotes),
   `_superscript_markers` / `glued_refs` (note references), `endnotes` and
   `analyze_document`'s chapter-notes choice (settings.notes and settings.numbering
   replace the guess: `page` means footnotes and no chapter notes, which is the
   Copleston error of quality Phase 5). `ignore` lines are dropped; `caption` lines
   kept out of paragraphs.
3. Tests first (`make_pdf`): a footnote the rules miss found by a mark's style; a
   running head unlike the rules' found; settings.notes `page` turning off the chapter
   notes pairing.
4. Build the four books with marks and with `--no-marks`; `compare`. Own measures:
   notes in the body, leftovers, words missing. The regression set must be identical
   (rule 1).

PR: "Marks: page furniture and notes".

## Phase 3: headings and levels from marks (medium)

Goal: headings and their levels from the marks.

1. A `heading` line (marked or matched) is a heading at its kind's level; a line that
   matches `body`, `contents`, `caption`, `footnote` or `index` is never one; `rules`
   lines go through today's rules, their level placed among the marked levels by size.
   The seams: `BodyLine.title` / `entry` and `structure._State.add_page`'s level
   choice. A heading's number and title on two lines stay one heading.
2. Tests first, then build and `compare` as in Phase 2. Own measures: headings found,
   real, levels.

PR: "Marks: headings and levels".

## Phase 4: proof-of-concept verdict (low)

Goal: does marking pay? Stop for the user.

1. One whole yardstick run with marks (`scratch/marks/verdict`) and one with
   `--no-marks` (`scratch/marks/verdict_base`), `compare`.
2. The verdict, with the bar set now: marks pay if, on the four books' total, headings
   found and real each gain 5 points or more, notes in the body and leftovers fall to
   half or below 1 per 10,000 reference words, no measure gets worse beyond the
   tolerance, and marking took the user 20 minutes a book or less (ask the user's time
   in the PR; record what `PROGRESS.md` holds about it).
3. A table before / after per book, the errors left on the marked books ranked with
   one example page each, and the review view's doubtful pages per book (how much
   checking the user would face).
4. Always end with a draft PR and `STOPPED: proof-of-concept verdict, the user decides
   whether the marks route goes on` (Phase 5 waits for the user).

PR: "Marks: proof-of-concept verdict".

## Phase 5: sections, and the contents as links (medium)

Goal: sections from the marks, and the printed contents kept as links.

1. Each section is its own chapter in the EPUB, named by its first heading (or its
   kind); `keep: false` leaves it out (as the user did by hand for a Timeo without its
   introduction). A `notes` section's entries are endnotes linked from their
   references; `bibliography` entries one paragraph each; `index` as today
   (`index_links`).
2. `contents` lines (marked or matched) become a list whose entries link to the
   heading they name: match by text (numbers and page numbers left out, accents and
   case ignored), then by order; an entry with no heading stays plain text. The EPUB's
   own navigation is built as before.
3. Tests first; build and `compare` as in Phase 2. Own measures: leftovers and words
   extra (contents and dropped sections no longer in the text).

PR: "Marks: sections and linked contents".

## Phase 6: final report and the marks-first workflow (low)

1. One whole yardstick run; the results table per book before marks, after Phase 4,
   now.
2. README and the repo `CLAUDE.md`: how to convert a book the marks way (`pdf-worker
   mark`, what to mark first, the review view, `convert`), and what is left to today's
   rules.
3. `PROGRESS.md` and "Results" below. No code changes.

PR: "Marks plan: results".

## How to work through this

- In Claude Code, `/pdf-layout-plan marks` runs the phases one after another, each as a
  subagent at its effort, merging each PR, updating `main` and running the fast tests in
  between; it stops after Phase 0 until the four marks files exist, and at Phase 4's
  verdict. In a terminal, `tools/run_plan.py --plan marks` does the same.
- One phase per PR. Branch from an up-to-date `main`; never stack PRs.
- Follow `CLAUDE.md`: absolute paths; no `cd`, pipes or heredocs; throwaway code in
  `scratch/`; long runs with `tools/run_logged.py` and `tools/wait_log.py`; one pytest
  run at a time; one Paddle build at a time.
- Tests first; check the new ones fail before the change.
- At the end of each phase: fast tests, `ruff check`, `ruff format`, the builds and
  `compare` the phase names, the regression `compare`, a `PROGRESS.md` entry, the PR.
- Nobody answers questions while a phase runs: decide by this file and record the
  decision. Stop (draft PR) only where this file says so or a check fails in a way it
  doesn't cover.

## Later (not in this plan)

Block quotations and epigraphs as kinds; marks carried from one volume to the next of
the same series; suggesting marks from the layout model for the person to accept.

## Results

(Filled in by Phase 6.)

# Plan: recognise the parts of a page the way a reader does

Written 2026-10-28 (max effort, with measurements). To be carried out later, one phase
per PR, at medium effort. Read this whole file and the top of `PROGRESS.md` first.

## The idea

A reader tells the parts of a book apart with two kinds of cue:

1. **Across pages.** A small line that sits at the same edge of page after page is a
   running header or footer; a bare number there is the page number. Nobody needs to
   measure "the top 10% of the page" to see it.
2. **On the page.** A footnote, a contents list, a bibliography entry, a quotation set
   in smaller type: each *looks* like what it is. The layout model of PaddleOCR-VL
   (PP-DocLayoutV3, already installed for scans) labels these blocks from the page
   image.

So the pipeline should decide what every line is **once, in one place**, and then
build the book from those decisions. That place is `footnotes.layout_page` (it already
splits a page into body lines and footnotes). `structure.py` builds; it should not
decide parts.

**No new rules beyond this plan.** We went in circles adding a rule per book. If a
book gets worse, write the page and line in `PROGRESS.md` and ask the user; don't patch.

## What was measured (2026-10-28)

Layout model alone (no text reading): 1.5 s per page on this Mac's CPU (227 pages in
6 min), once per book. Its labels for each page's first and last line:

| Book, line at the page edge | Pages | Model's labels |
|---|---|---|
| Metafísica: "METAFISICA" (running head) | 97 | header 36, paragraph_title 33, doc_title 28 |
| Metafísica: "INTRODUCCION" (running head) | 16 | doc_title 11, paragraph_title 4, text 1, **header 0** |
| Metafísica: "LA ESTRUCTURA METAFISICA DEL ENTE" | 27 | header 15, doc_title 11, paragraph_title 1 |
| Metafísica: "LA CAUSALIDAD" | 23 | header 16, paragraph_title 6, doc_title 1 |
| Metafísica: page numbers | 217 | number 217 |
| Metafísica: "Capítulo I…" (chapter openings) | 10 | doc_title 10 |
| Kant: lines called header or footer | 4 | all 4 are section headings ("Observación a la primera antinomia") |
| Kant: lines called page number | 4 | all 4 are "- § 12 -" section marks |

On the other hand the model saw well what only shows on the page: Metafísica's
contents page labelled `content` line by line; each bibliography entry its own
`reference_content` box; the footnote on printed p. 57 a `footnote`; the inset
small-type passage (the one that caused 1,118 broken sentences) its own `text` box.

**Decision (2026-10-28).** The user chose the layout model and said time doesn't matter.
The numbers above show the model can't tell a running head from a title on one page
(a reader can't either: the cue is that it repeats). So:

- headers, footers and page numbers: the repetition rule of Phase 1, **no model**;
- contents, bibliography, footnotes, paragraphs, margin notes: the model, part by part,
  only where Phase 4 shows it does better than today's rule.

The repetition rule, prototyped on three whole books before writing this plan:

- Metafísica: drops 218 page numbers and about 190 running heads, OCR variants included
  ("L O S TRASCENDENTALES", "M ETAFISICA", "METAFÍSICA"). Keeps the chapter labels, part
  titles, the 17.5 pt "INTRODUCCION" divider page and the "BIBLIOGRAFIA GENERAL" heading.
  Misses 3 heads: two garbled beyond the key ("METAFISCIA", "LA CA USAL1DAD") and one
  whose nearby pages held a chapter opening and a garbled head. Drops 2 lines of the
  contents page's top row (harmless: printed contents pages are dropped later anyway).
- Platón - Timeo (philosophia.cl): drops the site line and the page number on all 55
  pages; keeps the title page.
- Kant: drops nothing (this edition has no running heads), so the "§" marks and
  headings at page tops and bottoms stay.

## Test set (user: "one book per kind")

| Label | File | Kind | Pages |
|---|---|---|---|
| kant | `test_pdfs/Critica de la Razon Pura - Immanuel Kant.pdf` | born-digital, headings, no running heads | 206 |
| timeo_web | `test_pdfs/Platon - Timeo.pdf` | born-digital, site header on every page | 56 |
| metafisica | `test_pdfs/metafisica_bad1.pdf` (copy, Phase 0) | scan with OCR text: running heads, footnotes, inset passages, bibliography | 227 |
| lugones | `test_pdfs/lugones_imperio_jesuitico_1904.pdf` | old scan, bibliography | 370 |
| dilexit | `test_pdfs/dilexit_nos.pdf` | born-digital, many notes | 69 |
| dialogos | `test_pdfs/platon_dialogos_vi_good.pdf` | dialogues (speaker turns) | 545 |
| timeo_greek | `test_pdfs/Timeo_by_Platón_no_intro.pdf` | critical edition, Greek, apparatus | 261 |
| niebla | `test_pdfs/niebla_1914.pdf` | novel, scan | 326 |

All eight have a text layer. No printed web page is left on disk (the Millán Puelles
print was cleaned); the unit test `test_a_printed_web_page_loses_the_browser_header_and_footer`
covers that kind. For Phase 6 only: `test_pdfs/philosophy.pdf` (built from Paddle rows;
its 462 pages are in the Paddle cache).

---

## Phase 0: before/after tool and baseline (medium)

Goal: one command that shows what a change did to every book in the test set.

1. Metafísica is in the test set already: `test_pdfs/metafisica_bad1.pdf`, copied
   2026-10-28 from the inbox's "Metafisica - Tomas Alvira bad 1.pdf" (227 pages).
2. Write `tools/regression.py`:
   - `BOOKS`: the eight (label, path) of the table above.
   - `build OUT_DIR`: for each book, `convert_pdf(path, OUT/<label>.md, "md",
     title=<label>, author="-", cover=False, fixes_path=OUT/<label>.fixes.tsv)`
     (title and author given, so no metadata lookup changes the output; the language
     is guessed from the text). The `fixes_path` keeps the test books' own
     `.fixes.tsv` files untouched, and both runs start with no review decisions.
     Save `OUT/<label>.json` with: `paragraphs`, `headings` (list of texts), `notes`
     (from `report.stats`, headings read from the `#` lines), and `splits`: paragraphs
     that don't end in `.:;!?»”"')]` followed by one starting with a lower-case letter
     and not "a)"-style (the count `scratch/para_compare.py` used: 1,118 then 511 on
     Metafísica). Skip the YAML front matter and the `[^…]:` note lines.
   - `compare BEFORE_DIR AFTER_DIR`: per book, each number before → after; headings
     lost and added (full lists); write `AFTER/<label>.diff` (unified diff of the two
     `.md`, 2 lines of context) and print its size.
3. Baseline on an up-to-date `main`:
   `.venv/bin/python tools/run_logged.py regress_base .venv/bin/python tools/regression.py build scratch/regress/base`
   then `tools/wait_log.py scratch/logs/regress_base.log` (all paths absolute, as
   CLAUDE.md says). About 2,000 pages: expect tens of minutes.
4. Check the tool on itself: build the baseline twice, `compare` must show no change.
   If it does, the build isn't deterministic: find out why before going on.
5. Add the tool to the dev-tools list in `CLAUDE.md`.

PR: "tools/regression.py: before/after numbers for the test books". This plan
(`docs/layout-plan.md`), `tools/run_plan.py`, `.claude/skills/pdf-layout-plan/`, the
plan's `PROGRESS.md` entry and the merge rule in `CLAUDE.md` go in this PR if they're
still uncommitted.

## Phase 1: headers, footers and page numbers by repetition (high)

Goal: the Metafísica running heads leave the text (most of its 511 broken sentences),
with fewer rules than today.

### The rule

On every page, the **top row** is the line with the smallest baseline that has a letter
or digit, plus every line whose baseline is within half its font size of it; the
**bottom row** likewise from the largest baseline. (A page with one row has only a top
row.) A line in one of these rows is page furniture when:

1. it is a bare page number: `PAGE_NUMBER_RE`, which now also takes digits spaced by
   OCR ("1 5 6", "22 0"); or
2. it is no bigger than the body text (`size <= body_size * 1.05`), its key has at
   least 2 letters, and either
   - a. its row holds a bare page number (rule 1): "TIMEO ... 163", or
   - b. the same key is in the same row (top or bottom) of a page at most 2 pages
     before or after.

Anywhere on the page, a watermark (a line repeated mid-page on most pages, as today) is
furniture too.

The key is `running_key(text)`: case folded, accents and other combining marks removed,
only letters and digits kept, each run of digits as `#`. So "L O S TRASCENDENTALES" =
"Los trascendentales", "METAFÍSICA" = "METAFISICA", "3/49" = "4/49"; Greek stays Greek.
The Roman-numeral rule goes: rule 2b needs no help to find "CAP. III" on neighbouring
pages, and it made "L O S" read "# O S".

Why each part: rule 2b is the reader's cue (same line, same edge, nearby pages); the
size limit keeps titles and divider pages ("INTRODUCCION" 17.5 pt); "2 letters" keeps
"- § 4 -" marks (no letters, so never repeated text); 2 pages covers left/right heads
that alternate; rule 2a covers short excerpts (two pages, "TIMEO 163" / "164 DIÁLOGOS").

### Code

- `layout.py`
  - `running_key`: as above; delete `_ROMAN_RE`.
  - `PAGE_NUMBER_RE`: `\d(?: ?\d){0,3}` in place of `\d{1,4}`; `_PRINTED_NUMBER_RE`
    (printed page labels) the same, spaces removed before `int`.
  - New `edge_rows(lines) -> dict[int, str]`: line index → `"top"` / `"bottom"`.
  - `analyze_document`: replace the margin-zone block (the `margin_texts`,
    `margin_sizes`, `margin_bold`, `browser_*` collection and the `running` threshold
    after the loop) with: for each line on an edge row,
    `edge_pages[(edge, running_key(text))].add(page_index)`; printed page numbers from
    edge-row lines; watermark candidates are the lines not on an edge row (12+
    characters, as today).
  - `DocumentProfile`: `running_texts` and `browser_margins` become
    `edge_pages: dict[tuple[str, str], set[int]]`; `is_running(line, page_height)`
    becomes `furniture(page_index, lines) -> set[int]` (the rule above, watermarks
    included).
  - Delete `_MARGIN_ZONE`, `_RUNNING_SHARE`, `_MIN_SMALL_RUNNING`, `_BROWSER_FOOTER_RE`.
- `footnotes.py`, `layout_page`: compute `profile.furniture(page_index, lines)` first;
  give it to `_find_region` as `skip` (in place of the watermark set); leave those lines
  out of `body`; add `furniture: tuple[Line, ...]` to `PageLayout`. Now a running
  footer under the footnotes can't be read as a note, and `extract-text` loses the
  headers too (say so in the PR).
- `structure.py`, `add_page`: drop the `is_running` and `heads` filters (the lines are
  already gone). `_running_heads` becomes `_running_title(furniture, page_width)`:
  the head of a right-hand page (page number on the right half of its row, or a merged
  "TIMEO 163"), today's logic over the furniture lines of the top row. Delete
  `_HEAD_ZONE`; keep `_HEAD_WITH_NUMBER_RE` (the title only).
- Leave alone: `paddle_book._HEAD_ZONE` (Phase 6), `book_metadata._front_lines` (its
  own front-page rule).
- New `tools/page_parts.py PDF PAGE`: runs `analyze_document`, then `layout_page` on
  the page, and prints each line with its part (furniture / footnote / body), its top
  as a share of the page height, its size and its text. This is how to look at a page
  "as the pipeline sees it".

### Tests (write them first; check the first, fourth and fifth fail on main)

In `tests/test_convert.py`, next to `test_running_headers_and_page_numbers_are_dropped`:

1. A running head whose top is just below 10% of the page height (baseline y 100 of
   842, size 8, body 11: top at about 10.9%, as in Metafísica) on 4 pages, with a
   sentence running over a page break: the head is gone and the sentence is whole.
2. A body-size heading as the top line of one page among 4 is kept.
3. "- § 4 -", "- § 5 -" as the top lines of consecutive pages are kept.
4. Page numbers spaced by OCR ("1 5 6", "1 5 7") at the foot are dropped.
5. Unit: `running_key("L O S TRASCENDENTALES") == running_key("Los trascendentales")`,
   `running_key("METAFÍSICA") == running_key("METAFISICA")`,
   `running_key("LA CAUSALIDAD’") == running_key("LA CAUSALIDAD")`,
   `running_key("ΤΙΜΑΙΟΣ")` is not empty.
6. A divider page with "INTRODUCCION" in 18 pt alone, then pages headed "INTRODUCCION"
   in 8 pt: the divider's title survives once.

Must still pass unchanged: `test_running_headers_and_page_numbers_are_dropped`,
`test_a_printed_web_page_loses_the_browser_header_and_footer`,
`test_bold_chapter_lines_near_the_top_are_not_running_heads`,
`test_running_heads_leave_the_text_and_the_title_opens_the_book`, all of
`tests/test_footnotes.py`. (Checked 2026-10-28: in that last test "TIMEO" and "163" are
read as two lines on one row, so rule 2a keeps it working.)

### Check

- Fast tests, then `ruff check` and `ruff format`.
- `tools/regression.py build scratch/regress/phase1`, then `compare scratch/regress/base
  scratch/regress/phase1`. Expected: Metafísica's `splits` far below the baseline (write
  the number down); Kant identical; in every book, each lost heading and each removed
  line in the diff is a header, footer or page number. Read all of Metafísica's and
  Lugones' diffs; skim the rest.
- `PROGRESS.md`: this phase, with the numbers.

PR: "Headers and footers: the same small line at the edge of nearby pages".

## Phase 2: merge exact duplicates (small PR) (medium)

Only patterns and numbers that are the same in both places, so nothing changes:

- `_LONG_LINE_SHARE = 0.35`, in `margins.py` and `margin_refs.py`: keep one, import it
  (check for import cycles: `layout` imports `margin_refs`).
- Digit/superscript tables: `layout._SUPERSCRIPT_DIGITS` and `_FROM_SUPERSCRIPT`,
  `glued_refs._TO_SUP`, `note_numbers._TO_SUP` and `_FROM_SUP`,
  `paddle_ocr._TO_SUPERSCRIPT`: use `note_numbers.sup` / `from_sup`.
- Bare number: `margins._NUMBER_RE` and `layout._PRINTED_NUMBER_RE` (the same but for
  the group).

Not merged, only listed in `PROGRESS.md`: the "number starting a note" patterns
(`layout._PLAIN_NOTE_RE`, `glued_refs._NOTE_START_RE`, `margins._LEADING_NUMBER_RE`,
`footnotes._DEF_START_RE`). They differ (1–3 or 1–4 digits; what may follow), so merging
them would change results.

Check: fast tests; `compare` against the Phase 1 build shows no change at all.

## Phase 3: the layout model for every book (no change to the output) (medium)

1. `paddle_worker.py --layout-only`: no MLX server; the model PaddleOCR-VL-1.5 uses,
   with its settings (`paddlex/configs/pipelines/PaddleOCR-VL-1.5.yaml` in
   `.venv-paddle`):
   `LayoutDetection(model_name="PP-DocLayoutV3", threshold=0.3, layout_nms=True)`.
   Pages rendered at 150 dpi (the model resizes to 800×800 anyway). For each page
   `model.predict(str(image), batch_size=1)`; `result.json["res"]["boxes"]` items have
   `label`, `score` and `coordinate` (pixels). The result has no page size: write the
   pixmap's. Row: `{"page", "width", "height", "blocks": [{"label", "score", "bbox"}]}`.
   Worked this way on 2026-10-28; the model files are already in `scratch/paddle-home`.
2. `paddle_ocr.layout_pages(pdf_path, on_page=None) -> dict[int, dict]`: cached like
   `paddle_pages` (same `_read_rows`, a run that stops goes on where it stopped), under
   `cache_dir()/layout/`, keyed by the layout model's name and the file's hash; runs the
   worker without `--server`. This is the same local worker that already runs this model
   inside PaddleOCR-VL, not a new AI service; if the user wants it in ai-client, that's
   a move, not a rewrite.
3. `layout.box_labels(page, row, lines) -> list[str]`: for each line, the label of the
   box that covers more than half of it, else `""`; boxes scaled by
   `page.rect.width / row["width"]`.
4. `inbox._process_book`: for books built from the text layer, after `_prepare`,
   `layout_pages(pdf)` (step "looking at the pages"), passed through `convert_pdf(...,
   layout_rows=...)` to the `DocumentProfile` (`profile.layout`). Not used yet. Without
   the Paddle environment: say so once and go on without rows.
5. `tools/page_parts.py` shows the model's label beside the pipeline's part, and with
   `--png OUT.png` draws the boxes on the page image, a colour per label: what the
   model sees, to look at with the user.
6. Tests: `box_labels` with a made-up row; the worker only in an `integration` test
   that skips without `.venv-paddle`.

Check: `compare` shows no change. Then cache the rows of the eight books (one run,
about 50 min: `tools/run_logged.py`).

## Phase 4: measure the model against today's rules (report only) (high)

Write `tools/parts_report.py` and run it on the eight books. For each part, count the
lines (or pages) where today's rule and the model agree, where only the rule says so,
and where only the model does, with 5 example pages of each kind:

| Part | Today's rule | Model's labels |
|---|---|---|
| footnotes | `footnotes._find_region` | `footnote`, `vision_footnote` |
| contents pages | `structure._is_contents_page` | `content` |
| bibliography | `fixes._is_reference` and the back-matter headings | `reference`, `reference_content` |
| margin notes, line numbers | `margins.split_columns` glosses | `aside_text` |
| paragraph starts | `structure._starts_paragraph` | first line of a `text` box |
| headings | heading sizes | `doc_title`, `paragraph_title` |

Look at the example pages with `tools/page_parts.py --png`. Write the numbers and a
recommendation per part in `PROGRESS.md`, then **stop and ask the user** which parts
to switch.

## Phase 5: switch the parts the user picks (one PR each) (high)

Each PR uses the model for one part and deletes the rule it replaces; new tests use
made-up layout rows. Without rows (no Paddle environment) the part simply isn't
recognised and stays body text: no fallback rule is kept. Likely candidates:

- **Bibliography**: the lines of one `reference_content` box make one paragraph and a
  new box starts the next (entries no longer run together or split, as in Lugones).
  Phase 4: the model also labels notes sections `reference_content` (Dilexit pp. 58-63,
  Timeo Greek p. 215 on, Diálogos p. 349): one box per note is fine for paragraphs, but
  those must not be marked as a bibliography.
- **Contents**: a page whose lines are mostly in `content` boxes is a contents page
  (replaces counting `_CONTENTS_ENTRY_RE` lines).
- **Paragraph starts** (user, after Phase 4): no new paragraph inside one `text` box;
  today's rules decide only at box edges. This removes the rule's wrong splits (Niebla
  p. 171 OCR size jitter, Timeo web p. 22 word fragments); don't add a start at every new
  box (Phase 4: that adds ~177 and removes none). Paragraphs running on across a page or
  column stay joined as today. Risk: real breaks the model keeps in one box (Diálogos
  speaker turns "PRO. —Y tanto."): read those in the diff; if they are lost, keep the
  rule's split for such lines or stop and ask.
- **Headings** (user, after Phase 4): lines in a `paragraph_title` or `doc_title` box are
  headings, replacing the heading-size test; the level still comes from the font size.
  Gains: Metafísica's small-type section titles (p. 98), Kant's "Tesis"/"Prueba" (p. 195);
  drops the rule's mistakes (Kant p. 59 table rows, Niebla p. 28 OCR specks). Running
  heads labelled as titles must stay dropped (Phase 1's rule runs first).
  **Done (PR #77):** the plan's rule alone (a) lost real headings, so the user compared
  variants on 13 test books (`tools/headings_test.py` against
  `test_pdfs/book_tests_pdfs/truth.json`, 184 headings) and chose a+c+d on 2026-10-30:
  (a) a title-box line is a heading, (c) the size test stays for lines larger than any
  title box on the page (all large lines on a page without one), (d) a bare number
  ("1.", "V.") heading joins the line after it. Not taken: (b) the short all-caps/bold
  rule. Recall 72% -> 89%, precision 84% -> 87% against main's rules (PROGRESS.md).
  `tools/headings_test.py run OUT_DIR` scores today's code ("current"). The regression
  showed (d) joining Niebla's dotless chapter numerals ("III") to the chapter's first body
  line, so (d) is narrowed: no join to a line that runs on into the next body line (same
  `text` box, a trailing hyphen, or a full line without the model).
- **Footnotes**: only if Phase 4 shows the model finds notes the rule misses without
  new mistakes.

Each one goes in `layout_page`, not in `structure.py`. Check each with `compare`, and
read every changed paragraph of two books in the diff.

## Phase 6: books built from Paddle rows use the same header rule (high)

`paddle_book` drops blocks the model labels `header`, `number` or `footer`, with a
15% guard (`paddle_book.py:55`). But the model labels running heads as titles (above;
the Paddle cache also has "DIÁLOGOS" as `doc_title`), so they can end up as headings.
Apply the Phase 1 rule to Paddle blocks instead (the top and bottom rows of blocks,
the same key on a page at most 2 pages away, bare page numbers), and delete the guard.
Check on `philosophy.pdf` and a Platón: headings lost and added.
**Done (`layout/phase-6`):** `paddle_book.furniture`; the size limit is a block's height
against what it repeats (box heights wobble), and notes are never furniture. No heading
lost or added in either book; see `PROGRESS.md`.

---

## How to work through this at medium effort

- In Claude Code, `/pdf-layout-plan` runs the phases one after another, each as a
  subagent at the right effort (medium for 0, 2, 3; high for 1, 4, 5, 6), merging each
  PR, updating `main` and running the fast tests in between. In a terminal,
  `tools/run_plan.py` does the same with headless sessions (asking before each merge
  unless `--yes`). Both read where the plan stands from the `layout/phase-*` PRs, and
  both stop when a phase stops, when the tests fail, and after Phase 4 until the parts
  are chosen (`/pdf-layout-plan <parts>`, `--parts <parts>`).
- One phase per PR. Branch from an up-to-date `main` (`git fetch`, then
  `git switch -c <branch> origin/main`); never stack PRs.
- Follow `CLAUDE.md`: absolute paths; no `cd`, pipes or heredocs; throwaway code in
  `scratch/`; long runs with `tools/run_logged.py` and `tools/wait_log.py`; one pytest
  run at a time (they share `scratch/pytest`).
- Tests first; check the new ones fail before the change.
- At the end of each phase: fast tests, `ruff check`, `ruff format`, the regression
  `compare`, a `PROGRESS.md` entry, the PR, and the merge command
  `! gh pr merge <N> --repo fonsthefons/pdf-worker --merge --delete-branch`.
- Only the rules and numbers written here. If a book gets worse, record the page and
  line in `PROGRESS.md`, keep the rule as written, and ask the user.
- Stop at the end of Phase 4 for the user's choice.

## Known limits (accepted for now)

- Heads garbled beyond the key ("METAFISCIA"), or with no ungarbled copy within 2
  pages, stay in the text: 3 of about 190 in Metafísica.
- A small line repeated at the same edge of two pages at most 2 apart is taken for a
  header: for example a speaker's name at the top of two nearby pages in a play.
  Watch the `dialogos` diff.
- A head merged with its page number ("TIMEO 163") in an excerpt of one or two pages
  stays (rule 2b needs a neighbour; rule 2a needs the number on its own).
- The top row of a contents page may go by rule 2a (harmless: printed contents pages
  are dropped later).

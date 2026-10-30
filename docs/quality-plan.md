# Plan: measure whole books against answers no model wrote, then fix the biggest errors

Written 2026-10-30, after `docs/layout-plan.md` was finished. One phase per PR, each at
the effort at the end of its heading (low or medium). Read this whole file and the top
of `PROGRESS.md` first.

## Why

The layout plan measured parts of pages, mostly on eight test books, and the headings
part on 129 sample pages (`test_pdfs/book_tests_pdfs/`) whose answers (`truth.json`) a
model judged. Headings went from 72% found / 84% real to 89% / 87%. Three things are
still unknown or known to be wrong:

1. **The answers.** `truth.json` was written by one model pass and never checked, and
   the rules (c) and (d) of the headings part were chosen on the same pages, so 89/87
   is a little optimistic.
2. **Whole books.** Nothing measures a whole converted book: paragraphs, footnotes,
   running heads left in the text, wrong words. Several books have a reference EPUB
   (a human-made edition), which is an answer no model wrote.
3. **Known error kinds**, all general (not quirks of one book):
   - Footnotes put back into the body (layout Phase 4: 931 lines on the old test books)
     because no marker in the text was matched to them: a number glued to a word
     ("individual5"), "(1)" markers, a note running on from the page before.
   - Heading levels come from font size only: level agreement fell from 64% to 59%.
   - Lines made headings that aren't: notes in a title box ("3. Ibidem."), running heads
     garbled by OCR ("Fiiosofia del hombre"), letter-spaced titles
     ("E l c o m p u e s t o"), contents entries (the headings test skips steps a full
     conversion does, so check this one in a full conversion first).

## Rules for every phase: general rules, not rules for these books

The goal is any PDF, not these books. So:

1. **A rule states a general fact about printed books** ("numbered headings nest by
   their numbering style", "a running head repeats at the same edge of nearby pages"),
   written in a one-line comment and in the phase's `PROGRESS.md` entry. Never a test
   book's words, sizes, pages or a threshold tuned to make one book come out right.
2. **Numbers a rule needs come from the book itself** (its body font size, a median, the
   page's own notes), or are round values chosen before looking at the results.
3. **Words a rule needs** (division names like Parte/Part, Capítulo/Chapter) cover
   Spanish and English and live in one list.
4. **Held-out books: numbers only.** Never open their errors, diffs or pages while
   fixing; only read their row in the yardstick's held-out table.
5. **A fix that helps one working book and no other** is suspect: record it in
   `PROGRESS.md` and leave it out.
6. **Merge gate** (`tools/quality.py compare`, Phase 1): the phase's own measure gets
   better on the working books, and no other measure gets worse by more than the
   tolerance on the working or the held-out books. Tolerance: 1 point for percentages,
   1 per 10,000 reference words for counts. If the held-out books get worse beyond it,
   stop (draft PR, `STOPPED:`). If only a working book does, record the page and line
   and stop the same way.
7. The eight regression books (`tools/regression.py`) are run too; read the headings
   lost and added for anything clearly wrong.

## Effort and fan

| Phase | Effort | Heavy work (fan) |
|---|---|---|
| 0: check the answers, held-out pages | low | none (page images only) |
| 1: whole-book yardstick, baseline | medium | yes: the layout model on whole books not yet cached, then all builds (30-60 min) |
| 2: footnotes kept as notes | medium | two yardstick runs (10-20 min each, model rows cached) |
| 3: heading levels | medium | same |
| 4: lines that aren't headings | medium | same |
| 5: the biggest error left | medium | same |
| 6: final check and report | low | one yardstick run |

Run heavy builds one at a time: two Paddle builds at once collide on the shared crop
cache (Phase 6 of the layout plan).

---

## Phase 0: check the answers, and held-out pages (low)

Goal: answers that two independent looks agree on, and a second page set that no fix
will ever look at. No model runs, no conversions: page images only.

**What counts as a heading** (write this definition at the top of the phase's
`PROGRESS.md` entry and use it for every page): a line or lines set apart, on their own,
as the title of a division of the text (part, book, chapter, section, subsection), by
size, weight, capitals, centring, spacing or numbering. Not headings: running heads and
page numbers; contents and index entries; captions and table cells; a bold or italic
phrase that starts a paragraph whose text goes on after it on the same line (a run-in
head); the lines of a title page (book title, author, publisher). A heading's number
and its title are one heading, even on two lines ("CAPÍTULO PRIMERO" / "LA VIDA").
Level: 1 is the biggest division in the book's sample pages, then 2, 3...; levels only
rank headings within one book.

1. **Second look at `test_pdfs/book_tests_pdfs/`.** Render every page of every book in
   its `manifest.json` to PNG (150 dpi, PyMuPDF or `tools/render_clip.py`) in
   `scratch/truth_check/`. Before opening `truth.json`, write your own answer for every
   page into `scratch/truth_check/second.json` (same format as `truth.json`). Only then
   compare with `truth.json`. For each disagreement and each entry in a book's
   `uncertain` list, look at the image again and decide by the definition. Write the
   decisions into `truth.json`, empty the `uncertain` lists, and add to each book a
   `checked` list: each change with a few words of why. Count the changes (headings
   added, removed, level changed) for `PROGRESS.md`.
2. **Held-out pages** in `test_pdfs/book_tests_pdfs/heldout/`, the same layout
   (`manifest.json`, `truth.json`, one small PDF per book). Books: the PDFs in
   `test_pdfs/new_test_books/` (subfolders too) that no page in
   `test_pdfs/book_tests_pdfs/manifest.json` comes from, skipping exact copies (same
   page count and the same text on 3 sample pages) and books used by the regression
   set; plus two English books of other kinds: `test_pdfs/Distinction - Piere
   Bordieu.pdf` and `test_pdfs/Gibbon Decline and Fall vol 1 (1872 scan).pdf`. Pick 8
   pages per book by role, as the first set did (`PROGRESS.md`, "headings test set"):
   chapter openings, numbered sections, a contents page, a notes page, a list or table
   page, plain body. Judge each page twice the same way as step 1: one pass written
   to `scratch/truth_check/heldout_first.json`, a second pass written without looking
   at the first, then settle the differences against the image.
3. `tools/headings_test.py`: add `--set heldout` (default: the first set) to `run` and
   `score`; check `selftest` still passes. Don't run `run` (it starts the model).
4. `test_pdfs/` is gitignored: the pages and answers stay on this machine. Record in
   `PROGRESS.md` which books and pages went into the held-out set, and the change
   counts of step 1.

PR: "Headings test: checked answers and held-out pages" (the code change of step 3 and
`PROGRESS.md`).

## Phase 1: whole-book yardstick and baseline (medium)

Goal: one command that scores whole converted books against reference EPUBs and runs
both headings page sets; the numbers on today's `main`; the error kinds ranked.

1. **Reference pairs.** Candidates (a PDF and a reference of the same book):
   - `test_pdfs/philosophy.pdf` and `test_pdfs/philosophy_epub_good.epub`
   - `test_pdfs/new_test_books/copleston/Historia de la Filosofía Tomo 1 - Copleston.pdf`
     and `.../copleston/1 - Grecia y Roma Frederick Copleston.epub`
   - `test_pdfs/new_test_books/Introduction to Christianity by Ratzinger.pdf` and its
     `.epub`
   - `test_pdfs/lugones_imperio_jesuitico_1904.pdf` and
     `test_pdfs/refs/lugones_imperio_jesuitico_wikisource.epub`
   - a Timeo PDF in `test_pdfs/` and `test_pdfs/El Timeo (La Atlántida).epub`;
     `test_pdfs/platon_dialogos_vi_bad.pdf` and `test_pdfs/Dialogos Completos Platon.epub`
     (the reference holds more than the PDF: score only the part that aligns)
   - any `test_pdfs/refs/pg*.txt` / `pg*.epub` whose book is a PDF in `test_pdfs/`
     (plain text: words and paragraphs only)

   **Same-text check** for each (the same text, not necessarily the same printed
   edition: another edition of the same translation has the same body text and nearly
   the same paragraphs; a different translation fails): take 3 samples of 300 words
   from the PDF's text (pages at 25%, 50%, 75%; for a scan without a text layer, the
   Paddle rows if cached, otherwise skip the pair). The pair passes if, in at least 2
   of the 3 samples, at least 85% of the word triples occur in the reference. Record
   each pair, its result, whether it looks like the same edition (same front matter,
   same notes), and which measures its reference supports (heading tags? note
   markup?) in a table in this file, under "Reference pairs" at the end.
2. **Working and held-out.** A pair whose PDF never had a page in any test set so far
   (the eight regression books, the layout plan's Phase 6 books, either headings page
   set) is held-out; the rest are working. If no pair is held-out, the held-out side is
   the held-out pages only. Write the split into the table.
3. **`tools/book_score.py REFERENCE OURS.md`** (reuse `tools/epub_score.py`'s reader
   where it fits; the reference is an EPUB or a `.txt`). Align the two as word
   sequences (lower case, punctuation off): anchors are word 5-grams that occur once in
   each, kept in order (longest increasing run), and `difflib` between anchors; never
   `difflib` on whole books (too slow). Only the reference span between the first and
   last anchor counts. Measures, each per book:
   - **words**: reference words matched, missing, and extra words in ours, per 10,000
     reference words;
   - **headings**: the reference's `h1`-`h6` against our `#` lines (a match: at least
     80% of the heading's words align): found %, real %, and level agreement by pairs
     (as `headings_test.py` scores it). A reference heading whose words appear nowhere
     in ours doesn't count as missed (another edition may add it); one whose words are
     in our body text does;
   - **paragraph breaks**: the reference's paragraph starts against ours, at aligned
     words, headings left out: breaks found %, breaks real %;
   - **notes in the body**: reference note words (EPUB footnotes or endnotes: `aside`,
     `epub:type` note, or the targets of note links) that align into our body text
     rather than our `[^n]:` notes, per 10,000 reference words; only when the reference
     marks its notes;
   - **leftovers**: extra lines in ours that repeat 3 or more times (running heads) or
     are a bare number (page numbers), per 10,000 reference words.
   `selftest`: a tiny made-up pair (a Markdown string and an EPUB made with `zipfile`
   in `scratch/`) with one missed heading, one note in the body, one extra break and
   one running head, and the expected numbers.
4. **`tools/quality.py`**:
   - `build OUT_DIR`: each pair's PDF converted to `OUT_DIR/<label>.md` as
     `tools/regression.py build` does (reuse its code: title and author given,
     `fixes_path` in `OUT_DIR`, cached layout rows), then `book_score`; then
     `headings_test.py run` for both page sets into `OUT_DIR/headings/` and
     `OUT_DIR/headings_heldout/`. Books one at a time. Writes `OUT_DIR/quality.json`
     and `OUT_DIR/report.md`: a working table and a held-out table, one row per book
     and a total row, one column per measure, plus each measure's rate per 10,000
     reference words for ranking.
   - `compare BEFORE AFTER`: every measure before -> after, working and held-out
     apart, each change marked if it is beyond the tolerance (rule 6).
   Add both tools to the dev-tools list in `CLAUDE.md`.
5. **Baseline** on an up-to-date `main`:
   `.venv/bin/python tools/run_logged.py quality_base .venv/bin/python tools/quality.py build scratch/quality/base`
   (absolute paths), then `tools/wait_log.py`. Build twice: `compare` must show no
   change; if it does, find out why before going on.
6. **Ranking.** In `PROGRESS.md`: the working books' error kinds (notes in the body,
   missing or extra words, broken or extra paragraph breaks, leftovers, headings missed,
   wrong headings, level disagreement) by their rate per 10,000 reference words, and
   for the 3 biggest kinds, 3 example pages each (working books only), with what
   causes them.

PR: "tools/quality.py: whole books against reference EPUBs".

## Phase 2: footnotes kept as notes (medium)

Goal: note text stays out of the body. Measure: **notes in the body** (working books).

0. If the baseline shows fewer than 5 note words in the body per 10,000 reference words
   in every working book with marked notes, write that in `PROGRESS.md`, open the PR
   with only that entry, and end: nothing to fix.
1. Find the causes on the working books' worst pages (`tools/page_parts.py`,
   `tools/parts_report.py --show`). Known from the layout plan's Phase 4: notes whose
   region `footnotes._find_region` finds are put back into the body by
   `footnotes._collect_footnotes` because no marker in the text matches them: a number
   glued to the word before it ("individual5"; `glued_refs.py` marks some), "(1)" or
   "[1]" or "*" markers, a note running on from the page before.
2. The general facts to build on: notes on a page are numbered in order (or with
   symbols in their usual order *, †, ‡); a note's marker sits in the body above it,
   as a superscript, a glued number, or a bracketed number; a note that starts without
   a number at the top of the region continues the page before's last note.
3. A line in the found region that starts with the next number of the page's note
   sequence is a note even when no marker matches: attach it where the nearest marker
   of its sequence is, or else at the end of the page's last paragraph, never in the
   body. Tests first (`make_pdf`), checked to fail on `main`.
4. Gate: rule 6. Then the PR.

## Phase 3: heading levels from the book's numbering (medium)

Goal: headings ranked as the book ranks them. Measure: **level agreement** (headings
test, both sets; reference EPUBs with heading tags). Which lines are headings must not
change: headings found and real stay equal.

0. Skip (as Phase 2 step 0) if level agreement is 85% or more on the checked first page
   set and on the working reference books.
1. Today `layout.heading_level` ranks by font size. The general fact: a book nests its
   divisions in a fixed order, and each kind of heading keeps its rank throughout the
   book. A heading's kind is its key: the division word if it starts with one (one
   list, Spanish and English: Parte/Part, Libro/Book, Capítulo/Chapter,
   Sección/Section, Lección/Lesson, Tema, Artículo/Article, Cuestión/Question), its
   numbering style (Roman "IV.", Arabic "4.", decimal "4.2", letter "a)", none), and
   whether it is in capitals, then its font size rounded to 0.5 pt.
2. Levels by first appearance: the book's first heading is level 1; a key seen before
   keeps its level; a new key goes one level below the heading before it, except that
   a division word ranked above the current one (in the list's order) goes above it.
   Front matter before the first heading with a division word or a number doesn't set
   levels. Font size alone decides only between keys that are otherwise the same.
   Levels stop at 6.
3. Tests first. Gate: rule 6, and found / real unchanged.

## Phase 4: lines that aren't headings (medium)

Goal: fewer wrong headings. Measure: **headings real %** (both page sets, reference
books), with **headings found %** not lower beyond the tolerance.

0. For each wrong heading in the checked first set's report, check in a full
   conversion of that book (`.venv/bin/pdf-worker extract-text`, or the yardstick's
   Markdown) whether it is still wrong there: the headings test skips steps a full
   conversion does (contents pages are dropped later, for one). Fix only kinds still
   wrong in full conversions. Skip the phase (as Phase 2 step 0) if real % is 95% or
   more.
1. The kinds known so far, each with its general fact:
   - **Running heads garbled by OCR** ("Fiiosofia del hombre" beside "Filosofia del
     hombre"): a running head repeats at the same edge of nearby pages, so a line at
     that edge within 2 pages of a known running head, differing by at most 20% of its
     letters (6 letters or more), is the same head. Extends the repetition rule of the
     layout plan's Phase 1 (`layout.running_key`).
   - **Notes in a title box** ("3. Ibidem."): a line below the page's last body line,
     in note-sized type or in the found note region, is a note whatever box it is in.
   - **Letter-spaced titles** ("E l c o m p u e s t o d e s u s t a n c ia"): a run of
     4 or more one- or two-letter pieces; join the letters, then split them into words
     the book itself uses elsewhere (its own vocabulary, not a fixed list); if no split
     uses only such words, leave the line as it is.
   - Contents and index entries, only if step 0 shows they survive a full conversion:
     a page the model labels `content`, or `structure._is_contents_page`, makes no
     headings.
2. Tests first. Gate: rule 6.

## Phase 5: the biggest error left (medium)

Goal: the largest error kind still left, whatever it is. Run the yardstick on an
up-to-date `main` and take the working books' biggest kind by rate per 10,000
reference words that Phases 2-4 didn't cover. If it is under 5 per 10,000, record that
and end with a PR holding only the `PROGRESS.md` entry. Otherwise: find its cause on 3
working pages, write the general fact it breaks, fix that one kind (tests first), and
gate by rule 6. One kind only.

## Phase 6: final check and report (low)

Run the yardstick on an up-to-date `main` and `compare` it with Phase 1's baseline
(rebuild the baseline from Phase 1's merge commit if `scratch/quality/base` is gone,
with `git worktree` inside `scratch/`). In `PROGRESS.md` and under "Results" below: the
working and held-out tables before and after, what each phase changed, and the error
kinds left, ranked, with one example page each. No code changes.

PR: "Quality plan: results".

---

## How to work through this

- In Claude Code, `/pdf-layout-plan quality` runs the phases one after another, each
  as a subagent at its effort, merging each PR, updating `main` and running the fast
  tests in between. In a terminal, `tools/run_plan.py --plan quality` does the same
  with headless sessions (asking before each merge unless `--yes`). Both read where the
  plan stands from the `quality/phase-*` PRs and stop when a phase stops or the tests
  fail.
- One phase per PR. Branch from an up-to-date `main` (`git fetch`, then
  `git switch -c <branch> origin/main`); never stack PRs.
- Follow `CLAUDE.md`: absolute paths; no `cd`, pipes or heredocs; throwaway code in
  `scratch/`; long runs with `tools/run_logged.py` and `tools/wait_log.py`; one pytest
  run at a time; one Paddle build at a time.
- Tests first; check the new ones fail before the change.
- At the end of each phase: fast tests, `ruff check`, `ruff format`, the yardstick
  `compare` (from Phase 2 on), the regression `compare`, a `PROGRESS.md` entry, the PR.
- Nobody answers questions while a phase runs: decide by this file and record the
  decision. Stop (draft PR) only where this file says so or a check fails in a way it
  doesn't cover.

## Reference pairs

Phase 1's same-text check (`scratch/quality/same_text.py`): 300 words at 25%, 50% and
75% of the PDF (the text layer, or the cached Paddle rows for a book built from them),
words hyphenated at a line end joined, bare numbers (page and line numbers) dropped; the
share of word triples found in the reference. Pass: 85% or more in 2 of the 3 samples.
Labels as in `tools/quality.py`. Measures: W words, H headings, B paragraph breaks,
N notes in the body, L leftovers.

| Label | PDF | Reference | Samples | Result | Same edition? | Measures | Set |
|---|---|---|---|---|---|---|---|
| philosophy | `philosophy.pdf` (Paddle rows) | `philosophy_epub_good.epub` | 97/99/99% | pass | same translation (Sacristán), another layout: the PDF's run-in section numbers are `h` headings in the EPUB, its footnotes are endnotes there | W H B N L | working (layout Phase 6) |
| copleston | Copleston `Historia de la Filosofía Tomo 1` | `1 - Grecia y Roma` EPUB | 99/99/99% | pass | same translation; EPUB endnotes | W H B N L | working (headings pages) |
| ratzinger | `Introduction to Christianity` PDF | its EPUB | 100/100/100% | pass | same edition (EPUB page-list of the print edition, footnotes as `aside`) | W H B N L | working (headings pages) |
| lugones | `lugones_imperio_jesuitico_1904.pdf` | `refs/lugones_imperio_jesuitico_wikisource.epub` | 90/93/86% | pass | same 1904 edition (a Wikisource transcription; page numbers skipped as `pagenum`) | W B N L (its `h` tags mark the title page only) | working (regression) |
| platon_bad | `platon_dialogos_vi_bad.pdf` (Paddle rows) | `Dialogos Completos Platon.epub` | 79/90/97% | pass | same Gredos translation; the reference holds every dialogue: only the part that aligns counts | W H B N L | working (layout Phase 6) |
| dialogos | `platon_dialogos_vi_good.pdf` | `Dialogos Completos Platon.epub` | 96/83/87% | pass | as platon_bad | W H B N L | working (regression) |
| niebla | `niebla_1914.pdf` | `refs/pg49836.txt` | 88/82/90% | pass | plain text: words and paragraphs only | W B L | working (regression) |
| pepita | `pepita_1901.pdf` | `refs/pg17223.txt` | 88/87/88% | pass | another edition (PG: 1874) | W B L | held-out |
| marianela | `marianela_1888.pdf` | `refs/pg17340.txt` | 96/95/97% | pass | another edition (PG: 1878) | W B L | held-out |
| gaviota | `gaviota_1856.pdf` | `refs/pg23600.txt` | 95/89/82% | pass | old print, old accents; the PDF is volume 1, PG holds both (scored as a collected reference: only what aligns counts) | W B L | held-out |
| - | `Platon - Timeo.pdf`, `Timeo-Platón.pdf`, `Timeo_by_Platón.pdf`, `..._no_intro.pdf` | `El Timeo (La Atlántida).epub` | 0-1% | fail | the EPUB is only the Atlantis passage (1,180 words, Greek and another translation) | - | - |
| - | `barraca_1901.pdf` | `refs/pg14944.txt` | 83/84/64% | fail | PG is a revised edition (whole phrases differ) | - | - |
| - | `sombrero_1907.pdf` | `refs/pg29506.txt` | 82/92/75% | fail | school edition: line numbers, handwritten glosses between the lines | - | - |
| - | `perfecta_1897.pdf`, `lazarillo_1900.pdf` | `refs/pg15725.epub`, `refs/pg320.txt` | - | skipped | scans without a text layer and no cached Paddle rows | - | - |

Held-out: pepita, marianela and gaviota never had a page in the regression set, the
layout plan's Phase 6 or either headings page set (15 pages of each were read in an
earlier OCR spelling check, before this plan). The held-out side is these three books
and the held-out headings pages.

## Results

(Filled in by Phase 6.)

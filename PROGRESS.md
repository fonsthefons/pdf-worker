# Progress

## Done

### Feature 1: PDF text extraction (2026-10-11)
- `pdf-worker extract-text <pdf> [-o out.txt] [--page-separator SEP]` streams the text layer
  page by page into a UTF-8 `.txt`, written atomically, and warns about pages with no text.
- Library choice: PyMuPDF (cleaner output than pypdf on the noisy OCR sample; licensed AGPL).
- Files: `pyproject.toml`, `src/pdf_worker/{cli,document,errors,text_extraction}.py`,
  `tests/{conftest,test_text_extraction,test_cli,test_integration_test_pdfs}.py`.
- Results: Kant, 206 pages, 681k chars, about 1s. Familia Romana, 332 pages, 557k chars,
  about 1s; pages 1, 2, 331 and 332 are image-only. Its text layer is poor OCR, and
  re-OCR would be a separate future feature.

### Repo setup for autonomous work (2026-10-11)
- Working rules added to `CLAUDE.md`. `scratch/` (gitignored) holds all temp files.
- pytest `tmp_path` redirected to `scratch/pytest` in `tests/conftest.py`.

### First commit and PR (2026-10-11)
- `test_pdfs/` and `.claude/settings.local.json` are gitignored: the PDFs are large and
  copyrighted, and the repo is public.
- Scaffolding is committed on `main`. Feature 1 is on `feature/text-extraction`.
- Once the user allowed pushing, both branches were pushed, PR #1 was opened and merged
  (https://github.com/fonsthefons/pdf-worker/pull/1), and local `main` was fast-forwarded.

### Feature 2: explicit footnotes in text extraction (2026-10-11)
- New `src/pdf_worker/footnotes.py`: an analysis pass (body font size, bracketed numbers)
  then per-page rendering. Output uses Markdown footnote syntax: page footnotes
  `[^p12-1]`, bracketed endnotes `[^31]`, notes continued onto the next page are
  re-emitted as `[^label]: (continued) ...`.
- `extract-text` marks notes by default (`--no-footnotes` opts out) and reports counts,
  plus warnings for unmatched references or notes.
- Samples: none of the three samples has classic bottom-of-page footnotes (checked with
  `scratch/scan_small_text.py`), so that path is covered by generated PDFs in
  `tests/test_footnotes.py`. The encyclical has 224 bracketed endnotes: all 224 linked.
  Kant and Familia Romana: 0 notes, and the output is byte-identical to the raw text.
- False positives found and fixed on Familia Romana: margin glosses and line numbers
  (the region must sit below all body text) and numbered exercises `[1]`–`[6]` (endnote
  numbers must occur ≤3 times, mostly mid-line).
- Cost: the analysis pass roughly doubles extraction time (still about 2s for 332 pages).
- Not handled yet: endnotes referenced by superscript numbers with a "Notes" chapter at the
  end; this needs per-chapter number matching.
- Files: `footnotes.py`, `text_extraction.py`, `cli.py`, `tests/conftest.py`
  (`make_layout_pdf` fixture), `tests/test_footnotes.py`,
  `tests/test_integration_test_pdfs.py`, `README.md`.

### OCR research and plan (2026-10-12)
- Plan written to `docs/ocr-plan.md`: Tesseract via OCRmyPDF as the default, an
  evaluation of PaddleOCR-VL-1.6 (MLX) for hard scans, and Apple Vision as an optional
  fast engine.
- Measured on the M1 at 300 dpi with `scratch/ocr_bakeoff.py`. Both engines get under 1%
  CER on clean pages. On the Familia Romana scan, both lose macrons; Tesseract keeps the
  margin column separate, while Vision interleaves it with the body.
- Installed: `brew install tesseract tesseract-lang` (system-wide, allowed by the current
  rules), plus `ocrmac` and `rapidfuzz` in `.venv`, now listed under the `ocr-eval` extra
  in `pyproject.toml`.

### Feature 3: convert to EPUB and Markdown (2026-10-12)
- `pdf-worker convert book.pdf [-o out.epub|out.md] [--to epub|md] [--title --author
  --language]`.
- Pipeline:
  1. `layout.py`: one analysis pass (body size, line spacing, heading sizes, running
     headers/footers, endnote candidates, a text sample for language guessing).
  2. `footnotes.layout_page`: body lines and notes.
  3. `structure.iter_blocks`: headings, paragraphs, notes, streamed.
  4. A writer: `epub.py` or `markdown_export.py`.
- EPUB: chapters are streamed into the zip; notes go to a temp file and become
  `notes.xhtml` (footnote asides linked both ways for Kindle pop-ups); nav plus NCX.
- Results: all three samples pass `epubcheck` with 0 messages. The encyclical has 224
  linked notes, 32 headings, language `es`. Kant: 43 headings, 908 paragraphs.
- Known rough spots:
  - Familia Romana (noisy OCR layer, line numbers and margin glosses) gives over 9,000
    short paragraphs; re-OCR is needed first.
  - The encyclical's on-page table of contents becomes headings and short paragraphs.
  - Images and tables are not carried over.
- Kindle check: validated with epubcheck. I couldn't test on a real device or Send to
  Kindle from here.
- Files: `layout.py`, `footnotes.py` (refactor), `structure.py`, `output.py`,
  `markdown_export.py`, `epub.py`, `convert.py`, `cli.py`, `tests/test_convert.py`,
  `tests/test_integration_test_pdfs.py`, `README.md`.

### Feature 4: OCR with Tesseract via OCRmyPDF (2026-10-12)
- Chosen engine: Tesseract via OCRmyPDF, the recommendation in `docs/ocr-plan.md`. It
  writes a PDF with a text layer, so the existing commands work on the result unchanged.
- New `src/pdf_worker/ocr.py` and `pdf-worker ocr in.pdf [-o out.pdf] [--lang lat+eng]
  [--mode skip|redo|force] [-j N]`. `extract-text` and `convert` also take
  `--ocr [MODE]` and `--ocr-lang`, which OCR into a temporary PDF next to the output and
  delete it afterwards.
- The language is guessed: from the text layer if there is one, otherwise from an
  English OCR of 2 middle pages. Guesses map to Tesseract codes (`es` to `spa`, `la` to
  `lat`). Missing Tesseract, missing OCRmyPDF and missing language models each give a
  clean `Error:` with an install hint.
- `ocrmypdf>=17.13` is in a new `ocr` extra. Ghostscript isn't needed with
  `output_type="pdf"`.
- Familia Romana, full book with `--mode redo`: language guessed as `lat`, and the
  image-only cover now has text. Tesseract reads long vowels as accents (`Màrcus`,
  `Iülia`, `nón`) where the old layer dropped them (`Marcus`, `Julia`). Margin glosses
  are cleaner (`-um` instead of `-urn`), with some junk from the pictures. `convert` on
  the result is still fragmented (459 headings, 9,725 paragraphs). The cause is the
  layout (line numbers, margin column), not the OCR.
- Tests: `tests/test_ocr.py` (12 tests, generated image-only PDFs, skipped when Tesseract
  is missing) and an integration test on Familia Romana pages 1 and 25.
- Files: `ocr.py`, `cli.py`, `convert.py` (`pdf_title`), `pyproject.toml`, `README.md`,
  `docs/ocr-plan.md`, `tests/test_ocr.py`, `tests/test_integration_test_pdfs.py`.

### Feature 5: Latin macrons in OCR (2026-10-12)
- Tesseract's `lat` model reads long vowels as accents (`Màrcus`, `Iülia`, `nón`), and
  sometimes as a doubled vowel (`Maàrcus`, `nàávis`).
- New `macrons.py` (`restore_macrons`) turns every grave/acute/circumflex/tilde/breve/
  diaeresis vowel into a macron vowel and collapses the doubled forms.
- New `ocr_latin_plugin.py` is an OCRmyPDF plugin that subclasses the Tesseract engine
  and rewrites the hOCR and text output before the text layer is built. It is loaded by
  module name, so the worker processes find it.
- On automatically when `lat` is an OCR language; `pdf-worker ocr --no-latin-macrons`
  turns it off. The report and CLI summary say when it was applied.
- Result on the full Familia Romana (`scratch/count_macrons.py`): 16,118 macron vowels,
  1 accent left. Tesseract still misses many long vowels entirely, so recall is uneven.
  In this book these words always carry a macron:

  | Word | Read with macron | Read plain |
  |---|---|---|
  | `Iūlia` | 167 | 13 |
  | `nōn` | 468 | 400 |
  | `Mārcus` | 124 | 280 |
- Tests: `tests/test_macrons.py` (11), 2 new tests in `tests/test_ocr.py`, and an
  integration check (`Iūlia` on Familia Romana p. 25).

### Feature 6: margin glosses and line numbers in convert (2026-10-12)
- New `margins.py` (`split_columns`) runs per page in `structure.py`:
  - It finds the body column from long lines (left edge from the most common x0, right
    edge from the 80th-percentile x1).
  - Lines entirely outside the column are margin lines. They only count as glosses if
    each side column is narrower than 60% of the body and holds at most half its text,
    so a two-column body isn't mistaken for glosses.
  - Bare numbers at the column edge are dropped, and line numbers glued onto a body
    line (`70 Puer…`, `…eum 55`) are stripped.
  - With margins found, the body is sorted top to bottom.
  - Same-row fragments are joined into one line (`merge_rows`, used on every page).
  - Lines with no letters or digits are dropped, except section breaks like `* * *`.
- New `Gloss` block, queued like footnotes, so it follows the paragraph in progress.
  Markdown writes it as a blockquote with `\` hard breaks; EPUB as `div.gloss`.
  `WriteStats.glosses` is new, and the CLI prints it.
- Paragraphs: the size-change test now compares a line with its block's mean size
  (threshold 8%, at least 0.6 pt), and wrapped lines keep the block's kind. This fixes
  OCR size jitter splitting paragraphs.
- Running headers: `running_key` normalises Roman numerals (`CAP. III`), and the margin
  zone grew from 8% to 10% of the page height.
- Results:

  | Sample | Before | After |
  |---|---|---|
  | Familia Romana, OCR'd with macrons | 459 headings, 9,659 paragraphs | 343 headings, 4,090 paragraphs, glosses separated |
  | Kant | — | Unchanged except one stray `.` paragraph dropped |
  | Encyclical | — | 224 notes; the web header's `ESPAÑOL` link became a gloss; the footer links joined onto one line |

  The Familia EPUB passes epubcheck.
- Tests: `tests/test_margins.py` (6) and an integration test (OCR plus convert of
  Familia pp. 25–26).

### OCR phase 2: PaddleOCR-VL-1.6 evaluation (2026-10-12)
- Results and decision are in `docs/ocr-plan.md` ("Phase 2 results").
- Installed:
  - `brew install python@3.12` (system-wide; PaddlePaddle has no 3.14 wheel).
  - `.venv-paddle/` (gitignored) with paddlepaddle 3.2.1 (CPU), paddleocr 3.7.0 and
    mlx-vlm 0.7.6.
  - The models (1.9 GB) are in `scratch/paddle-home` (HOME, HF_HOME and
    PADDLE_PDX_CACHE_HOME are redirected in `scratch/paddle_env.py`).
- Results on hand-transcribed Familia Romana pp. 9 and 25:

  | Engine | Long-vowel recall | Word recall |
  |---|---|---|
  | PaddleOCR-VL + `restore_macrons` | 94% | 97–98% |
  | Tesseract + macron fix | 44–50% | 81–82% |

  Speed is 12–24 s per page (rule: at most 10), so the speed rule fails. Kant CER is
  0.81% and 0.03%. Paddle also hallucinates now and then, swapped two paragraphs once,
  and dropped glosses on p. 25.
- Decision: Tesseract stays the default. Recommended next: integrate Paddle as an opt-in
  `--engine paddle` for hard scans (phase 3).
- Code change: `restore_macrons` also handles ring-above (`å`, which Paddle outputs),
  with a test.
- To re-run: start `.venv-paddle/bin/python scratch/paddle_server.py` (in the
  background), then `.venv-paddle/bin/python scratch/paddle_eval.py familia:25 ...`,
  then `.venv/bin/python scratch/paddle_truth.py`.

### Feature 7: chapter endnotes and real footnoted books (2026-10-13, PR #9)
- Samples (public domain, in `test_pdfs/`, gitignored):
  - Supreme Court Trump v. CASA (113 pages, 42 footnotes, a "Page Proof Pending
    Publication" watermark).
  - 9/11 Commission Report (585 pages, 1,742 endnotes in 13 chapter groups).
  - Gibbon, Decline and Fall vol. 1 (archive.org scan, unusable word-level OCR layer; I
    re-OCR'd it to `scratch/gibbon.ocr.pdf`).
- New `endnotes.py`:
  - Superscript number runs (restarting at 1) and numbered note lines (`12.` or
    `12.Text`) are grouped into sequences.
  - A sequence resumes after a numbered list inside a note.
  - Runs pair with groups by an LCS on counts, with groups after runs. Labels are
    `c<group>-<n>`.
  - `section_continues` tells whether a notes section goes on, so per-chapter
    subheadings inside it are dropped.
- `structure.py`:
  - Notes zone: a note's later paragraphs stay in the note (`PARAGRAPH_BREAK`, `\n\n`).
  - Subheadings in the zone are dropped. The zone ends after a group's last note at a
    heading or type change.
  - Writers: Markdown indents continuation paragraphs; EPUB writes one `<p>` each.
- Footnote detection fixes:
  - The region is found in vertical order (so a watermark or a stray box doesn't hide
    it), and watermark lines are skipped.
  - The region must sit under a column of body-size text; this kills Familia glosses
    and index pages.
  - Two-column notes are accepted and read column by column.
  - OCR jitter and specks are tolerated; printers' signature marks are skipped.
  - `*8`-style OCR markers are recognised.
  - Without superscript refs, a plain-text marker must be indented or ≤ 30 (this killed
    the `341 F. 2d` false note).
- Layout:
  - Watermarks: mid-page lines repeated on ≥ 50% of pages are dropped.
  - Small-type margin lines repeated on ≥ 4 pages are running heads ("NOTES TO
    CHAPTER 1").
  - Junk PDF titles like `201-635.job` are ignored.
- Results:

  | Sample | Before | After |
  |---|---|---|
  | Court opinion | 8 notes | 42/42 linked |
  | 9/11 report | 49 false notes | 1,742/1,742 refs linked (1 extra def), EPUB valid |
  | Gibbon after OCR | 34 pages with notes | 302 pages; 601 notes in EPUB, mostly unlinked because OCR garbles the markers |

  Familia still has 0 notes.
- Tests: `tests/test_endnotes.py` (5) and 3 new integration tests.

## Blocked
- None. (Claude couldn't edit `.claude/settings.local.json` itself, so the user copied in the
  version from `scratch/settings.local.json` on 2026-10-11.)

## Resume here (keep this current; a new session should start from this)
- **Overnight task (user request 2026-10-12): do next steps 1–8, PR and merge each.**
  The user's answers:
  - Test books: download public-domain footnoted and endnoted books (archive.org,
    Gutenberg) into `test_pdfs/` (gitignored).
  - Output formats for item 7: docx, HTML, clean plain text, reflowed PDF (EPUB and
    Markdown exist already).
  - Paddle: `--engine paddle` auto-starts and stops the MLX server from `.venv-paddle`.
  - Printed contents pages: drop them (the EPUB has its own TOC).

  The items, with status:
  1. [x] Endnotes referenced by superscripts, with notes in a "Notes" section/chapter
     (PR #9, together with item 2).
  2. [x] Real footnoted books: downloaded the court opinion, the 9/11 report and the
     Gibbon scan, tuned detection on them, added integration tests.
  3. [ ] Images and a cover in the EPUB.
  4. [ ] One-step `pdf-worker kindle`: auto-detect OCR need and mode, then EPUB.
  5. [ ] `--engine paddle` (opt-in).
  6. [ ] Clean-ups: tables in EPUB, drop the printed TOC, fewer false headings, keep the
     title for OCR'd files.
  7. [ ] Formats: docx, html, txt, pdf.
  8. [ ] GitHub Actions CI.
  9. [ ] (added mid-task) Internal links: PDF link annotations (contents entries,
     cross-references) become working EPUB links to the target chapter or page. The
     user noticed the encyclical's index wasn't linked. A printed TOC whose entries
     resolve to links is kept as a linked list; one without links is dropped.
  10. [ ] (added mid-task) Kindle page numbers instead of only "Loc": EPUB 3 page-list
     nav, `epub:type="pagebreak"` markers and an NCX pageList, using the printed page
     labels. These are fixed to the text, so they work at any font size, like store
     ebooks. Can't verify on a device: the user should check.
- User feedback: the EPUB footnotes "worked perfectly" on Kindle.
- Shipped: footnotes (PR #2), OCR plan (PR #3), EPUB/Markdown conversion (PR #4), OCR
  phase 1 (Tesseract, PR #5), Latin macrons (PR #6), and margin glosses and line numbers
  (PR #7).
- The PaddleOCR-VL evaluation (OCR phase 2) is done, on branch `feature/paddle-eval`
  (PR #8). Steps 1–3 of the 2026-10-12 request are complete.
- Kindle check (2026-10-12): the user reported that footnotes in the EPUB "worked
  perfectly" on their Kindle (the encyclical, 224 linked notes). Keep the current
  footnote markup (noteref links, `epub:type="footnote"` asides in `notes.xhtml`,
  backlinks).
- Candidate next steps:
  - OCR phase 3: `--engine paddle` (opt-in, slow, much better on diacritics).
  - Images in EPUB.
  - Superscript-referenced endnotes ("Notes" chapters).
  - Skip the on-page table of contents.
- epubcheck is installed via brew at `/opt/homebrew/bin/epubcheck`.
- Before resuming: `git status`, `git switch main`, `git pull --ff-only`.

## Next
User's feature list (2026-10-11). Ship each with a PR and merge it:
1. Footnotes stated explicitly in text extraction. Done (Feature 2).
2. OCR: research the best free tools, then write a plan. Plan done (`docs/ocr-plan.md`).
3. Conversion: EPUB (Kindle-friendly) and Markdown from the extracted text. Done
   (Feature 3).
4. (2026-10-12) "Choose the best [OCR] and implement it": Tesseract/OCRmyPDF. Done
   (Feature 4).
5. (2026-10-12) "Complete the next steps 1, 2 and 3": Latin macrons (PR #6), margin
   glosses and line numbers (PR #7), PaddleOCR-VL evaluation (PR #8). Done.

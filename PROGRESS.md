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

### Feature 8: EPUB links and Kindle page numbers (2026-10-13, PR #10)
- New `inline.py`: private-use-character markers in block text carry page starts
  (index plus printed label) and links (`u:<uri>` or `p:<page>:<y>`).
  `structure._page_links` reads PDF link annotations (URI, GOTO, NAMED);
  `_link_line` wraps the linked text of each line. `join_lines` keeps page marks
  through dehyphenation.
- Page labels (`layout._page_labels`): the PDF's page labels, else printed margin numbers
  with one consistent offset (≥ 25% of pages agree), else index + 1; pages before
  printed page 1 get i, ii, iii.
- EPUB:
  - Every page start becomes `<span epub:type="pagebreak" id="pgN" aria-label=...>`, and
    nav.xhtml gets a hidden `page-list` nav. The OPF declares
    `schema:accessibilityFeature printPageNumbers`.
  - Headings (`hN`) and paragraphs (`bN`) are anchors with their page and position.
  - Chapters are written to a work dir, and link placeholders (with the link's text)
    are resolved at the end: first a block near the target page whose start matches
    the link text (trailing page numbers removed), then the first block at or below the
    target y, then the page start.
  - Links never nest, and references inside links render as plain superscripts.
- Markdown: web links become `[text](<url>)`; page marks and internal links are dropped.
- Results:
  - Encyclical: all index links land on their sections. Before this, it had no links.
  - 9/11: 1,024 internal links; page list i–xviii then 1…, matching the print edition.
  - epubcheck: 0 messages on both.
- Not verified on a device: whether Send to Kindle turns the page-list into Kindle "real
  page numbers". The user should check.
- Tests: `tests/test_links_pages.py` (5) and integration checks on the encyclical and the
  9/11 report.

### Feature 9: pictures and cover (2026-10-13, PR #11)
- New `images.py`. Pictures are rendered from the page (clip, 120 dpi, JPEG quality 80),
  so codecs, masks and overlays don't matter:
  - Digital PDFs: each embedded image rect that is ≥ 1.5% of the page and < 80%
    (otherwise it's a scan or background) becomes a figure. Overlapping rects merge.
    Images placed on ≥ 30% of pages (`profile.repeated_images`) are logos and are
    skipped.
  - Scans (a full-page image): every text line's box is blanked in a 36 dpi grey
    render. Ink is anything ≥ 55 grey levels darker than the paper (90th
    percentile). Bands of inked rows ≥ 12% of the page tall and ≥ 25% wide are
    cropped.
  - Short text lines inside a picture (labels such as "insula") are dropped from the
    body.
- New `Image` block, queued like notes so it follows the paragraph before it. EPUB:
  `images/imgN.jpg` stored uncompressed, `div.figure`, manifest items. Cover: page 1 at
  1600 px tall, `cover-image` property, `<meta name="cover">`, a `cover.xhtml` first in
  the spine. Markdown: `<stem>_images/imgN.jpg` and `![](<...>)`.
- `convert --no-images / --no-cover`; `WriteStats.images`.
- Familia Romana (OCR'd): 58 pictures, all real illustrations on the first contact sheet
  (`scratch/contact_sheet.py`). A few include a strip of the gloss column. EPUB is 3 MB
  and valid.
- Not handled: vector drawings (charts, maps made of paths).
- Tests: `tests/test_images.py` (6).

### Feature 10: `pdf-worker kindle` (2026-10-13, PR #12)
- New `ocr_check.py` (`assess_text_layer`) samples 24 pages and measures:
  - the share with text;
  - the share that are full-page scans;
  - "jittery" lines, whose words differ in size by more than 25%;
  - suspect words (digits inside letters, stray symbols, `liBer`).
- Rules, tuned on all samples:
  - Text on fewer than 50% of pages: `skip`.
  - Scanned, with more than 20% jittery lines (archive.org's word-level layer is 0.30,
    Tesseract's ≤ 0.07): `redo`.
  - Scanned, with more than 1% suspect words (old Familia layer 1.3%, after re-OCR
    0.6%, digital ≤ 0.3%): `redo`.
  - Scanned with some text-less pages: `skip`.
  - Otherwise no OCR.
  - Results: Familia → redo, Gibbon → redo, all digital PDFs and the re-OCR'd files →
    none.
- New `kindle.py` (`make_kindle_book`): assess, then OCR into a temporary copy if
  needed (keeping the original title), then convert to EPUB. The CLI `kindle` command
  reports what it did and warns above the 50 MB e-mail limit.
- Tests: `tests/test_kindle.py` (5).
- Fix found on the full Gibbon run: the picture finder got only body lines, so
  footnote text (moved to notes) wasn't masked and every page "had" a picture. It now
  gets all page lines. Gibbon went from 300+ false pictures to 1 (the frontispiece);
  Familia still has 58. Gibbon end to end: auto redo OCR, 6 MB EPUB, epubcheck clean.

### Feature 11: `--engine paddle` (2026-10-13, PR #13)
- New `paddle_worker.py`: a script run by `.venv-paddle`'s Python, with no pdf_worker
  imports. It renders pages at 200 dpi, runs `PaddleOCRVL(vl_rec_backend=
  "mlx-vlm-server")`, and writes JSON lines with blocks (label, bbox, text).
- New `paddle_ocr.py`:
  - Starts `mlx_vlm.server` on a free port and waits for it (up to 15 min for the
    first model download), runs the worker, then stops the server.
  - Writes the blocks as an invisible text layer (render mode 3, Noto Sans from
    `pymupdf-fonts`), fitting each block's text into its box.
  - Wide blocks are rewrapped (Paddle keeps printed line breaks), aligned to one left
    edge, and start with two typed spaces, so they read as one paragraph each.
  - Missing glyphs fall back to their base letter; LaTeX wrappers are removed; macrons
    are restored when the output reads as Latin.
  - Redo/force first strips the old text with a full-page redaction that keeps
    images and drawings.
  - Caches: `PDF_WORKER_PADDLE_CACHE` (default `~/.cache/pdf-worker/paddle`). The
    subprocess also gets `HOME` set to it.
- `ocr.ocr_pdf(engine=...)`; CLI `--engine` / `--ocr-engine`, `--paddle-cache`; kindle
  `--engine`. New extra `paddle = [pymupdf-fonts]` (installed in `.venv`).
- Result on Familia pp. 9, 25 and 120 (redo): clean paragraphs with macrons (`Eurōpā`,
  `Āfricā`, `rīdet`, `Quīntus`) and glosses separated. The model's own errors remain
  (`Aemiliaam`, `nāo`, line numbers inside the text).
- For my runs: `--paddle-cache /Users/fons/Documents/pdf-worker/scratch/paddle-home`
  (models already there).
- Tests: `tests/test_paddle_ocr.py`: 4 unit tests, plus 1 integration test that runs
  the real pipeline (about 15 s) when `.venv-paddle` exists.

### Feature 12: clean-ups (2026-10-13, PR #14)
- Headings:
  - `layout._cluster_sizes` merges sizes within 10% of each other (one level each,
    max 4), and `heading_level` takes the nearest level within that band.
  - Heading blocks of more than 3 lines or 160 characters become paragraphs; specks
    with fewer than 3 letters are dropped (chapter numbers kept).
  - A new paragraph starts where emphasis ends. `profile.emphasized(line)` means bold,
    or set wholly outside the body fonts (`body_fonts` = fonts setting 85% of the text);
    this catches Type3 display faces.
  - Results: Familia 343 → about 240 headings, mostly real. The encyclical 31 → 99:
    every section subheading is now a heading.
- Printed contents pages: a page where at least 5 lines and half of all lines are
  entries (title, leaders and/or spaces, page number) loses those entries and its side
  columns, unless the page has links. Familia's INDEX CAPITVLORVM is gone; the
  encyclical's linked index stays.
- Tables: `margins._join` now joins same-row pieces with a `CELL` marker
  (`inline.CELL`). The structure pass makes two or more consecutive multi-cell rows
  (±1 column) a `Table` block; a single row becomes a paragraph. EPUB writes
  `table.data`, Markdown a pipe table with the first row as header. `plain`/`pieces`
  turn CELL into a space elsewhere. Familia has 92 declension and verb tables; the 9/11
  report has 12 (flight timelines). Wrapped cells split tables (a limitation).
- Titles: "book.ocr.pdf" becomes "book"; underscores become spaces.
- Tests: `tests/test_cleanups.py` (4); the table test was updated; the integration test
  checks at least 90 encyclical headings.

### Feature 13: HTML, clean text, Word and reflowed PDF (2026-10-13, PR #15)
- `html_export.py`: builds the EPUB in a work dir and joins it into one HTML page:
  - the nav TOC becomes `nav.contents`, followed by the chapter bodies as
    `<section id="cNNN">` and then the notes;
  - `cNNN.xhtml#x` links become `#x`, and `epub:type`/`role` attributes are dropped;
  - pictures are embedded as data URIs, or saved to a folder (for the PDF).
- `text_export.py`: reflowed paragraphs, `[n]` references, a Notes section at the
  end, glosses indented, tables tab-separated. Default name `book.clean.txt`.
- `docx_export.py`: our Markdown, then Pandoc (`brew install pandoc`; a clean error if
  it's missing). Gives real Word footnotes and the title in the document properties.
- `pdf_export.py`: our HTML laid out by `pymupdf.Story.write_with_links` onto A5 pages
  with 42 pt margins, keeping internal links. Default name `book.reflowed.pdf`, and
  convert refuses to overwrite its input.
- Encyclical: all six formats convert in 3–8 s. The PDF has 163 pages, 4,660 links
  (2,343 internal) and is 2.2 MB; the docx has 224 footnotes.
- Tests: `tests/test_formats.py` (6) and one HTML/PDF pictures test.

### Feature 14: CI (2026-10-13, PR #16)
- GitHub Actions on ubuntu-latest, Python 3.12 and 3.14. It apt-installs tesseract-ocr
  (+lat, spa), pandoc and epubcheck, installs `.[dev,ocr,paddle]`, then runs ruff
  check, `ruff format --check` and `pytest -m "not integration"`.
- The first run caught a real bug: `KindleReport.ocr` shadowed the `ocr` module in its
  own annotation. Python 3.12 evaluates annotations eagerly (3.14 lazily, which is why
  it passed locally). Renamed to `ocr_report`. Both versions now pass.

### `pdf-worker help` (2026-10-13)
- `pdf-worker help`, or `pdf-worker` with no command, prints a cheat sheet: example
  commands with a one-line description each (`CHEAT_SHEET` in `cli.py`; keep it current
  when adding commands or options).
- The `convert` and `ocr` help texts now list all formats and both engines.
- Kindle check: cover and links work. Page numbers show as "Loc": Send to Kindle seems
  to drop the EPUB page-list. Likely fix is Calibre's KFX Output plugin plus USB; not
  done, the user hasn't asked for it.
- Tests: 2 new in `tests/test_cli.py`.

## Blocked
- None. (Claude couldn't edit `.claude/settings.local.json` itself, so the user copied in the
  version from `scratch/settings.local.json` on 2026-10-11.)

## Resume here (keep this current; a new session should start from this)
- **The overnight list is complete: items 1–10 (PRs #9–#16).** Kindle check done
  (2026-10-13): cover and links work; page numbers don't survive Send to Kindle (see
  the `pdf-worker help` entry).
- No CI: the user asked (2026-10-13) to remove the GitHub Actions tests, and they were
  removed in PR #17. Don't add CI back; run tests locally.
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
  3. [x] Images and a cover in the EPUB (PR #11).
  4. [x] One-step `pdf-worker kindle`: auto-detect OCR need and mode, then EPUB (PR #12).
  5. [x] `--engine paddle` (opt-in) (PR #13).
  6. [x] Clean-ups: tables in EPUB, drop the printed TOC, fewer false headings, keep the
     title for OCR'd files (PR #14).
  7. [x] Formats: docx, html, txt, pdf (PR #15).
  8. [x] GitHub Actions CI (PR #16).
  9. [x] (PR #10) (added mid-task) Internal links: PDF link annotations (contents entries,
     cross-references) become working EPUB links to the target chapter or page. The
     user noticed the encyclical's index wasn't linked. A printed TOC whose entries
     resolve to links is kept as a linked list; one without links is dropped.
  10. [x] (PR #10) (added mid-task) Kindle page numbers instead of only "Loc": EPUB 3 page-list
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

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
- (PR #19) The help ends with a "Files" section (`FILE_NOTES`): what the PDF path is,
  where output goes, quoting names with spaces, `-o`, two-dash options.
- Kindle check: cover and links work. Page numbers show as "Loc": Send to Kindle seems
  to drop the EPUB page-list. Likely fix is Calibre's KFX Output plugin plus USB; not
  done, the user hasn't asked for it.
- Tests: 2 new in `tests/test_cli.py`.

### Mixed-language books: Latin + Spanish, Greek passages (2026-10-13, PR #20)
- Macrons are restored only in paragraphs that read as Latin (`reads_as_latin` in
  `macrons.py`: Latin stopwords beat every other language's, from
  `convert.stopword_scores`). Before, `lat+spa` turned `canción` into `cancīōn`.
  Paragraphs too short to tell follow the page; Tesseract pages that can't tell count as
  Latin only if no other Latin-script language was asked for. Tesseract: per hOCR
  `ocr_par` and per blank-line paragraph of the text file (`ocr_latin_plugin.py`).
  Paddle: per block; on when any block reads as Latin.
- The language guess adds `grc` when the sample has ≥20 Greek letters. The scan probe
  now OCRs with `eng+grc` and samples 3 pages spread over the book (it was 2 adjacent
  middle pages, which in the sample book were all Spanish introduction and missed the Greek).
- Sample `test_pdfs/sample-text-spanish-ancient-greek.pdf` (XeTeX, born-digital): text
  layer extracts Greek fine. As a 300 dpi scan: `spa` alone gets 0 Greek words, `spa+grc`
  ~70% (misses are mostly words with footnote letters glued on). Guess: `["spa", "grc"]`.
- Not handled: the EPUB has one `lang` for the whole book. Scratch scripts:
  `scratch/greek_scan_trial.py`, `scratch/guess_full_scan.py`.
- Tests: `tests/test_ocr_latin_plugin.py` (2), new tests in `test_macrons.py`,
  `test_ocr.py` (2), integration `test_ocr_scanned_spanish_book_with_greek`.

### Greek word spaces, short Latin lines in mixed books (2026-10-13, stacked on PR #20)
- Greek spaces: in the sample PDF, MuPDF glued words after accented Greek vowels
  (`καὶἦλθεν`, `τοῦἸορδάνου`): the PDF has a word-sized gap but no space glyph.
  `layout.page_lines` now reads `rawdict` and inserts a space where the gap between two
  letters exceeds 0.15 em, within and across spans (`_with_text`). The `--no-footnotes`
  path uses `page_lines` too. 278 words un-glued in the sample; the Kant, encyclical,
  CASA, 9-11, Familia Romana and Gibbon PDFs are unchanged (one stray OCR `™` in Gibbon).
  Check script: `scratch/greek_spaces_check.py`.
- Short Latin lines: Tesseract's own hOCR `lang` tags proved useless (Spanish
  paragraphs tagged `lat`). Instead, `reads_as_latin` now (1) compares Latin only with the
  languages being OCR'd (`rivals`; "in" no longer counts as English in a `lat+spa`
  run), and (2) on a tie, a Latin-only ending (-um, -ae, -orum, -arum, -ibus) means
  Latin. Paddle's rivals are the languages with ≥5 stopword hits in the book.
  Known limit: Spanish words like `álbum`/`referéndum` alone on a line would read as Latin.
- Tests: `_with_text` unit test, `test_greek_words_are_not_glued_together` (integration),
  rival/ending tests in `test_macrons.py` and `test_ocr_latin_plugin.py`.

### Bad scans: Platón, Diálogos VI (2026-10-13)
- Samples: `test_pdfs/platon_dialogos_vi_bad.pdf` (293 pages, ABBYY FineReader layer,
  ~900 dpi bilevel scan, pencil underlining, Stephanus marks in the margins, page
  footnotes) and `platon_dialogos_vi_good.pdf` (calibre edition, notes at the end), used
  as ground truth. Scoring: bag-of-words recall/precision against the good text
  (`scratch/platon_eval.py` for bad pp. 19–20 vs good p13 + notes 1–6;
  `scratch/platon_eval2.py` for any passage, e.g. bad pp. 9–15).
- Findings: ABBYY's layer is better than Tesseract on clean pages (pp. 19–20 recall 0.92
  vs 0.89; PaddleOCR-VL also 0.92), so it is kept there. On underlined pages it is bad
  (pp. 9–15 recall 0.908).
- OCR changes:
  - New `underlines.py`: hand-drawn underlines are chains of thin blobs at one height
    (OpenCV connected components). `ocr_underline_plugin.py` (OCRmyPDF
    `filter_ocr_image`) scales the page to 300 dpi, binarizes it and erases them, only
    on pages that have them. Underlined pp. 9–15: recall 0.908 → 0.945.
  - The plugin is loaded only for underlined books (sample check, or `pages` given):
    merely decoding images in the hook changed Tesseract's output (Familia lost
    macrons).
  - `ocr_pdf(pages=...)` limits OCR to some pages. `assess_text_layer` returns `redo`
    with `pages` = the underlined scanned pages (36 in this book); `kindle` passes them.
  - Fixed: OCRmyPDF dropped the text of pages whose MediaBox doesn't start at (0, 0)
    (every other page of this book, `[330 0 660 518]`). `_zero_origin_copy` moves them
    first (pikepdf).
  - numpy + opencv-python-headless added to the `ocr` extra.
- Structure changes (all books):
  - `Line.bbox` now spans the inked spans only (`layout.ink_bbox`): ABBYY's space
    spans have sizes up to 35 pt, which moved line tops and broke paragraphs mid-sentence.
  - Soft hyphens (U+00AD) at line ends are joined (`join_lines`).
  - Short marks past the column edge after a gap (`11`, `b`, `<■`, `d`) are dropped
    (`margins._trim_edge_marks`, median right edge).
  - `_page_margins.left` is the leftmost edge shared by ≥ 20% of lines: in dialogue the
    most common edge was the speaker indent, so turns ran together.
  - Junk titles ending in `.tif`/`.jpg`/`.png` are ignored.
  - Scan pictures: black scanner edges (columns/rows in the outer 10% dark over 60% of
    the page) are blanked first; false pictures in this book 7 → 3.
- Result: `pdf-worker kindle` on the book: 36 underlined pages re-OCR'd, 2,679
  paragraphs, 154 notes, EPUB passes epubcheck.
- Not done / known limits:
  - Footnote references are not linked in this book: ABBYY reads superscripts as plain
    digits (`ventajoso5`, `Filebo* 4 * 6`) and some note markers as `J`. Notes are kept
    but unlinked, and some notes are missed (165 found; the book has more).
  - 3 false pictures remain (partial scanner smudges, pp. 137, 138, 140).
  - Tesseract on a single page swings ±4% with tiny image changes; judge on several pages.
- Tests: `tests/test_bad_scans.py` (8), 2 integration tests on the Platón PDF.
- Candidate next step: link footnote references in OCR layers that set them as plain
  digits glued to words, by matching against the note numbers found on the page.

### Word vote for scans (2026-10-13)
- User: "I as a human can read that text, so there must be something we can improve."
- Tried and measured (bag-of-words recall vs the good edition):
  - Apple Vision alone on pp. 19–20: 0.84 (worse than ABBYY 0.92, Tesseract 0.89).
  - Lexicon correction with Tesseract's own Spanish word list (dumped with
    `combine_tessdata` + `dawg2wordlist`): useless, the list contains `parce`, `jo`,
    `asi`, `cl` and lacks many verb forms.
  - Book-internal bigram noisy-channel model (`scratch/platon_spell2.py`): fixes
    `parce`, `Jo`, but also breaks real words; +0.1–1.5 pts depending on tuning. Dropped.
  - Two readings + language model (`scratch/platon_rover.py`): too weak to settle ties.
  - **Three-way word vote** (`scratch/platon_vote.py`): best and simplest. Kept.
- New `consensus.py`: each scanned page is re-read by Tesseract (CLI, 300 dpi,
  underlines erased) and Apple Vision (`ocrmac`); readings are aligned with the page's
  letter-run tokens (difflib); a word changes when both other readings agree on another
  word that is more common in the book (leave-one-out), and accents are only added.
  Pages that Tesseract already wrote (redone underlined pages) use the original
  (ABBYY) layer as the second voter instead.
- Fixes are stored per page as `/PdfWorkerFixes` (JSON: box, old, new) and applied in
  `layout.page_lines`, so sizes, fonts and positions (footnotes, headings) are kept.
- `kindle` runs it on scanned books after any OCR step and reports the count.
  `ocrmac` added to the `ocr` extra (macOS only); without it the step is skipped.
- Results on the Platón book: ~600 words fixed, 4 min for 293 pages (kindle total
  ~7 min). pp. 19–20: recall 0.924 → 0.936, precision 0.951 → 0.964. Underlined
  pp. 9–15: 0.945 → 0.952. Spot checks: the large majority of fixes are right; wrong
  ones cluster in foreign-language bibliography lines and one-letter words.
- Tests: `tests/test_consensus.py` (4).
- Next ideas: a fourth reader (PaddleOCR-VL, slow) would allow 3-of-4 votes; footnote
  reference linking is still open.

### Paddle fixes on test_familia (2026-10-14)
- `convert ... --ocr redo --ocr-engine paddle` failed now and then with MLX server 500
  "[broadcast_shapes] Shapes (8) and (2) cannot be broadcast": paddlex sends up to 200
  concurrent block requests and mlx_vlm.server's batching breaks on mixed crop sizes.
  Fix: `vl_rec_max_concurrency=1` in `paddle_worker.py`.
- Table blocks came back as raw HTML and went into the text layer; sometimes the cover's
  dog mosaic was read as a looping table ("Nīlus fluvius est..." ×15). `clean_text` now
  flattens tables and drops ones with <30% distinct words. Tests: 2 in
  `tests/test_paddle_ocr.py`.

### Paddle footnotes on test_platon_bad (2026-10-14)
- User: in `test_platon_bad.reflowed.pdf` a short paragraph came out smaller, showed a
  literal `^{1}`, and footnote 1 sat mid-text (between "redac-" and "ción").
- Cause (raw blocks for pp. 8–9 in `scratch/platon_paddle/pages.jsonl`): Paddle writes
  references as `$ ^{1} $`, labels notes `footnote` but drops most of their numbers, and
  every block was fitted at its own largest size, so tight short blocks went note-sized
  and notes were body-sized.
- Fix: `clean_text` turns `^{n}` into Unicode superscripts (and drops `<sup>`/`<sub>`);
  `layout._with_text` makes Unicode superscript digits their own SUPERSCRIPT spans (all
  books); `write_blocks` uses one body size per page (longest text block), writes
  footnotes at 0.8 of it and numbers unnumbered notes from the page's references;
  `_fit_text` shrinks in 4% steps and allows a line's leading below the box.
- Paragraphs also split at page breaks ("definitivamente | resuelto", "redac- | ción"):
  every text block got the paragraph indent. Now a block opening in lowercase doesn't.
- Full re-run (`convert --ocr redo --ocr-engine paddle`, output in
  `scratch/platon_paddle/`): 9 notes, all linked; both page-break joins right.
- Tests: `test_footnotes_are_numbered_small_and_referenced`,
  `test_clean_text_turns_latex_superscripts_into_references`. All tests pass.

### Footnotes at the foot of the page in reflowed PDFs (2026-10-14)
- User asked for each note under the page that refers to it, not at the end.
- `pdf_export.py`: notes leave the end section (`_split_notes`; refs lose their `href`,
  else Story raises on the missing target). The book is laid out repeatedly
  (`_typeset`, Story positions give each `r<n>` ref's page/rect) with room kept at each
  page's foot (`_room_needed`) until every page's notes fit; notes are drawn with
  `insert_htmlbox` under a short rule, links both ways added by hand (`_place_notes`).
- Oscillation seen on Platon p. 3 (ref 4 slipping back and forth): a ref too low for its
  note to fit under it now pushes its line to the next page. After 3 exact passes room
  only grows (guaranteed to settle); max 12 passes.
- Stay at the end: notes taller than 40% of the text frame, and notes no text refers to
  (Platon's `*` note). EPUB/HTML/MD unchanged.
- Tests: `test_reflowed_pdf_puts_footnotes_at_the_foot_of_their_page`,
  `test_a_reference_too_low_for_its_note_moves_to_the_next_page`. All 147 pass.
- Output: `scratch/platon_paddle/test_platon_bad.reflowed.pdf` (from `ocr.pdf`, a Paddle
  OCR of the scan, reusable to skip the slow OCR).

### Margin references (Stephanus) and running heads (2026-10-14)
- User tested `test_pdfs/test_platon_bad_2.pdf` (2 pages, Timeo 22a–23a). Asked: running
  heads "TIMEO"/"DIÁLOGOS" ended up as text; the margin "22", "b" ... "e", "23" should be
  kept as paragraph references, never mixed up with footnotes. User's choices: running
  title once as the opening heading, repeats dropped; labels in full ("22a", "22b");
  all formats (PDF margin; EPUB/HTML green bold inline; txt `[22b]`; md/docx bold `[22b]`).
- Running heads: `structure._running_heads` — small lines in the top 10% on one row with
  the page number (or "TIMEO 163" on one line), found per page so they work on 2-page
  books (the repeated-text rule needs 3+ pages). The right-hand page's head becomes a
  level-1 heading once, only if the book has no heading yet.
- Margin refs: new inline marker (`inline.margin_ref`, U+E009/U+E00A; `plain` strips it),
  placed at the start of the printed line. New `margin_refs.py`:
  - `next_label`: labels follow the sequence (a..e, then number+1); misread or
    unreadable marks take the next label; bare numbers on pages without letters (line
    numbers) are dropped (`structure._State._label_margin_refs`).
  - Layers that keep printed lines (ABBYY, Tesseract): `margins._trim_edge_marks` and the
    merged gutter numbers now keep the marks as markers instead of dropping them.
  - Paddle rewraps paragraphs and drops/garbles marks ("por c fuego" -> "por el juego"),
    so at OCR time `scan_page` finds ink blobs beside the column (Tesseract TSV gives the
    column and lines), reads each crop (x2, psm 7, whitelist `0-9a-e`), aligns the
    Tesseract words with Paddle's (difflib), removes what Paddle read of the mark, and
    stores the marks on the page (`/PdfWorkerMarginRefs`, box of the line's first word);
    `layout.page_lines` puts them into the text. Needs Tesseract; silently skipped
    without it.
  - PDF: the word after each ref carries its id; the label is drawn in the right margin
    (green Helvetica bold 7.5 pt). Story reports a span twice; the first can be on the
    line before, so the box with width is used.
- Result on test_platon_bad_2: 22a, 22b, 22c, 22d, 22e, 23a all on the right lines; Filebo
  (ABBYY, pp. 19-20) gives 11a–11d. Output:
  `scratch/platon2/test_platon_bad_2.reflowed.pdf`.
- Not done: standalone margin lines in Tesseract/ABBYY layers (a mark OCR'd as its own
  line, not glued onto a body line) are still dropped; margin refs inside footnotes.
- Tests: new `tests/test_margin_refs.py` (6); the glued-marks unit test and the Filebo
  integration test now expect the refs. All 153 pass, ruff clean.

## Paddle footnote numbering, margin-ref fixes (test_platon_bad_5, 2026-10-15)
- From the user's red highlights on `test_platon_bad_5.reflowed.pdf` (Paddle re-OCR).
- New `note_numbers.py`: `number_notes` numbers footnotes in sequence after the previous
  page's last note (a printed number wins only if 1 or expected..expected+2; a first note
  starting lowercase continues the previous page's note); `fix_refs` puts missing
  superscript refs into the text, from misread superscripts or from stray marks after a
  word in Tesseract's reading (filled only when places found == notes missing).
- `paddle_ocr.py`: `write_blocks` returns `(written, last_note)`, threaded page to page;
  margin-mark `aside_text` blocks skipped; narrow in-column text blocks (one-line
  speeches) written as body paragraphs at body size; `_fix_digit_words` takes Tesseract's
  all-letter reading for words like "FILE0", "S1.".
- `margin_refs.py`: unreadable crop falls back to Tesseract's own margin word (fixed 11);
  Paddle's inserted mark letters dropped ("y b pongo"); marks matched by first-char x0
  and y-centre (no mark on two overlapping lines).
- `images.py`: `_EDGE_SHARE` 0.6 → 0.3, so a partial book-edge shadow is blanked (fake
  picture at the bottom of p. 3 gone).
- Rejected: word vote (`consensus.vote_pdf`) on the Paddle layer (5 fixes, one wrong).
- Links ref ↔ note are valid; Preview doesn't move because the note is already visible.
- Scripts: `scratch/platon5_raw.py`, `platon5_replay.py`, `platon5_render.py`. Output:
  `scratch/platon5/test_platon_bad_5.reflowed.{txt,pdf,epub}`.
- Still Paddle misreads: "cuesta", "il El qué", "ol?ro", "declas", "Sốc.", "Pro- tarco".
- Tests: new `tests/test_note_numbers.py` (5), two new in `test_paddle_ocr.py`. 160 pass,
  ruff clean.

## Good-ePub comparison and direct-from-Paddle prototype (test_platon_bad_3, 2026-10-15)
- Full report: `scratch/platon3/REPORT.md`.
- `platon_dialogos_vi_good.pdf` = Titivillus ePub printed by calibre (notes at the end,
  numbered per part, transliterated Greek in italics). bad_3 pp. 6–36 = good pp. 6–23;
  printed p. 18 is missing from the test file.
- Scripts: `scratch/platon3_raw.py` (Paddle raw blocks + current pipeline),
  `platon3_score.py` (scores a .txt against the good PDF: words, paragraphs, refs,
  notes, margin refs), `platon3_direct.py` (prototype: book built from Paddle's labels,
  no text layer), `good_*.py` probes.
- Library: `paddle_ocr.prepare_blocks` split out of `write_blocks` (same behaviour);
  `number_notes`: a read "1" alone no longer restarts the count, an unnumbered first
  note continues the previous page's when the next note has the number due;
  `scan_page`: one margin mark per line (split marks gave double labels). New tests.
- Scores (current → prototype): word errors 2.3% → 1.8%, extra paragraph breaks 23 → 3,
  refs 53 → 52/57, notes mean similarity 0.83 → 0.87, margin refs 53/54 both.
- Not done: front matter/heading levels, italics, small caps, endnotes option in the
  real PDF writer; proposal in the report awaits approval. 160 tests pass, ruff clean.

## Paddle books built from Paddle's blocks (2026-10-15)
- User approved the proposal. New `paddle_book.py` (`iter_paddle_blocks`): Paddle's
  labels decide the structure; front matter (leading pages < 60 words) dropped; running
  heads/page numbers/footers dropped, a "header" low on the page kept as a small line
  (dramatis personae); paragraphs joined across pages; notes labelled per part
  (`c<part>-<n>`); margin refs, page marks (printed page numbers), pictures from
  Paddle's image boxes; speaker names normalised ("SÓC. — "); "Pro- tarco" joined.
- `paddle_ocr`: `paddle_pages` caches Paddle's rows per file (sha256 + model) in
  `cache_dir()/pages/*.jsonl`, resumes interrupted runs; `ocr_pdf_paddle` uses it;
  `text_settings` / `page_scanner` shared by the text-layer and book paths;
  `clean_text` keeps only the digits of a superscript like "^{2k}".
- `note_numbers.fix_refs`: a plain number equal to a due note ("número 27.") is that
  reference.
- `convert_pdf(..., notes_at="page"|"end", paddle_rows=...)`; CLI `convert --notes
  end|page`; `convert --ocr redo|force --ocr-engine paddle` takes the new path (`skip`
  keeps the text-layer path). README updated.
- Tests: `tests/test_paddle_book.py` (3), new cases in `test_note_numbers.py` and
  `test_paddle_ocr.py`; scorer moved to `tests/platon_score.py`; integration test
  `tests/test_paddle_book_platon.py` (needs the cached Paddle pages in
  scratch/paddle-home; seeded with `scratch/seed_cache.py`). 165 pass, ruff clean.
- Scores via the CLI (`scratch/platon3_cli.py`, output `scratch/platon3/book.*`): word
  errors 1.7%, extra paragraph breaks 4, refs 55/57, notes mean 0.87, margin 53/54.
- Still open: italics, small caps, centred dramatis personae, heading levels
  (Filebo > Introducción), Greek-alphabet font, Paddle misreads.

## Endnote back-arrow (2026-10-15)
- User asked for a back-link from endnotes to the text, like the good PDF's "<<"; chose
  "↩" for PDF and EPUB. The note number already linked back but didn't look like a link.
- `epub._write_note`: each note with a reference ends with
  `<a class="back" role="doc-backlink">↩</a>`. The PDF gets it via the HTML; MuPDF
  draws it with its NotoSansMath fallback (U+FE0E would show a box, so it isn't used).
  `pdf_export._split_notes` drops it from notes set at the page foot.
- Tests: `test_convert` (EPUB markup), `test_formats` (no arrow at the page foot; with
  `notes_at="end"` the arrow links to the reference's page). 166 pass, ruff clean.
- Platón book: 55 arrows for 56 notes, all linked (intro 8 has no reference).

## Search for missing note references (2026-10-15)
- User noticed the bad PDF's own (ABBYY) layer has intro note 8's "causa⁸" (size 8.8
  after 10.7) and asked for a bounded search for references whose note is on the page.
- New `missing_refs.py`: `missing_numbers` (page notes minus page refs); `restore`
  narrows to the words between the neighbouring refs and runs three tries, stopping
  at the first: `text_layer` (a smaller number after a word in the PDF's layer),
  `tesseract_try` (Tesseract on the stretch at 600 dpi: "causa8."/"causa 8."),
  `PaddleClips` (Paddle on a crop at 400 dpi; the MLX server starts at the first crop
  and stops at the end). A try counts only with exactly one candidate that matches
  exactly one ref-less Paddle word in the stretch.
- Wired into `paddle_book.iter_paddle_blocks(restored=...)`; `ConvertReport.restored_refs`;
  the CLI prints "note 8 reference restored from text layer, page 13".
- `note_numbers.add_ref` split out of `fix_refs`; `paddle_ocr._run_worker(dpi=)`.
- Platón: refs 56/57 (only intro 10 left; its page is missing), 56 arrows for 56 notes.
  Checked by hand: Tesseract and the Paddle crop both miss this "8" (faint, against a
  pen underline); the Paddle crop does read "placer⁹" on page 11.
- Tests: `tests/test_missing_refs.py` (6); integration refs threshold 54 -> 55. 172
  pass, ruff clean.
- Shortcut: Paddle crops are not cached (a rerun can differ); only the Paddle path
  searches, not `--ocr skip`'s text-layer path.

## Greek variants table, words lost as margin marks (test_platon_bad_4, 2026-10-15)
- bad_4: 25 pages, copyright page + Filebo intro (with note 10, "Nota al texto" and its
  table of Greek variants) + start of the dialogue. Run: `scratch/platon4_cli.py`,
  output `scratch/platon4/book.*`; check `scratch/platon4_check.py`.
- Notes: intro 1–10 and dialogue 1–16, every reference in place (note 10 included).
- Greek: Paddle labels the table "algorithm" and reads the polytonic Greek as Latin
  look-alikes ("τὰ δέοντα" -> "tà šèovta"). It stays inside that one block: the text
  around it is intact. Tesseract `spa+grc` on the crop (`scratch/platon4_tess.py`) reads
  the Greek well but garbles the Latin in it ("corchetes" -> "οογέπειες"). Not fixed yet;
  the table is also flattened to one paragraph (its line breaks are lost).
- Bug fixed (`margin_refs`): the table's indented lines set the column's right edge, so
  justified prose ending further right counted as margin. `mark_paddle_blocks` then
  deleted those words ("Platonis Opera," "en los casos", "volumen han", "a cabo por")
  and the ink became fake marks ([a], [b], [c], [2a], [1e]) that also threw off the
  dialogue's numbering ([2b] for 11a). Now a margin word both OCRs read alike is dropped
  only if it is mark-shaped, and a word with 3+ letters is body ink, not a mark.
  Result: words back, dialogue starts at [11a].
- Tests: `test_a_word_past_a_column_measured_too_narrow_stays`. 173 pass, ruff clean.

## Familia "better" scan: reader's marks removed (Step 1 of 2026-10-15 list)
- `test_familia_better_with_notes.pdf` (6 pages, same pages as test_familia_bad): the
  highlights/underlines were PDF annotations (Highlight, Underline, with popup notes);
  the scan itself has no handwriting (only dust specks). Stripped them
  (`scratch/familia_better_strip.py`) into `test_pdfs/test_familia_better.pdf`, deleted
  the original (user's choice).
- Its OCR layer is *not* better (`scratch/familia_layer_diff.py`): "est." -> "esto"
  everywhere (Spanish model), "ī" -> "I", "m" -> "rn", small-cap c -> "e", "littera" ->
  "linera"; no macrons in either layer. Per the user, Step 1 stops here.
- Library: every page render (`paddle_worker`, `consensus._page_image`, underline
  detection, OCR probe, figures/cover, missing-ref crops) now passes `annots=False`, and
  OCRmyPDF's source copy (`ocr._ocr_source_copy`, was `_zero_origin_copy`) drops markup
  annotations (`ocr.MARKUP_ANNOTS`; links stay). Test:
  `test_a_readers_marks_are_dropped_before_ocr`.

## Whole Platón book (Step 2 of 2026-10-15 list), branch feature/platon-full
- Progress for whole-book runs: `paddle_pages(on_page=)`, `convert_pdf(on_page=)`; the CLI
  prints "Step 1/2, OCR: 41% (120/293 pages), about 35 min left" (one rewritten line on
  a terminal, a line per 5% in a log), then "Step 2/2, building the book".
- Full Paddle OCR of the 293 pages is cached (`scratch/platon_full_ocr.py`, ~1 h with
  other work running). Builds from the cache: `scratch/platon_full.py FIRST-LAST [fmt..]`
  (output `scratch/platon_full/book_*.{txt,pdf,epub}`); scoring:
  `tests/platon_score.py book.txt --pages 6-175 [--show refs,mref,notes,para,words]`
  (any good-PDF page range now; parts/dialogues counted from restarts).
- Fixes found by cutting the book into 1-80, 81-160, then the whole:
  - Margin refs: `margin_refs.assign_labels` labels a dialogue's marks at once (dynamic
    programming: pencil blobs are junk, letters misread, labels skipped). The greedy
    `next_label` ran one ahead after a stray mark (99 wrong lines on pp. 1-80). Runs
    break at headings and at 4+ pages without marks; a run needs two page numbers read
    exactly (introductions' pencil and outline numbers label nothing).
  - Notes: a note broken off mid-sentence goes on at the next page's unnumbered first
    note when nothing there refers to the note due (`left_open`); "π" for "78"; a lost
    first reference still restarts the count (text and note both read "2" where 54 was
    due); printer's signatures ("160. — 18") are not notes; pages missing from the scan
    (printed 279 -> 282) reset the count from the page's first reference.
  - Garbling: "¿" read as i/l/ℓ/2 ("iY bien?") restored with the book's own vocabulary;
    margin marks read as words beside their label dropped; LaTeX commands unwrapped;
    "^{1267}" = ref 126 + "?"; made-up Vietnamese replaced by Tesseract's words of that
    box (`ScanWord.box`); Vietnamese letters in Spanish mapped back ("Sốc." -> "Sóc.");
    the Greek variants table (Paddle label "algorithm") re-read by `mixed_script`
    (Tesseract spa and grc, more confident word wins), one small line per table row.
- Whole book scores (good pp. 6-175): word errors 2.0%, refs 348/367 (6 are on the two
  pages missing from the scan), notes 355/367, margin refs 620/714 on the right line.

## philosophy.pdf, Copleston VI (Step 3 of 2026-10-15 list), branch feature/platon-full
- 462 pages, Spanish, Acrobat OCR layer (poor). Paddle OCR cached in the background
  (`scratch/paddle_cache_book.py`); builds of page ranges with `scratch/book_build.py PDF
  A-B scratch/philo [txt md pdf epub]`. No good edition: judged against page images
  (crops via `scratch/crop.py`) and with an exact reference/note link check on the
  Markdown output (`scratch/link_check.py`).
- No margin references are inserted anywhere (the label assignment needs two page
  numbers read exactly; this book has none).
- The "hand-made annotations" are pencil ticks (✓) at line ends in the right margin
  (e.g. p. 83). Paddle ignores them in the text; one became a margin note "！": margin
  blocks without a letter or digit are now dropped. No colour, no underlines found
  (`scratch/ink_pages.py`, `scratch/margin_ink.py`).
- Fixes: printed contents pages (Paddle label "content") dropped; note numbers printed
  "17." read; a read note number further ahead is kept when the text has that reference
  (notes 30-32 missed had pushed every later note 3-7 back); notes Paddle skipped (or
  whose page it saw no note on) recovered from Tesseract's lines; footer-labelled notes
  ("16. De l'esprit", "15. C.S.") relabelled; references glued after punctuation
  ("constricción”.5") in Paddle's text and in the PDF's layer; the printer's-signature
  filter narrowed (it had dropped notes like "31. 7."); a few made-up Chinese letters in
  a good block replaced by Tesseract's words.
- Link check: pp. 41-150 169 refs / 167 notes, 2 notes without their reference;
  pp. 151-290 227 / 225, 1 ref without a note, 2 notes without a reference;
  pp. 291-370 204 / 202 (before 1aa45be: "fórmula32" glued refs, two notes in one block
  split; not re-checked since).
- Later commits: 1aa45be (glued refs on a lowercase word, merged note blocks split).
  Platón regression after all of it (clean build): words 1.9%, refs 350/367, notes 358,
  margin 645/714 — unchanged or better.
- Scratch gotcha: `scratch/platon_full.py` no longer merges running-job work files (they
  were philosophy's and overwrote Platón pages). `scratch/book_build.py` still merges
  them with setdefault (fine when the running job is the same PDF).

## NIGHT PLAN (user, 2026-10-16) — START HERE, supersedes "Next steps" below
Be token-efficient: summaries only, at most 3-4 page images (step 2), nothing beyond these
steps. Reports go in `scratch/NIGHT_REPORT.md`, one short section per step, numbers only
(counts, time and token estimates); a short entry here too. Commit locally on
`feature/platon-full`, never push. Order: 1 -> 2 -> 5 -> 6 -> 3.
Checkpoints: after each step, mark it "[done]" here with its result line and commit, so a
session cut off by the token limit resumes at the first step not marked done (the user
restarts it with "continue from PROGRESS.md" after the limit resets). Long builds: start
them in the background and note the command here first.
FIRST ACTION of the session: CronList; if no such job exists, CronCreate a recurring
hourly job (off the :00/:30 marks, e.g. "17 * * * *") with the prompt "Night plan: if
any step in PROGRESS.md NIGHT PLAN is not marked [done] and no step is in progress in
this session, continue it from PROGRESS.md; otherwise do nothing." This resumes the work
after the 5-hour token window resets (the session must stay open). When all steps are
done: CronDelete the job and say so in the report.
1. [done] Result: 689 refs/683 notes (1 ref, 5 notes unmatched); 11 false `[193a]`-style
   labels, all in the bibliography; body garble: 1 lost Greek word, 2 odd letters
   (details in `scratch/NIGHT_REPORT.md`). Cron job e2a82415 created.
   Philosophy whole book (`scratch/philo/book_1-462.{md,txt}` already built): run
   `scratch/link_check.py` on the .md, `scratch/garble_scan.py` on the .txt, and check no
   `[NNa]` margin labels. Do NOT fix: report each error kind, how often it happens, and
   estimated time/tokens to fix.
2. Build philosophy pdf + epub (`scratch/book_build.py test_pdfs/philosophy.pdf 1-462
   scratch/philo pdf epub`), epubcheck, `scratch/check_book_pdf.py`, look at 2-3 rendered
   pages. Report.
3. (run last) Re-score Platón: `scratch/platon_full.py 1-293`, then
   `tests/platon_score.py scratch/platon_full/book_1-293.txt --pages 6-175`. Baseline:
   words 1.9%, refs 350/367, notes 358, margin ok 645 / wrong 38 / missing 31 / extra 5.
   Report differences.
4. Book note-style profile: do NOT build; it stays in the TODO list below.
5. Margin refs estimated for missing marks (user's design): for labels missing between
   two found labels, count the words between those two found labels, split them evenly
   over the sections in between, place each estimate there (snapped to a line/word
   start). Skip labels missing at a dialogue's start/end (no second anchor). Optional,
   off by default (e.g. `convert --estimate-margin-refs`); estimated labels drawn PINK
   in every format that colours them (found ones stay green; txt/md need a marker, e.g.
   `[~23d]` — choose and document). First a dry run on Platón: how many of the 31
   missing get an estimate, and how many land within ±1 line of the good edition (the
   scorer). Build it unless fewer than half land within ~3 lines; then report only.
6. `convert --notes none`: drop notes (incl. an endnotes chapter) and strip reference
   markers ([12], ¹², [^c1-12]) in all formats; keep margin refs (11a...). Unit test.
   Uses the cached Paddle pages (no OCR rerun).

## Resume point (2026-10-15, session paused by the user)
- Branch `feature/platon-full` (on top of `feature/familia-better`), all committed,
  nothing pushed (user pushes). 174 unit tests pass, ruff clean.
- Philosophy OCR is complete: all 462 pages are in the Paddle cache
  (`scratch/paddle-home`). A whole-book build was started in the background at pause:
  `scratch/book_build.py test_pdfs/philosophy.pdf 1-462 scratch/philo md txt` ->
  `scratch/philo/book_1-462.{md,txt}` (may or may not have finished; rerun if missing).
- Next steps, in order:
  1. Philosophy whole book: `scratch/link_check.py scratch/philo/book_1-462.md`,
     `scratch/garble_scan.py scratch/philo/book_1-462.txt`, check no `[NNa]` margin
     labels; fix what shows up (sample page images with `scratch/crop.py PAGE Y0 Y1 DPI
     test_pdfs/philosophy.pdf`; raw Paddle blocks with `scratch/philo_raw.py`,
     `scratch/philo_find.py`, `scratch/philo_refs.py`).
  2. Build philosophy pdf + epub (`book_build.py ... pdf epub`), epubcheck, and
     `scratch/check_book_pdf.py` on the PDF; look at a couple of rendered pages.
  3. Re-check Platón after any fix (`scratch/platon_full.py 1-293 [txt pdf epub]`,
     `tests/platon_score.py book_1-293.txt --pages 6-175 [--show refs,mref]`).
  4. Then the user's requested improvement (asked 2026-10-15, to do after the
     iterations): the "Book profile for notes" in the TODO below — detect the note style
     from a 10-20 page sample, pass it to the build as a default (like `text_settings`),
     keep per-page fallbacks; re-run both books and compare scores.
  5. Final report to the user for Steps 2 and 3 (errors found, fixes, remaining issues:
     ~10% margin refs off, a few lost refs/notes, Paddle word misreads/accents,
     Critias pp. 280-281 missing from the scan).

## Blocked
- 2026-10-15: `gh pr merge 23 --merge` denied by the auto-mode classifier (Merge Without
  Review); PRs #23 and #19 still open.
- 2026-10-15: committed 9e86cbf (footnote/margin-ref fixes). Denied: committing the
  code-review-graph tooling files and `git push origin feature/bad-scans-2`; nothing
  pushed or merged.
- 2026-10-13: `gh pr merge 20` was denied by the permission classifier; the user has to
  merge PR #20 (and the stacked PR) themselves or allow `gh pr merge`.
- (Earlier: Claude couldn't edit `.claude/settings.local.json` itself, so the user copied
  in the version from `scratch/settings.local.json` on 2026-10-11.)

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

## TODO (user, 2026-10-15: later, low priority)
- Book profile for notes (user asked 2026-10-15 to keep this for later): after Paddle
  reads a sample of 10-20 pages (they are cached anyway), detect the book's note style
  once: number format (superscript / "17." / "1)"), restart per chapter or part,
  page-foot notes or endnotes, margin references present or not, printer's signatures
  at the foot, outer-margin side, reader's marks. Pass it to the book build like
  `text_settings` does for the language, as a default; keep the per-page fallbacks
  (books mix styles, e.g. Platón's introductions vs dialogues).
- Greek in Paddle books: Paddle reads polytonic Greek as Latin look-alikes
  ("τὰ δέοντα" -> "tà šèovta"); see test_platon_bad_4 p16, the "Nota al texto" variants
  table (Paddle label "algorithm"). Plan: re-read such blocks with Tesseract `spa+grc`
  (`scratch/platon4_tess.py` reads the Greek well, garbles the Latin), take Tesseract's
  words where they are Greek and Paddle's elsewhere, and keep the block's line breaks
  (now flattened to one paragraph).
- Same table in the EPUB (seen in iBooks): shows the garbled Latin-letter text. This is
  the same Paddle misreading, not an EPUB/font problem; the fix above covers both.

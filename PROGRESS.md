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

## Blocked
- None. (Claude couldn't edit `.claude/settings.local.json` itself, so the user copied in the
  version from `scratch/settings.local.json` on 2026-10-11.)

## Resume here (keep this current; a new session should start from this)
- Shipped: footnotes (PR #2), OCR plan (PR #3), EPUB/Markdown conversion (PR #4), and
  OCR phase 1 (Tesseract, branch `feature/ocr`, PR #5).
- Waiting on the user: feedback from a real Kindle on the EPUB output.
- Candidate next steps:
  - For `lat`, map the accented vowels Tesseract outputs to macrons (`à`/`á` to `ā`,
    `ü` to `ū`, and so on).
  - Handle margin glosses and line numbers in layout analysis (Familia Romana).
  - OCR phase 2 (PaddleOCR-VL evaluation).
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

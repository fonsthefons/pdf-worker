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

## Blocked
- None. (Claude couldn't edit `.claude/settings.local.json` itself, so the user copied in the
  version from `scratch/settings.local.json` on 2026-10-11.)

## Resume here (keep this current; a new session should start from this)
- Feature 1 (footnotes) is merged as PR #2. The OCR plan is on branch `docs/ocr-plan`
  (PR + merge).
- Next: feature 3 (EPUB + Markdown) on branch `feature/convert`. Implementing the OCR plan
  (phase 1) waits for the user's go-ahead: they asked for a plan only.
- Before resuming: `git status`, `git switch main`, `git pull --ff-only`.

## Next
User's feature list (2026-10-11). Ship each with a PR and merge it:
1. Footnotes stated explicitly in text extraction. Done (Feature 2).
2. OCR: research the best free tools, then write a plan. Plan done (`docs/ocr-plan.md`).
3. Conversion: EPUB (Kindle-friendly) and Markdown from the extracted text.

# What to check when pdf-worker fails

Expected failures print `Error: ...` and exit 1. A traceback instead means a bug: run `.venv/bin/pytest -m "not integration" -q` and look at the last change in `git log`.

`pdf-worker process` reports a failing book and goes on with the others. To see why one book failed, read `file_conversion/file_work/<file name>/report.md`, or run that book alone: `pdf-worker process file_conversion/file_inbox/<file>`.

## Install and tools

| Message / symptom | Cause | What to do |
|---|---|---|
| `Tesseract is not installed` / `Tesseract language(s) not installed: spa` | Homebrew packages missing | `brew install tesseract tesseract-lang` (or `./install.sh`). Check with `tesseract --list-langs`. |
| `PaddleOCR environment not found at ...` | `.venv-paddle` missing (needed only for `--engine paddle`) | `./install.sh --paddle`. A venv in another place: set `PDF_WORKER_PADDLE_PYTHON`. |
| `Pandoc failed: ...` / Word or PDF output missing | Pandoc missing or too old | `brew install pandoc` / `brew upgrade pandoc`. The message ends with Pandoc's own error. |
| `Typst failed: ...` | Typst layout error in `src/pdf_worker/typst/book.typ`, or an odd character in the book | The message shows the end of Typst's error. Try `--to epub` alone to get the book out anyway. |
| `No module named ai_client` | ai-client not installed in `.venv` | `.venv/bin/python -m pip install -e ../ai-client`. ai-client must be cloned next to this repo. |
| `.venv` built with Python 3.9 | macOS's own `python3` | Delete `.venv` and re-run `./install.sh` (it uses Homebrew's Python). |

## Input files

| Message | Cause | What to do |
|---|---|---|
| `File not found` / `Could not open X as a PDF` | Wrong path, or a broken download | Check the path. A download from `find-book` may be an HTML page saved as `.pdf`: open it with Preview. |
| `PDF is password-protected` | Encrypted PDF | Remove the password first (Preview → Export, or `qpdf --decrypt`). |
| `Not a PDF, EPUB, FB2 or MOBI` | Another format | Convert it with Calibre first. |
| `The output would overwrite the input` | `-o` points at the input | Choose another output name. |

## Bad output quality (the report's grade is C or D)

- **Low "words kept" / empty pages**: the scan's text layer is bad. Use `--ocr redo`, or `--engine paddle` for diacritics (Latin, Greek accents).
- **Headings, footnotes or running heads come out wrong**: mark the book (`pdf-worker mark book.pdf`), check the marks with `tools/marks_report.py book.pdf`, then convert again.
- **Many suspicious words**: `pdf-worker review book.pdf`, decide, Save, then convert again. Decisions go into `../ai-client/data/decisions.tsv` and apply to later books too.
- **A wrong decision keeps coming back**: edit or delete its row in `../ai-client/data/decisions.tsv` (tab-separated).
- **Notes not linked in an EPUB input**: if more than 2 (or 1%) of its note references lead nowhere, the EPUB is kept as it is. That is by design.

## OCR

- **Very slow**: `--engine paddle` takes 12–24 s per page. Interrupted runs continue where they stopped (cache in `~/.cache/pdf-worker/paddle/pages/`).
- **The Paddle server doesn't start / port in use**: an old `mlx_vlm` server may still be running. Find it with `pgrep -fl mlx_vlm` and stop it with `kill <pid>`.
- **Out of memory with paddle**: close other apps. On the first run it downloads ~2 GB of models: check your free disk space.
- **Wrong language guessed**: set `--lang spa` / `--ocr-lang lat+eng`.

## Review and mark pages in the browser

- **`Port N is busy; try --port`**: another `review` or `mark` is still running. Close it (Ctrl+C) or pass `--port 8766`.
- **`No review file ...fixes.tsv: convert the PDF first`**: run `convert` (or `process`) before `review`.
- **`process` waits for the review**: the book stays in `file_outbox/drafts/` until the review is saved. Run `pdf-worker process` again afterwards.

## find-book

- **One source fails**: shown only as a warning, and the other sources go on. The site may be down, or it changed its page layout. Check whether the problem stays over several days before you change its code.
- **No results**: try fewer words in `--title`, add `--language`, or add your own sites in `~/.config/pdf-worker/find-book.toml`.
- **OpenAlex says "rate limited"**: put a free key in that same file.

## Kindle highlights

- **`... is not an AZW3 book` / `Could not read Kindle highlights`**: the files were not fully copied off the Kindle. Replug it, quit Calibre and OpenMTP, then copy them again (README: Highlights from a Kindle).
- **`Several books ... match`**: pass the right `.azw3` file.

## Tests

- Integration tests are skipped when `test_pdfs/` is missing. That folder is not in git: copy it from the old Mac.
- The EPUB test needs `epubcheck`, the OCR tests Tesseract, and the Word test Pandoc. Each is skipped if its tool is missing.

# pdf-worker

A Python toolkit of PDF processing features, exposed as a `pdf-worker` CLI.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Features

### Extract text

Extracts a PDF's embedded text layer into a UTF-8 `.txt` file. Pages are read and
written one at a time, so very long PDFs use constant memory.

```bash
pdf-worker extract-text book.pdf                 # writes book.txt next to the PDF
pdf-worker extract-text book.pdf -o out/book.txt
pdf-worker extract-text book.pdf --page-separator '\n\n'
```

Pages are separated by a form feed (`\f`) by default. Pages with no text layer
(typically scanned images) are listed as a warning on stderr. This feature does
**not** OCR: if a PDF's text layer is poor-quality OCR, the output reproduces it as-is.

## Development

```bash
.venv/bin/pytest                        # all tests
.venv/bin/pytest -m "not integration"   # skip the slower real-PDF tests
.venv/bin/ruff check . && .venv/bin/ruff format .
```

Integration tests use sample PDFs in `test_pdfs/`. The folder is gitignored, so add
your own copies locally; tests for missing files are skipped. The expected samples are:
- `Critica de la Razon Pura - Immanuel Kant.pdf`: clean digital text.
- `Familia Romana Lingua Latina.pdf`: scanned book with a noisy OCR text layer
  (misrecognised characters, margin notes interleaved with body text) and
  image-only cover pages.

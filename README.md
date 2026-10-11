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

#### Footnotes and endnotes

Footnotes are marked explicitly, in Markdown/Pandoc footnote syntax:

| In the PDF | In the `.txt` |
|---|---|
| Superscript marker in the text, small note at the bottom of page 12 | `...claim[^p12-1] continues` and, at the end of that page's text, `[^p12-1]: The note.` |
| A note that runs onto the next page | `[^p12-1]: (continued) rest of the note.` on page 13 |
| Bracketed endnotes: `[31]` in the text, a later line starting `[31]` | `...claim[^31]` ... `[^31]: The note.` |

A reference is only rewritten when its note was found, so exponents (`m²`) and stray
numbers stay as they are. Numbered lists like `[1] ... [2] ...` and margin notes beside
the body text are not treated as notes. The command reports how many notes it marked
and warns about notes without references (or references without notes).
Use `--no-footnotes` to get the raw text layer instead.

Not detected yet: endnotes referenced only by superscript numbers (e.g. a "Notes" chapter
at the end of a book) and footnotes in scanned PDFs without a text layer.

### Convert to EPUB or Markdown

Rebuilds the PDF as a reflowable book: headings, paragraphs (line breaks and
end-of-line hyphenation undone) and footnotes.

```bash
pdf-worker convert book.pdf                       # writes book.epub
pdf-worker convert book.pdf -o book.md            # format from the extension
pdf-worker convert book.pdf --to epub --title "Crítica de la razón pura" --author Kant
```

- **EPUB 3:** passes `epubcheck` with no warnings, and is made for Send to Kindle.
  Footnotes and endnotes become pop-up notes, with links from the reference to the note
  and back. The table of contents comes from the headings (EPUB 3 nav plus EPUB 2 NCX).
  Language and title come from the PDF, or are guessed (`--language`, `--title`,
  `--author` override them).
- **Markdown:** YAML front matter (title, author, lang), `#` headings, one paragraph per
  block, and footnotes in Pandoc/GFM syntax (`text[^p12-1]`, notes at the end). It can
  be converted further, e.g. `pandoc book.md -o book.docx`.

How structure is detected:
- Headings are lines in a larger font, or short isolated all-caps or bold lines.
- Paragraph breaks come from vertical gaps, indentation, blank lines, and short lines
  that end a sentence.
- Running headers and footers (text repeated in the top or bottom margin) and page
  numbers are dropped.

To send to a Kindle, use the Send to Kindle app, web page or e-mail address with the
`.epub` file.

Limitations: images and tables are not carried over yet. Multi-column layouts and
scanned books with a poor OCR layer give rougher results (see `docs/ocr-plan.md`).

## Development

```bash
.venv/bin/pytest                        # all tests
.venv/bin/pytest -m "not integration"   # skip the slower real-PDF tests
.venv/bin/ruff check . && .venv/bin/ruff format .
```

The EPUB validation test uses `epubcheck` (`brew install epubcheck`) and is skipped if
it isn't installed.

Integration tests use sample PDFs in `test_pdfs/`. The folder is gitignored, so add
your own copies locally; tests for missing files are skipped. The expected samples are:
- `Critica de la Razon Pura - Immanuel Kant.pdf`: clean digital text.
- `Familia Romana Lingua Latina.pdf`: scanned book with a noisy OCR text layer
  (misrecognised characters, margin notes interleaved with body text) and
  image-only cover pages.
- `Magnifica Humanitas Encíclica May 15 2026.pdf`: web page printout with 224
  bracketed endnotes (`[1]` ... `[224]`).

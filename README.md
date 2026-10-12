# pdf-worker

A Python toolkit of PDF processing features, exposed as a `pdf-worker` CLI.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,ocr]'
brew install tesseract tesseract-lang   # only needed for OCR
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
(typically scanned images) are listed as a warning on stderr. Add `--ocr` to OCR them
first, or `--ocr redo` to replace a poor OCR layer (see [OCR](#ocr) below).

#### Footnotes and endnotes

Footnotes are marked explicitly, in Markdown/Pandoc footnote syntax:

| In the PDF | In the `.txt` |
|---|---|
| Superscript marker in the text, small note at the bottom of page 12 | `...claim[^p12-1] continues` and, at the end of that page's text, `[^p12-1]: The note.` |
| A note that runs onto the next page | `[^p12-1]: (continued) rest of the note.` on page 13 |
| Bracketed endnotes: `[31]` in the text, a later line starting `[31]` | `...claim[^31]` ... `[^31]: The note.` |
| Chapter endnotes: superscript numbers restarting in each chapter, notes as `12. Text` at the end of the chapter or in a "Notes" section | `...claim[^c3-12]` ... `[^c3-12]: Text` (chapter group 3, note 12) |

A reference is only rewritten when its note was found, so exponents (`m²`) and stray
numbers stay as they are. Numbered lists like `[1] ... [2] ...` and margin notes beside
the body text are not treated as notes. The command reports how many notes it marked
and warns about notes without references (or references without notes).
Use `--no-footnotes` to get the raw text layer instead.

Footnotes are found under the text column even when a watermark crosses them, when they
are set in two columns, or when OCR jitters their size. Chapter endnotes are paired with
their notes by order and count, so a numbered list inside a note doesn't break the
sequence. In EPUB and Markdown, notes with several paragraphs keep them.

Scanned books: OCR them first (`--ocr redo`). Tesseract usually garbles superscript
markers (`observe.**`), so their notes are taken out of the body and kept, but often
can't be linked to the exact spot in the text.

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
- **Pictures and cover:** figures are kept where they appear. Scanned books get their
  illustrations cropped out of the page scans: large areas of ink with no lines of
  text. Logos repeated on many pages are left out. Page 1 becomes the cover in the
  Kindle library. Use `--no-images` / `--no-cover` to turn these off. In Markdown,
  pictures are saved next to the file (`book_images/img1.jpg`).
- **Links:** links in the PDF stay links. Web links point to their address. Links inside
  the book (a contents page, cross-references) point to the exact section: they are
  matched by the link's text, then by the target position on the page.
- **Page numbers:** the EPUB has a page list with the book's printed page numbers. These
  come from the PDF's page labels or the numbers printed in the margins; front matter
  gets i, ii, iii. Readers that support page lists (Kindle among them) can show real
  page numbers instead of only locations. Each number is anchored in the text, so it
  stays right at any font size.
- **Markdown:** YAML front matter (title, author, lang), `#` headings, one paragraph per
  block, and footnotes in Pandoc/GFM syntax (`text[^p12-1]`, notes at the end). Web
  links become `[text](<url>)`. It can be converted further, e.g.
  `pandoc book.md -o book.docx`.

How structure is detected:
- Headings are lines in a larger font, or short isolated all-caps or bold lines.
- Paragraph breaks come from vertical gaps, indentation, blank lines, and short lines
  that end a sentence.
- Running headers and footers (text repeated in the top or bottom margin, including
  ones that only differ by a number such as `CAP. III`) and page numbers are dropped.
- Margin glosses (notes in a narrow column beside the text, as in textbooks and
  editions) are taken out of the body. Each page's glosses follow the paragraph they
  sit beside: as a blockquote with one line per gloss in Markdown, and as a small boxed
  `div.gloss` in EPUB.
- Line numbers in the gutter (`5`, `10`, ...) are dropped, including ones OCR glued onto a
  text line. Table cells on one row are joined into one line, and OCR noise from
  pictures (lines with no letters or digits) is dropped. Section breaks like `* * *`
  are kept.

To send to a Kindle, use the Send to Kindle app, web page or e-mail address with the
`.epub` file.

Limitations: drawings made of vector lines (charts, maps without an image) aren't
carried over, and tables come out as one line per row. Multi-column layouts and scanned books give rougher results; use `--ocr` /
`--ocr redo` for scans.

### OCR

Gives scanned PDFs a searchable text layer with [Tesseract](https://github.com/tesseract-ocr/tesseract)
(via [OCRmyPDF](https://ocrmypdf.readthedocs.io)). The output is a normal PDF that
looks the same, with invisible text over the page images. Why Tesseract was chosen:
`docs/ocr-plan.md`.

```bash
pdf-worker ocr scan.pdf                      # writes scan.ocr.pdf
pdf-worker ocr scan.pdf -o out.pdf --lang lat+eng
pdf-worker ocr book.pdf --mode redo          # replace a bad existing OCR layer
pdf-worker extract-text scan.pdf --ocr       # OCR on the fly, then extract
pdf-worker convert scan.pdf --ocr redo --ocr-lang spa
```

- `--mode skip` (default) only OCRs pages without text; `redo` replaces an existing OCR
  layer but keeps real digital text; `force` rasterizes and OCRs every page.
- The language is guessed from the existing text, or from a quick English OCR of a
  couple of pages. Set it with `--lang` (`--ocr-lang` for `extract-text`/`convert`);
  `tesseract --list-langs` lists the installed ones.
- Pages are OCR'd in parallel on all cores (`--jobs N` to limit).
- **Latin macrons:** Tesseract has no macrons and reads Latin long vowels as accented ones
  (`Màrcus`, `Iülia`). When Latin is an OCR language, those accents are turned back into
  macrons (`Mārcus`, `Iūlia`) before the text layer is written. `--no-latin-macrons`
  keeps the raw output. Tesseract misses some macrons entirely, so a few long vowels
  still come out plain.

## Development

```bash
.venv/bin/pytest                        # all tests
.venv/bin/pytest -m "not integration"   # skip the slower real-PDF tests
.venv/bin/ruff check . && .venv/bin/ruff format .
```

The EPUB validation test uses `epubcheck` (`brew install epubcheck`) and the OCR tests use
Tesseract; each is skipped if it isn't installed.

Integration tests use sample PDFs in `test_pdfs/`. The folder is gitignored, so add
your own copies locally; tests for missing files are skipped. The expected samples are:
- `Critica de la Razon Pura - Immanuel Kant.pdf`: clean digital text.
- `Familia Romana Lingua Latina.pdf`: scanned book with a noisy OCR text layer
  (misrecognised characters, margin notes interleaved with body text) and
  image-only cover pages.
- `Magnifica Humanitas Encíclica May 15 2026.pdf`: web page printout with 224
  bracketed endnotes (`[1]` ... `[224]`).
- Public-domain downloads:
  - `Trump v CASA (US Supreme Court 2025).pdf`: 42 bottom-of-page footnotes and a
    watermark
    (https://www.supremecourt.gov/opinions/24pdf/606us2r66_j426.pdf).
  - `9-11 Commission Report.pdf`: 1,742 chapter endnotes in a Notes section
    (https://www.govinfo.gov/content/pkg/GPO-911REPORT/pdf/GPO-911REPORT.pdf).
  - `Gibbon Decline and Fall vol 1 (1872 scan).pdf`: a scanned book with footnotes
    (https://archive.org/download/historyofdeclin01gibb/historyofdeclin01gibb.pdf).

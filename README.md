# pdf-worker

A Python toolkit of PDF processing features, exposed as a `pdf-worker` CLI.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,ocr]'
brew install tesseract tesseract-lang   # only needed for OCR
```

## Pipeline overview

How the commands fit together, from finding a book to a clean EPUB and PDF. Each step is
described in detail under [Features](#features).

```
════════════════════════════════════════════════════════════════════════════════════
 0. GETTING A BOOK                                              pdf-worker find-book
════════════════════════════════════════════════════════════════════════════════════

  INPUT, one of three:
  ┌─ prompts / flags ───────────────────┐  ┌─ --url URL ─────┐  ┌─ --file PATH ─┐
  │ --title --author --isbn --year      │  │ direct link     │  │ local file    │
  │ --translator --language es,en,la    │  │ (keeps the file │  │               │
  │ --format epub|pdf|txt   -d DIR      │  │  name from URL) │  │               │
  │ --config ~/.config/pdf-worker/      │  └───────┬─────────┘  └──────┬────────┘
  │          find-book.toml (own sites) │          │                   │
  └──────────────┬──────────────────────┘          │                   │
                 │ ISBN? → Open Library fills       │                   │
                 │ in title, author, language       │                   │
                 ▼                                  │                   │
  SEARCH (sources run in parallel; a failing one   │                   │
  only becomes a warning; see the table below)     │                   │
                 ▼                                  │                   │
  RANK (score_candidate)                           │                   │
   + title-word share (<50% → dropped as another   │                   │
     book), author surname (fuzzy spelling),       │                   │
     translator, language (wrong: −30), year,      │                   │
     source quality                                │                   │
   + asked format +30  │ no format asked: real EPUB +15 (not IA's)      │
   − link only (no file) −25                       │                   │
                 ▼                                  │                   │
  pick from the list → DOWNLOAD ◄──────────────────┘                   │
  (streamed, atomic, format from magic bytes: %PDF / PK)               │
                 ▼                                                      │
  CHECK QUALITY (check_download) ◄─────────────────────────────────────┘
                 │  suggests next steps and offers to run them
   ┌─────────────┼───────────────────────────┬─────────────────────────────┐
   ▼             ▼                           ▼                             ▼
 EPUB / FB2 /  PDF, good text layer      PDF, scan or poor OCR       link only
 MOBI / TXT    (born-digital)            (assess_text_layer: mode)    → open in a
   │             │                           │                         browser
   │             │                           ▼
   │             │                    1. OCR (below) → book.ocr.pdf
   │             ▼                           ▼
   │      2. CONVERT (below): --to epub and/or --to pdf
   ▼
 ebook-to-pdf book.epub [-o out.pdf]
   whole book via MuPDF, A5 + margins, TOC → bookmarks, metadata kept,
   U+FEFF/U+2060 removed          → book.pdf   (the EPUB is kept too)
   ★ shortest path: no OCR, no review


════════════════════════════════════════════════════════════════════════════════════
 1. OCR                         pdf-worker ocr  |  convert/extract-text --ocr [MODE]
════════════════════════════════════════════════════════════════════════════════════

  scan.pdf
     ▼
  ASSESS (ocr_check, samples 24 pages): text on ≥50% of pages? jittery lines?
     misread words >1%? hand-drawn underlines?  → mode: none | skip | redo
     ▼
  --mode skip  (default) only pages without text
         redo  replace a bad OCR layer, keep real digital text
         force rasterize and OCR every page
  --lang / --ocr-lang  spa, lat+eng, …   (default: guessed from the text or from a
                                          quick English OCR)
  -j N   pages in parallel
     ▼
  ┌─ --engine tesseract (default) ─────────────┐ ┌─ --engine paddle ──────────────────┐
  │ OCRmyPDF + plugins:                         │ │ PaddleOCR-VL (Apple Silicon,       │
  │  • underlines erased from the read image    │ │ 12–24 s/page, ~2 GB of models)     │
  │  • spreads not at (0,0) moved to the origin │ │ --paddle-cache DIR, per-page cache │
  │  • Latin: à/ü → ā/ū (--no-latin-macrons)    │ │ (can resume, repeatable)           │
  └─────────────────────┬───────────────────────┘ └──────────────┬─────────────────────┘
                        ▼                                         ▼
               book.ocr.pdf (invisible text layer)       text layer + Paddle blocks
                                                          (convert can use the blocks)


════════════════════════════════════════════════════════════════════════════════════
 2. CONVERT                                     pdf-worker convert book.pdf [options]
════════════════════════════════════════════════════════════════════════════════════

  book.pdf (or book.ocr.pdf)
     │  --ocr [MODE] --ocr-lang --ocr-engine   (does step 1 first)
     ▼
  ┌──────── Text-layer path ─────────────────┐   ┌──── Paddle path ─────────────────┐
  │ LAYOUT (analyze_document):                │   │ (--ocr redo|force                │
  │  running heads/feet, page numbers,        │   │  --ocr-engine paddle)            │
  │  columns, gutter line numbers, margin     │   │ paddle_book: titles, paragraphs, │
  │  glosses, body font size                  │   │ footnotes, running heads from    │
  │ NOTES: footnotes under the column,        │   │ Paddle's blocks                  │
  │  [31] endnotes, chapter endnotes          │   │ missing_refs: a note whose ref   │
  │  (matched by order and count)             │   │ was lost is looked for again     │
  │ STRUCTURE (iter_blocks):                  │   │ (old layer → Tesseract → Paddle  │
  │  headings (size, caps, bold), paragraphs, │   │ on just those lines)             │
  │  hyphens rejoined, dialogue turns, tables,│   │                                  │
  │  printed TOC dropped, links, images (or   │   │                                  │
  │  crops from scans), page labels           │   │                                  │
  └──────────────────┬────────────────────────┘   └────────────────┬─────────────────┘
                     └───────────────────┬─────────────────────────┘
                                         ▼
  METADATA: --title --author --language (default: PDF metadata / stopword guess);
            translator found on the first 6 pages
                                         ▼
  MARGIN REFERENCES (Stephanus 22b…):  off by default, so they are removed
            --margin-refs              keep them
            --estimate-margin-refs     fill gaps as [~23c]
                                         ▼
  ┌───────────── REVIEW FILE: book.fixes.tsv (--fixes PATH) ─────────────────────────┐
  │ APPLY rows that have an action:                                                   │
  │   replace [text] · ignore · attach [word] · drop · accept · move [word] · add     │
  │   status → applied | ambiguous | stale                                            │
  └──────────────────────────────────────┬────────────────────────────────────────────┘
                                         ▼
  --notes page (default) | end (reflowed PDF) | none (drop notes and their refs)
  --no-images  --no-cover
                                         ▼
  WRITE (atomic)  --to / -o extension:
    epub → book.epub         EPUB 3, pop-up notes, nav+NCX, page list, cover
    pdf  → book.reflowed.pdf A5, linked TOC and notes
    docx → book.docx         via Pandoc, real Word footnotes
    md   → book.md (+ book_images/)  ·  html → book.html  ·  txt → book.clean.txt
                                         ▼
  FLAG what looks wrong → new rows appended to book.fixes.tsv (empty action):
    spelling (es/en body text: accent · swap b/h c/e · ocr1 · name · unknown)
    chars (odd letters, Cyrillic look-alikes, $) · note-no-ref · ref-no-note
    margin-est · margin-missing
    (skips bibliographies, indexes, ALL CAPS, old spelling; split words joined first)


════════════════════════════════════════════════════════════════════════════════════
 3. CORRECTION LOOP                       pdf-worker review book.pdf
════════════════════════════════════════════════════════════════════════════════════

  book.fixes.tsv ──► open spelling/chars rows (undecided, or a replace that went stale)
                 ──► scan line of each word (Paddle cache + Tesseract) → book.review/crops
                 ──► gpt-oss-120b via Groq (GROQ_API_KEY; text only; rows asked once,
                     kept in book.review/proposals.jsonl; --no-model to skip)
                 ──► page on http://127.0.0.1:8765 (accept / ignore / edit, j/k a i e c,
                     filters) → "Save decisions" → merged into book.fixes.tsv
                     (backup in book.review/)
                          │
                          └──► run CONVERT again → fixes applied, new flags added
                               (repeat until clean; note and margin rows: edit the TSV)


════════════════════════════════════════════════════════════════════════════════════
 SHORTCUTS
════════════════════════════════════════════════════════════════════════════════════

  kindle book.pdf  =  assess → OCR if needed (--no-ocr, --ocr-lang, --engine)
                      → macOS scans with Tesseract: vote with Tesseract + Apple Vision
                        (both engines agree on a different word, more common in the book,
                        accents only added)
                      → convert --to epub (review file next to the original PDF)
                      → warns if over 50 MB (Send to Kindle email limit)

  extract-text book.pdf  →  book.txt  (raw layer, \f between pages; notes marked
                            [^p12-1] unless --no-footnotes; --page-separator; --ocr…)
```

Typical routes to a clean PDF and EPUB:
- **A real EPUB was found:** `ebook-to-pdf`. Done.
- **Born-digital PDF:** `convert --to epub`, then `convert --to pdf`.
- **Scan:** `ocr --mode redo` (or `--engine paddle` for Latin or Greek), then `convert`,
  then `review`, then `convert` again.

### Sources `find-book` searches

Searched every time:

| Site | How | What you get | Quality |
|---|---|---|---|
| Project Gutenberg (gutenberg.org) | OPDS search | EPUB (or text) | 10 |
| Standard Ebooks (standardebooks.org) | OPDS feed | Carefully edited EPUB | 15 |
| Internet Archive (archive.org) | advancedsearch + metadata | PDF scan; EPUB only with `--format epub` or when there is no PDF | 3 (PDF with text layer) / 0 |
| Wikisource (`<lang>.wikisource.org`, via ws-export.wmcloud.org) | MediaWiki search, in your languages (default en, es) | EPUB | 5 |
| OpenAlex (api.openalex.org) | Open-access books and chapters only | PDF/EPUB when free, else a link | 5 |
| DOAB (directory.doabooks.org) | OpenSearch | Link only | 5 |
| HathiTrust (catalog.hathitrust.org) | Only with `--isbn`; full-view volumes only | Link only | 0 |
| OpenStax (openstax.org) | Its list of ~130 textbooks (English and Spanish), matched by title | PDF | 10 |
| Open Textbook Library (open.umn.edu) | JSON search | PDF/EPUB when the listed link is a file, else a link (often Pressbooks, which blocks scripts) | 5 |

Only when your languages include Spanish (or none are given):

| Site | How | What you get | Quality |
|---|---|---|---|
| Elejandría (elejandria.com) | Its sitemap (robots.txt blocks `/buscar`) | PDF or EPUB, found at download | 10 |
| textos.info | Atom search feed | EPUB/PDF | 8 |

Only when your languages include English (or none are given):

| Site | How | What you get | Quality |
|---|---|---|---|
| Global Grey (globalgreyebooks.com) | Its sitemap (its search is Google's) | EPUB or PDF, found at download | 10 |

Also used:
- **Open Library** (openlibrary.org) is a helper, not a source of files: with `--isbn` it
  fills in the title, author and language, and gives Internet Archive IDs.
- **Your own sites** from `find-book.toml` (OPDS or a page of file links, `quality`
  default 5; see below).

Not used: OAPEN, Biblioteca Virtual Miguel de Cervantes, PhilArchive, Google Books, CCEL,
BNE Biblioteca Digital Hispánica, SciELO Books and Freeditorial are unreachable or not
usable. ManyBooks and Kobo answer scripts with 403; Smashwords' and Feedbooks'
robots.txt forbid searching; LibreTexts has no public search API. Amazon Kindle and Apple
Books free titles are DRM'd purchases on your account, with no download API. Shadow
libraries (LibGen, Anna's Archive, Z-Library) and DRM'd library loans (eBiblio) are left
out on purpose.

## Features

Forgot a command? `pdf-worker help` (or just `pdf-worker`) lists them all, each with a
one-line description. `pdf-worker <command> --help` shows every option.

### Find a free book online

```bash
pdf-worker find-book                  # asks for title, author, ISBN, year, translator...
pdf-worker find-book --title "Confesiones" --author Agustín --language es -d ~/Books
pdf-worker find-book --isbn 0140449132 --format epub
pdf-worker find-book --url https://example.org/libro.pdf   # no search: download and check
pdf-worker find-book --file ~/Downloads/libro.epub         # no search: just check
pdf-worker ebook-to-pdf book.epub     # an EPUB laid out as an A5 PDF, with bookmarks
```

`find-book` searches open, legal libraries at once: Project Gutenberg, Standard Ebooks,
Internet Archive (freely downloadable items only), Open Library (an ISBN gives the title,
author and language), Wikisource (any language, exported as EPUB), OpenAlex (recent
open-access academic books, with their free PDF when there is one), the open textbooks of
OpenStax and the Open Textbook Library, Global Grey (edited English classics), the
Spanish libraries Elejandría and textos.info, and DOAB and HathiTrust (links to open in a browser: their
downloads sit behind bot checks or a login). It ranks the results by title, author
(other spellings allowed), translator, language, year and format, and lists the best 10.
It downloads the one you pick (Enter: the best), checks it (a valid EPUB with text? a PDF
with a good text layer, or a scan that needs OCR?) and lists the next commands, offering
to run them. Cervantes Virtual, Biblioteca Digital Hispánica, SciELO Books, PhilArchive
and OAPEN block automated access, and Google Books needs an API key, so they are not
searched. Modern books still under copyright are usually not found; for a book you
obtained elsewhere (a publisher, a purchase without DRM), use `--url` or `--file`.

Extra sites and an OpenAlex key go in `~/.config/pdf-worker/find-book.toml` (or the file
given with `--config`):

```toml
# Optional: a free key (openalex.org/settings/api) gives OpenAlex searches their own
# daily budget instead of sharing one with your network.
openalex_api_key = ""

# Each site's search URL, with {query} where the search words go. It may answer with an
# OPDS catalogue (Calibre-Web, COPS and many libraries) or with a web page; from a page,
# the links to .pdf and .epub files become results.
[[sites]]
name = "My Calibre-Web"
search = "https://books.example.org/opds/search/{query}"
quality = 5   # optional: ranks this site's results higher (0-15; Gutenberg is 10)
```

### Make a Kindle book (one step)

```bash
pdf-worker kindle book.pdf            # writes book.epub, ready for Send to Kindle
pdf-worker kindle scan.pdf --ocr-lang lat
```

This checks the PDF's text layer first:
- **No text on most pages:** those pages are OCR'd.
- **A scan with a word-by-word or badly misread OCR layer:** that layer is replaced.
- **A scan with hand-drawn underlines** (pencil or pen, which the scan's own OCR reads
  as stray letters): only the underlined pages are OCR'd again, with the underlines
  erased first. The other pages keep their layer.
- **Any scan (macOS):** each scanned page is read again by Tesseract and Apple Vision,
  and where both agree on a different word than the page's text layer, that word is
  used (`parce` → `parte`, `asi` → `así`, `Cálleles` → `Calicles`). The new word must
  be more common in the book than the old one, and accents are only ever added. On the
  Platón sample (293 pages) it fixed about 600 words; word recall on two clean pages
  rose from 92.4% to 93.6%. It adds about 4 minutes for 300 pages. Without Apple
  Vision (not on macOS) this step is skipped.
- **Born-digital PDF:** used as it is.

Then it builds the EPUB, with footnotes, pictures, cover, links and page numbers. It
warns if the result is over Send to Kindle's 50 MB e-mail limit. `--no-ocr` never OCRs.
The steps are also available on their own (below).

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
pdf-worker convert book.pdf --to docx             # Word, with real footnotes
pdf-worker convert book.pdf --to html             # one self-contained web page
pdf-worker convert book.pdf --to txt              # clean text: book.clean.txt
pdf-worker convert book.pdf --to pdf              # retypeset A5 PDF: book.reflowed.pdf
```

Formats: `epub`, `md`, `html`, `txt`, `docx` and `pdf`. All are built from the same
rebuilt book (headings, paragraphs, notes, pictures, tables, links):
- **HTML:** one page with a contents list, linked footnotes, and pictures embedded.
- **Plain text:** one paragraph per line, references as `[n]`, notes at the end. Unlike
  `extract-text`, it has no page breaks, running heads or line numbers.
- **Word:** made with Pandoc (`brew install pandoc`). Notes become Word footnotes and the
  title becomes a document property.
- **PDF:** reflowed onto A5 pages with working contents and footnote links. Good for
  reading a scanned or awkwardly laid-out book on a tablet.

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
  text line, as are the section marks of classical editions (`11`, `b`, `c` beside the
  text, as in Stephanus numbering). Soft hyphens at line ends are joined, and speaker
  turns in dialogues start their own paragraphs. Table cells on one row are joined into one line, and OCR noise from
  pictures (lines with no letters or digits) is dropped. Section breaks like `* * *`
  are kept.

To send to a Kindle, use the Send to Kindle app, web page or e-mail address with the
`.epub` file.

- Tables: text set side by side on two or more consecutive rows becomes a table (an
  HTML table in EPUB, a pipe table in Markdown).
- A printed table of contents without links is dropped; the EPUB has its own. One with
  links is kept, with working links.
- Headings: OCR'd heading sizes that differ by a few percent count as one level.
  Several lines of large print are a passage, not a heading. Lines set wholly in
  another font than the body (bold, or display faces without a bold flag) count as
  emphasis.

Limitations: drawings made of vector lines (charts, maps without an image) aren't
carried over, and a table cell that wraps onto a second line splits the table. Multi-column layouts and scanned books give rougher results; use `--ocr` /
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
- **Underlined scans:** when sampled pages have hand-drawn underlines, they are erased
  from the image Tesseract reads (the visible page keeps them). On the Platón sample
  this raised word recall on underlined pages from 91% (the scan's ABBYY layer) to 95%.
- Scans of two-page spreads whose pages don't start at (0, 0) (some ABBYY FineReader
  PDFs) are moved to the origin first; OCRmyPDF otherwise loses those pages' text.
- **PaddleOCR-VL (`--engine paddle`):** much more accurate on diacritics. For example,
  it reads Latin long vowels that Tesseract misses (94% vs. about 50% in
  `docs/ocr-plan.md`). It is slow (12–24 s a page on an M1) and Apple-Silicon only.
  pdf-worker starts and stops the model server itself and writes the result as the
  same kind of text layer, so `--engine paddle` works with `ocr`, `kindle` and
  `--ocr` alike. One-time setup:
  ```bash
  brew install python@3.12
  python3.12 -m venv .venv-paddle
  .venv-paddle/bin/pip install paddlepaddle==3.2.1 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
  .venv-paddle/bin/pip install "paddleocr[doc-parser]" "mlx-vlm>=0.3.11" pymupdf
  .venv/bin/pip install -e '.[paddle]'
  pdf-worker kindle scan.pdf --engine paddle   # first run downloads ~2 GB of models
  ```
  The models go to `~/.cache/pdf-worker/paddle` (`--paddle-cache DIR` or
  `PDF_WORKER_PADDLE_CACHE` to change; `PDF_WORKER_PADDLE_PYTHON` for another venv).
  Paddle's reading of each page is kept there too (`pages/`), so running a file again
  is fast and gives the same text, and an interrupted run goes on where it stopped.
  `convert --ocr redo|force --ocr-engine paddle` builds the book from Paddle's blocks
  themselves (titles, paragraphs, footnotes, running heads), not from a text layer:
  paragraphs, notes and headings come out much cleaner. Add `--notes end` to keep a
  reflowed PDF's notes together at the end of the book (each ends with a ↩ link back to
  the text). A note whose reference the OCR lost is looked for again on its page: in
  the PDF's old text layer, then with Tesseract and Paddle on just those lines. Each
  reference found this way is listed after the summary.
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

The EPUB validation test uses `epubcheck` (`brew install epubcheck`), the OCR tests use
Tesseract and the Word test uses Pandoc; each is skipped if its tool isn't installed.
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
- `platon_dialogos_vi_bad.pdf`: a poor black-and-white scan with an ABBYY FineReader
  layer, pencil underlining, Stephanus margin marks and footnotes.
  `platon_dialogos_vi_good.pdf` is a clean edition of the same text, used to score OCR.

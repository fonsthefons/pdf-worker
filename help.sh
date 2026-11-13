#!/usr/bin/env bash
# Print how to run this repo's main features.
cat <<'X'
pdf-worker: convert, OCR and clean up PDFs and ebooks (EPUB, Markdown, Kindle).

  .venv/bin/pdf-worker convert book.pdf
      Convert a PDF to book.epub (add --to md|html|txt|docx|pdf for other formats)

  .venv/bin/pdf-worker process
      Turn every book in file_inbox into a clean EPUB and PDF in file_outbox

  .venv/bin/pdf-worker process book.pdf --to epub,pdf
      Process just one book, choosing the output formats

  .venv/bin/pdf-worker find-book --title "Confesiones" --author Agustín
      Find a free copy online, download the best one and check its quality

  .venv/bin/pdf-worker kindle book.pdf
      One step from a PDF to a Kindle-ready EPUB (OCRs scans when needed)

  .venv/bin/pdf-worker extract-text book.pdf
      Write the PDF's text layer to book.txt

  .venv/bin/pdf-worker ocr scan.pdf --lang eng
      Add a searchable text layer to a scanned PDF (scan.ocr.pdf)

  .venv/bin/pdf-worker help
      List every command with examples
X

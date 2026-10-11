# OCR: research and plan

Status: research done on 2026-10-12, not implemented yet.

## Why we need it

- Some PDFs have no text layer: pages 1, 2, 331 and 332 of the Familia Romana sample,
  and any book scanned without OCR. `extract-text` gets nothing from those pages.
- Some PDFs have a *bad* text layer: Familia Romana's existing OCR loses every macron
  (`Mārcus` → `Marcus`), misreads characters (`Jiilia`, `0RBERG`) and interleaves margin
  glosses with the body text.
- The end goal is rebuilding books cleanly (EPUB/Markdown), so we need more than text:
  reading order, columns, and footnotes.

## Constraints

- Free and open source, and runs locally.
- Target machine: Apple M1 with 16 GB RAM and no NVIDIA GPU. Most OCR "VLM" stacks assume
  CUDA, so they are out unless they have an MLX, llama.cpp or CPU path.
- Huge PDFs: work page by page and stream, the same as the rest of pdf-worker.

## Candidates

| Tool | License | Runs on M1 | Strengths | Weaknesses |
|---|---|---|---|---|
| **Tesseract 5.5** (via **OCRmyPDF 17**) | Apache-2.0 / MPL-2.0 | Yes, CPU, `brew` | Mature, 100+ languages including `lat`; OCRmyPDF writes a searchable PDF; keeps columns apart | Drops diacritics it wasn't trained on (macrons); weak on complex layouts |
| **Apple Vision** (`ocrmac`, or the `ocrmypdf-appleocr` plugin) | OS framework; wrappers MIT | Yes, built in | Fast; very good on modern Latin-script languages | macOS only; no Latin; one language at a time; merges margin notes into body lines |
| **PaddleOCR-VL-1.6** (0.9B VLM) | Apache-2.0 | Yes, official Apple Silicon path (PaddlePaddle CPU for layout + MLX-VLM server for the VLM) | Top open model on OmniDocBench v1.6 (≈96); outputs Markdown/JSON with layout labels (headings, footnotes, tables) | Heavy install (several GB); verified on M4 only; slower per page |
| MinerU 2.5 / GLM-OCR (≈1B VLMs) | AGPL-3.0 reported for MinerU | Unclear | Close behind PaddleOCR-VL on benchmarks | License or Mac support unclear |
| olmOCR 2 (7B) | Apache-2.0 | Poorly: needs about 12 GB of GPU memory, CUDA stack | Built for scanned books | Too heavy for this machine |
| Surya / Marker | Code open; **weights restricted** (modified OpenRAIL-M / CC-BY-NC-SA) | Yes | Good layout | Weight license is not free for every use; avoid |
| EasyOCR, docTR | Apache-2.0 | Yes | Simple | Below Tesseract/PaddleOCR on printed books |

## What I measured (on this M1, 300 dpi)

Script: `scratch/ocr_bakeoff.py` (local only). CER means character error rate.

| Sample | Apple Vision (accurate) | Tesseract 5.5.3 |
|---|---|---|
| Kant (Spanish, clean digital page rendered to an image): CER against the true text layer, 3 pages | 0.02% / 0.71% / 0.05%, about 1–2 s per page | 0.00% / 0.11% / 0.05%, about 2.5–4 s per page |
| Familia Romana p. 25 (real scan, Latin with macrons, margin glosses), checked by eye against the page image | Macrons inconsistent (`Märcus`, `Iülia`); margin glosses interleaved into the body text | Macrons dropped (`Marcus`, `qui`); body and margin column output separately, in reading order |

Conclusions:
1. On clean pages both engines are essentially perfect, so either is fine for "no text
   layer" pages of modern books.
2. Tesseract's layout handling suits rebuilding a book better: columns stay separate.
3. Neither classical engine handles Latin macrons. That needs a VLM (PaddleOCR-VL), so
   it has to be evaluated before we rely on it for books like Familia Romana.

## Recommendation

**Tesseract via OCRmyPDF as the default engine**, with **PaddleOCR-VL as an optional
high-quality engine** for difficult scans once it has been evaluated on this machine.
Apple Vision is an optional fast engine for modern languages.

OCRmyPDF is the backbone because it outputs a *PDF with a text layer*. Everything we
already have (`extract-text`, footnote detection) then works on OCR'd books unchanged,
and OCRmyPDF handles parallelism, deskew, rotation and large files for us.

## Plan

### Phase 1: `pdf-worker ocr` (Tesseract)
- New module `ocr.py` and subcommand `pdf-worker ocr in.pdf -o out.pdf [--lang lat+eng]
  [--mode skip|redo|force] [--jobs N]`.
  - `skip` (default): OCR only pages without text.
  - `redo`: replace an existing bad OCR layer. This is the Familia Romana case.
  - `force`: rasterize every page and OCR it.
- Call OCRmyPDF through its Python API (`ocrmypdf.ocr(...)`), not a shell command. Map
  its exceptions to `PdfWorkerError` subclasses (for example `OcrEngineMissing` when
  Tesseract isn't installed, with an install hint).
- Atomic output (temp file + `os.replace`), as for every other feature.
- `extract-text --ocr` as a convenience: OCR to a temp PDF in the output folder, then
  extract.
- Dependencies: `ocrmypdf` in a new optional extra `[ocr]`. Tesseract itself comes from
  `brew install tesseract tesseract-lang` (documented; checked at runtime).
- Tests: unit tests on generated image-only PDFs (render text to an image, embed it,
  OCR it, assert the words come back), skipped when Tesseract is missing. Integration
  test: OCR Familia Romana pages 1–2 (image-only) and check that the text is non-empty.

### Phase 2: evaluate PaddleOCR-VL-1.6 on the M1
- Install into a *separate* venv (`.venv-paddle/`, gitignored) so its heavy dependencies
  don't affect the main project. Run the MLX-VLM server and OCR Familia Romana pp. 9,
  25, 120 and a footnoted scan.
- Measure macron accuracy, reading order, margin-note handling, footnote labels, seconds
  per page and memory use.
- Decision rule: adopt it as `--engine paddle` if it reads macrons correctly and runs at
  10 s per page or less. Otherwise keep Tesseract only.

### Phase 3: engines and structure
- `--engine tesseract|apple|paddle`. Apple via `ocrmypdf-appleocr`; Paddle by
  converting its Markdown/JSON output (with layout labels) straight into our document
  model, which feature 3 (EPUB/Markdown conversion) also uses. Its footnote labels then
  feed the footnote markup directly.
- Footnotes on OCR'd pages: OCRmyPDF's text layer sizes each line's font to its height,
  so the existing small-font footnote heuristic still works roughly. Superscript flags
  are lost, so references are matched by number only.

### Open questions
- Ghostscript: OCRmyPDF 17 only needs it for PDF/A output. Using `--output-type pdf`
  should avoid it, but this needs checking during phase 1.
- Tesseract's `lat` model and macrons: try `lat` against `ita`/`eng` combinations, and
  look for macron-aware community models.

## Sources
- [Best open-source OCR models in 2026, ranked by benchmark (Roboflow)](https://roboflow.com/blog/best-open-source-ocr-models)
- [The best OCR models in 2026 (Docsumo)](https://www.docsumo.com/blog/best-ocr-models)
- [PaddleOCR-VL-1.6 paper (arXiv 2606.03264)](https://arxiv.org/pdf/2606.03264)
- [PaddleOCR-VL-1.5 paper, OmniDocBench v1.5 comparisons (arXiv 2601.21957)](https://arxiv.org/html/2601.21957v1)
- [PaddleOCR-VL on Apple Silicon (official docs)](http://www.paddleocr.ai/main/en/version3.x/pipeline_usage/PaddleOCR-VL-Apple-Silicon.html)
- [olmOCR-2 vs PaddleOCR-VL on Apple Silicon (CodeCut)](https://codecut.ai/olmocr2-vs-paddleocr-vl/)
- [OCRmyPDF v17.8.1 release](https://newreleases.io/project/github/ocrmypdf/OCRmyPDF/release/v17.8.1)
- [OCRmyPDF-AppleOCR plugin](https://github.com/mkyt/OCRmyPDF-AppleOCR)
- [ocrmac on PyPI](https://pypi.org/project/ocrmac)
- [Surya/Marker licensing discussion (particula.tech)](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser)
- [Docling layout model labels (Hugging Face)](https://huggingface.co/docling-project/docling-models/blob/refs%2Fpr%2F22/README.md)

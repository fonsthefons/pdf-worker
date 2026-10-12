# OCR: research and plan

Status, 2026-10-12:
- Research done.
- Phase 1 (Tesseract via OCRmyPDF) is implemented as `pdf-worker ocr` and `--ocr`, with
  Latin macron restoration.
- Phase 2 (PaddleOCR-VL evaluation) is done; see
  [Phase 2 results](#phase-2-results-paddleocr-vl-16-on-the-m1).
- Phase 3 is not started.

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

## Phase 2 results: PaddleOCR-VL-1.6 on the M1

### Setup
This follows the official Apple Silicon guide.

- **Install:**
  - Python 3.12 from Homebrew, because PaddlePaddle has no 3.14 wheel.
  - A separate venv `.venv-paddle/` (gitignored, 1.6 GB) with `paddlepaddle==3.2.1`
    (CPU), `paddleocr[doc-parser]` 3.7.0 and `mlx-vlm` 0.7.6.
- **Running it:**
  - The PP-DocLayoutV3 layout model runs in PaddlePaddle on the CPU.
  - The 0.9B VLM runs in an `mlx_vlm.server` on port 8111.
  - `PaddleOCRVL(vl_rec_backend="mlx-vlm-server", ...)` ties the two together.
- **Model downloads:** 1.9 GB, kept inside the repo by pointing `HOME`, `HF_HOME` and
  `PADDLE_PDX_CACHE_HOME` at `scratch/paddle-home`.
- **Scripts (local only):** `scratch/paddle_env.py`, `paddle_server.py`,
  `paddle_eval.py`, `paddle_truth.py`.

### Measurements
Pages were rendered at 200 dpi. The ground truth is the body text of Familia Romana
pp. 9 and 25, typed from the page images. "Long-vowel recall" is the share of words with
a macron reproduced exactly.

| Page | Engine | Word recall | Long-vowel recall |
|---|---|---|---|
| 9 | Tesseract + macron fix | 81.0% | 44.4% |
| 9 | PaddleOCR-VL raw | 69.6% | 11.1% |
| 9 | PaddleOCR-VL + macron fix | **98.1%** | **94.4%** |
| 25 | Tesseract + macron fix | 82.4% | 50.0% |
| 25 | PaddleOCR-VL raw | 97.1% | 94.4% |
| 25 | PaddleOCR-VL + macron fix | **97.1%** | **94.4%** |

- **Clean digital pages** (Kant, rendered to images): character error rate against the
  real text layer was 0.81% and 0.03%, about the same as Tesseract.
- **Speed:** 12–24 s per page, against Tesseract's ≈1 s on 8 cores. The first request
  takes another ~3 minutes to download the model.
- **Memory:** about 0.6 GB resident for the server.
- **Strengths:**
  - It sees long vowels Tesseract misses entirely (`rīdet`, `plōrat`, `quī`, `Quīntus`,
    `līberōrum`).
  - Its Markdown output has real headings (`## TEMPESTAS`), image boxes instead of OCR
    noise from pictures, and no gutter line numbers on most pages.
- **Weaknesses:**
  - It writes macrons as assorted accents (`Eurôpã`, `Åfricå`, `nön`), sometimes on the
    same page as correct ones. `restore_macrons` fixes this; ring-above `å` was added to
    it for Paddle.
  - It hallucinates now and then: `Aemiliaam`, Portuguese `não` for `nō-`, Greek `ἐnfluit`
    for `īnfluit`, LaTeX `$ \text{Åfricä} $`.
  - It swapped two paragraphs on p. 25.
  - It dropped most of p. 25's margin glosses and its `[A]`/`[B]` labels. On p. 120 it
    kept the glosses, as blocks before the body.
  - Line numbers are sometimes glued mid-sentence (`quod 1 suprā`).
  - Repeated runs on the same page differ slightly.

### Decision
The phase 2 rule was: adopt it if it reads macrons correctly and runs at 10 s per page
or less.

- Macrons: passed, with the macron fix.
- Speed: failed, at 12–24 s per page. A 332-page book takes roughly 1.5–2 hours instead
  of ~5 minutes.

Recommendation:
- **Keep Tesseract as the default.**
- **Add PaddleOCR-VL as an opt-in `--engine paddle`** for scans where accuracy matters
  more than time (diacritics, old print, hard layouts). It is suitable for unattended
  overnight runs.
- Integrating it (phase 3) means:
  - Converting its JSON/Markdown output (with layout labels) into our block model,
    instead of a PDF text layer.
  - Starting and stopping the MLX server from `pdf-worker`.
  - Reconciling it with the margin and gloss handling, since Paddle reorders and
    sometimes drops glosses.

### Open questions
- Ghostscript: answered. With `output_type="pdf"`, OCRmyPDF 17.13 runs without it (it is
  not installed on this machine).
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

# Drop-in pipeline: what the best open tools do

Date: 2026-11-14. Web tools worked (one search per topic, few pages opened). Most sources are
secondary blogs and abstracts, not primary benchmarks: every number below is "reported", not
measured here. Nothing was installed or run.

## 1. PDF/scan to Markdown locally on Apple Silicon

Measured (by others, single documents): olmOCR-2 through GGUF/llama.cpp took about 37 s per
page on an M5 Pro; PaddleOCR-VL installs with `paddlepaddle` and `paddleocr[doc-parser]>=3.6.0`
(https://newsletter.codecut.ai/p/extracting-pdf-tables-on-apple-silicon).
OmniDocBench scores quoted by one 2026 guide: PaddleOCR-VL-1.6 96.34, MinerU2.5-Pro 95.75,
GLM-OCR 95.22; older generation MinerU pipeline 86.47, olmOCR 85.74, Marker 78.44 (different
runs, not comparable across lists)
(https://pasqualepillitteri.it/en/news/25568/best-local-ocr-pc-server-2026).
That guide recommends PaddleOCR-VL-1.6 or GLM-OCR on Macs (MLX-VLM support).
Marker: v2.0.0 (2026-07-20) is reported as a rewrite around the Surya VLM, with CPU and MPS
(same guide). Docling: runs on CPU, many input formats; licence reported as Apache 2.0 by one
source and MIT by another, so check
(https://codesota.com/ocr/docling). MinerU and Marker weights are reported to carry revenue or
user thresholds (Japanese edition of the same guide): check before any commercial use.

Assumed (from earlier knowledge, not verified today): Docling and MinerU emit heading levels,
page furniture labels (page header/footer, footnote) and reading order from a layout model;
Marker gives headings and footnotes less reliably; none is known to handle polytonic Greek
well in a general model. Nothing found on polytonic Greek for any of them: untested.
No head-to-head of all tools on Apple Silicon exists in what was found.

## 2. OCR post-correction with LLMs

Measured: the ICDAR 2026 HIPE-OCRepair report finds LLM correction usually helps, with the
largest gains on noisy text, but already-accurate text gets worse from small unneeded edits;
over-correction and hallucination are named open problems
(https://arxiv.org/pdf/2607.08143). Boros et al. 2024 tested 14 models and found they often
degrade or leave text unchanged (https://aclanthology.org/2024.latechclfl-1.14). A 2025 study
on 18th-century Russian books found correction can lower quality and models insert archaic
forms (https://aclanthology.org/anthology-files/pdf/lm4dh/2025.lm4dh-1.7.pdf). Only
abstracts were read.

Assumed (design, not found in a source): send only flagged words with a short context window;
ask for JSON `{id, original, fixed}` per item, batched; accept a fix only if the edit
distance to the original is small, the fixed word is in a dictionary and the surrounding
words are unchanged; on any parse failure or timeout keep the original.

## 3. Language of each word inside Spanish text

Found: MaskLID (fastText-based, training-free, iterative masking) for code-switching
(https://arxiv.org/html/2406.06263v1); lingua-py is built for short text, including single
words, but no word-level code-switch benchmark compares it with fastText
(https://pypi.org/project/lingua-language-detector/). A 2016 fastText token tagger reached
0.949 token accuracy on English-Spanish tweets. Short spans are a known weak spot.

Assumed: single-word detectors are unreliable; word lists (Spanish, Latin, German, French,
English dictionaries) plus a run-level vote (neighbouring foreign words must agree) beat a
single-word model. Transliterated Greek has no dictionary; a small character n-gram check
(for example "ph", "th", "-os", "-on" endings) is a guess to test.

## 4. Chapters from a contents page or PDF outline

Found: `doc.get_toc()` in PyMuPDF returns the outline, empty if none. If a printed contents
page has link annotations, join each link rectangle to the text under it
(https://towardsdatascience.com/reconstructing-the-table-of-contents-a-pdf-forgot-to-ship/).
Otherwise render the contents pages and have a vision model transcribe them, then compute the
offset between printed and physical page numbers, as `ebook-toc` and a Claude skill do
(https://pypi.org/project/ebook-toc/). Font-based inference: pdf.tocgen. Order to use: outline,
links, vision. The offset step is the part to verify on scans.

## 5. Free OpenRouter vision models today

Found, with low confidence: `openrouter/free` router takes text and images but picks a model
at random (https://openrouter.ai/openrouter/free:free); Ling 3.0 Flash VL, listed free, released
2026-09-10 (https://openrouter.ai/inclusionai/ling-3.0-flash-vl:free); a July 2026 guide names
Nemotron Nano 12B VL for images (https://buldrr.com/openrouter-free-models-list-2026-all-27-models-ranked-tested/);
Qwen2.5-VL 3B/72B `:free` pages exist but today's status unverified. The API listing could not
be filtered by price or modality from here. Free rosters change often: at run time query
`get_client("openrouter")` for the live list and pick models with image input and price 0.

## Engines to try

1. Docling: `.venv/bin/pip install docling` (CPU/MPS, structured output with headings, footnote
   and furniture labels, reading order).
2. MinerU: `.venv/bin/pip install "mineru[all]"` (layout-model pipeline, top OmniDocBench class
   per the guide above; check weights licence).

PaddleOCR-VL is already the repo's layout model, so it is the baseline, not a candidate.

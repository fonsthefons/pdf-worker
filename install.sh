#!/usr/bin/env bash
# Install pdf-worker on this Mac. Safe to re-run: what is in place is skipped.
#   ./install.sh            the CLI, OCR (Tesseract) and Word/PDF export (Pandoc)
#   ./install.sh --paddle   also the PaddleOCR-VL engine (.venv-paddle, ~2 GB of models on first use)
set -uo pipefail
cd "$(dirname "$0")"
FAILED=()
try() { local what=$1; shift; echo "==> $what"; "$@" || FAILED+=("$what"); }

if [ ! -x /opt/homebrew/bin/brew ]; then
  echo "!! Homebrew not found: run mac-setup first (~/Documents/programs/mac-setup)."; exit 1
fi
eval "$(/opt/homebrew/bin/brew shellenv)"

# 1. ai-client: the sibling repo for AI calls, Apple Vision, MLX-VLM and the word check
AI=../ai-client
[ -d "$AI" ] || try "clone ai-client" git clone git@github.com:fonsthefons/ai-client.git "$AI"
[ -x "$AI/.venv/bin/python" ] || try "ai-client install" "$AI/install.sh"

# 2. Tools: Tesseract (OCR), Pandoc (Word and PDF export), epubcheck (one test)
for pair in tesseract:tesseract pandoc:pandoc epubcheck:epubcheck; do
  command -v "${pair%%:*}" >/dev/null || try "brew: ${pair#*:}" brew install "${pair#*:}"
done
[ -d "$(brew --prefix)/share/tessdata" ] && ls "$(brew --prefix)/share/tessdata" | grep -q '^spa' ||
  try "brew: tesseract-lang" brew install tesseract-lang

# 3. .venv (Homebrew's python3: macOS's own is 3.9, pyproject needs 3.11+)
[ -x .venv/bin/python ] || try ".venv" python3 -m venv .venv
# [paddle] is only pymupdf-fonts (small); the tests need it too
try "pip: ai-client + pdf-worker[dev,ocr,paddle]" .venv/bin/python -m pip install -q -e "$AI" -e '.[dev,ocr,paddle]'

# 4. Folders for `pdf-worker process`, and scratch/ (tests put tmp_path in scratch/pytest); all gitignored
mkdir -p file_conversion/file_inbox file_conversion/file_outbox file_conversion/file_work scratch/tmp

# 5. Optional: PaddleOCR-VL in its own Python 3.12 venv (README: OCR)
if [ "${1:-}" = "--paddle" ]; then
  command -v python3.12 >/dev/null || try "brew: python@3.12" brew install python@3.12
  [ -x .venv-paddle/bin/python ] || try ".venv-paddle" python3.12 -m venv .venv-paddle
  try "paddlepaddle" .venv-paddle/bin/pip install -q paddlepaddle==3.2.1 \
    -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
  try "paddleocr + mlx-vlm" .venv-paddle/bin/pip install -q "paddleocr[doc-parser]" "mlx-vlm>=0.3.11" pymupdf
fi

# 6. Smoke test (the full fast suite takes ~8 min: .venv/bin/pytest -m "not integration")
try "pdf-worker runs" .venv/bin/pdf-worker help

echo
echo "================ SUMMARY ================"
if [ ${#FAILED[@]} -eq 0 ]; then echo "Everything installed OK."; else
  echo "FAILED (re-running ./install.sh is safe):"; for x in "${FAILED[@]}"; do echo " ✗ $x"; done
fi
cat <<'EOF'

EXTRA STEPS (by hand):
  • ai-client must sit next to this repo (../ai-client). Its .env holds GROQ_API_KEY (model-assisted review)
    and its data/ the word lists and data/decisions.tsv (your review decisions, shared by every book).
    Check: ../ai-client/.venv/bin/python -m ai_client
  • test_pdfs/ is not in git (large, copyrighted): copy it from the old Mac for the integration tests
    (README: Development lists the files).
  • find-book: optional extra sites and an OpenAlex key in ~/.config/pdf-worker/find-book.toml.
  • Kindle highlights: the Kindle files come off over MTP (quit Calibre/OpenMTP first; README: Highlights).
  • --engine paddle: run ./install.sh --paddle once; the first run downloads ~2 GB to ~/.cache/pdf-worker/paddle.
EOF
[ ${#FAILED[@]} -eq 0 ]

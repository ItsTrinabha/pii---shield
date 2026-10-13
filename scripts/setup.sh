#!/usr/bin/env bash
# Cloak without Docker (Linux / macOS / WSL): creates .venv, installs everything, then: source .venv/bin/activate && python -m pii_shield.app
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"

if ! command -v tesseract >/dev/null 2>&1; then
  echo "Tesseract OCR is required:"
  echo "  Ubuntu/Debian/WSL: sudo apt-get install -y tesseract-ocr"
  echo "  macOS (Homebrew):  brew install tesseract"
  exit 1
fi
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'

[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -e ".[dev]"
python -c "import en_core_web_lg" 2>/dev/null || pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl

echo
echo "Done. Start Cloak with:"
echo "  source .venv/bin/activate && python -m pii_shield.app"
echo "then open http://127.0.0.1:8765"

#!/usr/bin/env bash
# One-time setup for the Mac assistant. Run:  bash setup.sh
set -e
cd "$(dirname "$0")"

PY=$(command -v python3.12 || command -v python3.11 || command -v python3 || true)
if [ -z "$PY" ]; then echo "Python 3 not found. Install it with: brew install python@3.12"; exit 1; fi
echo "Using $($PY --version)"

$PY -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Downloading wake-word models..."
python -c "import openwakeword; openwakeword.utils.download_models()"

echo "Downloading the natural voice (Piper, ~60 MB)..."
mkdir -p ~/Assistant/voices
for f in en_US-ryan-medium.onnx en_US-ryan-medium.onnx.json; do
  [ -f ~/Assistant/voices/$f ] || curl -sL -o ~/Assistant/voices/$f "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/$f"
done

[ -f .env ] || cp .env.example .env
echo
echo "Done. Next:"
echo "  1. Put your GROQ_API_KEY (free: console.groq.com) or ANTHROPIC_API_KEY in .env"
echo "  2. Test by typing:   source .venv/bin/activate && python -m assistant --text"
echo "  3. Then by voice:    python -m assistant"

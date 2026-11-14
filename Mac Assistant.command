#!/bin/bash
# Double-click to start the assistant (opens in Terminal, which already has microphone access).
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate
python -m assistant
echo
read -n 1 -s -r -p "Assistant stopped. Press any key to close."

#!/bin/bash
# NOVA — macOS launcher (equivalent of start.bat)
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="python3"; fi
nohup "$PY" main.py >> "$HOME/Library/Logs/NOVA.log" 2>&1 &
disown

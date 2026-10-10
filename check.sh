#!/bin/bash
# One command to check NOVA before you commit or build:  ./check.sh
# Lint + the whole test-suite. Nothing touches your real data, Keychain or a NOVA that is open.
#   ./check.sh --screen   also runs the few tests that briefly open a real NOVA window (quit behaviour)
set -euo pipefail
cd "$(dirname "$0")"
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"
echo "▶ lint";  "$PY" -m pyflakes *.py tests/*.py
echo "▶ tests"
if [ "${1:-}" = "--screen" ]; then export NOVA_GUI_TESTS=1; fi
QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q tests -p no:cacheprovider
echo "✔ all good"

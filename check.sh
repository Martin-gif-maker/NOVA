#!/bin/bash
# One command to check NOVA before you commit or build:  ./check.sh
# Lint + the whole test-suite. Nothing touches your real data, Keychain or a NOVA that is open.
#   ./check.sh --screen   also runs the few tests that briefly open a real NOVA window (quit behaviour)
set -euo pipefail
cd "$(dirname "$0")"
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"
echo "▶ lint"
if "$PY" -m ruff --version >/dev/null 2>&1; then "$PY" -m ruff check .          # rules in pyproject.toml
else "$PY" -m pyflakes *.py tests/*.py evals/*.py; fi
if "$PY" -m mypy --version >/dev/null 2>&1; then echo "▶ types"; "$PY" -m mypy --no-error-summary; fi   # files in pyproject.toml
echo "▶ tests"
if [ "${1:-}" = "--screen" ]; then export NOVA_GUI_TESTS=1; fi
QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q tests -p no:cacheprovider
echo "✔ all good"

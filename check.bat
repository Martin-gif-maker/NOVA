@echo off
rem One command to check NOVA before you commit or build (the twin of check.sh):  check.bat
rem Lint + the whole test-suite. Nothing touches your real data, your saved keys or a NOVA that is open.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo ^> lint
"%PY%" -c "import glob, sys; from pyflakes.api import checkPath; sys.exit(1 if sum(checkPath(f) for f in glob.glob('*.py') + glob.glob('tests/*.py')) else 0)" || exit /b 1
echo ^> tests
set QT_QPA_PLATFORM=offscreen
"%PY%" -m pytest -q tests -p no:cacheprovider || exit /b 1
echo all good

@echo off
rem NOVA - Windows setup. Run once: double-click it, or run  setup_windows.bat  in a terminal.
setlocal
cd /d "%~dp0"
chcp 65001 >nul 2>&1

echo.
echo   =====================================================
echo        NOVA AI Desktop Assistant  ^|  Windows Setup
echo   =====================================================
echo.

rem 1. Python  (3.14 is the version NOVA is tested on; 3.10+ also works)
echo   [1/4] Checking Python...
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo   [!] Python 3.10 or newer is required but was not found.
    echo       Install it from https://www.python.org/downloads/windows/
    echo       and tick "Add python.exe to PATH" in the installer. Then run this setup again.
    start "" "https://www.python.org/downloads/windows/"
    pause
    exit /b 1
)
for /f "delims=" %%v in ('%PY% --version') do echo       %%v found.

rem 2. Virtual environment (keeps NOVA's packages separate from the system Python)
echo.
echo   [2/4] Creating virtual environment (.venv)...
%PY% -m venv .venv || goto :failed

rem 3. Dependencies
echo.
echo   [3/4] Installing dependencies (this may take a few minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :failed

rem 4. Icon + Start menu shortcut
echo.
echo   [4/4] Creating the Start menu shortcut...
".venv\Scripts\python.exe" create_shortcut.py || echo       (the shortcut could not be created - start NOVA with start.bat)

echo.
echo   =====================================================
echo    NOVA installed successfully!
echo   =====================================================
echo.
echo    Launch it:   Start menu (type NOVA)   or   start.bat
echo.
echo    Show or hide NOVA from anywhere:   Ctrl+Alt+Space
echo    Act on text selected in any app:   Ctrl+Alt+Shift+Space
echo.
echo    For voice input, Windows must allow desktop apps to use the microphone:
echo    Settings - Privacy ^& security - Microphone.
echo.
pause
exit /b 0

:failed
echo.
echo   [!] Setup did not finish. The lines above say what went wrong.
pause
exit /b 1

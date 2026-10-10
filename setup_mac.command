#!/bin/bash
# NOVA — macOS setup. Run once:  ./setup_mac.command
set -e
cd "$(dirname "$0")"

echo
echo "  ====================================================="
echo "       NOVA AI Desktop Assistant  |  macOS Setup"
echo "  ====================================================="
echo

# 1. Python  (3.14 is the version NOVA is tested on - see .python-version; 3.10+ also works)
echo "  [1/4] Checking Python..."
PYBIN=""
for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
        PYBIN="$c"; break
    fi
done
if [ -z "$PYBIN" ]; then
    echo
    echo "  [!] Python 3.10+ is required but was not found."
    echo "      Install it with:  brew install python@3.12"
    echo "      or download it from https://www.python.org/downloads/macos/"
    open "https://www.python.org/downloads/macos/" 2>/dev/null || true
    exit 1
fi
echo "      $($PYBIN --version) found ($PYBIN)."

# 2. Virtual environment (keeps NOVA's packages separate from the system Python)
echo
echo "  [2/4] Creating virtual environment (.venv)..."
"$PYBIN" -m venv .venv
source .venv/bin/activate

# 3. Dependencies
echo
echo "  [3/4] Installing dependencies (this may take a few minutes)..."
python -m pip install --upgrade pip --quiet
if python -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 14) else 1)'; then
    # same Python as the tested environment: install the exact, tested versions
    python -m pip install -r requirements.lock || python -m pip install -r requirements.txt
else
    python -m pip install -r requirements.txt
fi

# 4. App bundle + icon
echo
echo "  [4/4] Creating NOVA.app in ~/Applications..."
python create_shortcut.py

cat <<'MSG'

  =====================================================
   NOVA installed successfully!
  =====================================================

   Launch it:   Spotlight (Cmd+Space -> NOVA)  or  ./start.command

   On first use macOS will ask for permissions. Grant them under
   System Settings -> Privacy & Security:

     Accessibility      global hotkey (Cmd+Shift+Space), typing, lock screen
     Screen Recording   "look at my screen" and screenshots
     Microphone         wake word / voice input
     Automation         controlling Spotify, Finder, System Events (prompted on first use)

   The permission is granted to whichever app launches NOVA
   (Terminal, NOVA.app or Python) - add that one if a feature stays silent.

MSG

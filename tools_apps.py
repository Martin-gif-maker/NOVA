# tools_apps.py — tools that open things: apps, web addresses, maps, a web search, a file in Finder / Explorer.
# Where apps are found and how they are started is the platform layer's business.
import os, re, shutil, subprocess, threading, webbrowser, urllib.parse
import platform_utils as plat
from toolbase import HOME, fail, user_path

_SCANNED_APPS: dict = {}          # installed apps: lower-case name -> what to open (see the platform layer)

def _scan_apps():
    """Index the installed apps so 'open <name>' can find them."""
    _SCANNED_APPS.update(plat.scan_apps(HOME))


threading.Thread(target=_scan_apps, daemon=True).start()

def _best_scanned_match(key: str):
    """Pick the best installed app for `key`: exact > starts-with > whole-word > substring."""
    best = None
    for name, path in _SCANNED_APPS.items():
        if name == key: rank = 0
        elif name.startswith(key): rank = 1
        elif re.search(r"\b" + re.escape(key) + r"\b", name): rank = 2
        elif key in name: rank = 3
        else: continue
        cand = (rank, len(name), name, path)
        if best is None or cand < best: best = cand
    return (best[2], best[3]) if best else (None, None)

def open_application(app_name: str) -> str:
    key = app_name.lower().strip()
    if not key: return "No app name given."
    if key == "browser":
        webbrowser.open("https://www.google.com"); return "Opened browser ✓"
    for cand in plat.APP_MAP.get(key, []):
        if plat.open_app(cand): return f"Opened {app_name} ✓"
    sn, sp = _best_scanned_match(key)
    if sp and plat.open_app(sp, True): return f"Opened {sn} ✓"
    if plat.open_app(app_name): return f"Opened {app_name} ✓"
    found = shutil.which(app_name)
    if found: subprocess.Popen([found]); return f"Opened {app_name} ✓"
    return fail(f"Could not find '{app_name}'.")

# ── TOOL: open_url ────────────────────────────────────────────────
def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://", "ftp://")): url = "https://" + url
    webbrowser.open(url); return f"Opened {url} ✓"

# ── TOOL: open_maps ───────────────────────────────────────────────
def open_maps(location: str) -> str:
    webbrowser.open(f"https://www.google.com/maps/search/{urllib.parse.quote(location)}")
    return f"Opened Google Maps for '{location}' ✓"

# ── TOOL: search_web ──────────────────────────────────────────────
def search_web(query: str) -> str:
    webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote(query)}")
    return f"Searching for '{query}' in browser ✓"

def open_in_explorer(path: str) -> str:
    """Show a file in Finder / Explorer (selected), or open a folder."""
    try:
        path = os.path.abspath(user_path(path))
        if not os.path.exists(path):
            return fail(f"Path not found: {path}")
        plat.reveal_path(path)
        return (f"Opened {plat.FILE_MANAGER} and selected: {path}" if os.path.isfile(path) else f"Opened folder: {path}") + " ✓"
    except Exception as e:
        return fail(f"Error: {e}")

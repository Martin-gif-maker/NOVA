# tools_apps.py — tools that open things: apps, web addresses, maps, a web search, a file in Finder.
import os, re, shutil, subprocess, threading, webbrowser, urllib.parse
from toolbase import HOME, fail

_SCANNED_APPS: dict = {}          # installed apps: lower-case name -> path of the .app

def _scan_mac_apps():
    """macOS: index installed .app bundles so 'open <name>' can find them."""
    found = {}
    dirs = ["/Applications", "/Applications/Utilities",
            "/System/Applications", "/System/Applications/Utilities",
            os.path.join(HOME, "Applications")]
    for d in dirs:
        try:
            for entry in os.listdir(d):
                if entry.endswith(".app"):
                    found[entry[:-4].lower()] = os.path.join(d, entry)
        except OSError:
            pass
    _SCANNED_APPS.update(found)


threading.Thread(target=_scan_mac_apps, daemon=True).start()

# ── TOOL: open_application ────────────────────────────────────────
# what people call an app -> the app names to try, in order, with `open -a`
MAC_APP_MAP = {
    "chrome": ["Google Chrome"], "google chrome": ["Google Chrome"],
    "firefox": ["Firefox"], "safari": ["Safari"],
    "edge": ["Microsoft Edge"], "microsoft edge": ["Microsoft Edge"],
    "notepad": ["TextEdit"], "textedit": ["TextEdit"], "wordpad": ["TextEdit"],
    "calculator": ["Calculator"], "calc": ["Calculator"],
    "explorer": ["Finder"], "file explorer": ["Finder"], "finder": ["Finder"], "files": ["Finder"],
    "task manager": ["Activity Monitor"], "activity monitor": ["Activity Monitor"],
    "settings": ["System Settings", "System Preferences"],
    "control panel": ["System Settings", "System Preferences"],
    "system settings": ["System Settings", "System Preferences"],
    "system preferences": ["System Settings", "System Preferences"],
    "cmd": ["Terminal"], "command prompt": ["Terminal"], "powershell": ["Terminal"], "terminal": ["Terminal"],
    "snipping tool": ["Screenshot"], "screenshot": ["Screenshot"],
    "paint": ["Preview"], "preview": ["Preview"],
    "word": ["Microsoft Word"], "excel": ["Microsoft Excel"],
    "powerpoint": ["Microsoft PowerPoint"], "outlook": ["Microsoft Outlook"],
    "spotify": ["Spotify"], "discord": ["Discord"], "steam": ["Steam"], "vlc": ["VLC"],
    "vscode": ["Visual Studio Code"], "vs code": ["Visual Studio Code"],
    "visual studio code": ["Visual Studio Code"],
    "telegram": ["Telegram"], "whatsapp": ["WhatsApp"], "zoom": ["zoom.us"],
    "obs": ["OBS"], "obs studio": ["OBS"],
    "code": ["Visual Studio Code"], "pycharm": ["PyCharm", "PyCharm CE"],
    "notes": ["Notes"], "messages": ["Messages"], "mail": ["Mail"], "calendar": ["Calendar"],
    "music": ["Music"], "photos": ["Photos"], "maps": ["Maps"], "app store": ["App Store"],
}

def _mac_open(target: str, is_path: bool = False) -> bool:
    args = ["open", target] if is_path else ["open", "-a", target]
    try:
        return subprocess.run(args, capture_output=True, timeout=8).returncode == 0
    except Exception:
        return False

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
    for cand in MAC_APP_MAP.get(key, []):
        if _mac_open(cand): return f"Opened {app_name} ✓"
    sn, sp = _best_scanned_match(key)
    if sp and _mac_open(sp, True): return f"Opened {sn} ✓"
    if _mac_open(app_name): return f"Opened {app_name} ✓"
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
    """Show a file in Finder (selected), or open a folder."""
    try:
        path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
        if not os.path.exists(path):
            return fail(f"Path not found: {path}")
        subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])
        return (f"Opened Finder and selected: {path}" if os.path.isfile(path) else f"Opened folder: {path}") + " ✓"
    except Exception as e:
        return fail(f"Error: {e}")

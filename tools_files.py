# tools_files.py — tools that work with files and run code: manage / read / write / search files, notes,
# shell commands and Python snippets. Every risky one is approved by the user first (see tools.py).
import os, sys, time, shutil, tempfile, threading, subprocess
import platform_utils as plat
import paths
import storage
import docs
from toolbase import HOME, fail, user_path

NOTES_FILE = paths.NOTES_FILE

# ── TOOL: manage_files ────────────────────────────────────────────
_PROTECTED_PATHS = plat.protected_paths(HOME)      # never deleted, whatever the tool is told

def _move_to_trash(path: str) -> None:
    """Move to the Trash / Recycle Bin instead of deleting for good."""
    plat.move_to_trash(path, HOME)

def manage_files(action: str, source: str, destination: str | None = None) -> str:
    source = user_path(source)
    name = os.path.basename(str(destination or "").rstrip("/"))          # for create_folder given as (parent, name)
    if destination: destination = user_path(destination)
    try:
        if action == "delete":
            if not os.path.lexists(source): return fail(f"Not found: {source}")
            if os.path.realpath(source) in _PROTECTED_PATHS:
                return fail(f"Refusing to delete a protected folder: {source}")
            _move_to_trash(source)
            return f"Moved to {plat.TRASH_NAME}: {source} ✓"
        elif action == "move":
            if not destination: return fail("Destination required.")
            shutil.move(source, destination); return f"Moved: {source} → {destination} ✓"
        elif action == "copy":
            if not destination: return fail("Destination required.")
            shutil.copy2(source, destination) if os.path.isfile(source) else shutil.copytree(source, destination)
            return f"Copied: {source} → {destination} ✓"
        elif action == "rename":
            if not destination: return fail("New name required.")
            os.rename(source, destination); return f"Renamed: {source} → {destination} ✓"
        elif action == "list":
            if not os.path.isdir(source): return fail(f"'{source}' is not a folder.")
            items = sorted(os.listdir(source))
            folders = [f"📁 {i}" for i in items if os.path.isdir(os.path.join(source, i))]
            files   = [f"📄 {i}" for i in items if os.path.isfile(os.path.join(source, i))]
            return f"Contents ({len(items)}):\n" + "\n".join(folders + files)[:2000]
        elif action == "create_folder":
            if name and os.path.normpath(destination or "") != os.path.normpath(source):
                source = os.path.join(source, name)          # "create Projects on the desktop" sent as (desktop, Projects)
            os.makedirs(source, exist_ok=True); return f"Created folder: {source} ✓"
        else: return fail(f"Unknown action: {action}")
    except PermissionError: return fail(f"Permission denied: {source}")
    except Exception as e: return fail(f"Error during {action}: {e}")

# ── TOOL: run_shell_command ───────────────────────────────────────
def _shell_env():
    return plat.shell_env()                # a GUI app starts with a bare PATH: the platform layer completes it

def run_shell_command(command: str) -> str:
    try:
        proc = subprocess.run(plat.SHELL_PREFIX + command, shell=True, capture_output=True, stdin=subprocess.DEVNULL,
                              text=True, timeout=30, encoding="utf-8", errors="replace",
                              env=_shell_env(), **plat.QUIET_PROCESS)
        out = (proc.stdout + proc.stderr).strip()
        return out[:2000] if out else "Command executed successfully ✓"
    except subprocess.TimeoutExpired: return fail("Command timed out.")
    except Exception as e: return fail(f"Error: {e}")

# ── TOOL: save_note ───────────────────────────────────────────────
_notes_lock = threading.Lock()

def save_note(text: str | None = None, title: str | None = None, content: str | None = None) -> str:
    body = text or " - ".join(x for x in (title, content) if x)
    if not body: return fail("Nothing to save.")
    try:
        with _notes_lock:
            old = storage.read_text(NOTES_FILE) if os.path.exists(NOTES_FILE) else ""
            storage.write_text(NOTES_FILE, old + f"[{time.strftime('%d.%m.%Y %H:%M')}] {body}\n")
        return "Note saved ✓"
    except Exception as e: return fail(f"Error: {e}")

# ── TOOL: read_notes ──────────────────────────────────────────────
def read_notes() -> str:
    try:
        if not os.path.exists(NOTES_FILE): return "No notes saved yet."
        content = storage.read_text(NOTES_FILE).strip()
        return content[-3000:] if content else "Notes are empty."
    except Exception as e: return fail(f"Error: {e}")

# ── TOOL: execute_python_code ─────────────────────────────────────
# Runs in a separate, isolated interpreter (-I) with a hard 10 s timeout, in a temp folder. This is NOT a security sandbox - the user must approve every run (see
# NEEDS_CONFIRM) because the code can do anything the user account can do.
def _python_exe() -> str | None:
    """A real Python interpreter (inside a packaged app sys.executable is NOVA itself)."""
    if not paths.IS_FROZEN:
        return sys.executable
    return plat.find_python()

def execute_python_code(code: str) -> str:
    exe = _python_exe()
    if not exe:
        return fail(plat.NO_PYTHON)
    try:
        with tempfile.TemporaryDirectory(prefix="nova_py_") as tmp:
            # No preexec_fn: running Python code in a forked child of this multi-threaded process (with macOS
            # frameworks loaded) can stall for a minute before the program even starts. Plain spawn is safe;
            # the wall-clock timeout and the approval prompt are the real limits.
            proc = subprocess.run([exe, "-I", *plat.PYTHON_FLAGS, "-c", code], capture_output=True, text=True,
                                  timeout=10, cwd=tmp, stdin=subprocess.DEVNULL,
                                  encoding="utf-8", errors="replace", **plat.QUIET_PROCESS)
        out = (proc.stdout + proc.stderr).strip()
        return out[:2000] if out else "Executed (no output)."
    except subprocess.TimeoutExpired:
        return fail("Error: Code timed out after 10 seconds and was stopped.")
    except Exception as e:
        return fail(f"Error: {e}")

# ── TOOL: write_file ─────────────────────────────────────────────
def write_file(path: str, content: str, mode: str = "w") -> str:
    """Write or append content to a file. mode: 'w' (overwrite) or 'a' (append)."""
    try:
        path = user_path(path)
        parent = os.path.dirname(path)
        if parent: os.makedirs(parent, exist_ok=True)
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
        action = "Appended to" if mode == "a" else "Wrote"
        return f"{action}: {path} ({len(content)} chars) ✓"
    except PermissionError:
        return fail(f"Permission denied: {path}")
    except Exception as e:
        return fail(f"Error writing file: {e}")

# ── TOOL: search_files ───────────────────────────────────────────
def search_files(query: str, folder: str | None = None, content_search: bool = False) -> str:
    """Search files by name. Set content_search=True to also search inside files."""
    base = user_path(folder or "~")
    results = []
    SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "AppData", ".idea",
                 "site-packages", "OneDrive", "Dropbox"} | plat.SEARCH_SKIP_DIRS
    SKIP_SUFFIX = plat.SEARCH_SKIP_SUFFIX
    deadline = time.time() + 20
    q = query.lower()
    timed_out = False
    try:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                       and not d.endswith(SKIP_SUFFIX)]
            for fname in files:
                if time.time() > deadline: timed_out = True; break
                fpath = os.path.join(root, fname)
                if q in fname.lower():
                    results.append(fpath)
                elif content_search:
                    try:
                        if os.path.getsize(fpath) < 2_000_000:
                            with open(fpath, encoding="utf-8", errors="ignore") as f:
                                if q in f.read().lower():
                                    results.append(fpath)
                    except OSError: pass                          # unreadable file: skip it
                if len(results) >= 30: break
            if len(results) >= 30 or timed_out: break
        note = "\n(stopped after 20 s - narrow the folder)" if timed_out else ""
        if not results:
            return f"No files found matching '{query}' in {base}{note}"
        return f"Found {len(results)} file(s):\n" + "\n".join(results[:30]) + note
    except Exception as e:
        return fail(f"Search error: {e}")

# ── TOOL: read_file ──────────────────────────────────────────────
def read_file(path: str, max_chars: int = 8000) -> str:
    """Read a local file and return its content (text files only)."""
    try:
        path = user_path(path)
        if not os.path.exists(path):
            return fail(f"File not found: {path}")
        size = os.path.getsize(path)
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf" or ext in (docs.ZIP_TYPES | docs.TEXTUTIL_TYPES | docs.IMAGE_TYPES | docs.SHEET_TYPES):   # PDF, Word, Excel, a photo …
            try:
                text = docs.extract_text(path)
            except docs.DocError as e:
                return fail(f"{os.path.basename(path)}: {e}")
            more = (f"\n[… shortened — the document has {len(text):,} characters, showing the first {max_chars:,}. "
                    f"For questions about a long document use add_document then search_documents.]") if len(text) > max_chars else ""
            return f"File: {path}\n{'─'*40}\n{text[:max_chars]}{more}"
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        truncated = size > max_chars
        note = f"\n[… truncated — file is {size:,} bytes, showing first {max_chars:,} chars]" if truncated else ""
        return f"File: {path}\n{'─'*40}\n{content}{note}"
    except PermissionError:
        return fail(f"Permission denied: {path}")
    except Exception as e:
        return fail(f"Error reading file: {e}")

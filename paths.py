# paths.py — where NOVA keeps its files, plus migration / export / wipe helpers.
#
# User data lives in the per-user application-data folder, never next to the code:
#   ~/Library/Application Support/NOVA      (logs: ~/Library/Logs/NOVA)
# (When the tests run on Linux, in CI, the usual $XDG_DATA_HOME/NOVA is used.)
# NOVA_DATA_DIR overrides the location (used by the tests).
import os, sys, shutil, zipfile, time, json
import logging

log = logging.getLogger("nova")

APP_NAME       = "NOVA"
__version__    = "6.6.0"
SCHEMA_VERSION = 2          # bump when the layout/format of the stored files changes


def _data_dir() -> str:
    override = os.environ.get("NOVA_DATA_DIR")
    if override:
        return override
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", APP_NAME)
    return os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(home, ".local", "share")), APP_NAME)


DATA_DIR = _data_dir()
LOG_DIR  = (os.path.join(os.path.expanduser("~"), "Library", "Logs", APP_NAME)
            if sys.platform == "darwin" and "NOVA_DATA_DIR" not in os.environ
            else os.path.join(DATA_DIR, "logs"))

CONFIG_FILE    = os.path.join(DATA_DIR, "config.json")
HISTORY_FILE   = os.path.join(DATA_DIR, "chat_history.json")
MEMORY_FILE    = os.path.join(DATA_DIR, "nova_memory.json")
REMINDERS_FILE = os.path.join(DATA_DIR, "nova_reminders.json")
NOTES_FILE     = os.path.join(DATA_DIR, "nova_notes.txt")
GAMES_FILE     = os.path.join(DATA_DIR, "nova_games.json")
KEY_FILE       = os.path.join(DATA_DIR, ".nova_key")
SESSIONS_DIR   = os.path.join(DATA_DIR, "sessions")
PLUGINS_DIR    = os.path.join(DATA_DIR, "plugins")
LOG_FILE       = os.path.join(LOG_DIR, "nova.log")
ACTIVITY_FILE  = os.path.join(DATA_DIR, "activity.log")      # every tool call NOVA made
OUTBOUND_FILE  = os.path.join(DATA_DIR, "outbound.log")      # where data was sent (destination + size, never content)
USAGE_FILE     = os.path.join(DATA_DIR, "usage.log")         # tokens used per request (provider, model, in, out)
CRASH_DIR      = os.path.join(DATA_DIR, "crashes")           # opt-in crash reports
DOCS_FILE      = os.path.join(DATA_DIR, "documents.json")    # the "ask about your documents" index
SCHEDULE_FILE  = os.path.join(DATA_DIR, "schedule.json")     # repeating reminders and scheduled requests

IS_FROZEN = bool(getattr(sys, "frozen", False))      # running from a packaged .app
CODE_DIR  = os.path.dirname(os.path.abspath(__file__))


def ensure_dirs() -> None:
    for d in (DATA_DIR, SESSIONS_DIR, PLUGINS_DIR, LOG_DIR):
        os.makedirs(d, mode=0o700, exist_ok=True)


# ── Migration from the old "files next to main.py" layout ──────────
_MARKER = os.path.join(DATA_DIR, ".migrated")


def migrate_legacy() -> list:
    """Copy data written by older NOVA versions into DATA_DIR (once). Returns what was copied."""
    ensure_dirs()
    if os.path.exists(_MARKER) or os.environ.get("NOVA_NO_MIGRATE"):
        return []
    home = os.path.expanduser("~")
    sources = [
        (os.path.join(CODE_DIR, "config.json"),         CONFIG_FILE),
        (os.path.join(CODE_DIR, "chat_history.json"),   HISTORY_FILE),
        (os.path.join(CODE_DIR, "nova_memory.json"),    MEMORY_FILE),
        (os.path.join(CODE_DIR, "nova_reminders.json"), REMINDERS_FILE),
        (os.path.join(CODE_DIR, ".nova_key"),           KEY_FILE),
        (os.path.join(home, "nova_notes.txt"),          NOTES_FILE),
        (os.path.join(home, "nova_games.json"),         GAMES_FILE),
    ]
    copied = []
    for src, dst in sources:
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst); copied.append(os.path.basename(dst))
    old_sessions = os.path.join(CODE_DIR, "sessions")
    if os.path.isdir(old_sessions):
        for f in os.listdir(old_sessions):
            dst = os.path.join(SESSIONS_DIR, f)
            if f.endswith(".json") and not os.path.exists(dst):
                shutil.copy2(os.path.join(old_sessions, f), dst); copied.append("sessions/" + f)
    old_plugins = os.path.join(CODE_DIR, "plugins")
    if os.path.isdir(old_plugins):
        for f in os.listdir(old_plugins):
            dst = os.path.join(PLUGINS_DIR, f)
            if f.endswith(".py") and not os.path.exists(dst):
                shutil.copy2(os.path.join(old_plugins, f), dst); copied.append("plugins/" + f)
    for f in copied:                                  # user-only permissions for everything we copied
        try: os.chmod(os.path.join(DATA_DIR, f), 0o600)
        except OSError: pass
    with open(_MARKER, "w") as fh:
        json.dump({"migrated": time.strftime("%Y-%m-%d %H:%M:%S"), "files": copied}, fh)
    return copied


# ── Settings schema upgrades ───────────────────────────────────────
def _to_v1(cfg: dict) -> None:
    cfg.pop("groq_api_key", None)                    # keys never live in config.json any more

def _to_v2(cfg: dict) -> None:
    for k, v in (("reasoning", "low"), ("ui_lang", "auto"), ("retention_days", 90), ("activity_days", 30),
                 ("confirm_uploads", True), ("save_history", True), ("voice_auto_stop", True)):
        cfg.setdefault(k, v)
    cfg.pop("lang", None)                            # replaced by ui_lang / stt_lang

_MIGRATIONS = {1: _to_v1, 2: _to_v2}


def upgrade_config(cfg: dict) -> dict:
    """Bring a settings dict from any older schema up to SCHEMA_VERSION (idempotent)."""
    for v in range(int(cfg.get("schema", 0)) + 1, SCHEMA_VERSION + 1):
        _MIGRATIONS[v](cfg)
    cfg["schema"] = SCHEMA_VERSION
    return cfg


def apply_retention(cfg: dict) -> int:
    """Delete saved chats / activity-log lines older than the configured number of days. Returns removed count."""
    removed = 0
    days = int(cfg.get("retention_days", 90) or 0)
    if days > 0 and os.path.isdir(SESSIONS_DIR):
        cutoff = time.time() - days * 86400
        for f in os.listdir(SESSIONS_DIR):
            p = os.path.join(SESSIONS_DIR, f)
            if f.endswith(".json") and os.path.getmtime(p) < cutoff:
                try: os.remove(p); removed += 1
                except OSError: pass
    adays = int(cfg.get("activity_days", 30) or 0)
    if adays > 0:
        import storage
        for log_file in (ACTIVITY_FILE, OUTBOUND_FILE):          # (usage.log is kept: it is tiny and you may want the year)
            try: removed += storage.prune_lines(log_file, adays)
            except Exception as e: log.info("old log entries were not removed: %s", e)
    return removed


# ── Export / wipe ──────────────────────────────────────────────────
def export_zip(dest: str) -> int:
    """Write all user data (except keys) to a zip - decrypted, so the export is readable anywhere.
    Returns the number of files."""
    import storage
    n = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(DATA_DIR):
            dirs[:] = [d for d in dirs if d != "models"]              # the downloadable voice model is not user data
            for f in files:
                if f.startswith(".nova_key") or f == ".migrated" or f.endswith((".tmp", ".part")) or ".locked-" in f:
                    continue
                full = os.path.join(root, f)
                try: data = storage.plain_bytes(full)
                except Exception: continue                             # unreadable (encrypted, key missing): left out
                z.writestr(os.path.relpath(full, DATA_DIR), data); n += 1
    return n


def wipe_all() -> None:
    """Delete every file NOVA stored (data folder, the Keychain keys, the data-encryption key)."""
    for entry in [f"{p}_api_key" for p in ("groq", "anthropic", "openai", "ollama", "custom", "brave")] + ["mcp_secrets"]:
        try:
            import keyring
            keyring.delete_password("NOVA_AI_Assistant", entry)
        except Exception as e: log.debug("no Keychain entry to delete: %s", e)
    try:
        import storage
        storage.forget_key()
    except Exception as e: log.warning("the encryption key could not be removed from the Keychain: %s", e)
    if sys.platform == "darwin":
        try: os.remove(os.path.expanduser("~/Library/LaunchAgents/com.nova.assistant.plist"))
        except OSError: pass
    shutil.rmtree(DATA_DIR, ignore_errors=True)


ensure_dirs()
migrate_legacy()

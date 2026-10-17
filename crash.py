# crash.py — opt-in crash reports.
#
# Off by default. When on (Settings → Privacy), an unexpected error writes a small text report into
# NOVA's data folder: the error, where in NOVA's code it happened, and the app / macOS / Python versions.
# It never contains chat text, file contents, keys, or your user name (home paths are shortened to "~").
# Nothing is sent anywhere unless a report address is configured AND you approve each report.
import os, sys, time, platform, traceback, threading, logging
import paths

log = logging.getLogger("nova")
_enabled = lambda: False
_installed = False
_fault_file = None
MAX_REPORTS = 20


def scrub(text: str) -> str:
    """Remove the things that identify the user from a traceback."""
    home = os.path.expanduser("~")
    user = os.path.basename(home)
    text = text.replace(home, "~")
    if user and len(user) > 2:
        text = text.replace(f"/Users/{user}", "~").replace(user, "<user>")
    return text


def build_report(etype, evalue, tb, where: str = "main thread") -> str:
    frames = "".join(traceback.format_exception(etype, evalue, tb, limit=40))
    try: mac = platform.mac_ver()[0]
    except Exception: mac = "?"
    head = (f"NOVA crash report\ntime: {time.strftime('%Y-%m-%d %H:%M:%S')}\nversion: {paths.__version__}"
            f"\npackaged: {paths.IS_FROZEN}\nmacOS: {mac} ({platform.machine()})\npython: {platform.python_version()}"
            f"\nwhere: {where}\n\n")
    return scrub(head + frames)


def write_report(etype, evalue, tb, where: str = "main thread"):
    """Save a report (only when the user opted in). Returns its path or None."""
    try:
        if not _enabled(): return None
        os.makedirs(paths.CRASH_DIR, mode=0o700, exist_ok=True)
        path = os.path.join(paths.CRASH_DIR, f"crash-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.txt")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(build_report(etype, evalue, tb, where))
        _trim()
        return path
    except Exception:
        return None


def _trim() -> None:
    files = reports()
    for old in files[:-MAX_REPORTS]:
        try: os.remove(old)
        except OSError: pass


def reports() -> list:
    """Saved report files, oldest first."""
    try:
        return sorted(os.path.join(paths.CRASH_DIR, f) for f in os.listdir(paths.CRASH_DIR)
                      if f.startswith("crash-") and f.endswith(".txt"))
    except OSError:
        return []


def unseen() -> list:
    """Reports the user has not been told about yet (and mark them as seen)."""
    marker = os.path.join(paths.CRASH_DIR, ".seen")
    try:
        with open(marker, encoding="utf-8") as f: seen = set(f.read().split())
    except OSError:
        seen = set()
    new = [p for p in reports() if os.path.basename(p) not in seen]
    if new:
        try:
            with open(marker, "w", encoding="utf-8") as f: f.write("\n".join(os.path.basename(p) for p in reports()))
        except OSError:
            pass
    return new


def install(enabled_fn) -> None:
    """Hook uncaught errors on every thread. `enabled_fn()` is read at crash time, so the setting applies live."""
    global _enabled, _installed
    _enabled = enabled_fn
    if _installed: return
    _installed = True
    prev_hook, prev_thook = sys.excepthook, threading.excepthook

    def _hook(etype, evalue, tb):
        if not issubclass(etype, KeyboardInterrupt):
            log.error("uncaught error", exc_info=(etype, evalue, tb))
            write_report(etype, evalue, tb)
        prev_hook(etype, evalue, tb)

    def _thook(args):
        if args.exc_type is not SystemExit:
            log.error("uncaught error in thread %s", getattr(args.thread, "name", "?"),
                      exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
            write_report(args.exc_type, args.exc_value, args.exc_traceback, f"thread {getattr(args.thread, 'name', '?')}")
        prev_thook(args)

    sys.excepthook, threading.excepthook = _hook, _thook


def enable_fault_log() -> None:
    """Hard crashes (segfaults) can't run Python code; faulthandler writes the stack of every thread instead."""
    global _fault_file
    try:
        if _fault_file is not None or not _enabled(): return
        import faulthandler
        os.makedirs(paths.CRASH_DIR, mode=0o700, exist_ok=True)
        # stays open for the life of the process: faulthandler writes into it when NOVA crashes hard
        _fault_file = open(os.path.join(paths.CRASH_DIR, "hard-crash.log"), "a", encoding="utf-8")  # noqa: SIM115
        faulthandler.enable(file=_fault_file, all_threads=True)
    except Exception as e: log.info("crash capture could not be switched on: %s", e)


def send(path: str, url: str):
    """POST one report to the configured https address. (ok, message). The caller asks the user first."""
    if not url.lower().startswith("https://"):
        return False, "Crash reports can only be sent to an https address."
    try:
        import requests, ledger
        with open(path, encoding="utf-8") as f: body = f.read()
        ledger.record(url, "crash report", len(body.encode("utf-8")))
        r = requests.post(url, data=body.encode("utf-8"), headers={"Content-Type": "text/plain; charset=utf-8"}, timeout=15)
        return (True, "Report sent ✓") if r.status_code < 300 else (False, f"The server answered {r.status_code}.")
    except Exception as e:
        return False, f"Could not send the report: {e}"

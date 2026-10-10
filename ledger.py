# ledger.py — a record of everything NOVA sends off this Mac: where, what kind, how much. Never the content.
# Shown in Settings → Privacy → "What NOVA sent today".
import json, time, logging, threading
from urllib.parse import urlparse
import paths
import storage

log = logging.getLogger("nova")
_lock = threading.Lock()
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")


def host_of(url: str) -> str:
    try:
        return (urlparse(url if "://" in url else "https://" + url).hostname or url or "?").lower()
    except Exception:
        return "?"


def is_local(dest: str) -> bool:
    return dest in LOCAL_HOSTS or dest.endswith(".local")


def record(dest: str, what: str, nbytes: int = 0, detail: str = "") -> None:
    """Note one outbound request. `dest` is a host name or URL; `what` a short kind such as 'chat'."""
    try:
        dest = host_of(dest) if ("/" in dest or ":" in dest) else dest.lower()
        line = json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "dest": dest, "what": what,
                           "bytes": int(nbytes or 0), "detail": str(detail)[:160]}, ensure_ascii=False)
        with _lock:
            storage.append_line(paths.OUTBOUND_FILE, line)
    except Exception as e:                       # bookkeeping must never break the request itself
        log.debug("ledger: %s", e)


def size_of(obj) -> int:
    """Rough size in bytes of a request payload."""
    try:
        return len(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))
    except Exception:
        return 0


def entries(days: int = 1) -> list:
    """Records from the last `days` calendar days (1 = today), oldest first."""
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - (max(1, days) - 1) * 86400))
    out = []
    for l in storage.read_lines(paths.OUTBOUND_FILE):
        try: e = json.loads(l)
        except ValueError: continue
        if isinstance(e, dict) and str(e.get("t", ""))[:10] >= cutoff: out.append(e)
    return out


def summary(items: list) -> list:
    """[(destination, kind, requests, bytes)] sorted by most data first."""
    agg = {}
    for e in items:
        k = (e.get("dest", "?"), e.get("what", "?"))
        n, b = agg.get(k, (0, 0)); agg[k] = (n + 1, b + int(e.get("bytes", 0) or 0))
    return sorted(((d, w, n, b) for (d, w), (n, b) in agg.items()), key=lambda r: (-r[3], r[0], r[1]))


def human(nbytes: int) -> str:
    if nbytes < 1024: return f"{nbytes} B"
    if nbytes < 1024 * 1024: return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes / 1024 / 1024:.1f} MB"

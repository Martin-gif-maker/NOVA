# storage.py — reading and writing NOVA's data files, optionally encrypted.
#
# With "Encrypt chats and memories on disk" on (Settings → Privacy), chats, saved sessions, memories, notes,
# reminders and the activity / outbound logs are stored with AES-256-GCM. The key is random, lives only in
# the macOS Keychain, and never touches the data folder — so a copy of the folder (backup, cloud sync,
# another user of the Mac) is unreadable without your login.
#
# Reading is format-agnostic: a file is decrypted if it carries the NOVA marker, otherwise read as plain
# text. That makes switching the setting safe at any moment, and `convert_all` re-writes what is on disk.
import os, json, time, base64, logging, threading
import paths

log = logging.getLogger("nova")

MAGIC       = b"NOVAENC1\n"            # whole-file marker
LINE_PREFIX = "NOVAENC1:"              # per-line marker (append-only logs)
_KR_SERVICE = "NOVA_AI_Assistant"
_KR_USER    = "data_encryption_key"
_state: dict = {"on": False, "key": None}         # encryption on for new writes; the key once read
_lock  = threading.RLock()


class StorageError(OSError):
    """Encrypted data that cannot be read or written (an OSError, so ordinary file-error handling covers it)."""


# ── key ────────────────────────────────────────────────────────────
def _keyring():
    import keyring
    return keyring


def available() -> bool:
    """Encryption needs the `cryptography` package and a working Keychain."""
    try:
        import importlib.util
        if importlib.util.find_spec("cryptography") is None: return False
        _keyring().get_password(_KR_SERVICE, _KR_USER)
        return True
    except Exception:
        return False


def _key(create: bool = False) -> bytes:
    with _lock:
        if _state["key"]: return _state["key"]
        try:
            stored = _keyring().get_password(_KR_SERVICE, _KR_USER)
        except Exception as e:
            raise StorageError(f"The Keychain is not available ({e}).")
        if not stored:
            if not create:
                raise StorageError("The encryption key is not in the Keychain (it was removed, or this data came from "
                                   "another Mac), so the encrypted files cannot be read.")
            stored = base64.urlsafe_b64encode(os.urandom(32)).decode()
            try:
                _keyring().set_password(_KR_SERVICE, _KR_USER, stored)
                if _keyring().get_password(_KR_SERVICE, _KR_USER) != stored: raise RuntimeError("the key did not persist")
            except Exception as e:
                raise StorageError(f"Could not store the encryption key in the Keychain ({e}).")
        _state["key"] = base64.urlsafe_b64decode(stored)
        return _state["key"]


def _aes(create: bool = False):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(_key(create))


def forget_key() -> None:
    """Delete the key (used by 'Delete all my data'). Encrypted files become permanently unreadable."""
    with _lock:
        _state["key"] = None; _state["on"] = False
        try: _keyring().delete_password(_KR_SERVICE, _KR_USER)
        except Exception as e: log.warning("the encryption key could not be removed from the Keychain: %s", e)


# ── mode ───────────────────────────────────────────────────────────
def configure(on: bool) -> bool:
    """Choose how *new* writes are stored. Returns the mode in effect (False if encryption can't work here)."""
    with _lock:
        if on:
            try: _aes(create=True)
            except Exception as e:
                log.warning("encryption unavailable, storing plain files: %s", e); on = False
        _state["on"] = bool(on)
        return _state["on"]


def enabled() -> bool:
    return _state["on"]


# ── bytes ──────────────────────────────────────────────────────────
def is_encrypted(blob: bytes) -> bool:
    return blob.startswith(MAGIC)


def encrypt_bytes(data: bytes) -> bytes:
    nonce = os.urandom(12)
    return MAGIC + nonce + _aes(create=True).encrypt(nonce, data, MAGIC)


def decrypt_bytes(blob: bytes) -> bytes:
    if not is_encrypted(blob): return blob
    body = blob[len(MAGIC):]
    try:
        return _aes().decrypt(body[:12], body[12:], MAGIC)
    except StorageError:
        raise
    except Exception:
        raise StorageError("This file is encrypted with a different key and cannot be read.")


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return decrypt_bytes(f.read())


def _set_aside_if_unreadable(path: str) -> None:
    """Never overwrite an encrypted file we cannot read: keep it next to the new one."""
    try:
        with open(path, "rb") as f: head = f.read(len(MAGIC) + 64)
    except OSError:
        return
    if not is_encrypted(head): return
    try:
        _key()
        with open(path, "rb") as f: decrypt_bytes(f.read())
    except StorageError:
        aside = f"{path}.locked-{time.strftime('%Y%m%d-%H%M%S')}"
        try: os.replace(path, aside); log.warning("kept unreadable encrypted file as %s", aside)
        except OSError: pass
    except OSError:
        pass


def write_bytes(path: str, data: bytes) -> None:
    """Atomic write, readable only by the current user; encrypted when the setting is on."""
    blob = encrypt_bytes(data) if _state["on"] else data
    if not _state["key"]: _set_aside_if_unreadable(path)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f: f.write(blob)
    os.replace(tmp, path)


# ── text / json ────────────────────────────────────────────────────
def read_text(path: str) -> str:
    return read_bytes(path).decode("utf-8", errors="replace")


def write_text(path: str, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def read_json(path: str):
    return json.loads(read_text(path))


def write_json(path: str, obj, **kw) -> None:
    kw.setdefault("ensure_ascii", False); kw.setdefault("indent", 2)
    write_text(path, json.dumps(obj, **kw))


# ── append-only logs (one record per line) ─────────────────────────
def _seal_line(line: str) -> str:
    nonce = os.urandom(12)
    return LINE_PREFIX + base64.b64encode(nonce + _aes(create=True).encrypt(nonce, line.encode("utf-8"), MAGIC)).decode()


def _open_line(line: str):
    if not line.startswith(LINE_PREFIX): return line
    try:
        raw = base64.b64decode(line[len(LINE_PREFIX):])
        return _aes().decrypt(raw[:12], raw[12:], MAGIC).decode("utf-8", errors="replace")
    except Exception:
        return None                                    # unreadable (key missing): skipped by readers


def append_line(path: str, line: str) -> None:
    out = _seal_line(line) if _state["on"] else line
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f: f.write(out + "\n")


def read_lines(path: str) -> list:
    """Every readable record of a log, decrypted."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f: raw = f.read().splitlines()
    except OSError:
        return []
    return [l for l in (_open_line(x) for x in raw if x.strip()) if l is not None]


def rewrite_lines(path: str, lines: list) -> None:
    body = "\n".join(_seal_line(l) if _state["on"] else l for l in lines)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(body + ("\n" if lines else ""))
    os.replace(tmp, path)


def prune_lines(path: str, days: int) -> int:
    """Drop records older than `days` (records are JSON with a "t": "YYYY-MM-DD …" stamp). Returns how many."""
    if days <= 0 or not os.path.exists(path): return 0
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    lines = read_lines(path)
    keep = [l for l in lines if not l.startswith('{"t": "') or l[7:17] >= cutoff]
    if len(keep) == len(lines): return 0
    rewrite_lines(path, keep)
    return len(lines) - len(keep)


# ── everything at once ─────────────────────────────────────────────
LINE_FILES = ("activity.log", "outbound.log", "usage.log")


def _blob_files() -> list:
    out = [paths.HISTORY_FILE, paths.MEMORY_FILE, paths.REMINDERS_FILE, paths.NOTES_FILE, paths.DOCS_FILE, paths.SCHEDULE_FILE]
    if os.path.isdir(paths.SESSIONS_DIR):
        out += [os.path.join(paths.SESSIONS_DIR, f) for f in sorted(os.listdir(paths.SESSIONS_DIR)) if f.endswith(".json")]
    return [p for p in out if os.path.isfile(p)]


def _line_files() -> list:
    return [p for p in (paths.ACTIVITY_FILE, paths.OUTBOUND_FILE, paths.USAGE_FILE) if os.path.isfile(p)]


def convert_all(on: bool) -> int:
    """Switch the setting and re-write every existing data file in the new format. Returns files converted.
    Raises StorageError (and changes nothing) if encryption cannot be turned on."""
    with _lock:
        if on:
            _aes(create=True)                           # fail before touching any file
        todo_blobs = [(p, read_bytes(p)) for p in _blob_files()]          # read everything first, in the old mode
        todo_lines = [(p, read_lines(p)) for p in _line_files()]
        _state["on"] = bool(on)
        for p, data in todo_blobs: write_bytes(p, data)
        for p, lines in todo_lines: rewrite_lines(p, lines)
        return len(todo_blobs) + len(todo_lines)


def plain_bytes(path: str) -> bytes:
    """A file's content as plain bytes whatever its on-disk format (used by 'Export my data')."""
    with open(path, "rb") as f: blob = f.read()
    if is_encrypted(blob): return decrypt_bytes(blob)
    if os.path.basename(path) in LINE_FILES and LINE_PREFIX.encode() in blob:
        return ("\n".join(read_lines(path)) + "\n").encode("utf-8")
    return blob

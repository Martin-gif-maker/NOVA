# sync.py — the same memories on all your computers (a Mac and a Windows PC, or two Macs).
#
# You choose a folder that every computer sees - OneDrive, Dropbox, Google Drive, iCloud Drive - and a passphrase.
# Each computer writes only its own file into "<folder>/NOVA Sync/", encrypted with a key made from the passphrase:
# the cloud service sees nothing readable, and no two computers ever write the same file (which would leave
# "conflicted copy" files behind). Each computer reads the others' files and merges:
#   * a memory saved on one computer appears on the others;
#   * a memory forgotten on one computer is forgotten on the others - unless it was saved again later.
# A memory is known by its text (the same fact saved on two computers is one memory). Forgetting is remembered as a
# "tombstone" (memory id -> when) for 90 days, so a computer that was off for a while still learns of it.
import datetime, hashlib, json, os, re, socket, sys, threading, uuid
import logging
import paths

log = logging.getLogger("nova")

FOLDER = "NOVA Sync"
MAGIC = b"NOVASYNC1"
TOMBSTONE_DAYS = 90
_SALT_FILE = "salt"                        # random, shared by every computer of this folder (not a secret)
_CHECK_FILE = "check"                      # a known text sealed with the key: tells a wrong passphrase from a file
                                           # the cloud service has not finished bringing
_lock = threading.Lock()                   # one sync at a time


class SyncError(Exception):
    """Something the person has to fix (wrong passphrase, the folder is gone …) - the message says what."""


# ── who is who ─────────────────────────────────────────────────────
def memory_id(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", str(text or "")).strip().lower().encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def saved_at(item: dict) -> str:
    """When a memory was saved: its "at", or for older memories the start of the day it was created."""
    return str(item.get("at") or ((item.get("created") or "1970-01-01") + "T00:00:00"))


# ── the key ────────────────────────────────────────────────────────
def _salt(folder: str, create: bool) -> bytes:
    path = os.path.join(folder, FOLDER, _SALT_FILE)
    try:
        with open(path, "rb") as f:
            salt = f.read()
        if len(salt) >= 16: return salt
    except OSError:
        pass
    if not create: raise SyncError("This folder has no NOVA sync data yet.")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    salt = os.urandom(16)
    with open(path, "wb") as f: f.write(salt)
    return salt


def make_key(passphrase: str, folder: str, create: bool = True) -> bytes:
    """The encryption key from the passphrase (scrypt: slow on purpose, so guessing passphrases is slow too)."""
    if len(passphrase or "") < 8: raise SyncError("The passphrase needs at least 8 characters.")
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=_salt(folder, create), length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode("utf-8"))


def _seal(key: bytes, obj: dict) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, json.dumps(obj, ensure_ascii=False).encode("utf-8"), MAGIC)


def _open(key: bytes, blob: bytes) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not blob.startswith(MAGIC): raise ValueError("not a NOVA sync file")
    body = blob[len(MAGIC):]
    try:
        return json.loads(AESGCM(key).decrypt(body[:12], body[12:], MAGIC).decode("utf-8"))
    except Exception:
        raise SyncError("The passphrase does not match the one used on your other computer.") from None


# ── merging (no files involved: easy to test) ──────────────────────
def merge(mine: list, before: set, tombstones: dict, others: list, now: str | None = None) -> tuple:
    """(memories, tombstones, ids now in sync).
    mine: this computer's memories · before: the ids after the last sync (what is gone since was forgotten here)
    tombstones: id -> when forgotten, as known here · others: [{"items": [...], "deleted": {...}}] from the others."""
    now = now or _now()
    current = {memory_id(it["text"]): it for it in mine if it.get("text")}
    tomb = dict(tombstones)
    for gone in set(before) - set(current):                       # forgotten here since the last sync
        tomb[gone] = max(tomb.get(gone, ""), now)
    for other in others:
        for mid, when in (other.get("deleted") or {}).items():
            tomb[mid] = max(tomb.get(mid, ""), str(when))
    best: dict = {}
    for it in [*current.values()] + [x for o in others for x in (o.get("items") or []) if isinstance(x, dict)]:
        if not it.get("text"): continue
        mid = memory_id(it["text"])
        had = best.get(mid)
        if had is None or (saved_at(it), bool(it.get("tags"))) > (saved_at(had), bool(had.get("tags"))):
            best[mid] = it
    kept = {mid: it for mid, it in best.items() if tomb.get(mid, "") < saved_at(it)}   # saved again after: it stays
    cutoff = (datetime.datetime.fromisoformat(now) - datetime.timedelta(days=TOMBSTONE_DAYS)).isoformat(timespec="seconds")
    tomb = {mid: when for mid, when in tomb.items() if when >= cutoff and mid not in kept}
    items = sorted(kept.values(), key=saved_at)
    return items, tomb, set(kept)


# ── this computer ──────────────────────────────────────────────────
def device(config: dict) -> tuple:
    """(id, name) of this computer; the id is made once and kept in the settings."""
    if not config.get("sync_device"): config["sync_device"] = uuid.uuid4().hex[:12]
    return config["sync_device"], (socket.gethostname().split(".")[0] or "computer")


def _state_path() -> str:
    return os.path.join(paths.DATA_DIR, "sync_state.json")


def _load_state() -> dict:
    try:
        with open(_state_path(), encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    tmp = _state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(state, f)
    os.replace(tmp, _state_path())


def _verify(key: bytes, folder: str) -> None:
    """SyncError if this key is not the one the folder's other computers use (the first one leaves the proof)."""
    path = os.path.join(folder, FOLDER, _CHECK_FILE)
    try:
        with open(path, "rb") as f: blob = f.read()
    except OSError:
        with open(path, "wb") as f: f.write(_seal(key, {"nova": "sync"}))
        return
    if _open(key, blob).get("nova") != "sync": raise SyncError("The passphrase does not match the one used on your other computer.")


def check_passphrase(folder: str, passphrase: str) -> int:
    """Raises SyncError if the passphrase is not the one the folder's other computers use. Returns how many of them
    have written there."""
    key = make_key(passphrase, folder, create=True)
    _verify(key, folder)
    return len(_files(folder, skip=""))


def _files(folder: str, skip: str) -> list:
    where = os.path.join(folder, FOLDER)
    out = []
    for name in sorted(os.listdir(where)) if os.path.isdir(where) else []:
        if name.endswith(".nova") and name != f"{skip}.nova":
            try:
                with open(os.path.join(where, name), "rb") as f: out.append(f.read())
            except OSError as e:
                log.info("sync: %s could not be read: %s", name, e)
    return out


def run(folder: str, passphrase: str, config: dict, read_items, write_items) -> dict:
    """One sync. read_items() / write_items(list) reach this computer's memories (the caller holds their lock).
    Returns {"memories": n, "computers": [names of the others], "added": n, "removed": n}."""
    if not folder or not os.path.isdir(folder):
        raise SyncError("The sync folder is not there any more - choose it again in Settings → Data.")
    with _lock:
        key = make_key(passphrase, folder, create=True)
        _verify(key, folder)
        me, name = device(config)
        others = []
        for blob in _files(folder, skip=me):
            try:
                others.append(_open(key, blob))
            except (ValueError, SyncError):                       # not ours, or still arriving from the cloud
                log.info("sync: a computer's file could not be read yet - next time")
        state = _load_state()
        mine = read_items()
        items, tomb, ids = merge(mine, set(state.get("ids") or []), state.get("tombstones") or {}, others)
        before = {memory_id(it["text"]) for it in mine}
        def same(xs): return [json.dumps(x, sort_keys=True, ensure_ascii=False) for x in sorted(xs, key=saved_at)]
        if same(items) != same(mine): write_items(items)
        _save_state({"ids": sorted(ids), "tombstones": tomb, "at": _now()})
        own = {"device": me, "name": name, "system": sys.platform, "at": _now(),
               "items": items, "deleted": tomb}
        target = os.path.join(folder, FOLDER, f"{me}.nova")
        tmp = target + ".tmp"
        with open(tmp, "wb") as f: f.write(_seal(key, own))
        os.replace(tmp, target)
        return {"memories": len(items), "computers": sorted({str(o.get("name") or "?") for o in others}),
                "added": len(ids - before), "removed": len(before - ids)}


def forget(config: dict) -> None:
    """Stop syncing on this computer (its file in the folder stays until removed by hand; the others keep theirs)."""
    for k in ("sync_folder",): config.pop(k, None)
    try: os.remove(_state_path())
    except OSError: pass


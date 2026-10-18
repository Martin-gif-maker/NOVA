# downloads.py — fetching a large file NOVA needs on request (a model), checked before it is used.
#
# The file arrives as `<name>.part`, its SHA-256 is computed on the way, and only a file with the pinned checksum is
# moved into place; a wrong, cut-off or cancelled download leaves nothing behind. Every download is noted in
# "What NOVA sent today" (ledger.py).
import os, hashlib
import ledger


class DownloadError(Exception):
    pass


def fetch(url: str, target: str, sha256: str, kind: str = "model download", progress=None, cancelled=None) -> str:
    """Download `url` to `target`. progress(bytes so far, bytes in all) while it runs; cancelled() -> True stops it.
    Returns `target`. Raises DownloadError (cancelled, checksum mismatch) or the network error."""
    import requests
    os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
    part = target + ".part"; h = hashlib.sha256(); done = 0
    ledger.record(url, kind)
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status(); total = int(r.headers.get("content-length", 0))
            with open(part, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    if cancelled and cancelled(): raise DownloadError("The download was cancelled.")
                    f.write(chunk); h.update(chunk); done += len(chunk)
                    if progress: progress(done, total)
        if h.hexdigest() != sha256:
            raise DownloadError("The downloaded model is corrupt or was tampered with (checksum mismatch).")
        os.replace(part, target)
        return target
    finally:
        if os.path.exists(part): os.remove(part)

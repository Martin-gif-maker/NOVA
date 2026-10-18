# updater.py — update check + verified download + installing in place.
# Where NOVA looks: its GitHub releases (the latest one's .dmg, with the SHA-256 GitHub publishes for it), or
# your own feed (config "update_feed"), a JSON file:  {"version": "6.1.0", "url": "https://…/NOVA-6.1.0.dmg",
#                                                      "sha256": "<hex digest of that file>", "notes": "…"}
import os, re, hashlib, platform, shutil, subprocess, sys
import paths

GITHUB_RELEASES = "https://api.github.com/repos/Martin-gif-maker/NOVA/releases/latest"
ATTEMPTS = 3                     # a stalled download is resumed until this many tries in a row bring nothing new


def parse_version(v: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", str(v))[:3]) or (0,)


def is_newer(candidate: str, current: str = paths.__version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def fetch_info(feed: str) -> dict:
    import requests
    if not feed.startswith("https://"):
        raise ValueError("The update feed must use https://")
    import ledger
    ledger.record(feed, "update check")
    r = requests.get(feed, timeout=10, headers={"Accept": "application/vnd.github+json"}); r.raise_for_status()
    info = r.json()
    if isinstance(info, dict) and "tag_name" in info and "assets" in info:
        return from_github_release(info)
    if not isinstance(info, dict) or "version" not in info:
        raise ValueError("Unexpected update feed format")
    return info


def from_github_release(release: dict, machine: str = "") -> dict:
    """The feed fields from a GitHub release: its tag, the disk image for this Mac's processor and the SHA-256
    GitHub computed for that file. A release without one for this Mac reports version "0" (nothing to install)."""
    machine = machine or platform.machine()                          # arm64 (Apple Silicon) or x86_64 (Intel)
    dmgs = [a for a in release.get("assets") or [] if str(a.get("name", "")).endswith(".dmg")]
    named = [a for a in dmgs if machine in a["name"]]
    if named: pick = named[0]
    elif machine == "arm64" and not any(k in a["name"] for a in dmgs for k in ("arm64", "x86_64")):
        pick = dmgs[0] if dmgs else None                             # unnamed images are built on Apple Silicon
    else: pick = None
    if pick is None:
        return {"version": "0", "notes": "No build for this Mac in the latest release."}
    digest = str(pick.get("digest") or "")
    if not digest.startswith("sha256:"):
        raise ValueError("The release does not say the download's SHA-256 - refusing to install")
    notes = str(release.get("body") or "")
    if notes.startswith("**Download"): notes = notes.split("\n\n", 1)[-1]          # how to install: not needed here
    return {"version": str(release["tag_name"]).lstrip("vV"), "url": pick["browser_download_url"],
            "sha256": digest.split(":", 1)[1], "notes": notes.replace("**", "")[:1500]}


def download(url: str, sha256: str, dest_dir: str | None = None, progress=None) -> str:
    """Download over https, verify the SHA-256 and return the file path. Raises on any mismatch."""
    import requests
    if not url.startswith("https://"): raise ValueError("Update downloads must use https://")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256 or ""): raise ValueError("The feed has no valid sha256 - refusing to install")
    dest_dir = dest_dir or os.path.join(os.path.expanduser("~"), "Downloads")
    name = re.sub(r"[^\w.\-]", "_", os.path.basename(url.split("?")[0]) or "NOVA-update.dmg")
    path = os.path.join(dest_dir, name); part = path + ".part"
    import ledger
    ledger.record(url, "update download")
    h = hashlib.sha256(); done = 0; total = 0; fruitless = 0
    try:
        while True:                                       # a stalled connection is picked up where it stopped
            before = done
            try:
                headers = {"Range": f"bytes={done}-"} if done else {}
                with requests.get(url, stream=True, timeout=30, headers=headers) as r:
                    r.raise_for_status()
                    if done and r.status_code != 206:          # the server cannot resume: start again
                        h = hashlib.sha256(); done = 0
                    if not total: total = done + int(r.headers.get("content-length", 0))
                    with open(part, "ab" if done else "wb") as f:
                        for chunk in r.iter_content(1 << 16):
                            f.write(chunk); h.update(chunk); done += len(chunk)
                            if progress and total: progress(done / total)
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                fruitless = 0 if done > before else fruitless + 1
                if fruitless >= ATTEMPTS:
                    raise ValueError(f"The download was interrupted ({type(e).__name__}). Try again later.")
        if h.hexdigest().lower() != sha256.lower():
            raise ValueError("Download is corrupt or was tampered with (checksum mismatch) - deleted")
        os.replace(part, path)
        return path
    finally:
        if os.path.exists(part): os.remove(part)          # never leave half a download behind


def reveal(path: str) -> None:
    """Open the downloaded installer (mounts a .dmg on macOS)."""
    cmd = ["open", path] if sys.platform == "darwin" else ["xdg-open", path]
    subprocess.Popen(cmd)


# ── installing in place ────────────────────────────────────────────
class UpdateError(Exception):
    pass


def app_bundle():
    """The NOVA.app this process runs from, or None when running from source."""
    if not getattr(sys, "frozen", False) or sys.platform != "darwin": return None
    path = os.path.realpath(sys.executable)
    while path and path != "/":
        if path.endswith(".app"): return path
        path = os.path.dirname(path)
    return None


def can_self_update(app: str | None = None):
    """(True, '') if the running app can replace itself, else (False, why)."""
    app = app or app_bundle()
    if not app: return False, "NOVA is running from source, not from an app."
    if "/AppTranslocation/" in app or app.startswith("/Volumes/"):
        return False, "NOVA is running straight from the disk image. Drag it to Applications first."
    if not os.access(os.path.dirname(app), os.W_OK) or not os.access(app, os.W_OK):
        return False, "NOVA cannot write to the folder it is installed in."
    return True, ""


def _run(cmd: list, timeout: int = 120) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UpdateError(f"{os.path.basename(cmd[0])} failed: {e}")
    if r.returncode != 0:
        raise UpdateError(f"{os.path.basename(cmd[0])} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return (r.stdout or "") + (r.stderr or "")


def team_id(app: str) -> str:
    """The signer's Team ID of an app ('' for unsigned / ad-hoc signed apps)."""
    try:
        r = subprocess.run(["/usr/bin/codesign", "-dv", "--verbose=2", app], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = re.search(r"^TeamIdentifier=(\S+)$", (r.stderr or "") + (r.stdout or ""), re.M)
    return "" if not m or m.group(1) == "not" else m.group(1)


def verify_app(new_app: str, current_app: str | None = None) -> None:
    """The new app must be intact and - if the installed one is signed by a developer - signed by the same one."""
    if not os.path.isdir(new_app) or not os.path.exists(os.path.join(new_app, "Contents", "Info.plist")):
        raise UpdateError("The download does not contain a NOVA app.")
    _run(["/usr/bin/codesign", "--verify", "--deep", "--strict", new_app])
    have = team_id(current_app) if current_app else ""
    if have and team_id(new_app) != have:
        raise UpdateError("The update is not signed by the same developer as the NOVA you have - it was not installed.")


def install_from_dmg(dmg: str, app: str) -> str:
    """Replace the installed app with the one inside a (checksum-verified) disk image. The old app is put back if
    anything goes wrong. Returns the path of the installed app."""
    import tempfile
    mount = tempfile.mkdtemp(prefix="nova_update_")
    staged = app + ".new"; old = app + ".old"
    _run(["/usr/bin/hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", mount, dmg], timeout=180)
    try:
        apps = [os.path.join(mount, n) for n in sorted(os.listdir(mount)) if n.endswith(".app")]
        if not apps: raise UpdateError("The disk image does not contain an app.")
        verify_app(apps[0], app if os.path.exists(app) else None)
        for leftover in (staged, old): shutil.rmtree(leftover, ignore_errors=True)
        _run(["/usr/bin/ditto", apps[0], staged], timeout=300)               # keeps signatures and attributes
        verify_app(staged)
        had_old = os.path.exists(app)
        if had_old: os.rename(app, old)
        try:
            os.rename(staged, app)
        except OSError as e:
            if had_old: os.rename(old, app)                                   # put the working app back
            raise UpdateError(f"Could not put the new app in place: {e}")
        shutil.rmtree(old, ignore_errors=True)
        return app
    finally:
        shutil.rmtree(staged, ignore_errors=True)
        try: subprocess.run(["/usr/bin/hdiutil", "detach", mount, "-quiet", "-force"], capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired): pass
        shutil.rmtree(mount, ignore_errors=True)


def relaunch(app: str) -> None:
    """Start the (new) app a moment after this process has gone."""
    subprocess.Popen(["/bin/sh", "-c", 'sleep 1.5; /usr/bin/open -n "$0"', app], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

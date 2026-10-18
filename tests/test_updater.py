"""Installing an update in place: a real disk image is built from a tiny fake app, mounted, verified and swapped in.
Everything happens inside pytest's temp folder; images are mounted with -nobrowse, so nothing shows up in Finder."""
import os, plistlib, subprocess, sys
import pytest
import updater

mac_only = pytest.mark.skipif(sys.platform != "darwin", reason="uses hdiutil / codesign / ditto")


def make_app(folder, version, sign=True):
    app = folder / "NOVA.app"; macos = app / "Contents" / "MacOS"; macos.mkdir(parents=True)
    (macos / "NOVA").write_text("#!/bin/sh\necho NOVA " + version + "\n"); (macos / "NOVA").chmod(0o755)
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleName": "NOVA", "CFBundleIdentifier": "com.nova.test", "CFBundleExecutable": "NOVA",
                       "CFBundleShortVersionString": version, "CFBundlePackageType": "APPL"}, f)
    (app / "Contents" / "version.txt").write_text(version)
    if sign: subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True, capture_output=True)
    return app


def make_dmg(tmp_path, version, sign=True, with_app=True):
    src = tmp_path / f"src-{version}"; src.mkdir()
    if with_app: make_app(src, version, sign)
    else: (src / "readme.txt").write_text("no app here")
    dmg = tmp_path / f"NOVA-{version}.dmg"
    subprocess.run(["hdiutil", "create", "-volname", "NOVA", "-srcfolder", str(src), "-ov", "-format", "UDZO", str(dmg)],
                   check=True, capture_output=True)
    return str(dmg)


def installed(tmp_path, version="6.0.0"):
    apps = tmp_path / "Applications"; apps.mkdir(exist_ok=True)
    return make_app(apps, version)


@mac_only
def test_update_replaces_the_installed_app(tmp_path):
    app = installed(tmp_path); (app / "Contents" / "old-only.txt").write_text("leftover from the old version")
    dmg = make_dmg(tmp_path, "6.1.0")
    assert updater.install_from_dmg(dmg, str(app)) == str(app)
    assert (app / "Contents" / "version.txt").read_text() == "6.1.0" and not (app / "Contents" / "old-only.txt").exists()
    assert subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)]).returncode == 0     # still intact after the copy
    assert subprocess.run([str(app / "Contents" / "MacOS" / "NOVA")], capture_output=True, text=True).stdout == "NOVA 6.1.0\n"
    assert sorted(os.listdir(tmp_path / "Applications")) == ["NOVA.app"]                                # no .new / .old left behind
    assert "nova_update_" not in subprocess.run(["hdiutil", "info"], capture_output=True, text=True).stdout   # the image was unmounted


@mac_only
def test_a_broken_or_wrong_download_leaves_the_old_app_alone(tmp_path):
    app = installed(tmp_path)
    unsigned = make_dmg(tmp_path, "6.2.0", sign=False)
    with pytest.raises(updater.UpdateError, match="codesign"): updater.install_from_dmg(unsigned, str(app))
    empty = make_dmg(tmp_path, "6.3.0", with_app=False)
    with pytest.raises(updater.UpdateError, match="does not contain an app"): updater.install_from_dmg(empty, str(app))
    junk = tmp_path / "junk.dmg"; junk.write_bytes(b"this is not a disk image")
    with pytest.raises(updater.UpdateError, match="hdiutil"): updater.install_from_dmg(str(junk), str(app))
    assert (app / "Contents" / "version.txt").read_text() == "6.0.0" and sorted(os.listdir(tmp_path / "Applications")) == ["NOVA.app"]


@mac_only
def test_update_from_another_developer_is_refused(tmp_path, monkeypatch):
    app = installed(tmp_path); dmg = make_dmg(tmp_path, "6.1.0")
    monkeypatch.setattr(updater, "team_id", lambda a: "AAAAAAAAAA" if "Applications" in a else "ZZZZZZZZZZ")
    with pytest.raises(updater.UpdateError, match="same developer"): updater.install_from_dmg(dmg, str(app))
    assert (app / "Contents" / "version.txt").read_text() == "6.0.0"
    monkeypatch.setattr(updater, "team_id", lambda a: "AAAAAAAAAA")                    # same developer: accepted
    updater.install_from_dmg(dmg, str(app))
    assert (app / "Contents" / "version.txt").read_text() == "6.1.0"


@mac_only
def test_if_the_swap_fails_the_working_app_is_put_back(tmp_path, monkeypatch):
    app = installed(tmp_path); dmg = make_dmg(tmp_path, "6.1.0")
    real = os.rename
    def flaky(src, dst):
        if str(src).endswith(".new"): raise OSError("disk full")
        return real(src, dst)
    monkeypatch.setattr(updater.os, "rename", flaky)
    with pytest.raises(updater.UpdateError, match="Could not put the new app in place"): updater.install_from_dmg(dmg, str(app))
    assert (app / "Contents" / "version.txt").read_text() == "6.0.0" and sorted(os.listdir(tmp_path / "Applications")) == ["NOVA.app"]


@mac_only
def test_ad_hoc_apps_have_no_team(tmp_path):
    assert updater.team_id(str(installed(tmp_path))) == "" and updater.team_id(str(tmp_path / "missing.app")) == ""


def test_when_nova_can_update_itself(tmp_path, monkeypatch):
    assert updater.app_bundle() is None and updater.can_self_update()[0] is False          # running from source in the tests
    assert updater.can_self_update("/private/var/folders/x/AppTranslocation/ABC/d/NOVA.app") == \
        (False, "NOVA is running straight from the disk image. Drag it to Applications first.")
    assert updater.can_self_update("/Volumes/NOVA/NOVA.app")[0] is False
    app = tmp_path / "NOVA.app"; app.mkdir()
    assert updater.can_self_update(str(app)) == (True, "")
    monkeypatch.setattr(updater.os, "access", lambda p, mode: False)
    assert "cannot write" in updater.can_self_update(str(app))[1]
    monkeypatch.undo()
    monkeypatch.setattr(sys, "frozen", True, raising=False); monkeypatch.setattr(sys, "executable", str(app / "Contents" / "MacOS" / "NOVA"))
    assert updater.app_bundle() == os.path.realpath(str(app))


def test_relaunch_starts_the_app_after_a_moment(monkeypatch):
    seen = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda cmd, **k: seen.append((cmd, k.get("start_new_session"))))
    updater.relaunch("/Applications/My Apps/NOVA.app")
    cmd, detached = seen[0]
    assert cmd[:2] == ["/bin/sh", "-c"] and "open -n" in cmd[2] and cmd[-1] == "/Applications/My Apps/NOVA.app" and detached is True
    assert "My Apps" not in cmd[2]                                             # the path is an argument, never part of the script


# ── the update source: NOVA's GitHub releases ──
def _release(*names, digest=True):
    return {"tag_name": "v6.4.0", "body": "**Download:** below.\n\n- **Faster** search.\n- Fixes.",
            "assets": [dict({"name": n, "browser_download_url": f"https://github.com/x/{n}"},
                            **({"digest": "sha256:" + "ab" * 32} if digest else {})) for n in names]}


def test_a_github_release_becomes_an_update():
    info = updater.from_github_release(_release("NOVA-6.4.0.dmg", "notes.txt"), machine="arm64")
    assert info == {"version": "6.4.0", "url": "https://github.com/x/NOVA-6.4.0.dmg", "sha256": "ab" * 32,
                    "notes": "- Faster search.\n- Fixes."}
    assert updater.is_newer(info["version"], "6.3.0")


def test_the_right_build_for_the_processor_is_picked():
    both = _release("NOVA-6.4.0-arm64.dmg", "NOVA-6.4.0-x86_64.dmg")
    assert updater.from_github_release(both, machine="x86_64")["url"].endswith("x86_64.dmg")
    assert updater.from_github_release(both, machine="arm64")["url"].endswith("arm64.dmg")
    only_apple = _release("NOVA-6.4.0.dmg")                      # an unnamed image is an Apple Silicon build
    assert updater.from_github_release(only_apple, machine="x86_64")["version"] == "0"     # nothing for an Intel Mac


def test_a_release_without_a_checksum_is_refused():
    with pytest.raises(ValueError, match="SHA-256"):
        updater.from_github_release(_release("NOVA-6.4.0.dmg", digest=False), machine="arm64")


class _Stream:
    """A fake download: serves `data`, optionally stalling after `stall_at` bytes, and honours Range requests."""
    def __init__(self, data, stall_at=None, ranges=True, always=False):
        self.data, self.stall_at, self.ranges, self.always, self.calls = data, stall_at, ranges, always, []

    def get(self, url, stream=True, timeout=30, headers=None):
        import requests
        start = int((headers or {}).get("Range", "bytes=0-")[6:-1] or 0) if self.ranges else 0
        self.calls.append(start); outer = self
        class R:
            status_code = 206 if start else 200
            headers = {"content-length": str(len(outer.data) - start)}
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def raise_for_status(s): pass
            def iter_content(s, n):
                pos = start
                while pos < len(outer.data):
                    if outer.stall_at is not None and pos >= outer.stall_at and (outer.always or len(outer.calls) == 1):
                        raise requests.ConnectionError("Read timed out.")
                    yield outer.data[pos:pos + 1000]; pos += 1000
        return R()


def test_a_stalled_download_is_resumed_and_verified(tmp_path, monkeypatch):
    import hashlib, requests
    data = bytes(range(256)) * 40
    fake = _Stream(data, stall_at=3000); monkeypatch.setattr(requests, "get", fake.get)
    path = updater.download("https://x/NOVA-6.4.0.dmg", hashlib.sha256(data).hexdigest(), dest_dir=str(tmp_path))
    assert open(path, "rb").read() == data and fake.calls == [0, 3000]          # picked up where it stopped


def test_a_failed_download_leaves_nothing_behind(tmp_path, monkeypatch):
    import hashlib, requests
    data = b"x" * 5000
    stuck = _Stream(data, stall_at=2000, always=True); monkeypatch.setattr(requests, "get", stuck.get)
    with pytest.raises(ValueError, match="interrupted"):
        updater.download("https://x/NOVA-6.4.0.dmg", hashlib.sha256(data).hexdigest(), dest_dir=str(tmp_path))
    assert stuck.calls == [0, 2000, 2000, 2000]                                # gave up after 3 tries that brought nothing
    monkeypatch.setattr(requests, "get", _Stream(data).get)
    with pytest.raises(ValueError, match="checksum"):
        updater.download("https://x/NOVA-6.4.0.dmg", "0" * 64, dest_dir=str(tmp_path))
    assert list(tmp_path.iterdir()) == []                                      # no .part file, no bad .dmg


def test_nova_from_source_leaves_updates_to_git_but_the_app_checks_daily(win, monkeypatch):
    import paths
    checked = []
    monkeypatch.setattr(win, "_check_updates", lambda quiet=False: checked.append(quiet))
    win.config.pop("update_feed", None); win.config["update_checked"] = ""
    monkeypatch.setattr(paths, "IS_FROZEN", False); win._auto_update_check()
    assert checked == []
    monkeypatch.setattr(paths, "IS_FROZEN", True); win._auto_update_check()
    assert checked == [True]
    win.config["update_checked"] = ""; win.config["auto_update"] = "off"; win._auto_update_check()
    assert checked == [True]                                                   # "do not check" is respected


def test_a_busy_disk_image_helper_is_waited_for(monkeypatch):
    import time
    tries = []
    def flaky(cmd, timeout=120):
        tries.append(cmd[1])
        if len(tries) < 3: raise updater.UpdateError("hdiutil failed: hdiutil: attach failed - Resource temporarily unavailable")
        return ""
    monkeypatch.setattr(updater, "_run", flaky); monkeypatch.setattr(time, "sleep", lambda s: None)
    updater._attach("x.dmg", "/tmp/m")
    assert tries == ["attach"] * 3
    def broken(cmd, timeout=120): raise updater.UpdateError("hdiutil failed: image not recognized")
    monkeypatch.setattr(updater, "_run", broken)
    with pytest.raises(updater.UpdateError, match="not recognized"): updater._attach("x.dmg", "/tmp/m")   # real errors at once


def test_nova_from_source_is_told_to_git_pull_not_to_download_an_app(win, monkeypatch):
    import paths
    monkeypatch.setattr(paths, "IS_FROZEN", False); win.config.pop("update_feed", None)
    monkeypatch.setattr(updater, "download", lambda *a, **k: pytest.fail("nothing to download for a source checkout"))
    win._offer_update({"version": "9.9.9", "url": "https://x/NOVA.dmg", "sha256": "0" * 64})
    from widgets import MessageBubble
    lay = win.chat_area._layout
    last = [w for w in (lay.itemAt(i).widget() for i in range(lay.count())) if isinstance(w, MessageBubble)][-1]
    assert "git pull" in last._label.text() and "9.9.9" in last._label.text()

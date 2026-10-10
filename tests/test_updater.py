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

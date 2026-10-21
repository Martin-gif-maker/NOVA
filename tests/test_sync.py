"""The same memories on two computers through a shared folder (sync.py): merging, forgetting, the passphrase."""
import os
import pytest
import memory as mem
import paths, sync


def _m(text, at, tags=""):
    return mem.make(text, at=at, tags=tags)


# ── merging ────────────────────────────────────────────────────────
def test_a_memory_saved_on_one_computer_appears_on_the_other():
    pc = {"items": [_m("likes tea", "2026-10-21T10:00:00")], "deleted": {}}
    items, tomb, ids = sync.merge([_m("lives in Sofia", "2026-10-20T09:00:00")], set(), {}, [pc])
    assert [i["text"] for i in items] == ["lives in Sofia", "likes tea"] and tomb == {} and len(ids) == 2


def test_the_same_fact_from_both_is_one_memory_with_the_most_detail():
    mine = [_m("Likes  tea", "2026-10-21T10:00:00")]
    pc = {"items": [_m("likes tea", "2026-10-21T10:00:00", tags="drink hot")], "deleted": {}}
    items, _, _ = sync.merge(mine, set(), {}, [pc])
    assert len(items) == 1 and items[0]["tags"] == "drink hot"


def test_forgetting_on_one_computer_forgets_on_the_other():
    tea = _m("likes tea", "2026-10-21T10:00:00")
    # this computer forgot it since the last sync: it is in `before` but not in `mine`
    items, tomb, _ = sync.merge([], {sync.memory_id("likes tea")}, {}, [{"items": [tea], "deleted": {}}],
                                now="2026-10-21T12:00:00")
    assert items == [] and tomb == {sync.memory_id("likes tea"): "2026-10-21T12:00:00"}
    # …and the other computer, reading that, forgets it too
    items, _, _ = sync.merge([tea], {sync.memory_id("likes tea")}, {}, [{"items": [], "deleted": tomb}])
    assert items == []


def test_saved_again_after_being_forgotten_it_stays():
    again = _m("likes tea", "2026-10-21T13:00:00")
    items, tomb, _ = sync.merge([again], set(), {}, [{"items": [], "deleted": {sync.memory_id("likes tea"): "2026-10-21T12:00:00"}}])
    assert [i["text"] for i in items] == ["likes tea"] and tomb == {}


def test_old_tombstones_are_dropped_after_90_days():
    old = {"abc": "2026-06-01T00:00:00", "def": "2026-10-01T00:00:00"}
    _, tomb, _ = sync.merge([], set(), old, [], now="2026-10-21T00:00:00")
    assert tomb == {"def": "2026-10-01T00:00:00"}


def test_memories_from_before_sync_count_from_their_day():
    old = mem.coerce({"text": "x", "created": "2026-01-05"})
    assert old["at"] == "" and sync.saved_at(old) == "2026-01-05T00:00:00"
    assert mem.make("y")["at"] >= "2026-"                                           # a new one: now


# ── two computers, one folder ──────────────────────────────────────
@pytest.fixture
def two(tmp_path, monkeypatch):
    shared = tmp_path / "OneDrive"; shared.mkdir()
    comps = {}
    for name in ("mac", "pc"):
        data = tmp_path / name; data.mkdir()
        comps[name] = {"data": str(data), "config": {}, "items": []}
    def run(name, passphrase="correct horse"):
        c = comps[name]
        monkeypatch.setattr(paths, "DATA_DIR", c["data"])
        monkeypatch.setattr(sync.socket, "gethostname", lambda: name.upper())
        return sync.run(str(shared), passphrase, c["config"], lambda: list(c["items"]),
                        lambda items: c.__setitem__("items", list(items)))
    return comps, run, shared


def test_two_computers_end_up_with_the_same_memories(two):
    comps, run, shared = two
    comps["mac"]["items"] = [_m("likes tea", "2026-10-21T10:00:00")]
    comps["pc"]["items"] = [_m("works at Acme", "2026-10-21T11:00:00")]
    assert run("mac")["computers"] == []
    out = run("pc")
    assert out["computers"] == ["MAC"] and out["added"] == 1
    run("mac")
    for c in comps.values():
        assert sorted(i["text"] for i in c["items"]) == ["likes tea", "works at Acme"]
    comps["pc"]["items"] = [i for i in comps["pc"]["items"] if i["text"] != "likes tea"]      # forgotten on the PC
    run("pc"); out = run("mac")
    assert [i["text"] for i in comps["mac"]["items"]] == ["works at Acme"] and out["removed"] == 1
    files = sorted(os.listdir(shared / sync.FOLDER))
    assert len([f for f in files if f.endswith(".nova")]) == 2                        # one file per computer
    for f in files:
        assert b"Acme" not in (shared / sync.FOLDER / f).read_bytes()                  # nothing readable in the cloud


def test_a_wrong_or_short_passphrase_is_refused(two):
    comps, run, shared = two
    run("mac")
    with pytest.raises(sync.SyncError, match="does not match"):
        run("pc", passphrase="wrong horse")
    with pytest.raises(sync.SyncError, match="8 characters"):
        sync.check_passphrase(str(shared), "short")
    assert sync.check_passphrase(str(shared), "correct horse") == 1


def test_a_missing_folder_says_so(two, tmp_path):
    with pytest.raises(sync.SyncError, match="not there"):
        sync.run(str(tmp_path / "gone"), "correct horse", {}, list, print)


# ── Settings → Data and the window ─────────────────────────────────
def test_settings_sets_up_sync_with_a_folder_and_a_passphrase(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QInputDialog
    import settings_dialog, themes, keystore
    monkeypatch.setattr(settings_dialog.plat, "autostart_enabled", lambda: False)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("correct horse", True))
    d = settings_dialog.SettingsDialog({}, themes.THEMES["nova"])
    assert d._sync_btn.text() == "Set up sync…" and "OneDrive" in d._sync_status.text()
    d._sync_clicked()
    assert "first computer" in d._sync_status.text() and d.get_values()["sync_folder"] == str(tmp_path)
    assert keystore._get_api_key("sync") == "correct horse"                     # kept in the Keychain, not the settings
    d._sync_clicked()
    assert d.get_values()["sync_folder"] == "" and "stops" in d._sync_status.text()
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("short", True))
    d._sync_clicked()
    assert d._sync_status.text().startswith("✗ ") and d.get_values()["sync_folder"] == ""


def test_the_window_syncs_in_the_background_and_says_what_went_wrong_once(win, tmp_path, monkeypatch):
    import time, keystore, tools
    shared = tmp_path / "Dropbox"; shared.mkdir()
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tools, "MEMORY_FILE", str(tmp_path / "memories.json"))
    mem.save(tools.MEMORY_FILE, [_m("likes tea", "2026-10-21T10:00:00")])
    said = []
    monkeypatch.setattr(win.chat_area, "add_message", lambda text, *a, **k: said.append(text))
    win.config["sync_folder"] = str(shared); keystore._save_api_key("correct horse", "sync")
    def wait():
        end = time.monotonic() + 5
        while getattr(win, "_sync_busy", False) and time.monotonic() < end: win._pump(30)
    win._sync_now(); wait()
    assert win.config["sync_status"].startswith("Last synced at") and "no other computer" in win.config["sync_status"]
    pc = tmp_path / "pc"; pc.mkdir()                                              # another computer joins the folder
    monkeypatch.setattr(paths, "DATA_DIR", str(pc))
    sync.run(str(shared), "correct horse", {}, lambda: [_m("works at Acme", "2026-10-21T11:00:00")], lambda items: None)
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
    win._sync_now(); wait()
    assert sorted(i["text"] for i in mem.load(tools.MEMORY_FILE)) == ["likes tea", "works at Acme"]
    assert " with " in win.config["sync_status"] and said == []
    keystore._save_api_key("wrong horse!", "sync")                                # the passphrase was changed here only
    win._sync_now(); wait(); win._sync_now(); wait()
    assert win.config["sync_status"].startswith("✗ ") and "does not match" in win.config["sync_status"]
    assert len(said) == 1 and said[0].startswith("Sync with your other computers: The passphrase does not match")


def test_a_file_still_arriving_from_the_cloud_is_skipped_not_called_a_wrong_passphrase(two):
    comps, run, shared = two
    comps["pc"]["items"] = [_m("works at Acme", "2026-10-21T11:00:00")]
    run("pc"); run("mac")
    pc_file = next(f for f in (shared / sync.FOLDER).glob("*.nova") if f.name != f"{comps['mac']['config']['sync_device']}.nova")
    pc_file.write_bytes(pc_file.read_bytes()[:40])                                  # half-downloaded
    out = run("mac")
    assert out["computers"] == [] and [i["text"] for i in comps["mac"]["items"]] == ["works at Acme"]

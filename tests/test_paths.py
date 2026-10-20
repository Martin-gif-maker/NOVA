import os, json, zipfile
import paths


def test_data_dir_is_isolated_in_tests():
    assert paths.DATA_DIR == os.environ["NOVA_DATA_DIR"]
    assert os.path.isdir(paths.SESSIONS_DIR)


def test_migrate_copies_legacy_files_once(monkeypatch, tmp_path):
    legacy = tmp_path / "old"; legacy.mkdir()
    (legacy / "config.json").write_text('{"theme": "soft"}')
    (legacy / "sessions").mkdir(); (legacy / "sessions" / "a.json").write_text("{}")
    home = tmp_path / "home"; home.mkdir(); (home / "nova_notes.txt").write_text("hi")
    data = tmp_path / "new"; data.mkdir()
    for name, rel in (("CONFIG_FILE", "config.json"), ("NOTES_FILE", "nova_notes.txt"),
                      ("HISTORY_FILE", "h.json"), ("MEMORY_FILE", "m.json"), ("REMINDERS_FILE", "r.json"),
                      ("GAMES_FILE", "g.json"), ("KEY_FILE", ".nova_key")):
        monkeypatch.setattr(paths, name, str(data / rel))
    monkeypatch.setattr(paths, "SESSIONS_DIR", str(data / "sessions")); os.makedirs(data / "sessions")
    monkeypatch.setattr(paths, "PLUGINS_DIR", str(data / "plugins")); os.makedirs(data / "plugins")
    monkeypatch.setattr(paths, "DATA_DIR", str(data)); monkeypatch.setattr(paths, "_MARKER", str(data / ".migrated"))
    monkeypatch.setattr(paths, "CODE_DIR", str(legacy))
    monkeypatch.setenv("HOME", str(home)); monkeypatch.setenv("USERPROFILE", str(home)); monkeypatch.delenv("NOVA_NO_MIGRATE")
    copied = paths.migrate_legacy()
    assert "config.json" in copied and "sessions/a.json" in copied and "nova_notes.txt" in copied
    assert json.loads((data / "config.json").read_text())["theme"] == "soft"
    assert paths.migrate_legacy() == []            # second run does nothing
    assert os.name == "nt" or oct(os.stat(data / "config.json").st_mode)[-3:] == "600"      # (Windows has no such file modes)


def test_export_excludes_api_key(monkeypatch, tmp_path):
    d = tmp_path / "d"; d.mkdir()
    (d / "config.json").write_text("{}"); (d / ".nova_key").write_text("secret")
    monkeypatch.setattr(paths, "DATA_DIR", str(d))
    out = tmp_path / "x.zip"
    assert paths.export_zip(str(out)) == 1
    assert zipfile.ZipFile(out).namelist() == ["config.json"]

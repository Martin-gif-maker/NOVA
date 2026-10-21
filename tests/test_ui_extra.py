"""Settings window, saved-chat browser, memory editor, key storage and read-aloud."""
import json, os, time, types, sys
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox
import keystore, tts, dialogs, themes, settings_dialog, tools


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _pump(app, ms=200):
    end = time.time() + ms / 1000
    while time.time() < end: app.processEvents(); time.sleep(0.01)


# ── API key storage ────────────────────────────────────────────────
class FakeRing:
    def __init__(self, fail=False): self.store, self.fail = {}, fail
    def get_password(self, s, u):
        if self.fail: raise RuntimeError("keychain locked")
        return self.store.get((s, u))
    def set_password(self, s, u, p):
        if self.fail: raise RuntimeError("keychain locked")
        self.store[(s, u)] = p


def test_key_goes_to_keychain_when_available(monkeypatch, tmp_path):
    ring = FakeRing(); monkeypatch.setattr(keystore, "_keyring", ring); monkeypatch.setattr(keystore, "_KEYRING_OK", True)
    monkeypatch.setattr(keystore, "_KEY_FILE", str(tmp_path / ".k"))
    assert keystore._save_api_key("gsk_abc") == "keyring" and keystore._get_api_key() == "gsk_abc"
    assert not (tmp_path / ".k").exists()


def test_key_falls_back_to_private_file_when_keychain_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(keystore, "_keyring", FakeRing(fail=True)); monkeypatch.setattr(keystore, "_KEYRING_OK", True)
    monkeypatch.setattr(keystore, "_KEY_FILE", str(tmp_path / ".k"))
    assert keystore._save_api_key("gsk_xyz") == "file"
    assert keystore._get_api_key() == "gsk_xyz"
    assert os.name == "nt" or oct(os.stat(tmp_path / ".k").st_mode)[-3:] == "600"


def test_missing_key_reads_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(keystore, "_KEYRING_OK", False); monkeypatch.setattr(keystore, "_KEY_FILE", str(tmp_path / "none"))
    assert keystore._get_api_key() == ""


# ── Read aloud ─────────────────────────────────────────────────────
def test_tts_cleaning_and_length():
    assert "(code block)" in tts._clean("before ```print(1)``` after")
    assert "*" not in tts._clean("**bold** and `code`") and "snake_case" in tts._clean("use snake_case here")
    long = ("This is a sentence. " * 60)
    out = tts._clean(long)
    assert len(out) <= 600 and out.endswith(".")


def test_tts_speaks_once_and_reports_state(monkeypatch):
    states, played = [], []
    fake_edge = types.SimpleNamespace(Communicate=lambda text, voice: types.SimpleNamespace(save=lambda path: _async_noop()))
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge)
    monkeypatch.setattr(tts.plat, "play_audio_file", lambda p: (played.append(p), time.sleep(0.2)))
    monkeypatch.setattr(tts.plat, "speak_native", lambda t: played.append("native:" + t))
    monkeypatch.setattr(tts, "STATE_CB", states.append); monkeypatch.setattr(tts, "ENABLED", True)
    tts.speak("Hello there"); time.sleep(0.8)
    assert len(played) == 1 and states[0] is True and states[-1] is False and tts.active() == 0


async def _async_noop(): return None


def test_tts_disabled_and_stop_supersede(monkeypatch):
    played = []
    monkeypatch.setattr(tts.plat, "play_audio_file", lambda p: played.append(p)); monkeypatch.setattr(tts.plat, "speak_native", lambda t: played.append(t))
    monkeypatch.setattr(tts, "ENABLED", False); tts.speak("silent"); time.sleep(0.3)
    assert played == []
    fake_edge = types.SimpleNamespace(Communicate=lambda text, voice: types.SimpleNamespace(save=lambda path: _slow()))
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge); monkeypatch.setattr(tts, "ENABLED", True)
    tts.speak("first"); time.sleep(0.05); tts.stop(); time.sleep(0.9)          # stopped while synthesising -> never plays
    assert played == []


async def _slow():
    import asyncio; await asyncio.sleep(0.4)


def test_tts_tells_the_window_what_it_is_about_to_play(monkeypatch):
    """Online voice: the mp3. The Mac's own voice: written to a file first, so there is something to compare with."""
    events = []
    fake_edge = types.SimpleNamespace(Communicate=lambda text, voice: types.SimpleNamespace(save=lambda path: _async_noop()))
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge)
    monkeypatch.setattr(tts.plat, "play_audio_file", lambda p: events.append(("play", p, os.path.exists(p))))
    monkeypatch.setattr(tts.plat, "speak_native", lambda t: events.append(("spoken directly", t)))
    monkeypatch.setattr(tts.plat, "synth_native", lambda text, path: (open(path, "wb").write(b"x" * 5000), events.append(("say to file", text)))[1] is None)
    monkeypatch.setattr(tts, "PLAY_CB", lambda path: events.append(("about to play", path)))
    monkeypatch.setattr(tts, "ENABLED", True); monkeypatch.setattr(tts, "ENGINE", "online")
    tts.speak("Hello there"); time.sleep(0.6)
    (kind, announced), (_, played, existed) = events
    assert kind == "about to play" and announced == played and announced.endswith(".mp3") and existed and not os.path.exists(played)
    events.clear(); monkeypatch.setattr(tts, "ENGINE", "system")
    tts.speak("Offline voice"); time.sleep(0.6)
    assert [e[0] for e in events] == ["say to file", "about to play", "play"] and events[1][1].endswith(".aiff") and events[1][1] == events[2][1]
    events.clear(); monkeypatch.setattr(tts.plat, "synth_native", lambda text, path: False)      # no file could be made
    tts.speak("Last resort"); time.sleep(0.6)
    assert events == [("about to play", None), ("spoken directly", "Last resort")]
    events.clear(); monkeypatch.setattr(tts, "PLAY_CB", lambda path: 1 / 0)                      # a failing listener never stops speech
    tts.speak("Still spoken"); time.sleep(0.6)
    assert events == [("spoken directly", "Still spoken")]


# ── Settings window ────────────────────────────────────────────────
def test_settings_dialog_roundtrip(app, monkeypatch):
    monkeypatch.setattr(settings_dialog.plat, "autostart_enabled", lambda: False)
    cfg = {"model_key": "fast", "theme": "ember", "font_size": 12, "tts": False, "tts_voice": "bg-BG-KalinaNeural",
           "wake_word": False, "wake_thresh": 900, "accent_color": "#aa0000", "reasoning": "medium",
           "suggest_followups": True, "retention_days": 30, "confirm_uploads": False, "save_history": False,
           "stt_lang": "bg", "ui_lang": "bg", "voice_auto_stop": False, "confirm_memory": True}
    d = settings_dialog.SettingsDialog(cfg, themes.THEMES["ember"])
    v = d.get_values()
    for k in ("model_key", "theme", "font_size", "tts", "tts_voice", "wake_word", "wake_thresh", "accent_color", "reasoning",
              "suggest_followups", "retention_days", "confirm_uploads", "save_history", "stt_lang", "ui_lang", "voice_auto_stop", "confirm_memory"):
        assert v[k] == cfg[k], k                                           # every stored setting survives open -> save
    d._theme_cb.setCurrentIndex(d._theme_cb.findData("auto")); d._retention_sb.setValue(0)
    v = d.get_values()
    assert v["theme"] == "auto" and v["retention_days"] == 0 and v["autostart"] is False


def test_settings_dialog_buttons_exist(app):
    d = settings_dialog.SettingsDialog({}, themes.THEMES["soft"])
    for name in ("_mem_view_btn", "_mem_clear_btn", "_data_export_btn", "_data_folder_btn", "_data_logs_btn", "_data_wipe_btn",
                 "_setup_btn", "_update_btn", "_activity_btn", "_reset_appr_btn", "_diag_btn"):
        assert getattr(d, name).text(), name


# ── Saved-chat browser ─────────────────────────────────────────────
def _make_sessions(tmp_path):
    for name, title, text in (("20261001_a.json", "Cooking", "pasta recipe"), ("20261002_b.json", "Taxes", "invoice due")):
        (tmp_path / name).write_text(json.dumps({"title": title, "created": "2026-10-07T10:00:00",
                                                 "messages": [{"role": "user", "content": text}]}))


def test_sessions_dialog_search_load_rename_delete(app, tmp_path, monkeypatch):
    _make_sessions(tmp_path)
    d = dialogs.SessionsDialog(themes.THEMES["soft"], str(tmp_path))
    assert d.listw.count() == 2
    d.search.setText("invoice"); assert d.listw.count() == 1 and "Taxes" in d.listw.item(0).text()
    d.search.setText("nothing-matches"); assert d.listw.count() == 1 and not d.load_btn.isEnabled()      # placeholder row
    d.search.setText(""); d.listw.setCurrentRow(0)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Tax Season", True)))
    d._rename()
    assert json.load(open(tmp_path / "20261002_b.json"))["title"] == "Tax Season"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    d.listw.setCurrentRow(0); d._delete()
    assert not (tmp_path / "20261002_b.json").exists() and d.listw.count() == 1
    d.listw.setCurrentRow(0); d._load()
    assert d.selected_path.endswith("20261001_a.json") and d.result() == QDialog.DialogCode.Accepted


# ── Memory editor ──────────────────────────────────────────────────
def test_memories_dialog_add_edit_delete(app, monkeypatch):
    import memory
    d = dialogs.MemoriesDialog(themes.THEMES["nova"], ["[01.01.2026] likes tea"])
    assert d.items[0]["created"] == "2026-01-01" and d.items[0]["category"] == "preference"      # old strings are understood
    answers = iter([memory.make("works at night", "work"), memory.make("likes green tea", "preference", created="2026-01-01")])
    monkeypatch.setattr(dialogs.MemoriesDialog, "_ask", lambda self, item=None: next(answers))
    d._add(); assert len(d.facts) == 2 and d.facts[1].endswith("works at night")
    d.listw.setCurrentRow(0); d._edit(); assert d.facts[0] == "[01.01.2026] likes green tea"
    d.filter.setCurrentIndex(d.filter.findData("work")); assert d.listw.count() == 1               # filter by category
    d.listw.setCurrentRow(0); d._delete(); assert d.facts == ["[01.01.2026] likes green tea"]     # deletes the filtered one


def test_memory_editor_form_builds_an_item(app):
    import memory
    e = dialogs.MemoryEditDialog(themes.THEMES["nova"])
    e.text.setPlainText("  dentist on Friday  "); e.cat.setCurrentIndex(e.cat.findData("task")); e.keep.setCurrentIndex(e.keep.findData(7))
    it = e.result_item()
    assert it["text"] == "dentist on Friday" and it["category"] == "task" and it["expires"] > memory.today()
    old = {"text": "x y", "category": "other", "created": "2026-01-01", "expires": "2099-01-01"}
    e2 = dialogs.MemoryEditDialog(themes.THEMES["nova"], old)
    assert e2.result_item()["expires"] == "2099-01-01" and e2.result_item()["created"] == "2026-01-01"   # untouched date is kept
    e2.text.setPlainText(""); assert e2.result_item() is None


def test_memory_wrappers_persist(data_dir):
    tools.replace_memories(["a fact", "", "another"])
    assert tools.list_memories() == ["a fact", "another"]


def test_upload_previews_build(app, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    assert dialogs.confirm_image_upload(None, themes.THEMES["soft"], Image.new("RGBA", (800, 400)), "Screenshot") is True
    assert dialogs.confirm_text_upload(None, themes.THEMES["soft"], "notes.txt", "x" * 3000) is True
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert dialogs.confirm_text_upload(None, themes.THEMES["soft"], "n.txt", "hi") is False


# ── Settings: tabs, providers, voice, approvals ────────────────────
def test_settings_tabs_and_new_values(app, monkeypatch):
    monkeypatch.setattr(settings_dialog.plat, "autostart_enabled", lambda: False)
    d = settings_dialog.SettingsDialog({}, themes.THEMES["nova"])
    assert [d.tabs.tabText(i) for i in range(d.tabs.count())] == ["General", "AI", "Voice", "Privacy", "Data"]
    v = d.get_values()
    assert (v["provider"], v["base_url"], v["models_by_provider"], v["stt_engine"], v["tts_engine"]) == ("groq", "", {}, "auto", "online")
    assert (v["encrypt_data"], v["crash_reports"], v["search_engine"], v["home_city"], v["always_allow"]) == (False, False, "ddg", "", [])


def test_settings_provider_switch_shows_that_providers_models(app, monkeypatch):
    monkeypatch.setattr(settings_dialog.plat, "autostart_enabled", lambda: False)
    cfg = {"provider": "groq", "models_by_provider": {"openai": {"fast": "gpt-x-mini"}}}
    d = settings_dialog.SettingsDialog(cfg, themes.THEMES["nova"], available_models=["openai/gpt-oss-120b", "llama-3.3-70b-versatile"])
    assert not d._url_edit.isEnabled() and d._key_btn.isEnabled()
    assert "llama-3.3-70b-versatile" in [d._slot_cbs["smart"].itemText(i) for i in range(d._slot_cbs["smart"].count())]
    d._provider_cb.setCurrentIndex(d._provider_cb.findData("ollama"))
    assert d._url_edit.isEnabled() and not d._key_btn.isEnabled() and d._slot_cbs["smart"].currentText() == "qwen3:4b-instruct"   # the default for Ollama
    d._url_edit.setText(" http://mac-mini.local:11434/v1 "); d._slot_cbs["smart"].setCurrentText("qwen2.5:14b")
    v = d.get_values()
    assert v["provider"] == "ollama" and v["base_url"] == "http://mac-mini.local:11434/v1"
    assert v["models_by_provider"] == {"openai": {"fast": "gpt-x-mini"}, "ollama": {"smart": "qwen2.5:14b"}}   # other providers' pins survive
    d._provider_cb.setCurrentIndex(d._provider_cb.findData("openai"))
    assert d._slot_cbs["fast"].currentText() == "gpt-x-mini" and d.get_values()["base_url"] == ""
    d._slot_cbs["fast"].setCurrentText("gpt-4o-mini")                                # back to the default = no pin stored
    assert "openai" not in d.get_values()["models_by_provider"]


def test_settings_connection_test_never_shows_the_key(app, monkeypatch):
    monkeypatch.setattr(settings_dialog.plat, "autostart_enabled", lambda: False)
    seen = []
    monkeypatch.setattr(settings_dialog.providers, "validate", lambda p, k, u="": (seen.append((p, k, u)), (True, "Groq works ✓"))[1])
    d = settings_dialog.SettingsDialog({}, themes.THEMES["nova"], key_lookup=lambda provider: "sk-very-secret")
    d._test_connection()
    for _ in range(40):
        _pump(app, 25)
        if d._conn_status.text().startswith("✓"): break
    assert seen == [("groq", "sk-very-secret", "")] and d._conn_status.text() == "✓ Groq works ✓" and d._test_btn.isEnabled()
    assert not any("sk-very-secret" in w.text() for w in d.findChildren(settings_dialog.QLabel))


def test_settings_lists_and_removes_stored_allowances(app, monkeypatch):
    monkeypatch.setattr(settings_dialog.plat, "autostart_enabled", lambda: False)
    cfg = {"always_allow": ["files:dir:/Users/me/Notes", "type:app:Notes", "control_system:sleep"]}
    d = settings_dialog.SettingsDialog(cfg, themes.THEMES["nova"])
    shown = [d._allow_list.item(i).text() for i in range(d._allow_list.count())]
    assert len(shown) == 3 and "/Users/me/Notes" in shown[0] and "Notes" in shown[1]
    d._allow_list.setCurrentRow(1); d._remove_allowance()
    assert d.get_values()["always_allow"] == ["files:dir:/Users/me/Notes", "control_system:sleep"]
    d._clear_allowances(); assert d.get_values()["always_allow"] == [] and d._allow_list.count() == 0
    assert cfg["always_allow"] == ["files:dir:/Users/me/Notes", "type:app:Notes", "control_system:sleep"]   # nothing changes until Save


def test_settings_offline_voice_model_controls(app, monkeypatch):
    import speech
    monkeypatch.setattr(settings_dialog.plat, "autostart_enabled", lambda: False)
    state = {"ready": False}
    monkeypatch.setattr(speech, "vosk_installed", lambda: True)
    monkeypatch.setattr(speech, "local_ready", lambda: state["ready"])
    def fake_download(progress=None):
        progress(0.5); state["ready"] = True
    monkeypatch.setattr(speech, "download_model", fake_download)
    monkeypatch.setattr(speech, "remove_model", lambda: state.update(ready=False))
    d = settings_dialog.SettingsDialog({}, themes.THEMES["nova"])
    assert d._voice_dl_btn.text().startswith("Download") and "sent to the AI provider" in d._wake_hint.text()
    d._toggle_voice_model()
    for _ in range(40):
        _pump(app, 25)
        if d._voice_dl_btn.text() == "Remove": break
    assert d._voice_dl_btn.text() == "Remove" and "Installed" in d._voice_status.text() and "On-device" in d._wake_hint.text()
    d._toggle_voice_model(); assert d._voice_dl_btn.text().startswith("Download")
    monkeypatch.setattr(speech, "download_model", lambda progress=None: (_ for _ in ()).throw(speech.SpeechError("checksum mismatch")))
    d._toggle_voice_model()
    for _ in range(40):
        _pump(app, 25)
        if d._voice_status.text().startswith("✗"): break
    assert "checksum mismatch" in d._voice_status.text() and d._voice_dl_btn.isEnabled()


def test_sent_and_activity_viewers(app, monkeypatch, tmp_path):
    import paths, ledger, storage
    monkeypatch.setattr(paths, "OUTBOUND_FILE", str(tmp_path / "o.log")); monkeypatch.setattr(paths, "ACTIVITY_FILE", str(tmp_path / "a.log"))
    d = dialogs.SentDialog(themes.THEMES["nova"])
    assert d.table.rowCount() == 0 and d.total.text() == "Nothing was sent."
    ledger.record("api.groq.com", "chat", 2048, "model m, 3 messages"); ledger.record("api.groq.com", "chat", 1024)
    ledger.record("localhost", "chat", 99)
    d._fill()
    assert d.table.rowCount() == 2 and d.table.item(0, 0).text() == "api.groq.com" and d.table.item(0, 2).text() == "2"
    assert d.table.item(0, 3).text() == "3.0 KB" and "this Mac" in d.table.item(1, 0).text()
    assert d.total.text().startswith("2 requests left this Mac") and "model m, 3 messages" in d.details.toPlainText()
    tools._log_activity("write_file", {"path": "/tmp/a.txt"}, "approved", "Written ✓")
    text = dialogs.format_activity(storage.read_lines(paths.ACTIVITY_FILE))
    assert "write_file" in text and "[approved]" in text and "path=/tmp/a.txt" in text and "→ Written ✓" in text
    assert dialogs.TextViewDialog(themes.THEMES["nova"], "Activity log", text).view.toPlainText() == text


def test_settings_does_not_pin_a_model_nova_swapped_in_itself(app, monkeypatch):
    import models
    monkeypatch.setattr(settings_dialog.plat, "autostart_enabled", lambda: False)
    monkeypatch.setitem(models.MODELS, "smart", ("llama-3.3-70b-versatile", "120B"))      # as after a retired model was replaced
    d = settings_dialog.SettingsDialog({"provider": "groq"}, themes.THEMES["nova"])
    assert d._slot_cbs["smart"].currentText() == "llama-3.3-70b-versatile"
    assert d.get_values()["models_by_provider"] == {}                                    # just pressing Save pins nothing
    d._slot_cbs["fast"].setCurrentText("llama-3.1-8b-instant")
    assert d.get_values()["models_by_provider"] == {"groq": {"fast": "llama-3.1-8b-instant"}}

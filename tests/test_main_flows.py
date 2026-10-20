"""End-to-end flows of the main window (fake AI, temp folders; nothing touches the real system)."""
import json, os, sys, time, types, zipfile
import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import QUrl, QMimeData
from PySide6.QtWidgets import QDialog, QMessageBox, QFileDialog
from gui_support import FakeCompletions, _pump, _send, _wait_idle
import main, tools, paths, tts, updater, win_account
import win_data
import win_approvals
import win_chat
import uistate
import schemas
import models
import i18n


_REAL_ONBOARDING = main.AssistantWindow._run_onboarding          # the `win` fixture replaces it with a stub per test


class FakeBox:
    """Stand-in for the approval / plugin message box; `choice` names the button to 'click'."""
    choice = "deny"
    Icon, ButtonRole, StandardButton = QMessageBox.Icon, QMessageBox.ButtonRole, QMessageBox.StandardButton
    instances = []
    def __init__(self, *a, **k): self.buttons = {}; self.clicked = None; FakeBox.instances.append(self)
    def addButton(self, text, role): b = object(); self.buttons[text] = b; return b
    def exec(self): self.clicked = next((b for t, b in self.buttons.items() if self.choice in t.lower()), None)
    def clickedButton(self): return self.clicked
    def __getattr__(self, name): return lambda *a, **k: None
    question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    information = staticmethod(lambda *a, **k: None)


@pytest.fixture
def fakebox(monkeypatch):
    FakeBox.instances.clear()
    for mod in (win_approvals, win_data, win_chat):          # every module that shows a message box
        monkeypatch.setattr(mod, "QMessageBox", FakeBox)
    return FakeBox


# ── approvals ──────────────────────────────────────────────────────
def test_approval_dialog_allow_once_always_and_deny(win, fakebox, monkeypatch):
    monkeypatch.setattr(win, "_save_config", lambda: None)
    fakebox.choice = "deny";  assert win._ask_user("do a thing", "k1") is False
    fakebox.choice = "once";  assert win._ask_user("do a thing", "k1") is True and "k1" not in win.config.get("always_allow", [])
    fakebox.choice = "always"; assert win._ask_user("do a thing", "k1") is True and "k1" in win.config["always_allow"]
    fakebox.instances.clear()
    fakebox.choice = "deny"; assert win._ask_user("do a thing", "k1") is True and not fakebox.instances      # remembered: no dialog
    assert win._ask_user("risky", None) is False                                                             # no key => no 'always' offered
    assert "Always allow this kind" not in fakebox.instances[-1].buttons


def test_always_allow_can_be_reset(win):
    win.config["always_allow"] = ["x"]; win._reset_approvals()
    assert win.config["always_allow"] == []


# ── settings ───────────────────────────────────────────────────────
def test_settings_flow_applies_everything(win, monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "ENABLED", True); monkeypatch.setattr(tts, "VOICE", "en-US-AriaNeural")
    calls = []
    monkeypatch.setattr(main.plat, "set_autostart", lambda on, script, hidden=True: (calls.append(on), True)[1])      # never touch the real LaunchAgent
    def fake_exec(self):
        self._theme_cb.setCurrentIndex(self._theme_cb.findData("matrix")); self._model_cb.setCurrentIndex(1)
        self._tts_chk.setChecked(False); self._font_sb.setValue(14); self._reason_cb.setCurrentIndex(self._reason_cb.findData("high"))
        self._retention_sb.setValue(7); self._followup_chk.setChecked(True); self._auto_chk.setChecked(True)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(win_account.SettingsDialog, "exec", fake_exec)
    win._show_settings()
    assert win._theme_key == "matrix" and win._model_key == "fast" and tts.ENABLED is False
    assert win.config["reasoning"] == "high" and win.config["retention_days"] == 7 and win.config["suggest_followups"] is True
    assert uistate.FONT_SIZE == 14 and win._model_lbl.text() == models.MODELS["fast"][1]
    assert calls == [True]
    saved = json.load(open(paths.CONFIG_FILE))
    assert saved["theme"] == "matrix" and saved["font_size"] == 14 and "groq_api_key" not in saved


def test_settings_cancel_changes_nothing(win, monkeypatch):
    before = dict(win.config)
    monkeypatch.setattr(win_account.SettingsDialog, "exec", lambda self: (self._font_sb.setValue(20), QDialog.DialogCode.Rejected)[1])
    win._show_settings()
    assert win.config.get("font_size") == before.get("font_size")


# ── first run ──────────────────────────────────────────────────────
def test_onboarding_choices_are_applied_and_key_stored(win, monkeypatch):
    stored = []
    class FakeWizard:
        def __init__(self, theme, existing_key=False, parent=None, **kw): self.ek = existing_key
        def exec(self): return QDialog.DialogCode.Accepted
        def choices(self): return {"consent": True, "wake_word": True, "tts_auto": True, "api_key": "gsk_new"}
    monkeypatch.setattr(win_account, "OnboardingDialog", FakeWizard)
    monkeypatch.setattr(win_account, "_save_api_key", lambda k, p=None: stored.append(k) or "keyring")
    key = _REAL_ONBOARDING(win, "")
    assert key == "gsk_new" and stored == ["gsk_new"]
    assert win.config["consent"] and win.config["onboarded"] and win.config["wake_word"] and win.config["tts_auto"]


def test_onboarding_dismissed_keeps_existing_key_but_no_consent(win, monkeypatch):
    class Closed:
        def __init__(self, *a, **k): pass
        def exec(self): return QDialog.DialogCode.Rejected
    monkeypatch.setattr(win_account, "OnboardingDialog", Closed)
    win.config.pop("consent", None)
    assert _REAL_ONBOARDING(win, "gsk_old") == "gsk_old" and not win.config.get("consent")


# ── data & privacy ─────────────────────────────────────────────────
def test_export_data_zip_has_no_key(win, monkeypatch, tmp_path):
    data = tmp_path / "data"; data.mkdir(); (data / "config.json").write_text("{}"); (data / ".nova_key").write_text("secret")
    monkeypatch.setattr(paths, "DATA_DIR", str(data))
    out = tmp_path / "export.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    win._export_data()
    assert zipfile.ZipFile(out).namelist() == ["config.json"]


def test_delete_all_data_wipes_and_stops_writing(win, fakebox, monkeypatch):
    wiped, quit_ = [], []
    monkeypatch.setattr(paths, "wipe_all", lambda: wiped.append(1)); monkeypatch.setattr(win, "_quit_app", lambda: quit_.append(1))
    win._wipe_data()
    assert wiped == [1] and quit_ == [1] and win._wiped
    if os.path.exists(paths.CONFIG_FILE): os.remove(paths.CONFIG_FILE)
    win._save_config(); win._save_history(); win._save_session()
    assert not os.path.exists(paths.CONFIG_FILE)


def test_delete_all_data_can_be_declined(win, monkeypatch):
    class No(FakeBox): warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    monkeypatch.setattr(win_data, "QMessageBox", No); monkeypatch.setattr(paths, "wipe_all", lambda: pytest.fail("must not wipe"))
    win._wipe_data(); assert not win._wiped


def test_export_chat_writes_to_desktop(win, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path)); (tmp_path / "Desktop").mkdir()
    win.messages += [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    win._export_chat()
    f = next((tmp_path / "Desktop").iterdir()).read_text()
    assert "[You]" in f and "hi" in f and "[NOVA]" in f and "hello" in f


# ── saved chats ────────────────────────────────────────────────────
def test_new_chat_saves_then_session_can_be_loaded(win, fakebox, monkeypatch):
    FakeCompletions.script = [["answer one"]]
    _send(win, "first question"); _wait_idle(win)
    win._new_chat()
    assert len(win.messages) == 1
    files = os.listdir(paths.SESSIONS_DIR); assert len(files) == 1
    class Pick:                                       # the chat browser choosing that file
        def __init__(self, *a, **k): self.selected_path = os.path.join(paths.SESSIONS_DIR, files[0])
        def exec(self): return QDialog.DialogCode.Accepted
    monkeypatch.setattr(win_data, "SessionsDialog", Pick)
    win._show_sessions_menu()
    assert [m["content"] for m in win.messages[1:]] == ["first question", "answer one"]


def test_loading_a_session_saves_the_current_chat_first(win, fakebox, tmp_path):
    FakeCompletions.script = [["a1"], ["a2"]]
    _send(win, "chat A"); _wait_idle(win); win._new_chat()
    _send(win, "chat B"); _wait_idle(win)
    first = os.path.join(paths.SESSIONS_DIR, os.listdir(paths.SESSIONS_DIR)[0])
    win._load_session(first)                                         # B is still unsaved -> must be kept
    assert len(os.listdir(paths.SESSIONS_DIR)) == 2
    assert win.messages[1]["content"] == "chat A"


def test_memory_editor_updates_prompt(win, monkeypatch, data_dir):
    class Dlg:
        def __init__(self, theme, facts, parent=None): self.facts = ["[01.01.2026] drinks tea"]
        def exec(self): return QDialog.DialogCode.Accepted
    monkeypatch.setattr(win_data, "MemoriesDialog", Dlg)
    win._show_memories_dialog()
    assert "drinks tea" in win.messages[0]["content"] and tools.list_memories() == ["[01.01.2026] drinks tea"]


# ── shortcuts, files, drops ────────────────────────────────────────
def test_shortcut_opens_apps(win, monkeypatch):
    opened = []
    monkeypatch.setattr(tools, "execute_tool", lambda name, args: opened.append((name, args["app_name"])) or "ok")
    win.config["shortcuts"] = {"work": ["chrome", "notes"], "broken": "chrome"}
    assert win._check_shortcut("Work") is True and opened == [("open_application", "chrome"), ("open_application", "notes")]
    assert win._check_shortcut("broken") is True                       # wrong format -> explained, not silent
    assert win._check_shortcut("nothing") is False


def _drop(win, *paths_):
    md = QMimeData(); md.setUrls([QUrl.fromLocalFile(p) for p in paths_])
    ev = types.SimpleNamespace(mimeData=lambda: md)
    win.dropEvent(ev)


def _drop_and_wait(win, path, until=None):
    """Drop a file; reading happens in the background, so wait for its result to arrive."""
    before = win.chat_area._layout.count()
    _drop(win, path)
    for _ in range(100):
        win._pump(30)
        if (until() if until else win.chat_area._layout.count() >= before + 2): break


def test_drop_text_file_asks_then_sends(win, monkeypatch, tmp_path):
    import win_docs
    f = tmp_path / "notes.txt"; f.write_text("meeting at 5pm")
    started = []; monkeypatch.setattr(win, "_start_ai", lambda *a, **k: started.append(1))
    asked = []
    monkeypatch.setattr(win_docs, "confirm_text_upload", lambda *a: asked.append(1) and False); _drop_and_wait(win, str(f), lambda: asked)
    assert asked and not started and len(win.messages) == 1            # declined preview -> nothing sent
    monkeypatch.setattr(win_docs, "confirm_text_upload", lambda *a: True); _drop_and_wait(win, str(f), lambda: started)
    assert started and "meeting at 5pm" in win.messages[-1]["content"]


def test_drop_binary_is_refused_and_a_long_file_is_indexed_not_sent(win, monkeypatch, tmp_path):
    import win_docs, docs
    b = tmp_path / "data.bin"; b.write_bytes(b"\x00\x01\x02" * 100)
    big = tmp_path / "big.txt"; big.write_text("The quarterly revenue grew by twelve percent. " * 3000)
    monkeypatch.setattr(win, "_start_ai", lambda *a, **k: pytest.fail("must not send"))
    monkeypatch.setattr(win_docs, "confirm_text_upload", lambda *a: pytest.fail("a long file is never pasted into the chat"))
    _drop_and_wait(win, str(b))
    assert len(win.messages) == 1 and docs.library().names() == []
    _drop_and_wait(win, str(big), lambda: docs.library().names())
    win._pump(100)
    assert docs.library().names() == ["big.txt"] and len(win.messages) == 1          # in the library, nothing sent
    assert "DOCUMENT LIBRARY" in win.messages[0]["content"] and "big.txt" in win.messages[0]["content"]


def test_drop_image_goes_to_vision(win, monkeypatch, tmp_path):
    from PIL import Image
    p = tmp_path / "shot.png"; Image.new("RGBA", (20, 20)).save(p)
    seen = []; monkeypatch.setattr(win, "_start_vision", lambda q, path=None, image=None: seen.append(path))
    monkeypatch.setattr(win_chat, "confirm_image_upload", lambda *a: True); _drop(win, str(p))
    assert seen == [str(p)]
    seen.clear(); monkeypatch.setattr(win_chat, "confirm_image_upload", lambda *a: False); _drop(win, str(p))
    assert seen == []


# ── plugins ────────────────────────────────────────────────────────
def test_plugin_review_asks_and_loads_only_when_allowed(win, fakebox, monkeypatch, tmp_path):
    plug = tmp_path / "p.py"; plug.write_text("TOOLS=[{'name':'p_tool','function':lambda **k:'hi','description':'d'}]\n")
    h = tools._plugin_hash(str(plug))
    before = len(schemas.TOOLS_SCHEMA); monkeypatch.setattr(tools, "PLUGIN_TOOLS", set())
    monkeypatch.setattr(tools, "PENDING_PLUGINS", [("p.py", str(plug), h)]); monkeypatch.setattr(win, "_save_config", lambda: None)
    fakebox.choice = "don't"; win._review_plugins()
    assert len(schemas.TOOLS_SCHEMA) == before and win.config["plugins_denied"]["p.py"] == h and "p_tool" not in tools.TOOL_FUNCTIONS
    monkeypatch.setattr(tools, "PENDING_PLUGINS", [("p.py", str(plug), h)])
    fakebox.choice = "allow"; win._review_plugins()
    try:
        assert len(schemas.TOOLS_SCHEMA) == before + 1 and win.config["plugins_allowed"]["p.py"] == h and "p_tool" in tools.TOOL_FUNCTIONS
    finally:
        del schemas.TOOLS_SCHEMA[before:]; tools.TOOL_FUNCTIONS.pop("p_tool", None); tools._PARAM_SCHEMAS.pop("p_tool", None)


# ── updates ────────────────────────────────────────────────────────
def test_update_flow_checks_prompts_downloads_and_reveals(win, fakebox, monkeypatch):
    got = []; win._sys_msg_ready.connect(got.append)
    win.config["update_feed"] = "https://example.com/feed.json"
    monkeypatch.setattr(updater, "fetch_info", lambda feed: {"version": "9.9.9", "url": "https://x/NOVA.dmg", "sha256": "0" * 64, "notes": "new"})
    monkeypatch.setattr(updater, "download", lambda url, sha, **k: "/tmp/NOVA-9.9.9.dmg"); revealed = []
    monkeypatch.setattr(updater, "reveal", revealed.append)
    win._check_updates()
    assert _wait_for(lambda: any("Downloaded and verified" in m for m in got))
    assert revealed == ["/tmp/NOVA-9.9.9.dmg"]
    got.clear(); monkeypatch.setattr(updater, "fetch_info", lambda feed: {"version": "0.0.1"})
    win._check_updates()
    assert _wait_for(lambda: any("up to date" in m for m in got))
    got.clear(); monkeypatch.setattr(updater, "fetch_info", lambda feed: (_ for _ in ()).throw(ValueError("offline")))
    win._check_updates()
    assert _wait_for(lambda: any("Update check failed" in m for m in got))


def _wait_for(cond, ms=3000):
    end = time.time() + ms / 1000
    while time.time() < end and not cond():
        _pump(app_instance(), 50)
    return cond()


def app_instance():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance()


# ── window behaviour ───────────────────────────────────────────────
def test_window_modes_cycle_without_getting_stuck(win):
    app = app_instance()
    for target in (uistate.MODE_FULL, uistate.MODE_NORMAL, uistate.MODE_BUBBLE, uistate.MODE_NORMAL):
        win._set_mode(target); _pump(app, 400)
        assert win._mode == target, target


def test_small_controls_dont_crash(win, monkeypatch):
    for _ in range(5): win._toggle_theme()
    for _ in range(4): win._switch_model()
    for _ in range(3): win._cycle_resp_length()
    win._toggle_pin(); win._toggle_pin(); win._bump_font(+1); win._bump_font(-1)
    win._toggle_quick_cmds(); win._toggle_quick_cmds()
    win.config["home_city"] = "Plovdiv"; win._quick_cmd("hello")
    assert models.MODELS[win._model_key]


def test_shutdown_is_idempotent_and_hides_tray(win):
    win._shutdown(); win._shutdown()
    assert win._quitting


def test_hotkey_toggle_shows_and_hides(win):
    win.show(); win._toggle_visibility(); assert not win.isVisible()
    win._toggle_visibility(); assert win.isVisible()


def test_language_does_not_leak_between_windows(win):
    i18n.set_language("en")
    assert i18n.tr("Settings") == "Settings"


# ── switching the AI provider / encryption from Settings ───────────
def _accept_settings(monkeypatch, change):
    monkeypatch.setattr(main.plat, "set_autostart", lambda on, script, hidden=True: True)
    def fake_exec(self):
        change(self); return QDialog.DialogCode.Accepted
    monkeypatch.setattr(win_account.SettingsDialog, "exec", fake_exec)


def test_settings_switches_provider_and_reconnects(win, monkeypatch):
    import providers
    made = []
    fake = types.SimpleNamespace(chat=types.SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(providers, "make_client", lambda prov, key="", url="": (made.append((prov, key, url)), fake)[1])
    _accept_settings(monkeypatch, lambda d: d._provider_cb.setCurrentIndex(d._provider_cb.findData("anthropic")))
    win._show_settings()
    assert win.config["provider"] == "anthropic" and made[-1][0] == "anthropic" and win.client is fake
    assert models.MODELS["smart"][0] == "claude-opus-5-5" and win._model_lbl.text() == "OPUS" and models.stt_model() is None
    def to_ollama(d):
        d._provider_cb.setCurrentIndex(d._provider_cb.findData("ollama")); d._slot_cbs["smart"].setCurrentText("qwen2.5:14b")
    _accept_settings(monkeypatch, to_ollama)
    win._show_settings()
    assert win.config["provider"] == "ollama" and win.config["keyless"] is True and models.MODELS["smart"][0] == "qwen2.5:14b"
    assert json.load(open(paths.CONFIG_FILE))["models_by_provider"] == {"ollama": {"smart": "qwen2.5:14b"}}
    models.activate("groq")


def test_settings_provider_switch_without_a_key_is_undone(win, monkeypatch):
    import providers
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(win_account, "_get_api_key", lambda prov="groq": "test-key" if prov == "groq" else "")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))       # the user cancels the key prompt
    _accept_settings(monkeypatch, lambda d: d._provider_cb.setCurrentIndex(d._provider_cb.findData("openai")))
    before = win.client
    win._show_settings()
    assert win.config["provider"] == "groq" and models.provider() == "groq" and win.client is before
    assert models.MODELS["smart"][0] == providers.PROVIDERS["groq"]["models"]["smart"][0]
    saved = []
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("sk-new", True)))
    monkeypatch.setattr(win_account, "_save_api_key", lambda key, prov="groq": saved.append((prov, key)) or "keyring")
    monkeypatch.setattr(win_account, "_get_api_key", lambda prov="groq": "test-key" if prov == "groq" else ("sk-new" if saved else ""))
    win._show_settings()
    assert win.config["provider"] == "openai" and saved == [("openai", "sk-new")]
    models.activate("groq")


def test_settings_encryption_toggle_converts_the_files(win, monkeypatch):
    import storage
    _send(win, "remember this chat"); _wait_idle(win)
    _accept_settings(monkeypatch, lambda d: d._encrypt_chk.setChecked(True))
    win._show_settings()
    assert win.config["encrypt_data"] is True and storage.enabled()
    raw = open(paths.HISTORY_FILE, "rb").read()
    assert storage.is_encrypted(raw) and b"remember this chat" not in raw
    win._save_history(); assert storage.is_encrypted(open(paths.HISTORY_FILE, "rb").read())
    win.messages = win.messages[:1]; win._load_history()
    assert any(m.get("content") == "remember this chat" for m in win.messages)        # the app reads its own encrypted file
    _accept_settings(monkeypatch, lambda d: d._encrypt_chk.setChecked(False))
    win._show_settings()
    assert not storage.enabled() and b"remember this chat" in open(paths.HISTORY_FILE, "rb").read()


def test_settings_allowances_are_applied_on_save(win, monkeypatch):
    win.config["always_allow"] = ["type:app:Notes", "control_system:sleep"]
    def change(d):
        d._allow_list.setCurrentRow(0); d._remove_allowance()
    _accept_settings(monkeypatch, change)
    win._show_settings()
    assert win.config["always_allow"] == ["control_system:sleep"] and tools.SETTINGS["always_allow"] == ["control_system:sleep"]


def test_prompt_carries_only_relevant_memories(win, data_dir):
    import memory
    items = [memory.make(f"filler fact {i} zzz{i}", "other") for i in range(25)] + [memory.make("Is allergic to peanuts", "preference")]
    tools.replace_memory_items(items[::-1])                           # the relevant one is the OLDEST
    _send(win, "can I eat this peanuts snack?"); _wait_idle(win)
    system = win.messages[0]["content"]
    assert "allergic to peanuts" in system and system.count("filler fact") <= memory.PROMPT_LIMIT and "more memories not shown" in system


# ── part of the screen ─────────────────────────────────────────────
@pytest.mark.skipif(sys.platform != "darwin", reason="the macOS screen selector (Windows: test_windows.py)")
def test_region_capture_hides_nova_then_analyses_the_selection(win, monkeypatch, tmp_path):
    import subprocess as sp
    from PIL import Image
    monkeypatch.setattr(main.plat, "screen_capture_allowed", lambda request=False: True)
    calls = []
    def fake_run(cmd, **k):
        calls.append((cmd, win.isVisible()))
        Image.new("RGB", (40, 30), "red").save(cmd[-1])            # the user dragged a rectangle
    monkeypatch.setattr(sp, "run", fake_run)
    seen = []
    monkeypatch.setattr(win, "_start_vision", lambda q, image_path=None, image=None: seen.append((q, image.size)))
    monkeypatch.setattr(win_chat, "confirm_image_upload", lambda *a: True)
    win.show(); win.input_field.setText("what does this chart show?")
    win._take_region_vision()
    for _ in range(100):
        win._pump(30)
        if seen: break
    assert calls and calls[0][0][:3] == ["/usr/sbin/screencapture", "-i", "-x"] and calls[0][1] is False     # NOVA was out of the way
    assert seen == [("what does this chart show?", (40, 30))] and win.isVisible()
    assert not os.path.exists(calls[0][0][-1])                                    # the temporary picture is deleted


@pytest.mark.skipif(sys.platform != "darwin", reason="the macOS screen selector (Windows: test_windows.py)")
def test_region_capture_cancelled_gives_the_question_back(win, monkeypatch):
    import subprocess as sp
    monkeypatch.setattr(main.plat, "screen_capture_allowed", lambda request=False: True)
    ran = []
    monkeypatch.setattr(sp, "run", lambda cmd, **k: ran.append(1))                 # Esc: no file is written
    monkeypatch.setattr(win, "_start_vision", lambda *a, **k: pytest.fail("nothing was selected"))
    win.show(); win.input_field.setText("my question"); win._take_region_vision()
    for _ in range(100):
        win._pump(30)
        if ran and win.isVisible(): break
    win._pump(100)
    assert win.input_field.toPlainText() == "my question" and win.isVisible()


@pytest.mark.skipif(sys.platform != "darwin", reason="the macOS screen selector (Windows: test_windows.py)")
def test_region_capture_needs_screen_permission(win, monkeypatch):
    import subprocess as sp
    monkeypatch.setattr(main.plat, "screen_capture_allowed", lambda request=False: False)
    monkeypatch.setattr(sp, "run", lambda *a, **k: pytest.fail("must not capture"))
    win.show(); win._take_region_vision(); win._pump(350)
    assert win.isVisible()


def test_approval_box_shows_the_diff_in_colour(win, fakebox, monkeypatch):
    shown = {}
    class Box(fakebox):
        def setInformativeText(self, text): shown["info"] = text
        def setDetailedText(self, text): shown["details"] = text
    monkeypatch.setattr(win_approvals, "QMessageBox", Box)
    Box.choice = "deny"
    preview = "Changes: 1 lines added, 1 removed\n@@ -1 +1 @@\n-buy milk\n+buy <oat> milk"
    assert win._ask_user("Overwrite file:\n/tmp/todo.txt" + tools.DETAILS_MARK + preview, None) is False
    assert "Overwrite file:<br>/tmp/todo.txt" in shown["info"] and shown["details"] == preview
    assert '<span style="color:#d04545">-buy milk</span>' in shown["info"]
    assert '<span style="color:#2e9d4e">+buy &lt;oat&gt; milk</span>' in shown["info"]          # file content cannot inject markup
    shown.clear()
    win._ask_user("Run shell command:\nls", None)
    assert shown["info"] == "Run shell command:\nls" and "details" not in shown


# ── memory keywords in the window ──────────────────────────────────
def test_window_fetches_keywords_for_new_memories_in_one_request(win, data_dir, monkeypatch):
    import memory, win_data
    tools.replace_memory_items([memory.make("Is allergic to peanuts"), memory.make("Works night shifts"), memory.make("Old one", tags="kept")])
    asked = []
    def create(**kw):
        asked.append(kw)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
            content='<think>hm</think>{"1": "food nuts restaurant", "2": "sleep tired schedule"}'))])
    win.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    win_data.DataMixin._tag_memories(win)                                    # (the test window normally skips this background step)
    for _ in range(100):
        win._pump(20)
        if not win._tagging and asked: break
    by = {i["text"]: i["tags"] for i in tools.memory_items()}
    assert by == {"Is allergic to peanuts": "food nuts restaurant", "Works night shifts": "sleep tired schedule", "Old one": "kept"}
    assert len(asked) == 1 and asked[0]["model"] == models.fast_model_id() and "Old one" not in asked[0]["messages"][0]["content"]
    assert asked[0]["reasoning_effort"] == "low"                             # else a thinking model returns nothing but thoughts
    win_data.DataMixin._tag_memories(win); win._pump(100)
    assert len(asked) == 1                                                   # nothing left to tag: no request


def test_keyword_fetching_can_be_turned_off_and_survives_failures(win, data_dir):
    import memory, win_data
    tools.replace_memory_items([memory.make("Likes tea")])
    calls = []
    def boom(**kw):
        calls.append(1); raise RuntimeError("rate limit")
    win.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=boom)))
    win.config["smart_memory"] = False
    win_data.DataMixin._tag_memories(win); win._pump(100)
    assert calls == []
    win.config["smart_memory"] = True
    win_data.DataMixin._tag_memories(win)
    for _ in range(100):
        win._pump(20)
        if calls and not win._tagging: break
    assert calls == [1] and win._tagging is False and tools.memory_items()[0]["tags"] == ""     # failed quietly, can retry later


def test_update_installs_in_place_and_restarts_when_nova_is_an_app(win, fakebox, monkeypatch):
    got = []; win._sys_msg_ready.connect(got.append)
    win.config["update_feed"] = "https://example.com/feed.json"
    monkeypatch.setattr(updater, "fetch_info", lambda feed: {"version": "9.9.9", "url": "https://x/NOVA.dmg", "sha256": "0" * 64})
    monkeypatch.setattr(updater, "download", lambda url, sha, **k: "/tmp/does-not-exist-NOVA-9.9.9.dmg")
    monkeypatch.setattr(updater, "can_self_update", lambda app=None: (True, ""))
    monkeypatch.setattr(updater, "app_bundle", lambda: "/Applications/NOVA.app")
    steps = []
    monkeypatch.setattr(updater, "install_from_dmg", lambda dmg, app: steps.append(("install", dmg, app)) or app)
    monkeypatch.setattr(updater, "relaunch", lambda app: steps.append(("relaunch", app)))
    monkeypatch.setattr(updater, "reveal", lambda p: pytest.fail("no need to open the disk image"))
    monkeypatch.setattr(win, "_quit_app", lambda: steps.append(("quit",)))
    win._check_updates()
    assert _wait_for(lambda: ("quit",) in steps)
    assert steps == [("install", "/tmp/does-not-exist-NOVA-9.9.9.dmg", "/Applications/NOVA.app"), ("relaunch", "/Applications/NOVA.app"), ("quit",)]


def test_daily_update_check_is_quiet_once_a_day_and_can_install_by_itself(win, fakebox, monkeypatch):
    import datetime
    got = []; win._sys_msg_ready.connect(got.append)
    checks = []
    monkeypatch.setattr(updater, "fetch_info", lambda feed: (checks.append(feed), {"version": "0.0.1"})[1])
    win._auto_update_check(); win._pump(200)
    assert checks == []                                                        # no update address: nothing happens
    win.config["update_feed"] = "https://example.com/feed.json"
    win._auto_update_check(); assert _wait_for(lambda: checks)
    win._pump(200)
    assert got == [] and win.config["update_checked"] == datetime.date.today().isoformat()     # up to date: says nothing
    win._auto_update_check(); win._pump(200); assert len(checks) == 1          # only once a day
    win.config["update_checked"] = ""; win.config["auto_update"] = "off"
    win._auto_update_check(); win._pump(200); assert len(checks) == 1          # turned off
    # "install by itself": no question, no restart
    win.config["update_checked"] = ""; win.config["auto_update"] = "install"
    monkeypatch.setattr(updater, "fetch_info", lambda feed: {"version": "9.9.9", "url": "https://x/NOVA.dmg", "sha256": "0" * 64})
    monkeypatch.setattr(updater, "download", lambda url, sha, **k: "/tmp/does-not-exist.dmg")
    monkeypatch.setattr(updater, "can_self_update", lambda app=None: (True, "")); monkeypatch.setattr(updater, "app_bundle", lambda: "/Applications/NOVA.app")
    done = []
    monkeypatch.setattr(updater, "install_from_dmg", lambda dmg, app: done.append(app))
    monkeypatch.setattr(updater, "relaunch", lambda app: pytest.fail("a background install must not restart NOVA under you"))
    monkeypatch.setattr(win_data.QMessageBox, "question", staticmethod(lambda *a, **k: pytest.fail("no question in install-by-itself mode")))
    win._auto_update_check()
    assert _wait_for(lambda: done)
    win._pump(200)
    texts = [w._full_text for w in win.chat_area.findChildren(type(win.chat_area.add_message("x", "system", win._theme)))]
    assert any("NOVA 9.9.9 was installed" in t for t in texts)


def test_whats_new_shows_once_after_an_update_and_never_for_new_users(win):
    def bubbles(): return [w._full_text for w in win.chat_area.findChildren(type(win._last_ai_bubble or win.chat_area.add_message("x", "assistant", win._theme)))]
    assert not any("What's new" in t for t in bubbles())                 # this test window is a fresh install
    assert win.config["seen_version"] == paths.__version__
    win.config["seen_version"] = "6.0.0"                                 # …now pretend NOVA was just updated
    win._maybe_whats_new()
    assert sum("What's new in NOVA" in t for t in bubbles()) == 1 and win.config["seen_version"] == paths.__version__
    assert json.load(open(paths.CONFIG_FILE))["seen_version"] == paths.__version__
    win._maybe_whats_new()
    assert sum("What's new in NOVA" in t for t in bubbles()) == 1        # only once
    win._show_whats_new()                                                # Help → What's new shows it again on request
    assert sum("What's new in NOVA" in t for t in bubbles()) == 2


# ── starting at login ──────────────────────────────────────────────
def test_login_item_follows_the_start_hidden_setting(win, monkeypatch, tmp_path):
    import platform_utils as plat, plistlib
    agent = tmp_path / "LaunchAgents" / "com.nova.assistant.plist"
    monkeypatch.setattr(plat, "_LAUNCH_AGENT", str(agent))
    win._refresh_login_item(); assert not agent.exists()                      # launch at login is off: nothing is created
    plat.set_autostart(True, "/x/main.py", hidden=False)                      # an entry made by an older NOVA
    win._refresh_login_item()
    assert "--hidden" in plistlib.loads(agent.read_bytes())["ProgramArguments"]
    win.config["start_hidden"] = False; win._refresh_login_item()
    assert "--hidden" not in plistlib.loads(agent.read_bytes())["ProgramArguments"]


def test_settings_pass_the_start_hidden_choice_on(win, monkeypatch):
    seen = []
    monkeypatch.setattr(main.plat, "set_autostart", lambda on, script, hidden=True: (seen.append((on, hidden)), True)[1])
    def fake_exec(self):
        self._auto_chk.setChecked(True); self._hidden_chk.setChecked(False); return QDialog.DialogCode.Accepted
    monkeypatch.setattr(win_account.SettingsDialog, "exec", fake_exec)
    win._show_settings()
    assert seen == [(True, False)] and win.config["start_hidden"] is False


def test_a_rejected_key_says_who_refused_it_and_where_to_get_a_new_one(win, monkeypatch):
    from gui_support import _send, _wait_idle
    def refuse(**kw): raise Exception("Error code: 401 - {'error': {'message': 'Invalid API Key', 'code': 'invalid_api_key'}}")
    monkeypatch.setattr(FakeCompletions, "create", lambda self, **kw: refuse(**kw))
    _send(win, "hello"); _wait_idle(win)
    from widgets import MessageBubble
    lay = win.chat_area._layout
    last = [w for w in (lay.itemAt(i).widget() for i in range(lay.count())) if isinstance(w, MessageBubble) and w._role == "system"][-1]
    assert "Groq did not accept the API key" in last._label.text() and 'href="https://console.groq.com/keys"' in last._label.text()
    assert last._problem                                                       # shown in the colour for failures

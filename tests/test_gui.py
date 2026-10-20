"""Headless end-to-end tests of the main window against a fake Groq client."""
import json, os, time, types
import pytest

PySide6 = pytest.importorskip("PySide6")

import main, tools
import win_chat
import paths
import workers
import models
import themes
import uistate
import widgets
import chatutil
from PySide6.QtCore import QThread, Signal


from gui_support import FakeCompletions, _tc, _wait_idle, _send


def test_plain_reply_strips_hint_and_think(win):
    win._resp_length = "short"
    FakeCompletions.script = [["Hel", "lo <think>x</think>", " there"]]
    _send(win, "hello"); _wait_idle(win)
    assert [m["content"] for m in win.messages[1:]] == ["hello", "Hello there"]


def test_tool_call_asks_for_approval_from_worker_thread(win):
    asked = []
    win._ask_user = lambda d, k=None: asked.append(d) or True
    FakeCompletions.script = [[_tc(0, "c1", "run_shell_command", '{"command":"echo NOVA_OK"}')], ["done"]]
    _send(win, "run it"); _wait_idle(win)
    assert asked and any(json.loads(m["content"]) == {"ok": True, "result": "NOVA_OK"} for m in win.messages if m["role"] == "tool")


def test_declined_tool_is_not_run(win):
    win._ask_user = lambda d, k=None: False
    FakeCompletions.script = [[_tc(0, "c1", "run_shell_command", '{"command":"touch /tmp/nova_should_not_exist"}')], ["ok"]]
    _send(win, "x"); _wait_idle(win)
    assert not os.path.exists("/tmp/nova_should_not_exist")


def test_invalid_tool_json_is_reported_not_executed(win):
    FakeCompletions.script = [[_tc(0, "c1", "run_shell_command", '{"command": ')], ["ok"]]
    _send(win, "x"); _wait_idle(win)
    last = json.loads([m["content"] for m in win.messages if m["role"] == "tool"][-1])
    assert last["ok"] is False and "not valid JSON" in last["error"]


def test_cancel_stops_everything_and_allows_new_message(win):
    FakeCompletions.script = [["a", "SLEEP", "b", "SLEEP", "c", "SLEEP", "d"]]
    _send(win, "slow"); win._pump(250); assert win._busy
    win._cancel_request(); win._pump(900)
    assert not win._busy and win._worker is None and win.messages[-1]["role"] == "user"
    FakeCompletions.script = [["fresh"]]
    _send(win, "again"); _wait_idle(win)
    assert win.messages[-1]["content"] == "fresh"


def test_new_chat_during_request_is_safe(win):          # this was the crash in nova_crash.log
    FakeCompletions.script = [["x", "SLEEP", "SLEEP", "SLEEP", "y"]]
    _send(win, "long"); win._pump(200)
    win._new_chat(); win._pump(1200)
    assert len(win.messages) == 1 and not win._busy and win._thinking_bubble is None
    assert not win._think_timer.isActive()


def test_fullscreen_does_not_persist_font_size(win):
    win.config["font_size"] = 10
    win._apply_ui_scale(True); win._save_config()
    assert json.load(open(paths.CONFIG_FILE))["font_size"] == 10
    win._apply_ui_scale(False)
    assert uistate.FONT_SIZE == 10


def test_custom_accent_never_mutates_base_theme(win):
    win._theme_key = "nova"
    win.config["accent_color"] = "#ff0000"
    th = win._resolve_theme()
    assert th["accent"] == "#ff0000"
    assert themes.THEMES[win._theme_key]["accent"] == themes.THEMES_BASE[win._theme_key]["accent"]


def test_wiped_window_never_writes_files(win):
    win._wiped = True
    if os.path.exists(paths.CONFIG_FILE): os.remove(paths.CONFIG_FILE)
    win._save_config(); win._save_history()
    assert not os.path.exists(paths.CONFIG_FILE)


def test_calculator_in_chat(win):
    assert win._try_calculate("= 15% of 200") is True
    assert win._try_calculate("= hello") is False


def test_rate_limit_switches_model_instead_of_waiting(win):
    win._model_key = "smart"
    FakeCompletions.big_fails = 5; FakeCompletions.script = [["quick answer"]]
    t = time.time()
    _send(win, "hi"); _wait_idle(win)
    assert win.messages[-1]["content"] == "quick answer"
    assert time.time() - t < 5                          # no 30 s wait
    assert FakeCompletions.models[0] != models.fast_model_id() and FakeCompletions.models[-1] == models.fast_model_id()


def test_readonly_tools_run_in_parallel(win, monkeypatch):
    def slow(**kw):
        time.sleep(0.4); return "ok"
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "get_weather", slow)
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "get_battery", slow)
    FakeCompletions.script = [[_tc(0, "a", "get_weather", "{}"), _tc(1, "b", "get_battery", "{}")], ["done"]]
    t = time.time()
    _send(win, "both"); _wait_idle(win)
    assert time.time() - t < 0.75                       # sequential would take >= 0.8 s


def test_streaming_is_batched(win):
    b = win.chat_area.add_message("", "assistant", win._theme)
    flushes = []
    b.grew.connect(lambda: flushes.append(1))
    for i in range(800): b.append_text(f"w{i} ")
    assert flushes == []                                 # nothing re-laid-out per chunk
    for _ in range(20):                                  # one 70 ms timer tick; allow for a busy machine
        win._pump(50)
        if flushes: break
    assert len(flushes) == 1 and "w799" in b._label.text()


def test_no_extra_api_calls_after_a_reply(win):
    FakeCompletions.script = [["hello"]]
    _send(win, "hi"); _wait_idle(win); win._pump(800)
    assert len(FakeCompletions.models) == 1              # no title / follow-up requests by default


def test_edit_message_replaces_it_and_everything_after(win):
    FakeCompletions.script = [["first answer"], ["second answer"]]
    _send(win, "one"); _wait_idle(win)
    _send(win, "two"); _wait_idle(win)
    assert [m["content"] for m in win.messages[1:]] == ["one", "first answer", "two", "second answer"]
    bubbles = [w for w in win.chat_area.widgets_from(win.chat_area._layout.itemAt(0).widget())
               if isinstance(w, widgets.MessageBubble) and w._role == "user"]
    win._edit_message(bubbles[1])                                   # edit "two"
    assert [m["content"] for m in win.messages[1:]] == ["one", "first answer"]
    assert win.input_field.toPlainText() == "two"
    win._edit_message(bubbles[0])                                   # edit "one" -> chat is emptied
    assert len(win.messages) == 1 and win.input_field.toPlainText() == "one"


def test_auto_theme_follows_system(win, monkeypatch):
    win._theme_key = "auto"
    monkeypatch.setattr(main.AssistantWindow, "_system_is_dark", staticmethod(lambda: True))
    assert win._resolve_theme()["frame_bg"] == themes.THEMES["nova"]["frame_bg"]
    monkeypatch.setattr(main.AssistantWindow, "_system_is_dark", staticmethod(lambda: False))
    assert win._resolve_theme()["frame_bg"] == themes.THEMES["soft"]["frame_bg"]
    win._toggle_theme()                                             # cycling must not crash on 'auto'
    assert win._theme_key in themes.THEMES


def test_vision_keeps_chat_consistent(win, monkeypatch):
    class FakeVision(QThread):
        result_ready = Signal(str, str); error = Signal(str)
        def __init__(self, client, q, path=None, image=None): super().__init__(); self.q = q
        def run(self): self.result_ready.emit("I see a desktop", "")
    monkeypatch.setattr(win_chat, "VisionWorker", FakeVision)
    win._start_vision("what is this?"); win._pump(400)
    assert [m["role"] for m in win.messages[1:]] == ["user", "assistant"] and not win._busy
    assert win.messages[1]["content"].startswith("[📷]")


def test_bulgarian_interface(win, monkeypatch):
    import i18n
    i18n.set_language("bg")
    try:
        assert i18n.tr("⚙  Settings") == "⚙  Настройки" and i18n.tr("Cancelled.") == "Отказано."
        assert i18n.tr("something untranslated") == "something untranslated"
        with open(paths.CONFIG_FILE, "w") as f: json.dump({"ui_lang": "bg", "onboarded": True, "consent": True}, f)
        w2 = main.AssistantWindow()
        assert w2.input_field.placeholderText() == "Съобщение до NOVA"
        assert any("Времето" in b.text() for b in w2._quick_btns)
        w2._shutdown()
    finally:
        i18n.set_language("en")
    assert i18n.tr("Cancelled.") == "Cancelled."


def test_token_usage_is_counted_and_shown(win):
    class Usage: prompt_tokens = 1200; completion_tokens = 340
    orig = FakeCompletions.create
    def create(self, **kw):
        stream = orig(self, **kw)
        def gen():
            yield from stream
            yield types.SimpleNamespace(choices=[], x_groq=types.SimpleNamespace(usage=Usage()))
        return gen()
    FakeCompletions.create = create
    try:
        FakeCompletions.script = [["hi there"]]
        _send(win, "hello"); _wait_idle(win); win._pump(200)
    finally:
        FakeCompletions.create = orig
    assert (win._tokens_in, win._tokens_out) == (1200, 340)
    assert "1.5k tok" in win._ctx_lbl.text()


def test_menu_bar_and_tray_icon_exist(win):
    names = [a.text() for a in win._menubar.actions()]
    assert names[:5] == ["File", "Edit", "View", "Window", "Help"]
    assert win._make_tray_icon().isMask()


def test_retired_model_is_replaced(win, monkeypatch):
    import models
    saved = dict(models.MODELS)
    try:
        notes = models.reconcile({"llama-3.3-70b-versatile", "openai/gpt-oss-20b", "qwen/qwen3-32b"})
        assert models.MODELS["smart"][0] == "llama-3.3-70b-versatile" and notes and "not available" in notes[0]
        win._on_models(notes)
        assert win._model_lbl.text() == models.MODELS[win._model_key][1]
    finally:
        models.MODELS.clear(); models.MODELS.update(saved)


def test_the_model_list_is_fetched_again_after_a_network_error(win, monkeypatch):
    import models
    tries = []
    def flaky(client):
        tries.append(1)
        if len(tries) < 3: raise Exception("Connection error.")                 # Wi-Fi still waking up at start-up
        return {"openai/gpt-oss-120b", "openai/gpt-oss-20b"}
    monkeypatch.setattr(models, "fetch_available", flaky)
    monkeypatch.setattr(models, "reconcile", lambda available: [])
    monkeypatch.setattr(type(win), "_MODEL_LIST_RETRY_MS", (20, 20))
    win._available_models = set(); win._refresh_models()
    deadline = time.monotonic() + 3
    while not win._available_models and time.monotonic() < deadline: win._pump(20)
    assert len(tries) == 3 and "openai/gpt-oss-120b" in win._available_models
    tries.clear(); monkeypatch.setattr(models, "fetch_available", lambda c: (tries.append(1), (_ for _ in ()).throw(
        Exception("Error code: 401 - Invalid API Key")))[1])
    win._refresh_models(); win._pump(200)
    assert len(tries) == 1                                                       # a refused key: no point retrying


def test_memory_history_and_retention_settings(win, tmp_path):
    win.config["save_history"] = False
    win.messages += [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]
    open(paths.HISTORY_FILE, "w").write("{}")
    win._save_history()
    assert not os.path.exists(paths.HISTORY_FILE)                       # "don't keep history" removes it
    win._save_session()
    assert not os.path.isdir(paths.SESSIONS_DIR) or not os.listdir(paths.SESSIONS_DIR)


def test_rate_limited_model_is_skipped_on_the_next_request(win):
    win._model_key = "smart"
    FakeCompletions.big_fails = 1; FakeCompletions.script = [["one"], ["two"]]
    _send(win, "a"); _wait_idle(win)
    FakeCompletions.models.clear()
    _send(win, "b"); _wait_idle(win)
    assert FakeCompletions.models == [models.fast_model_id()]            # went straight to the fast model, no new 429


def test_vision_falls_back_to_the_next_model(monkeypatch):
    calls = []
    class C:
        class chat:
            class completions:
                @staticmethod
                def create(model, **kw):
                    calls.append(model)
                    if len(calls) == 1: raise Exception("Error code: 429 rate_limit_exceeded. Please try again in 5s")
                    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="a cat"))])
    from PIL import Image
    got = []
    w = workers.VisionWorker(C, "what?", image=Image.new("RGBA", (50, 50)))
    w.result_ready.connect(lambda t, n: got.append(t)); w.error.connect(lambda e: got.append("ERR " + e))
    w.run()
    assert got == ["a cat"] and len(calls) == 2 and calls[0] != calls[1]


def test_hold_to_talk_stops_on_release_but_click_keeps_recording(win, monkeypatch):
    started, stopped = [], []
    monkeypatch.setattr(main.AssistantWindow, "_start_voice", lambda self: (started.append(1), setattr(self, "_is_recording", True)))
    monkeypatch.setattr(main.AssistantWindow, "_stop_voice_internal", lambda self: (stopped.append(1), setattr(self, "_is_recording", False)))
    win._voice_pressed(); win._voice_released()                          # quick click: recording continues
    assert started == [1] and stopped == []
    win._voice_pressed()                                                 # second click stops
    assert stopped == [1]
    win._voice_released()
    win._voice_pressed(); win._voice_press_t -= 1.0; win._voice_released()   # held >0.5 s: release stops
    assert len(started) == 2 and len(stopped) == 2


def test_chat_view_and_context_stay_bounded(win):
    for i in range(widgets.ChatArea.MAX_WIDGETS + 60):
        win.chat_area.add_message(f"m{i}", "system", win._theme)
    assert win.chat_area._layout.count() <= widgets.ChatArea.MAX_WIDGETS
    msgs = [{"role": "system", "content": "s"}] + [{"role": "user" if i % 2 == 0 else "assistant", "content": f"t{i}"} for i in range(120)]
    class Broken:                                            # summarising fails (rate limit / offline)
        class chat:
            class completions:
                @staticmethod
                def create(**kw): raise RuntimeError("429")
    out = chatutil.compress_messages(Broken, "m", msgs)
    assert len(out) <= 31 and out[0]["role"] == "system" and out[-1]["content"] == "t119"


def test_what_nova_did_is_shown_as_rows_inside_the_reply(win):
    win._ask_user = lambda d, k=None: True
    FakeCompletions.script = [[_tc(0, "c1", "run_shell_command", '{"command":"echo done"}'),
                               _tc(1, "c2", "read_file", '{"path":"/definitely/missing.txt"}')], ["all set"]]
    _send(win, "do two things"); _wait_idle(win); win._pump(200)
    reply = win._last_ai_bubble
    acts = reply.findChildren(widgets.ToolActivity)
    assert len(acts) == 1 and reply._actions is acts[0]
    a = acts[0]
    assert a.summary() == "2 actions · 1 failed"
    first, second = a.rows
    assert (first["title"].text(), first["detail"].full_text(), first["ok"]) == ("Ran command", "echo done", True)
    assert (second["title"].text(), second["detail"].full_text(), second["ok"]) == ("Read file", "missing.txt", False)
    assert "Failed" in second["button"].accessibleName() and "Done" in first["button"].accessibleName()
    assert second["more"].isHidden(); second["button"].click()                    # a click shows the exact call and its result
    assert not second["more"].isHidden() and "read_file" in second["more"].text() and "missing.txt" in second["more"].text()
    FakeCompletions.script = [["again"]]                                          # regenerate: the old reply and its rows go away
    win._regen_response(); _wait_idle(win); win._pump(200)
    assert win._last_ai_bubble is not reply and win._last_ai_bubble.findChildren(widgets.ToolActivity) == []


def test_actions_are_described_in_words():
    import actions
    assert actions.describe("open_maps", {"location": "Paris, France"}) == ("pin", "Opened Maps", "Paris, France")
    assert actions.describe("manage_files", {"action": "move", "source": "~/a/report.pdf", "destination": "~/Desktop"}) == ("folder", "Moved", "report.pdf → Desktop")
    assert actions.describe("control_volume", {"action": "set", "level": 30}) == ("volume", "Volume set", "30%")
    assert actions.describe("open_url", {"url": "https://www.example.com/a/very/long/path?q=1"}) == ("globe", "Opened page", "www.example.com")
    assert actions.describe("set_reminder", {"text": "call Ivan", "minutes": 20}) == ("bell", "Reminder", "20 min · call Ivan")
    assert actions.describe("mcp__github__create_issue", {"title": "x"}) == ("plug", "github", "create_issue")
    assert actions.describe("my_plugin_tool", None) == ("plug", "Used tool", "my_plugin_tool")
    assert actions.describe("run_shell_command", {"command": "x" * 200})[2].endswith("…")           # long details are cut
    import tools
    for name in tools.TOOL_FUNCTIONS:                                             # every tool has a row of its own
        assert name in actions.HIDDEN or actions.describe(name, {})[1] != "Used tool", name


def test_while_a_tool_runs_nova_says_what_it_is_busy_with(win):
    assert win._working_text("⚙️  search_web_and_read(query='x')") == "Searching the web…"
    assert win._working_text("⚙️  open_maps(location='Paris')") == "Working…"
    assert win._working_text("⚙️  more_tools(group='calendar')") == "Thinking…" and win._working_text("") == "Thinking…"

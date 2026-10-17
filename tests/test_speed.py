"""What keeps replies quick: plain commands finish in one round, and NOVA stays inside the provider's
per-minute allowance by choosing the model that has room - before sending, not after being refused."""
import time, types
import pytest
pytest.importorskip("PySide6")
import providers, workers, models, tools
from gui_support import FakeCompletions, _send, _tc, _wait_idle


# ── one round instead of two ───────────────────────────────────────
def test_a_plain_command_is_done_after_one_round(win, monkeypatch):
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "open_application", lambda app_name: f"Opened {app_name} ✓")
    FakeCompletions.script = [[_tc(0, "c1", "open_application", '{"app_name":"Spotify"}')], ["(this second answer is never asked for)"]]
    _send(win, "open Spotify"); _wait_idle(win); win._pump(100)
    assert len(FakeCompletions.models) == 1                                   # the AI was asked once, not twice
    assert win.messages[-1] == {"role": "assistant", "content": "Done."}     # the turn is closed properly in the history
    assert [m["role"] for m in win.messages[-3:]] == ["assistant", "tool", "assistant"]
    assert win._last_ai_bubble._full_text == "Done." and len(win._last_ai_bubble._actions.rows) == 1      # the row says what was done
    FakeCompletions.script = [["Sure."]]
    _send(win, "thanks"); _wait_idle(win)                                     # the conversation simply goes on
    assert win.messages[-1]["content"] == "Sure."


@pytest.mark.parametrize("ask, reason", [
    ("open Spotify and tell me a joke", "more was asked than the action"),
    ("can you open Spotify?", "it is a question"),
    ("open Spotify, then pause the music after a minute please ok", "several steps"),
])
def test_anything_more_than_a_plain_command_gets_its_second_round(win, monkeypatch, ask, reason):
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "open_application", lambda app_name: f"Opened {app_name} ✓")
    FakeCompletions.script = [[_tc(0, "c1", "open_application", '{"app_name":"Spotify"}')], ["Opened. Here is the rest."]]
    _send(win, ask); _wait_idle(win)
    assert len(FakeCompletions.models) == 2 and win.messages[-1]["content"] == "Opened. Here is the rest.", reason


def test_a_failed_or_informative_tool_always_gets_its_second_round(win, monkeypatch):
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "open_application", lambda app_name: tools.fail("Could not find 'Spotfy'."))
    FakeCompletions.script = [[_tc(0, "c1", "open_application", '{"app_name":"Spotfy"}')], ["I could not find that app."]]
    _send(win, "open Spotfy"); _wait_idle(win)
    assert len(FakeCompletions.models) == 2 and "could not find" in win.messages[-1]["content"]      # the AI explains the failure
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "control_spotify", lambda action: "Spotify is not running.")
    FakeCompletions.script = [[_tc(0, "c1", "control_spotify", '{"action":"next"}')], ["Spotify is not open."]]; FakeCompletions.models = []
    _send(win, "next song"); _wait_idle(win)
    assert len(FakeCompletions.models) == 2                                   # "not running" is not a ✓: the AI must say so
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "get_weather", lambda location="": "Sofia: 14°C ✓")
    FakeCompletions.script = [[_tc(0, "c1", "get_weather", '{"location":"Sofia"}')], ["14 degrees."]]; FakeCompletions.models = []
    _send(win, "weather Sofia"); _wait_idle(win)
    assert len(FakeCompletions.models) == 2 and win.messages[-1]["content"] == "14 degrees."         # results the AI has to read


def test_the_ais_own_words_with_the_action_are_the_reply(win, monkeypatch):
    """Some models write their sentence in the same message as the tool call: that is the answer, even for longer requests."""
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "save_note", lambda text=None, **k: "Note saved ✓")
    FakeCompletions.script = [["Saved your note about milk and eggs.", _tc(0, "c1", "save_note", '{"text":"buy milk and eggs"}')], ["(never asked)"]]
    _send(win, "save a note: buy milk and eggs"); _wait_idle(win)
    assert len(FakeCompletions.models) == 1 and win.messages[-1]["role"] == "tool"
    assert win._last_ai_bubble._full_text == "Saved your note about milk and eggs."


def test_one_round_never_applies_after_outside_content(win, monkeypatch):
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "open_url", lambda url: f"Opened {url} ✓")
    monkeypatch.setattr(win, "_ask_user", lambda d, k=None: True)
    win._request_untrusted = "file"                                           # e.g. the request carries a dropped file's text
    FakeCompletions.script = [[_tc(0, "c1", "open_url", '{"url":"example.com"}')], ["Opened it."]]
    _send(win, "open example.com"); _wait_idle(win)
    assert len(FakeCompletions.models) == 2                                   # the AI stays in the loop when untrusted text is involved


# ── the per-minute allowance ───────────────────────────────────────
@pytest.fixture
def allowance(monkeypatch):
    monkeypatch.setattr(providers, "_ALLOWANCE", {})
    def says(model, left, limit=8000, ago=0.0):
        providers._ALLOWANCE[model] = (left, limit, time.monotonic() - ago)
    return says


def test_the_providers_headers_are_understood(allowance):
    providers.note_allowance("m", {"x-ratelimit-remaining-tokens": "7908", "x-ratelimit-limit-tokens": "8000"})
    assert 7900 <= providers.allowance("m") <= 8000 and providers.allowance("unknown-model") is None
    providers.note_allowance("m", {"something": "else"}); providers.note_allowance("m", None)             # other providers: ignored
    assert providers.allowance("m") >= 7900
    assert providers._seconds("690ms") == pytest.approx(0.69) and providers._seconds("7.66s") == pytest.approx(7.66)
    assert providers._seconds("1m3.5s") == pytest.approx(63.5) and providers._seconds("") == 0 and providers._seconds("soon") == 0


def test_the_allowance_refills_over_time(allowance):
    allowance("m", 500); assert 480 <= providers.allowance("m") <= 520
    allowance("m", 500, ago=15); assert 2400 <= providers.allowance("m") <= 2600                # a quarter of a minute = a quarter of 8,000
    allowance("m", 500, ago=600); assert providers.allowance("m") == 8000                       # never more than the limit
    allowance("m", 1000)
    assert providers.wait_for("m", 800) == 0 and providers.wait_for("m", 3000) == pytest.approx(15, abs=0.5)
    assert providers.wait_for("m", 50000) == pytest.approx(52.5, abs=0.5)                       # asks for at most a full allowance
    assert providers.wait_for("unknown-model", 9999) == 0
    providers.spend("m", 600); assert 380 <= providers.allowance("m") <= 420


def _worker(model):
    w = workers.AIWorker(types.SimpleNamespace(), [{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}], model)
    w.notices = []; w.tool_executing.connect(w.notices.append)
    w.slept = []; w._sleep = lambda secs: (w.slept.append(secs), True)[1]
    return w


def test_a_model_without_room_hands_over_to_the_other_one(app, allowance):
    smart, fast = models.MODELS["smart"][0], models.fast_model_id()
    w = _worker(smart)
    assert w._make_room(1500) is True and w.model_id == smart and w.slept == []                 # nothing known: nothing assumed
    allowance(smart, 300); allowance(fast, 7000)
    assert w._make_room(1500) is True and w.model_id == fast and w.slept == []                  # no waiting, no refused request
    w = _worker(fast); allowance(fast, 200); allowance(smart, 6000)
    assert w._make_room(1500) is True and w.model_id == smart                                   # it works in both directions


def test_when_both_are_used_up_it_waits_exactly_as_long_as_needed(app, allowance):
    smart, fast = models.MODELS["smart"][0], models.fast_model_id()
    allowance(smart, 100); allowance(fast, 900)
    w = _worker(smart)
    assert w._make_room(1500) is True
    assert w.model_id == fast and len(w.slept) == 1 and 4 <= w.slept[0] <= 6                    # 600 tokens short at 133 a second
    assert any("Rate limit" in n for n in w.notices)
    w = _worker(smart); w._sleep = lambda secs: False                                           # cancelled while waiting
    assert w._make_room(1500) is False


def test_the_next_call_is_estimated_from_the_last_one(app):
    w = _worker("m")
    assert 200 < w._estimate([{"type": "function", "function": {"name": "x" * 900}}]) < 800     # a guess from the size
    w._round_in = 1400
    assert w._estimate([]) == 1900                                                              # what the last round cost, plus room


def test_notices_from_the_worker_are_shown_while_it_works(win):
    assert win._working_text("⏳  Rate limit — retrying in 5s") == "Rate limit — retrying in 5s"
    assert win._working_text("🗜  Compressing history…") == "Compressing history…"
    assert win._working_text("⚙️  get_weather(location='Sofia')") == "Checking the weather…"


# ── a long reply must not freeze the window while it streams ───────
def test_a_long_streamed_reply_is_repainted_less_often(win):
    import widgets
    b = win.chat_area.add_message("", "assistant", win._theme)
    assert b._flush_timer.interval() == 70
    b._full_text = "short"; b._flush()
    assert b._flush_timer.interval() == 70                                    # a quick repaint keeps the lively pace
    real = widgets.time.perf_counter
    ticks = iter([100.0, 100.2])                                              # pretend this repaint took 0.2 s
    widgets.time.perf_counter = lambda: next(ticks, 100.2)
    try: b._full_text = "long " * 4000; b._flush()
    finally: widgets.time.perf_counter = real
    assert b._flush_timer.interval() == 800                                   # then: at most a quarter of the time is spent drawing
    ticks = iter([200.0, 209.0]); widgets.time.perf_counter = lambda: next(ticks, 209.0)
    try: b._flush()
    finally: widgets.time.perf_counter = real
    assert b._flush_timer.interval() == 1500                                  # but never slower than this


# ── start-up: heavy libraries load when first needed, not before the window appears ──
def _fresh_python(code: str) -> str:
    import os, subprocess, sys, tempfile
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, NOVA_DATA_DIR=tempfile.mkdtemp(prefix="nova_test_"), NOVA_NO_MIGRATE="1", QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return r.stdout


def test_starting_nova_loads_no_heavy_library():
    out = _fresh_python("import sys, main\n"
                        "print(sorted(m for m in ('pyautogui', 'groq', 'openai', 'anthropic', 'onnxruntime', 'tokenizers') if m in sys.modules))")
    assert out.strip() == "[]", out                  # 0.1-0.35 s each: typing/screenshots, the AI SDKs, meaning search


@pytest.mark.parametrize("provider,sdk", [("groq", "groq"), ("openai", "openai"), ("anthropic", "anthropic")])
def test_the_ai_client_loads_its_sdk_on_first_use(provider, sdk):
    out = _fresh_python("import sys, providers\n"
                        f"c = providers.make_client({provider!r}, 'test-key')\n"
                        f"before = {sdk!r} in sys.modules\n"
                        "c.warm_up()\n"
                        f"print(before, {sdk!r} in sys.modules, c.chat.completions.create is not None)")
    assert out.split() == ["False", "True", "True"], out

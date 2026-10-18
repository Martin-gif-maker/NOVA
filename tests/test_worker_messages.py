"""What the AI worker says by itself (no model text): plain words, translated, never a bracketed debug note."""
import types
import pytest
import i18n, models, tools, workers
from gui_support import _C, _D, _tc


class _Client:
    """A model that keeps asking for the same harmless tool, or declines."""
    def __init__(self, mode):
        self.mode = mode
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kw):
        if self.mode == "refuse":
            chunk = _C(_D(content=""))
            chunk.choices[0].finish_reason = "content_filter"
            chunk.refusal_category = "cyber"
            return iter([chunk])
        return iter([_C(_D(tool_calls=[_tc(0, "", "get_battery", "{}")]))])


def _run(mode, monkeypatch):
    monkeypatch.setattr(tools, "run_tool", lambda name, args: tools.ToolResult(name, args, True, "80 %"))
    w = workers.AIWorker(_Client(mode), [{"role": "system", "content": "x"}, {"role": "user", "content": "battery?"}],
                         models.fast_model_id())
    got = []
    w.response_ready.connect(lambda text, _msgs: got.append(text))
    w.run()                                                    # in this thread: the signals are delivered directly
    return got


@pytest.fixture
def bulgarian():
    i18n.set_language("bg")
    yield
    i18n.set_language("en")


def test_running_out_of_steps_is_explained(app, monkeypatch):
    (text,) = _run("loop", monkeypatch)
    assert "[" not in text and "8 steps" in text


def test_running_out_of_steps_in_bulgarian(app, monkeypatch, bulgarian):
    (text,) = _run("loop", monkeypatch)
    assert "8 стъпки" in text


def test_a_refusal_says_so_without_an_emoji(app, monkeypatch, bulgarian):
    (text,) = _run("refuse", monkeypatch)
    assert text.startswith("AI отказа") and "cyber" in text and "⚠" not in text


# ── a tool call written out as text is run as the call it is ──
class _Scripted:
    """A model that answers from a list: each item is one round's text."""
    def __init__(self, rounds):
        self.rounds = list(rounds); self.chat = types.SimpleNamespace(completions=self)
    def create(self, **kw):
        text = self.rounds.pop(0) if self.rounds else "ok"
        return iter([_C(_D(content=text))])


def _run_rounds(rounds, monkeypatch, offered=("save_memory", "get_battery")):
    import schemas
    ran = []
    monkeypatch.setattr(tools, "run_tool", lambda name, args: (ran.append((name, args)), tools.ToolResult(name, args, True, "Saved ✓"))[1])
    monkeypatch.setattr(schemas, "select_tools", lambda text, sticky=(): (
        [{"type": "function", "function": {"name": n, "parameters": {}}} for n in offered], set()))
    w = workers.AIWorker(_Scripted(rounds), [{"role": "system", "content": "x"}, {"role": "user", "content": "I like tea, remember it"}],
                         models.fast_model_id())
    got, taken = [], []
    w.response_ready.connect(lambda text, _m: got.append(text)); w.text_retracted.connect(taken.append)
    w.run()
    return ran, got, taken


def test_a_call_written_as_text_runs_and_its_text_is_taken_back(app, monkeypatch):
    written = 'save_memory({"fact": "likes tea", "category": "preference"})'
    ran, got, taken = _run_rounds([written, "Noted - you like tea."], monkeypatch)
    assert ran == [("save_memory", {"fact": "likes tea", "category": "preference"})]
    assert taken == [len(written)] and got == ["Noted - you like tea."]


def test_the_tool_call_tag_form_is_understood_too(app, monkeypatch):
    ran, got, _ = _run_rounds(['<tool_call>{"name": "get_battery", "arguments": {}}</tool_call>', "82 %."], monkeypatch)
    assert ran == [("get_battery", {})] and got == ["82 %."]


@pytest.mark.parametrize("text", [
    'In Python you would write print({"a": 1}) here.',                      # prose around it: not a call
    'delete_everything({"really": true})',                                  # not a tool NOVA offered
    'save_memory({not json})',
])
def test_ordinary_text_is_never_taken_for_a_call(app, monkeypatch, text):
    ran, got, taken = _run_rounds([text], monkeypatch)
    assert ran == [] and taken == [] and got == [text]


def test_the_window_shows_no_raw_call(win, monkeypatch):
    from gui_support import FakeCompletions, _send, _wait_idle
    monkeypatch.setattr(tools, "run_tool", lambda name, args: tools.ToolResult(name, args, True, "Saved ✓"))
    FakeCompletions.script = [['save_memory({"fact": "likes tea"})'], ["Noted."]]
    _send(win, "remember that I like tea"); _wait_idle(win)
    shown = win._last_ai_bubble._full_text
    assert "save_memory" not in shown and shown == "Done."                 # a plain command: done after the one round

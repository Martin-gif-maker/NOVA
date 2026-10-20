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


# ── a tool call the provider refused (Groq checks it against the tool's schema) is tried again ──
class _RefusesOnce:
    """Groq's answer when the model sends null for an optional text argument - then a valid call."""
    def __init__(self):
        self.sent = []; self.chat = types.SimpleNamespace(completions=self)
    def create(self, **kw):
        self.sent.append([dict(m) for m in kw["messages"]])
        if len(self.sent) == 1:
            raise Exception("Error code: 400 - {'error': {'message': 'Tool call validation failed: parameters for tool "
                            "take_screenshot did not match schema: errors: [`/save_path`: expected string, but got null]', "
                            "'type': 'invalid_request_error', 'code': 'tool_use_failed'}}")
        if len(self.sent) == 2: return iter([_C(_D(tool_calls=[_tc(0, "c1", "take_screenshot", "{}")]))])
        return iter([_C(_D(content="Saved to your Desktop."))])


def test_a_refused_tool_call_is_tried_again_with_the_reason(app, monkeypatch):
    import providers
    assert providers.classify_error(Exception("… 'code': 'tool_use_failed' …"))[0] == "tool_json"
    monkeypatch.setattr(workers.AIWorker, "_sleep", lambda self, s: True)
    ran = []
    shot = "Screenshot saved: ~/Desktop/Screen 10.24.png (a browser with a news site)"          # not a bare "done": a next round
    monkeypatch.setattr(tools, "run_tool", lambda name, args: (ran.append(name), tools.ToolResult(name, args, True, shot))[1])
    client = _RefusesOnce()
    w = workers.AIWorker(client, [{"role": "system", "content": "x"}, {"role": "user", "content": "take a screenshot"}],
                         models.fast_model_id())
    got, errors = [], []
    w.response_ready.connect(lambda text, msgs: got.append((text, msgs))); w.error_occurred.connect(lambda *e: errors.append(e))
    w.run()
    assert errors == [] and ran == ["take_screenshot"]
    retry = client.sent[1][-1]
    assert retry["role"] == "user" and "refused your last tool call" in retry["content"] and "save_path" in retry["content"]
    assert all("refused your last tool call" not in str(m.get("content")) for m in client.sent[2])   # only that once
    (_text, kept), = got
    assert all("refused your last tool call" not in str(m.get("content")) for m in kept)              # not in the chat


def test_groq_is_told_that_optional_arguments_may_be_empty():
    import providers, schemas
    tools_ = [t for t in schemas.TOOLS_SCHEMA if t["function"]["name"] in ("take_screenshot", "control_volume")]
    sent = {t["function"]["name"]: t["function"]["parameters"] for t in providers.nullable_optionals(tools_)}
    assert sent["take_screenshot"]["properties"]["save_path"]["type"] == ["string", "null"]
    vol = sent["control_volume"]["properties"]
    assert vol["action"]["type"] == "string" and None not in vol["action"]["enum"]          # required: stays as it is
    assert vol["level"]["type"] == ["integer", "null"]
    assert schemas.TOOLS_SCHEMA[[t["function"]["name"] for t in schemas.TOOLS_SCHEMA].index("take_screenshot")][
        "function"]["parameters"]["properties"]["save_path"]["type"] == "string"           # NOVA's own copy untouched
    clean, problem = tools.validate_args("take_screenshot", {"save_path": None})
    assert clean == {} and problem == ""                                                    # null = not given, not "None"
    assert "missing" in tools.validate_args("control_volume", {"action": None})[1]

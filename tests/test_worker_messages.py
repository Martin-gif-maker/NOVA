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

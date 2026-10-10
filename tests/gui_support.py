"""Shared GUI test support: a fake Groq client and the `app` / `win` fixtures."""
import time, types
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
import main, tools, workers, models, providers, win_account
import paths

class _D:
    def __init__(s, content=None, tool_calls=None): s.content = content; s.tool_calls = tool_calls
class _C:
    def __init__(s, d): s.choices = [types.SimpleNamespace(delta=d)]
def _tc(i, id_, name, args):
    return types.SimpleNamespace(index=i, id=id_, function=types.SimpleNamespace(name=name, arguments=args))

class FakeCompletions:
    script = []
    big_fails = 0          # number of 429s to raise for the big model
    models = []
    tools = []             # per call: the names of the tools that were offered
    def create(self, **kw):
        FakeCompletions.models.append(kw["model"])
        FakeCompletions.tools.append([t["function"]["name"] for t in kw.get("tools") or []])
        if FakeCompletions.big_fails > 0 and kw["model"] != models.fast_model_id():
            FakeCompletions.big_fails -= 1
            raise Exception("Error code: 429 - rate_limit_exceeded. Please try again in 30s")
        step = FakeCompletions.script.pop(0) if FakeCompletions.script else ["ok"]
        def gen():
            for item in step:
                if item == "SLEEP": time.sleep(0.15)
                elif isinstance(item, str): yield _C(_D(content=item))
                else: yield _C(_D(tool_calls=[item]))
        return gen()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    for name, rel in (("CONFIG_FILE", "c.json"), ("HISTORY_FILE", "h.json"), ("MEMORY_FILE", "m.json")):
        monkeypatch.setattr(paths, name, str(tmp_path / rel))
    monkeypatch.setattr(paths, "SESSIONS_DIR", str(tmp_path / "s"))
    monkeypatch.setattr(paths, "DOCS_FILE", str(tmp_path / "docs.json"))
    monkeypatch.setattr(paths, "SCHEDULE_FILE", str(tmp_path / "schedule.json"))
    monkeypatch.setattr(paths, "USAGE_FILE", str(tmp_path / "usage.log"))
    monkeypatch.setattr(tools, "MEMORY_FILE", str(tmp_path / "m.json"))
    monkeypatch.setattr(tools, "REMINDERS_FILE", str(tmp_path / "r.json"))
    monkeypatch.setattr(win_account, "_get_api_key", lambda *a, **k: "test-key")
    fake = types.SimpleNamespace(chat=types.SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(providers, "make_client", lambda *a, **k: fake)
    models.activate("groq")
    W = main.AssistantWindow
    monkeypatch.setattr(W, "_run_onboarding", lambda self, k="": k)
    for name in ("_start_wake_listener", "_maybe_morning_briefing", "_start_spotify_monitor",
                 "_generate_followups", "_generate_session_title", "_tag_memories", "_refresh_documents"):
        monkeypatch.setattr(W, name, lambda self: None)
    monkeypatch.setattr(main.plat, "start_global_hotkey", lambda cb: True)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    FakeCompletions.script = []; FakeCompletions.big_fails = 0; FakeCompletions.models = []; FakeCompletions.tools = []
    workers._MODEL_COOLDOWN.clear()
    w = W()
    w.config["onboarded"] = True
    w._pump = lambda ms=300: _pump(app, ms)
    yield w
    w._shutdown()


def _pump(app, ms):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents(); time.sleep(0.01)

def _wait_idle(w, timeout=8):
    end = time.time() + timeout
    while w._busy and time.time() < end: w._pump(50)
    assert not w._busy


def _send(w, text):
    w.input_field.setText(text); w._send()

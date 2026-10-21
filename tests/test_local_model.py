"""Running NOVA on this computer: Ollama's state, its download of the recommended model, and Settings → AI."""
import json, types
import pytest
import providers


class _Stream:
    """What Ollama's /api/pull streams back: one JSON object per line."""
    def __init__(self, lines): self.lines = [json.dumps(x).encode() for x in lines]
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def raise_for_status(self): pass
    def iter_lines(self): yield from self.lines


@pytest.fixture
def ollama(monkeypatch):
    import requests
    sent = types.SimpleNamespace(gets=[], posts=[], stream=[], tags={"models": [{"name": "llama3.1:latest"}]}, up=True)
    def get(url, timeout=None):
        sent.gets.append(url)
        if not sent.up: raise requests.ConnectionError("refused")
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: sent.tags)
    def post(url, json=None, stream=False, timeout=None):
        sent.posts.append((url, json)); return _Stream(sent.stream)
    monkeypatch.setattr(requests, "get", get); monkeypatch.setattr(requests, "post", post)
    return sent


def test_ollama_says_which_models_it_has_or_that_it_is_not_running(ollama):
    assert providers.ollama_root("http://localhost:11434/v1") == "http://localhost:11434"
    assert providers.ollama_models() == {"llama3.1:latest", "llama3.1"}                 # "name:latest" is "name"
    assert ollama.gets == ["http://localhost:11434/api/tags"]
    ollama.up = False
    assert providers.ollama_models() is None


def test_the_download_reports_progress_over_all_its_parts(ollama):
    ollama.stream = [{"status": "pulling manifest"},
                     {"status": "pulling a", "digest": "sha256:a", "total": 900, "completed": 450},
                     {"status": "pulling b", "digest": "sha256:b", "total": 100, "completed": 100},
                     {"status": "pulling a", "digest": "sha256:a", "total": 900, "completed": 900},
                     {"status": "success"}]
    seen = []
    providers.ollama_pull("qwen3:4b-instruct", progress=seen.append)
    assert ollama.posts == [("http://localhost:11434/api/pull", {"model": "qwen3:4b-instruct", "stream": True})]
    assert seen == [0.5, 0.55, 1.0]


@pytest.mark.parametrize("lines, says", [
    ([{"error": "pull model manifest: file does not exist"}], "does not exist"),
    ([{"status": "pulling a", "digest": "sha256:a", "total": 9, "completed": 1}], "stopped before"),
])
def test_a_failed_download_says_why(ollama, lines, says):
    ollama.stream = lines
    with pytest.raises(RuntimeError, match=says):
        providers.ollama_pull("qwen3:4b-instruct")


def test_a_download_can_be_cancelled(ollama):
    ollama.stream = [{"status": "pulling a", "digest": "sha256:a", "total": 9, "completed": 1}, {"status": "success"}]
    with pytest.raises(RuntimeError, match="cancelled"):
        providers.ollama_pull("qwen3:4b-instruct", cancelled=lambda: True)


def test_nova_runs_the_recommended_model_on_ollama_by_default():
    m = providers.LOCAL_MODEL["id"]
    assert all(mid == m for mid, _ in providers.PROVIDERS["ollama"]["models"].values())
    assert all(slot[0] == m for slot in providers.PROVIDERS["ollama"]["preferred"].values())


def test_settings_offers_the_local_model_in_one_click(monkeypatch):
    from PySide6.QtWidgets import QApplication
    import settings_dialog, themes
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_dialog.plat, "autostart_enabled", lambda: False)
    monkeypatch.setattr(providers, "ollama_models", lambda url="": None)
    d = settings_dialog.SettingsDialog({}, themes.THEMES["nova"])
    assert d._local_row.isHidden()                                                   # Groq: nothing about Ollama
    d._select(d._provider_cb, "ollama")
    assert not d._local_row.isHidden()
    d._on_local_state(None)
    assert d._local_btn.text() == "Check again" and "not running" in d._local_status.text()
    d._on_local_state({"llama3.1"})
    assert d._local_btn.text() == "Download Qwen3 4B (2.5 GB)"
    d._on_local_progress(0.42, "")
    assert d._local_status.text() == "Downloading… 42%"
    d._on_local_progress(1.0, "ok")
    assert all(cb.currentText() == "qwen3:4b-instruct" for cb in d._slot_cbs.values())
    assert d._local_btn.text() == "Use Qwen3 4B" and "after you press Save" in d._local_status.text()
    d._on_local_progress(-1.0, "pull model manifest: file does not exist")
    assert d._local_status.text().startswith("✗ ")

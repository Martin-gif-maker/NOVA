"""Usage and cost: tokens per provider / model and the estimated cost."""
import json, time, types
import pytest
import usage, providers, paths, storage


def test_records_add_up_per_model_and_period(data_dir):
    usage.record("groq", "openai/gpt-oss-120b", 1200, 300)
    usage.record("groq", "openai/gpt-oss-120b", 800, 200)
    usage.record("anthropic", "claude-opus-5-5", 1_000_000, 100_000)
    usage.record("ollama", "llama3.1", 5000, 5000)
    usage.record("groq", "x", 0, 0)                                           # nothing reported: not recorded
    old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 10 * 86400))
    storage.append_line(paths.USAGE_FILE, json.dumps({"t": old, "provider": "groq", "model": "old-model", "in": 9, "out": 9}))
    today = usage.summary(usage.entries(1), {})
    by = {r["model"]: r for r in today["rows"]}
    assert set(by) == {"openai/gpt-oss-120b", "claude-opus-5-5", "llama3.1"}
    assert by["openai/gpt-oss-120b"]["requests"] == 2 and by["openai/gpt-oss-120b"]["in"] == 2000 and by["openai/gpt-oss-120b"]["out"] == 500
    assert by["claude-opus-5-5"]["cost"] == pytest.approx(4.0 + 2.0)          # 1M in at $4, 0.1M out at $20
    assert by["llama3.1"]["cost"] == 0.0                                      # runs on this Mac: free
    assert by["openai/gpt-oss-120b"]["cost"] is None and today["unpriced"] == ["openai/gpt-oss-120b"]
    assert today["cost"] == pytest.approx(6.0) and today["requests"] == 4
    assert today["rows"][0]["model"] == "claude-opus-5-5"                     # biggest user first
    assert "old-model" in {r["model"] for r in usage.summary(usage.entries(30), {})["rows"]}


def test_prices_can_be_set_and_dated_ids_use_the_base_price():
    assert usage.price_for("claude-opus-5-5-20260801", "anthropic", {}) == (4.0, 20.0)
    assert usage.price_for("gpt-x", "openai", {}) is None
    assert usage.price_for("gpt-x", "openai", {"gpt-x": [1.5, 6]}) == (1.5, 6.0)
    assert usage.price_for("claude-opus-5-5", "anthropic", {"claude-opus-5-5": [9, 9]}) == (9.0, 9.0)     # your price wins
    assert usage.price_for("m", "openai", {"m": "nonsense"}) is None
    assert usage.cost(500_000, 250_000, (2.0, 10.0)) == pytest.approx(3.5)
    assert usage.money(None) == "—" and usage.money(0) == "$0" and usage.money(0.00123) == "$0.0012" and usage.money(12.345) == "$12.35"
    assert usage.count(1234567) == "1 234 567"


def test_usage_is_metered_for_plain_and_streamed_answers(data_dir):
    client = types.SimpleNamespace(provider_id="openai")
    reply = types.SimpleNamespace(usage=types.SimpleNamespace(prompt_tokens=50, completion_tokens=7))
    assert providers.metered(client, {"model": "gpt-a"}, reply) is reply       # the answer itself is untouched
    chunks = [types.SimpleNamespace(usage=None, x_groq=None), types.SimpleNamespace(usage=None, x_groq=types.SimpleNamespace(
              usage=types.SimpleNamespace(prompt_tokens=120, completion_tokens=30))), types.SimpleNamespace(
              usage=types.SimpleNamespace(prompt_tokens=5, completion_tokens=1))]
    out = list(providers.metered(client, {"model": "gpt-b", "stream": True}, iter(chunks)))
    assert out == chunks
    rows = {r["model"]: r for r in usage.summary(usage.entries(1))["rows"]}
    assert (rows["gpt-a"]["in"], rows["gpt-a"]["out"]) == (50, 7) and (rows["gpt-b"]["in"], rows["gpt-b"]["out"]) == (125, 31)
    assert rows["gpt-a"]["provider"] == "openai"


def test_a_stream_that_is_abandoned_still_records_what_arrived(data_dir):
    client = types.SimpleNamespace(provider_id="groq")
    def gen():
        yield types.SimpleNamespace(usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=2), x_groq=None)
        yield types.SimpleNamespace(usage=None, x_groq=None)
    stream = providers.metered(client, {"model": "m", "stream": True}, gen())
    next(stream); stream.close()                                               # the user pressed ✕ mid-answer
    assert usage.summary(usage.entries(1))["rows"][0]["in"] == 10


def test_clients_know_which_provider_they_are(monkeypatch):
    c = providers.make_client("ollama")
    assert c.provider_id == "ollama"
    c = providers.make_client("groq", "gsk_test")
    assert c.provider_id == "groq"


def test_usage_is_encrypted_with_the_rest(data_dir):
    usage.record("groq", "secret-model-name", 10, 10)
    storage.convert_all(True)
    assert "secret-model-name" not in open(paths.USAGE_FILE).read() and usage.entries(1)[0]["model"] == "secret-model-name"
    usage.record("groq", "second", 1, 1); assert len(usage.entries(1)) == 2
    storage.convert_all(False)


def test_usage_window_and_price_editing(app, data_dir, monkeypatch):
    import dialogs, themes
    usage.record("groq", "openai/gpt-oss-120b", 2_000_000, 500_000); usage.record("anthropic", "claude-sonnet-5-5", 1000, 1000)
    d = dialogs.UsageDialog(themes.THEMES["nova"], {})
    assert d.table.rowCount() == 2 and d.table.item(0, 1).text() == "openai/gpt-oss-120b" and d.table.item(0, 5).text() == "—"
    assert d.table.item(0, 3).text() == "2 000 000" and "No price is set for: openai/gpt-oss-120b" in d.total.text()
    answers = iter([(0.15, 0.6), (), None])
    monkeypatch.setattr(dialogs.UsageDialog, "_ask_price", lambda self, model, current: next(answers))
    d.table.selectRow(0); d._set_price()
    assert d.prices() == {"openai/gpt-oss-120b": [0.15, 0.6]} and d.table.item(0, 5).text() == "$0.60" and "No price" not in d.total.text()
    d.table.selectRow(0); d._set_price(); assert "two numbers" in d.total.text()            # nonsense typed: explained, nothing changed
    d.table.selectRow(0); d._set_price(); assert d.prices() == {"openai/gpt-oss-120b": [0.15, 0.6]}    # cancelled
    empty = dialogs.UsageDialog(themes.THEMES["nova"], {})
    empty.period.setCurrentIndex(0)
    assert dialogs.UsageDialog.PERIODS[-1][1] == 365


def test_price_prompt_parses_what_people_type(app, monkeypatch):
    import dialogs, themes
    from PySide6.QtWidgets import QInputDialog
    d = dialogs.UsageDialog(themes.THEMES["nova"], {})
    for typed, want in (("4 / 20", (4.0, 20.0)), ("0,15/0.6", (0.15, 0.6)), ("$2 in, $10 out", (2.0, 10.0)), ("free", ()), ("1 2 3", ())):
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (typed, True)))
        assert d._ask_price("m", None) == want, typed
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    assert d._ask_price("m", (4.0, 20.0)) is None

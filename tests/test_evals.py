"""The evaluation set and its harness (evals/): the cases are valid, routing stays complete, and grading is right."""
import types
import pytest
import models, tools
from evals import harness
from gui_support import FakeCompletions, _C, _D, _tc

CASES = harness.load_cases()
BY_ID = {c["id"]: c for c in CASES}


def test_the_cases_are_valid_and_cover_both_languages():
    assert harness.problems(CASES) == []
    assert len(CASES) >= 80
    langs = {harness.lang(c) for c in CASES}
    assert langs == {"en", "bg"}
    assert sum(1 for c in CASES if not c["expect"]) >= 5                       # plain answers, no tool
    assert sum(1 for c in CASES if c.get("forbid")) >= 2                       # instructions hidden in a page / file


def test_every_request_gets_the_tools_it_needs_without_bloat():
    s = harness.routing_summary(harness.routing(CASES))
    assert s["misses"] == [], s["misses"]                                      # no extra more_tools round for any case
    assert s["avg_tokens"] < 1400, s["avg_tokens"]                             # tool definitions stay cheap


def test_grading():
    maps = BY_ID["en-maps"]
    assert harness.score(maps, [("open_maps", {"location": "Paris, France"})])["ok"]
    wrong = harness.score(maps, [("open_maps", {"location": "London"})])
    assert wrong["tool_ok"] and not wrong["args_ok"] and not wrong["ok"]
    assert harness.score(BY_ID["bg-maps"], [("open_maps", {"location": "Sofia"})])["ok"]       # either spelling
    assert harness.score(BY_ID["en-notify"], [("send_notification", {"title": "NOVA", "message": "Stand up!"})])["ok"]
    chain = BY_ID["en-chain-map-weather"]
    both = [("get_weather", {"location": "Paris"}), ("open_maps", {"location": "Paris"})]
    assert harness.score(chain, both)["ok"] and not harness.score(chain, both[:1])["ok"]
    chat = BY_ID["en-chat-hello"]
    assert harness.score(chat, [])["ok"] and not harness.score(chat, [("get_weather", {})])["ok"]
    assert harness.score(maps, [("more_tools", {"group": "files"}), ("open_maps", {"location": "paris"})])["ok"]


@pytest.fixture
def fake_model(app, monkeypatch):
    """A scripted model, and no real tool may run (only more_tools, which just switches a group on)."""
    real = tools.execute_tool
    def guard(name, args):
        assert name == "more_tools", f"a real tool ran during an eval: {name}"
        return real(name, args)
    monkeypatch.setattr(tools, "execute_tool", guard)
    FakeCompletions.script = []
    models.activate("groq")
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=FakeCompletions()))


def test_a_live_run_grades_what_the_model_did(fake_model):
    FakeCompletions.script = [[_tc(0, "c1", "open_maps", '{"location": "Paris, France"}')]]
    r = harness.run_case(BY_ID["en-maps"], fake_model, models.fast_model_id())
    assert r["ok"] and r["calls"] == [["open_maps", {"location": "Paris, France"}]] and r["reply"]


def test_a_hidden_instruction_that_is_followed_is_caught(fake_model):
    case = BY_ID["en-injection-page"]
    FakeCompletions.script = [[_tc(0, "c1", "read_webpage", '{"url": "https://example.com/recipe"}')],
                              [_tc(0, "c2", "run_shell_command", '{"command": "rm -rf ~/Documents"}')],
                              ["Here is the recipe."]]
    r = harness.run_case(case, fake_model, models.fast_model_id())
    assert r["args_ok"] and r["forbidden"] == ["run_shell_command"] and not r["ok"]
    assert r["unguarded"] == []                                                   # …but NOVA would have asked first
    assert harness.live_summary([r])["guarded_injection"] == "1/1"
    assert tools.run_tool.__name__ == "run_tool"                                 # the real tools are back afterwards


def test_a_model_that_asks_for_more_tools_still_counts(fake_model):
    FakeCompletions.script = [[_tc(0, "c1", "more_tools", '{"group": "shortcuts"}')],
                              [_tc(0, "c2", "list_shortcuts", "{}")], ["You have three shortcuts."]]
    r = harness.run_case(BY_ID["en-shortcut-list"], fake_model, models.fast_model_id())
    assert r["ok"] and [n for n, _ in r["calls"]] == ["list_shortcuts"]
    s = harness.live_summary([r])
    assert s["all"]["ok_pct"] == 100.0 and "| English | 1 |" in harness.markdown(live_sum=s)


# ── long runs: a token budget, the provider's limit, and carrying on later ──
def test_a_run_alternates_the_languages():
    order = [harness.lang(c) for c in harness.interleave(CASES)]
    assert order[:4] == ["en", "bg", "en", "bg"] and sorted(order) == sorted(harness.lang(c) for c in CASES)


class _Counted:
    """A model that answers in a word and, like a real provider, says what the request cost."""
    def __init__(self): self.chat = types.SimpleNamespace(completions=self)
    def create(self, **kw):
        chunk = _C(_D(content="Hi!")); chunk.usage = types.SimpleNamespace(prompt_tokens=900, completion_tokens=5)
        return iter([chunk])


def test_a_budget_stops_the_run_before_the_next_request(fake_model):
    chats = [BY_ID["en-chat-hello"]] * 3
    results, why = harness.run_all(chats, _Counted(), models.fast_model_id(), budget=1000)
    assert len(results) == 2 and results[0]["tok_in"] == 900 and "budget of 1000 tokens" in why


def test_the_providers_limit_stops_the_run_and_that_request_is_not_counted(fake_model, monkeypatch):
    import workers
    monkeypatch.setattr(workers.AIWorker, "_sleep", lambda self, s: True)            # no real waiting
    class Limited:
        chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(
            Exception("Error code: 429 - Rate limit reached on tokens per day (TPD): Limit 200000, Used 199990"))))
    results, why = harness.run_all([BY_ID["en-maps"], BY_ID["en-chat-hello"]], Limited(), models.fast_model_id())
    assert results == [] and "tokens per day" in why


def test_a_stopped_run_is_finished_later_into_the_same_file(fake_model, monkeypatch, tmp_path):
    from evals import __main__ as runner
    import keystore, providers
    monkeypatch.setattr(harness, "HERE", str(tmp_path))
    monkeypatch.setattr(keystore, "_get_api_key", lambda p: "test-key")
    monkeypatch.setattr(providers, "make_client", lambda *a: _Counted())
    ids = "en-chat-hello,bg-chat-hello"
    assert runner.main(["live", "--model", models.fast_model_id(), "--only", ids, "--budget", "1"]) == 0
    (first,) = (tmp_path / "results").glob("*.json")
    import json
    saved = json.loads(first.read_text())
    assert len(saved["results"]) == 1 and saved["left"] == 1
    assert runner.main(["live", "--model", models.fast_model_id(), "--only", ids, "--resume", str(first)]) == 0
    saved = json.loads(first.read_text())
    assert sorted(r["id"] for r in saved["results"]) == ["bg-chat-hello", "en-chat-hello"] and saved["left"] == 0
    assert "not run yet" not in (tmp_path / "results" / (first.stem + ".md")).read_text()

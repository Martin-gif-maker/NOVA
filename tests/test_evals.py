"""The evaluation set and its harness (evals/): the cases are valid, routing stays complete, and grading is right."""
import types
import pytest
import models, tools
from evals import harness
from gui_support import FakeCompletions, _tc

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

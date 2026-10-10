"""Tool definitions cost tokens on every request, so groups of tools travel only when the chat is about them."""
import json
import pytest
import schemas, tools, paths

ALWAYS = {"search_web_and_read", "read_webpage", "open_application", "open_url", "open_maps", "save_memory", "save_note",
          "set_reminder", "get_weather"}
CALENDAR = set(schemas.GROUPS["calendar"]["tools"]); MAIL = set(schemas.GROUPS["mail"]["tools"])


def names(text, sticky=()):
    out, active = schemas.select_tools(text, sticky)
    return {s["function"]["name"] for s in out}, active


@pytest.fixture(autouse=True)
def empty_library(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DOCS_FILE", str(tmp_path / "docs.json"))


def test_a_plain_question_carries_only_the_everyday_tools():
    got, active = names("what is the capital of France?")
    assert ALWAYS <= got and "more_tools" in got and active == set()
    for group in schemas.GROUPS.values():
        assert not (set(group["tools"]) & got), group["about"]
    all_names = {s["function"]["name"] for s in schemas.TOOLS_SCHEMA}
    assert len(got) <= 12 and len(all_names) >= 50                           # a dozen of fifty-odd: a real saving
    plain = len(json.dumps(schemas.select_tools("hello")[0]))
    assert plain < 3600, plain                                               # sent with every request: keep it small


@pytest.mark.parametrize("text, group", [
    ("what's on my calendar tomorrow?", "calendar"), ("add a meeting with Ann on Friday at 3", "calendar"),
    ("remind me on my phone to call the bank", "calendar"), ("какво имам в календара утре", "calendar"),
    ("draft a reply to this email", "mail"), ("напиши имейл до Иван", "mail"),
    ("summarize this page", "browser"), ("what does the article in my browser say", "browser"), ("обобщи тази страница", "browser"),
    ("what does my lease contract say about the deposit", "documents"), ("index the PDF on my desktop", "documents"),
    ("every morning at 8 give me the news", "schedule"), ("всеки ден в 9 ми дай времето", "schedule"),
    ("at 17:30 remind me to stretch", "schedule"), ("run my Morning Routine shortcut", "shortcuts"),
    ("delete old.txt from my desktop", "files"), ("what is in ~/Downloads?", "files"), ("изтрий файла от работния плот", "files"),
    ("what's my battery level?", "system"), ("turn the volume up", "system"), ("lock the screen", "system"),
    ("намали звука", "system"), ("колко е батерията", "system"),
    ("skip to the next song", "music"), ("пусни следващата песен", "music"),
    ("what's in my clipboard?", "clipboard"), ("type hello in the app I am using", "clipboard"),
    ("run ls -la in the terminal", "code"), ("use python to add these numbers", "code"), ("изчисли това с python", "code"),
    ("read my notes", "notes"), ("what do you know about me?", "notes"), ("забрави какво казах за работата", "notes"),
])
def test_the_right_group_comes_along(text, group):
    got, active = names(text)
    assert group in active and set(schemas.GROUPS[group]["tools"]) <= got, text


def test_groups_stay_on_once_used_and_the_fallback_lists_only_what_is_off():
    got, active = names("thanks!", sticky={"mail"})
    assert MAIL <= got and active == {"mail"}
    out, _ = schemas.select_tools("hello", {"mail", "calendar"})
    meta = next(s for s in out if s["function"]["name"] == "more_tools")["function"]
    assert meta["parameters"]["properties"]["group"]["enum"] == ["files", "system", "clipboard", "music", "notes", "code",
                                                                 "browser", "documents", "schedule", "shortcuts"]
    assert "calendar events" not in meta["description"] and "Apple Shortcuts" in meta["description"]
    out, _ = schemas.select_tools("x", set(schemas.GROUPS))
    assert "more_tools" not in {s["function"]["name"] for s in out}          # everything is on: nothing left to offer


def test_documents_come_along_whenever_something_is_indexed(tmp_path):
    import docs
    assert "search_documents" not in names("hello")[0]
    f = tmp_path / "a.txt"; f.write_text("some text"); docs.library().add_file(str(f))
    assert "search_documents" in names("hello")[0]


def test_connected_servers_are_groups_too(monkeypatch):
    monkeypatch.setattr(tools, "MCP_TOOLS", {"mcp__github__list_issues": {"server": "github", "tool": "list_issues"},
                                             "mcp__github__open_pr": {"server": "github", "tool": "open_pr"}})
    extra = [{"type": "function", "function": {"name": n, "description": "", "parameters": {"type": "object", "properties": {}}}}
             for n in tools.MCP_TOOLS]
    monkeypatch.setattr(schemas, "TOOLS_SCHEMA", schemas.TOOLS_SCHEMA + extra)
    got, active = names("what is the weather")
    assert "mcp__github__list_issues" not in got                             # 2 … or 40 server tools do not ride along for nothing
    meta = next(s for s in schemas.select_tools("hi")[0] if s["function"]["name"] == "more_tools")["function"]
    assert "github" in meta["parameters"]["properties"]["group"]["enum"] and "list_issues" in meta["description"]
    got, active = names("list my open GitHub issues")
    assert {"mcp__github__list_issues", "mcp__github__open_pr"} <= got and "mcp:github" in active
    assert schemas.group_of("mcp__github__open_pr") == "mcp:github" and schemas.group_of("read_file") == "files"
    assert schemas.group_of("get_weather") is None                           # the everyday tools belong to no group
    tools.begin_request()
    assert "Enabled: mcp__github__list_issues, mcp__github__open_pr" in tools.more_tools("GitHub") and tools.REQUESTED_GROUPS == {"mcp:github"}


def test_more_tools_switches_a_group_on_for_this_request():
    tools.begin_request()
    out = tools.more_tools("calendar")
    assert out.startswith("Enabled: get_calendar_events") and tools.REQUESTED_GROUPS == {"calendar"}
    assert isinstance(tools.more_tools("teleport"), tools.ToolFailure) and "calendar" in tools.more_tools("teleport")
    tools.begin_request(); assert tools.REQUESTED_GROUPS == set()            # a new request starts clean
    assert tools.needs_confirmation("more_tools", {"group": "mail"}) == ""    # switching tools on is not an action


def test_new_tool_definitions_stay_lean():
    """Each definition is sent with every request: keep the on-demand ones short."""
    for group in schemas.GROUPS.values():
        for name in group["tools"]:
            spec = next(s for s in schemas.TOOLS_SCHEMA if s["function"]["name"] == name)
            assert len(json.dumps(spec)) < 620, (name, len(json.dumps(spec)))


# ── in the window ──────────────────────────────────────────────────
def test_model_can_switch_a_group_on_mid_request_and_it_sticks(win):
    from gui_support import FakeCompletions, _send, _tc, _wait_idle
    FakeCompletions.script = [[_tc(0, "c1", "more_tools", json.dumps({"group": "calendar"}))], ["You are free on Friday."]]
    _send(win, "am I free on Friday?"); _wait_idle(win)
    first, second = FakeCompletions.tools[0], FakeCompletions.tools[1]
    assert "get_calendar_events" not in first and "more_tools" in first      # the question had no calendar word in it
    assert CALENDAR <= set(second)                                           # …after more_tools the calendar tools are there
    assert win._tool_groups == {"calendar"}
    FakeCompletions.script = [["Sure."]]
    _send(win, "and on Saturday?"); _wait_idle(win)
    assert CALENDAR <= set(FakeCompletions.tools[2])                         # still on for the follow-up
    win._reset_chat_state(); assert win._tool_groups == set()                # a new chat starts lean again


def test_keyword_requests_get_their_tools_at_once(win):
    from gui_support import FakeCompletions, _send, _wait_idle
    FakeCompletions.script = [["ok"]]
    _send(win, "draft an email to ann@example.com about lunch"); _wait_idle(win)
    assert MAIL <= set(FakeCompletions.tools[0]) and not (CALENDAR & set(FakeCompletions.tools[0]))


def test_an_unused_group_stops_travelling_after_a_while_and_comes_back_when_needed(win):
    from gui_support import FakeCompletions, _send, _tc, _wait_idle
    FakeCompletions.script = [[_tc(0, "c1", "get_battery", "{}")], ["81%."]]
    _send(win, "how charged is my laptop?"); _wait_idle(win)
    assert "system" in win._tool_groups
    for n, text in enumerate(("thanks", "tell me a joke", "another one")):
        FakeCompletions.script = [["ok"]]
        _send(win, text); _wait_idle(win)
        assert ("system" in win._tool_groups) == (n < win.GROUP_MEMORY), (n, win._tool_groups)
    assert "get_battery" not in FakeCompletions.tools[-1]                    # three requests later it no longer costs anything
    FakeCompletions.script = [["ok"]]
    _send(win, "and the battery now?"); _wait_idle(win)
    assert "get_battery" in FakeCompletions.tools[-1]                        # the word brings the tools straight back


def test_only_the_last_two_requests_decide_which_tools_come_along(win):
    from gui_support import FakeCompletions, _send, _wait_idle
    for text in ("draft an email to ann@example.com", "thanks", "what is 2+2", "and 3+3?"):
        FakeCompletions.script = [["ok"]]
        _send(win, text); _wait_idle(win)
    first, second, third, fourth = FakeCompletions.tools[:4]
    assert "draft_email" in first and "draft_email" in second                # the request itself and the follow-up
    assert "draft_email" not in third and "draft_email" not in fourth        # …then the mail tools stop riding along

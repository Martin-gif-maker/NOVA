"""Calendar, Reminders, Mail, browser and Shortcuts tools. The real apps are never touched: the EventKit helper,
AppleScript and the `shortcuts` command are replaced by fakes."""
import datetime, json, sys, types
import pytest
import mac_apps, tools, eventkit_helper

mac_only = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


@pytest.fixture
def kit(monkeypatch):
    """Records what is asked of the EventKit helper and answers from a script."""
    calls = []
    answers = {"events": {"ok": True, "events": []}, "add_event": {"ok": True, "calendar": "Home"},
               "reminders": {"ok": True, "reminders": [], "total": 0}, "add_reminder": {"ok": True, "list": "Reminders"}}
    def fake(request, timeout=130):
        calls.append(request); return answers[request["op"]]
    monkeypatch.setattr(mac_apps, "_eventkit", fake)
    return types.SimpleNamespace(calls=calls, answers=answers)


# ── Calendar ───────────────────────────────────────────────────────
def test_calendar_defaults_to_today_and_formats_events(kit):
    assert mac_apps.calendar_events().startswith("No events")
    today = datetime.datetime.combine(datetime.date.today(), datetime.time())
    assert kit.calls[0] == {"op": "events", "start": today.timestamp(), "end": (today + datetime.timedelta(days=1)).timestamp()}
    nine = today.replace(hour=9).timestamp()
    kit.answers["events"] = {"ok": True, "events": [
        {"title": "Standup", "start": nine, "end": nine + 900, "all_day": False, "calendar": "Work", "location": "Zoom"},
        {"title": "Birthday", "start": today.timestamp(), "end": today.timestamp() + 86399, "all_day": True, "calendar": "Home", "location": ""}]}
    out = mac_apps.calendar_events("2026-10-09T00:00", "2026-10-10")
    assert "09:00–09:15  Standup @ Zoom  [Work]" in out and "all day" in out and "Birthday  [Home]" in out
    assert kit.calls[-1]["start"] == datetime.datetime(2026, 10, 9).timestamp() and kit.calls[-1]["end"] == datetime.datetime(2026, 10, 10).timestamp()


def test_add_event_fills_in_a_sensible_end_and_rejects_nonsense(kit):
    out = mac_apps.add_calendar_event("Dentist", "2026-10-09T15:00")
    req = kit.calls[-1]
    assert req["title"] == "Dentist" and req["end"] - req["start"] == 3600 and "15:00–16:00" in out and "“Home”" in out
    mac_apps.add_calendar_event("Trip", "2026-10-09T15:00", all_day=True)
    req = kit.calls[-1]
    assert req["all_day"] is True and datetime.datetime.fromtimestamp(req["start"]).hour == 0 and req["end"] > req["start"]
    mac_apps.add_calendar_event("Backwards", "2026-10-09T15:00", "2026-10-09T14:00")
    assert kit.calls[-1]["end"] - kit.calls[-1]["start"] == 3600                      # an end before the start is repaired
    for bad in (("", "2026-10-09T15:00"), ("X", "next friday-ish"), ("X", "")):
        with pytest.raises(mac_apps.AppError): mac_apps.add_calendar_event(*bad)


def test_reminders_list_and_add(kit):
    assert mac_apps.list_reminders() == "No open reminders."
    due = datetime.datetime(2026, 10, 9, 18, 0).timestamp()
    kit.answers["reminders"] = {"ok": True, "total": 2, "reminders": [{"title": "Buy milk", "due": due, "list": "Home"},
                                                                    {"title": "Call mom", "due": None, "list": "Family"}]}
    out = mac_apps.list_reminders()
    assert "Open reminders (2)" in out and "Buy milk  — due Fri 09 Oct 18:00  [Home]" in out and "Call mom  [Family]" in out
    assert "due Fri 09 Oct 18:00" in mac_apps.add_reminder("Pay rent", "2026-10-09 18:00")
    assert kit.calls[-1] == {"op": "add_reminder", "title": "Pay rent", "due": due, "notes": "", "list": ""}
    mac_apps.add_reminder("No date"); assert kit.calls[-1]["due"] is None
    with pytest.raises(mac_apps.AppError): mac_apps.add_reminder("   ")


def test_helper_answers_are_parsed_and_a_killed_helper_is_explained(monkeypatch):
    class R:
        def __init__(self, out, code=0): self.stdout = out; self.stderr = ""; self.returncode = code
    monkeypatch.setattr(mac_apps.subprocess, "run", lambda *a, **k: R("noise\n" + mac_apps.EVENTKIT_MARK + json.dumps({"ok": True, "events": [1]}) + "\n"))
    assert mac_apps._eventkit({"op": "events"}) == {"ok": True, "events": [1]}
    monkeypatch.setattr(mac_apps.subprocess, "run", lambda *a, **k: R(mac_apps.EVENTKIT_MARK + json.dumps({"ok": False, "error": "Calendar access is off"})))
    with pytest.raises(mac_apps.AppError, match="access is off"): mac_apps._eventkit({"op": "events"})
    monkeypatch.setattr(mac_apps.subprocess, "run", lambda *a, **k: R("", -9))               # macOS ended the helper
    with pytest.raises(mac_apps.AppError, match="Start NOVA from the NOVA app"): mac_apps._eventkit({"op": "events"})
    def slow(*a, **k): raise mac_apps.subprocess.TimeoutExpired("x", 1)
    monkeypatch.setattr(mac_apps.subprocess, "run", slow)
    with pytest.raises(mac_apps.AppError, match="in time"): mac_apps._eventkit({"op": "events"})


# ── the helper itself, against a stand-in for Apple's EventKit ─────
class _FakeStore:
    status = {0: 3, 1: 3}            # entity type -> authorization status
    grant = True
    saved = []
    def alloc(self): return self
    def init(self): return self
    @classmethod
    def authorizationStatusForEntityType_(cls, etype): return cls.status[etype]
    def requestFullAccessToEventsWithCompletion_(self, cb): cb(self.grant, None)
    def requestFullAccessToRemindersWithCompletion_(self, cb): cb(self.grant, None)
    def predicateForEventsWithStartDate_endDate_calendars_(self, a, b, c): return ("pred", a, b)
    def eventsMatchingPredicate_(self, pred): return []
    def defaultCalendarForNewEvents(self): return None
    def calendarsForEntityType_(self, t): return []


def _fake_eventkit(monkeypatch, **store_attrs):
    store = type("Store", (_FakeStore,), dict(store_attrs))
    fake = types.SimpleNamespace(EKEventStore=types.SimpleNamespace(
        alloc=lambda: store(), authorizationStatusForEntityType_=store.authorizationStatusForEntityType_),
        EKEntityTypeEvent=0, EKEntityTypeReminder=1, EKSpanThisEvent=0)
    monkeypatch.setitem(sys.modules, "EventKit", fake)
    return store


@mac_only
def test_helper_permission_paths(monkeypatch):
    _fake_eventkit(monkeypatch)
    assert eventkit_helper.handle({"op": "events", "start": 0, "end": 10}) == {"ok": True, "events": []}
    _fake_eventkit(monkeypatch, status={0: 2, 1: 2})                                   # denied in System Settings
    with pytest.raises(eventkit_helper.Refused, match="Privacy & Security → Calendars"): eventkit_helper.handle({"op": "events", "start": 0, "end": 1})
    _fake_eventkit(monkeypatch, status={0: 0, 1: 0}, grant=False)                      # asked now, user says no
    with pytest.raises(eventkit_helper.Refused): eventkit_helper.handle({"op": "events", "start": 0, "end": 1})
    _fake_eventkit(monkeypatch, status={0: 0, 1: 0}, grant=True)                       # asked now, user says yes
    assert eventkit_helper.handle({"op": "events", "start": 0, "end": 1})["ok"] is True
    _fake_eventkit(monkeypatch, status={0: 4, 1: 4})                                   # "add only" access
    with pytest.raises(eventkit_helper.Refused): eventkit_helper.handle({"op": "events", "start": 0, "end": 1})
    with pytest.raises(eventkit_helper.Refused, match="no calendar"): eventkit_helper.handle({"op": "add_event", "title": "x", "start": 0, "end": 1})
    assert eventkit_helper.handle({"op": "nope"})["ok"] is False


@mac_only
def test_helper_main_always_prints_one_answer_line(monkeypatch, capsys):
    import io
    _fake_eventkit(monkeypatch, status={0: 2, 1: 2})
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"op": "reminders"})))
    assert eventkit_helper.main() == 0
    line = [l for l in capsys.readouterr().out.splitlines() if l.startswith(eventkit_helper.MARK)][-1]
    answer = json.loads(line[len(eventkit_helper.MARK):])
    assert answer["ok"] is False and answer["refused"] is True and "Reminders" in answer["error"]
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    eventkit_helper.main()
    assert '"ok": false' in capsys.readouterr().out


# ── Mail ───────────────────────────────────────────────────────────
@pytest.fixture
def osa(monkeypatch):
    calls = []
    box = types.SimpleNamespace(calls=calls, result="OK")
    monkeypatch.setattr(mac_apps, "_osa", lambda script, *args, timeout=20: (calls.append((script, args)), box.result)[1])
    monkeypatch.setattr(mac_apps, "_running", lambda app: True)
    return box


def test_draft_email_passes_text_as_arguments_never_as_script(osa):
    nasty = 'Hi"\nend tell\ndo shell script "rm -rf ~"'
    out = mac_apps.draft_email("ann@example.com, bob@example.org", "Lunch?", nasty)
    script, args = osa.calls[-1]
    assert "not sent" not in script and nasty not in script and "rm -rf" not in script        # the script text is constant
    assert args == ("Lunch?", nasty, "ann@example.com", "bob@example.org")
    assert "send" not in script.lower().replace("send yourself", "")                          # there is no send command at all
    assert "review it and press Send yourself" in out
    for bad in ("not-an-address", "a@b", "x@y.z; evil"):
        with pytest.raises(mac_apps.AppError): mac_apps.draft_email(bad, "s", "b")
    with pytest.raises(mac_apps.AppError): mac_apps.draft_email("a@b.co", "", "")
    assert "Draft opened in Mail —" in mac_apps.draft_email("", "Note to self", "text")       # no recipient is fine


def test_selected_email_and_reply(osa):
    osa.result = "Ann Lee <ann@example.com>\nLunch on Friday?\n2026-10-08T12:30:00\nHi Martin,\nare you free?\nAnn"
    e = mac_apps.selected_email()
    assert e == {"sender": "Ann Lee <ann@example.com>", "address": "ann@example.com", "subject": "Lunch on Friday?",
                 "date": "2026-10-08 12:30", "body": "Hi Martin,\nare you free?\nAnn"}
    text = mac_apps.read_selected_email()
    assert text.startswith("From: Ann Lee <ann@example.com>\nSubject: Lunch on Friday?") and "are you free?" in text
    out = mac_apps.draft_email_reply("Yes, 1pm works.")
    script, args = osa.calls[-1]
    assert args[0] == "Re: Lunch on Friday?" and args[2] == "ann@example.com"
    assert args[1].startswith("Yes, 1pm works.\n\nOn 2026-10-08 12:30, Ann Lee <ann@example.com> wrote:\n> Hi Martin,\n> are you free?")
    assert "Reply to Ann Lee" in out
    osa.result = "NONE"
    with pytest.raises(mac_apps.AppError, match="No message is selected"): mac_apps.selected_email()


def test_mail_must_be_open(monkeypatch):
    monkeypatch.setattr(mac_apps, "_running", lambda app: False)
    with pytest.raises(mac_apps.AppError, match="Mail is not open"): mac_apps.selected_email()


def test_applescript_errors_become_plain_messages(monkeypatch):
    class R:
        def __init__(self, code, err): self.returncode = code; self.stderr = err; self.stdout = ""
    monkeypatch.setattr(mac_apps.subprocess, "run", lambda *a, **k: R(1, "execution error: Not authorized to send Apple events to Mail. (-1743)"))
    with pytest.raises(mac_apps.AppError, match="Privacy & Security → Automation"): mac_apps._osa("x")
    monkeypatch.setattr(mac_apps.subprocess, "run", lambda *a, **k: R(1, "31:40: execution error: Mail got an error: Can’t get item 1. (-1728)"))
    with pytest.raises(mac_apps.AppError, match="Can’t get item 1"): mac_apps._osa("x")
    seen = {}
    class Ok: returncode = 0; stdout = "result\n"; stderr = ""
    monkeypatch.setattr(mac_apps.subprocess, "run", lambda cmd, **k: (seen.update(cmd=cmd, input=k["input"]), Ok())[1])
    assert mac_apps._osa("the script", "a b", 'c"d') == "result" and seen["cmd"] == ["osascript", "-", "a b", 'c"d'] and seen["input"] == "the script"


# ── browser ────────────────────────────────────────────────────────
def test_browser_tab_prefers_the_app_you_were_in(osa, monkeypatch):
    monkeypatch.setattr(mac_apps, "_running", lambda app: app in ("Safari", "Google Chrome"))
    assert mac_apps.frontmost_browser("Google Chrome") == "Google Chrome" and mac_apps.frontmost_browser("Notes") == "Safari"
    osa.result = "https://example.org/a\nExample title\nThe page text\nsecond line"
    tab = mac_apps.browser_tab("Safari")
    assert tab == {"browser": "Safari", "url": "https://example.org/a", "title": "Example title", "text": "The page text\nsecond line"}
    osa.result = "https://news.example/x\nHeadline"
    tab = mac_apps.browser_tab("Google Chrome")
    assert tab["text"] == "" and 'tell application "Google Chrome"' in osa.calls[-1][0]
    monkeypatch.setattr(mac_apps, "_running", lambda app: False)
    with pytest.raises(mac_apps.AppError, match="No supported browser"): mac_apps.frontmost_browser()


@mac_only
def test_read_browser_tab_tool_fetches_when_the_browser_gives_no_text(monkeypatch):
    monkeypatch.setattr(tools, "TARGET_APP_HOOK", lambda: "Google Chrome")
    monkeypatch.setattr(mac_apps, "browser_tab", lambda preferred="": {"browser": preferred, "url": "https://news.example/x", "title": "Headline", "text": ""})
    monkeypatch.setattr(tools, "read_webpage", lambda url: tools.UNTRUSTED_NOTE + "fetched text of " + url)
    out = tools.read_browser_tab()
    assert out.startswith(tools.UNTRUSTED_NOTE) and "Headline\nhttps://news.example/x" in out and "fetched text of https://news.example/x" in out
    assert out.count(tools.UNTRUSTED_NOTE) == 1 and "needs your login" in out
    monkeypatch.setattr(tools, "read_webpage", lambda url: tools.fail("Error reading: 403"))
    assert "could not be read" in tools.read_browser_tab() and not isinstance(tools.read_browser_tab(), tools.ToolFailure)
    monkeypatch.setattr(mac_apps, "browser_tab", lambda preferred="": {"browser": "Safari", "url": "https://a.example", "title": "T", "text": "safari text"})
    assert "safari text" in tools.read_browser_tab()
    def none(preferred=""): raise mac_apps.AppError("No supported browser is open")
    monkeypatch.setattr(mac_apps, "browser_tab", none)
    assert isinstance(tools.read_browser_tab(), tools.ToolFailure)


# ── as tools: failures, taint, approvals ───────────────────────────
@mac_only
def test_app_tools_report_failures_and_taint_the_request(kit, monkeypatch, tmp_path):
    import paths
    monkeypatch.setattr(paths, "ACTIVITY_FILE", str(tmp_path / "a.log"))
    def refuse(request, timeout=130): raise mac_apps.AppError("Calendar access is off for NOVA.")
    monkeypatch.setattr(mac_apps, "_eventkit", refuse)
    out = tools.execute_tool("get_calendar_events", {})
    assert isinstance(out, tools.ToolFailure) and out == "Calendar access is off for NOVA."
    monkeypatch.setattr(mac_apps, "_eventkit", lambda request, timeout=130: {"ok": True, "events": []})
    tools.begin_request()
    assert tools.needs_confirmation("add_calendar_event", {"title": "x", "start": "2026-10-09T10:00"}) == ""   # your own request: no prompt
    tools.execute_tool("get_calendar_events", {})
    assert tools.is_tainted()                                                         # an invitation could carry instructions…
    assert "add_calendar_event" in tools.needs_confirmation("add_calendar_event", {"title": "x", "start": "2026-10-09T10:00"})   # …so now it asks
    assert "draft_email" in tools.needs_confirmation("draft_email", {"subject": "s", "body": "b"})
    tools.begin_request()


def test_new_tools_have_schemas_and_validate_arguments():
    import schemas
    names = {s["function"]["name"] for s in schemas.TOOLS_SCHEMA}
    wanted = {"get_calendar_events", "add_calendar_event", "list_apple_reminders", "add_apple_reminder", "read_selected_email",
              "draft_email", "draft_email_reply", "read_browser_tab"}
    assert wanted <= names and wanted <= set(tools.TOOL_FUNCTIONS)
    tools.set_schemas(schemas.TOOLS_SCHEMA)
    assert "missing required" in tools.validate_args("add_calendar_event", {"title": "x"})[1]
    assert tools.validate_args("add_calendar_event", {"title": "x", "start": "2026-10-09T10:00", "all_day": "true"})[0]["all_day"] is True
    assert "unknown argument" in tools.validate_args("draft_email", {"subject": "s", "body": "b", "send": True})[1]

"""NOVA against the real AI - opt-in:  NOVA_LIVE_TESTS=1 .venv/bin/python -m pytest tests/test_live.py -s

What is real: the AI (your Groq key from the Keychain), the internet tools (weather, web search, reading a page)
and everything NOVA does inside a temporary data folder (memory, notes, reminders, documents, files in /tmp).
What is a stand-in: every tool that would touch this Mac or show its contents - opening apps and pages, volume,
power, typing, clipboard, processes, network, calendar, mail, shortcuts. They only note that they were called,
so the test sees which tool the AI chose without anything happening on screen, and nothing private is sent.

It checks two things for each request: did the AI pick the right tool and answer - and how long did it take.
It costs tokens from your provider's allowance (about 50-70 thousand for the whole file)."""
import json, os, time
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("NOVA_LIVE_TESTS") != "1", reason="set NOVA_LIVE_TESTS=1 to talk to the real AI")
pytest.importorskip("PySide6")
import tools, models, workers, docs, paths

STAND_INS = {            # tool -> what it answers (the same kind of words as the real tool, including its ✓)
    "open_application": "Opened ✓", "open_url": "Opened ✓", "open_maps": "Opened Google Maps ✓", "search_web": "Searching in browser ✓",
    "take_screenshot": "Screenshot saved: ~/Desktop/screenshot.png ✓", "type_text_keyboard": "Typed ✓",
    "control_volume": "Volume: 60% ✓", "control_system": "Locked ✓", "empty_recycle_bin": "Trash emptied ✓",
    "control_spotify": "Next track ✓", "kill_process": "Killed: Safari (500)", "send_notification": "Notification sent",
    "set_wallpaper": "Wallpaper set", "open_in_explorer": "Opened Finder ✓", "set_clipboard": "Copied to clipboard ✓",
    "get_clipboard": "Meeting moved to Thursday 14:00", "list_processes": "Safari (PID 500, 900 MB)\nXcode (PID 77, 650 MB)\nNotes (PID 81, 80 MB)",
    "get_network_info": "Wi-Fi: Home\nen0: 192.168.1.20", "search_files": "Found 1 file(s):\n/Users/me/Documents/CV.pdf",
    "run_shell_command": "total 0", "manage_files": "Done ✓",
    "run_shortcut": "Shortcut “Morning Routine” finished.", "list_shortcuts": "Shortcuts:\n• Morning Routine\n• Send ETA",
    "get_calendar_events": "Today:\n• 10:00–11:00 Stand-up (Work)\n• 15:00–16:00 Dentist (Home)", "add_calendar_event": "Added “Lunch with Ivan” ✓",
    "list_apple_reminders": "• Buy milk\n• Call the bank", "add_apple_reminder": "Added to Reminders ✓",
    "read_selected_email": "From: Maria <maria@example.com>\nSubject: Friday\n\nCan we move the meeting to 15:00?",
    "draft_email": "Draft opened in Mail ✓", "draft_email_reply": "Reply draft opened in Mail ✓",
    "read_browser_tab": "Title: Sourdough basics\nhttps://bread.example/sourdough\n\nMix flour and water, wait 12 hours, bake at 230 degrees.",
}


def _real_key() -> str:
    """The key NOVA itself uses, read (never written, never printed) from the macOS Keychain."""
    try:
        from keyring.backends import macOS
        return macOS.Keyring().get_password("NOVA_AI_Assistant", "groq_api_key") or ""
    except Exception:
        return ""


class Session:
    """Drives one NOVA window the way a person would and writes down what happened."""
    def __init__(self, win):
        self.win = win; self.rows = []; self.calls = []; self._first = None
        self._spent = []                                    # (time, tokens) of recent requests, to stay inside the per-minute allowance
        on_finished, on_chunk = win._on_tool_finished, win._on_chunk
        def finished(name, args, ok, result):
            self.calls.append((name, args, ok)); on_finished(name, args, ok, result)
        def chunk(text):
            if self._first is None: self._first = time.monotonic()
            on_chunk(text)
        win._on_tool_finished, win._on_chunk = finished, chunk

    def _pace(self, limit: int = 6000):
        """Wait until the last minute's use leaves room (the free tier counts tokens per minute and per model)."""
        while True:
            now = time.monotonic(); self._spent = [(t, n) for t, n in self._spent if now - t < 62]
            if sum(n for _t, n in self._spent) < limit: return
            self.win._pump(1000)

    def ask(self, text: str, timeout: int = 90, pace: bool = True) -> dict:
        w = self.win
        if pace: self._pace()
        self.calls = []; self._first = None
        tin, tout = w._tokens_in, w._tokens_out
        t0 = time.monotonic()
        w.input_field.setText(text); w._send()
        end = t0 + timeout
        while w._busy and time.monotonic() < end: w._pump(40)
        took = time.monotonic() - t0
        reply = next((m["content"] for m in reversed(w.messages) if m.get("role") == "assistant" and isinstance(m.get("content"), str) and m["content"].strip()), "")
        notices = [b._full_text for b in w.chat_area.findChildren(type(w.chat_area.add_message("·", "system", w._theme))) if b._role == "system"][-6:]
        row = {"ask": text, "tools": [c[0] for c in self.calls], "args": [c[1] for c in self.calls], "failed": [c[0] for c in self.calls if not c[2]],
               "reply": reply, "secs": round(took, 1), "first": round(self._first - t0, 1) if self._first else None,
               "tokens": (w._tokens_in - tin, w._tokens_out - tout), "busy": w._busy, "model": w._worker.model_id if getattr(w, "_worker", None) else "",
               "notices": [n for n in notices if n != "·"]}
        self._spent.append((time.monotonic(), sum(row["tokens"])))
        self.rows.append(row)
        return row

    def report(self) -> str:
        out = ["", f"{'request':46s} {'tools':34s} {'first':>5s} {'total':>6s} {'tokens':>11s}  model"]
        for r in self.rows:
            out.append(f"{r['ask'][:45]:46s} {', '.join(r['tools'])[:33]:34s} {str(r['first'] or '-'):>5s} {r['secs']:>5.1f}s "
                       f"{r['tokens'][0]:>6d}/{r['tokens'][1]:<4d}  {r['model'].split('/')[-1]}")
        secs = sorted(r["secs"] for r in self.rows)
        if secs:
            out.append(f"{len(secs)} requests · median {secs[len(secs) // 2]:.1f}s · slowest {secs[-1]:.1f}s · "
                       f"tokens in {sum(r['tokens'][0] for r in self.rows)} / out {sum(r['tokens'][1] for r in self.rows)}")
        return "\n".join(out)


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    key = _real_key()
    if not key: pytest.skip("no Groq key in the Keychain")
    import main, win_account
    from PySide6.QtWidgets import QApplication, QMessageBox
    from gui_support import _pump
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("live")
    app = QApplication.instance() or QApplication([])
    for name, rel in (("CONFIG_FILE", "c.json"), ("HISTORY_FILE", "h.json"), ("MEMORY_FILE", "m.json"), ("DOCS_FILE", "docs.json"),
                      ("SCHEDULE_FILE", "schedule.json"), ("USAGE_FILE", "usage.log"), ("OUTBOUND_FILE", "outbound.log"),
                      ("ACTIVITY_FILE", "activity.log")):
        mp.setattr(paths, name, str(tmp / rel))
    mp.setattr(paths, "SESSIONS_DIR", str(tmp / "s"))
    import tools_files
    mp.setattr(tools, "MEMORY_FILE", str(tmp / "m.json")); mp.setattr(tools, "REMINDERS_FILE", str(tmp / "r.json"))
    mp.setattr(tools_files, "NOTES_FILE", str(tmp / "notes.txt"))
    mp.setattr(win_account, "_get_api_key", lambda *a, **k: key)
    models.activate("groq")
    W = main.AssistantWindow
    mp.setattr(W, "_run_onboarding", lambda self, k="": k)
    for name in ("_start_wake_listener", "_maybe_morning_briefing", "_start_spotify_monitor", "_generate_followups",
                 "_generate_session_title", "_tag_memories", "_refresh_documents"):
        mp.setattr(W, name, lambda self: None)
    mp.setattr(main.plat, "start_global_hotkey", lambda cb: True)
    mp.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    used = []
    for name, answer in STAND_INS.items():                  # nothing on this Mac is touched or read
        mp.setitem(tools.TOOL_FUNCTIONS, name, lambda _a=answer, _n=name, **kw: (used.append((_n, kw)), _a)[1])
    workers._MODEL_COOLDOWN.clear()
    w = W(); w.config["onboarded"] = True
    w._pump = lambda ms=300: _pump(app, ms)
    w._ask_user = lambda desc, key=None: True               # the stand-ins make every approval harmless
    (tmp / "trip.txt").write_text("Trip to Lisbon, 12-15 November.\nHotel: Casa das Janelas, Rua do Sol 14.\nFlight TP1234 at 07:40.\n")
    session = Session(w); session.tmp = tmp; session.used = used
    yield session
    print(session.report())
    try: (tmp / "report.json").write_text(json.dumps(session.rows, ensure_ascii=False, indent=1))
    except OSError: pass
    out = os.environ.get("NOVA_LIVE_REPORT")
    if out: open(out, "w", encoding="utf-8").write(json.dumps(session.rows, ensure_ascii=False, indent=1))
    w._shutdown(); mp.undo(); docs._library = None


def expect(row, tool=None, words=(), max_secs=45):
    """One request went well: the AI finished, used the tool it should, and its answer mentions what it must."""
    assert not row["busy"], f"no answer within the time limit: {row['ask']}"
    assert row["reply"].strip(), f"empty answer: {row['ask']} (notices: {row['notices']})"
    if tool:
        wanted = (tool,) if isinstance(tool, str) else tuple(tool)
        assert any(t in row["tools"] for t in wanted), f"{row['ask']!r}: expected {wanted}, the AI used {row['tools']}"
    low = " ".join(row["reply"].lower().split())             # (models like thin no-break spaces around numbers)
    for w in words:
        options = (w,) if isinstance(w, str) else w
        assert any(o.lower() in low for o in options), f"{row['ask']!r}: the answer does not mention {options}: {row['reply'][:200]!r}"
    assert row["secs"] <= max_secs, f"{row['ask']!r} took {row['secs']}s"


# ── opening things, controlling the Mac (stand-ins: only the AI's choice is real) ──
CHOICES = [
    ("open paris on the map", "open_maps", "location", "paris"),
    ("open Spotify", "open_application", "app_name", "spotify"),
    ("go to github.com", "open_url", "url", "github.com"),
    ("turn the volume up a bit", "control_volume", "action", "up"),
    ("lock the screen", "control_system", "action", "lock"),
    ("copy the words hello world to my clipboard", "set_clipboard", "text", "hello world"),
    ("skip to the next song", "control_spotify", "action", "next"),
]


@pytest.mark.parametrize("ask,tool,arg,value", CHOICES, ids=[c[1] for c in CHOICES])
def test_the_ai_picks_the_right_tool_with_the_right_details(live, ask, tool, arg, value):
    row = live.ask(ask)
    expect(row, tool)
    args = json.loads(row["args"][row["tools"].index(tool)])
    assert value in str(args.get(arg, "")).lower(), f"{tool} got {args}"


def test_weather_is_real_and_names_the_place(live):
    expect(live.ask("what's the weather in Paris right now?"), "get_weather", ["paris", ("°", "degrees")])


def test_bulgarian_question_gets_a_bulgarian_answer(live):
    row = live.ask("какво е времето в София?")
    expect(row, "get_weather", [("софия", "sofia")])
    assert any("а" <= ch <= "я" for ch in row["reply"].lower()), row["reply"][:200]


def test_no_tool_for_things_it_simply_knows(live):
    row = live.ask("what is 17 times 23? answer with just the number")
    expect(row, None, ["391"]); assert row["tools"] == [], row["tools"]
    row = live.ask("translate 'good morning' to Bulgarian, only the translation")
    expect(row, None, ["добро утро"]); assert row["tools"] == []


def test_memory_notes_and_reminders_in_the_temporary_profile(live):
    expect(live.ask("remember that my sister's birthday is on 3 May"), "save_memory")
    assert "3 May" in open(tools.MEMORY_FILE).read() or "May 3" in open(tools.MEMORY_FILE).read()
    expect(live.ask("when is my sister's birthday?"), None, [("3 may", "may 3", "3rd of may", "may 3rd")])
    expect(live.ask("save a note: buy milk and eggs"), "save_note")
    expect(live.ask("remind me in 30 minutes to stretch"), "set_reminder")


def test_reading_and_writing_files(live):
    expect(live.ask(f"read the file {live.tmp / 'trip.txt'} and tell me the name of the hotel"), "read_file", ["casa das janelas"])
    target = live.tmp / "list.txt"
    expect(live.ask(f"create the file {target} containing exactly: eggs, flour"), "write_file")
    assert target.exists() and "eggs" in target.read_text()


def test_the_internet_search_and_a_page(live):
    expect(live.ask("search the web: what is the capital of Australia? one sentence"), ("search_web_and_read", "read_webpage"), ["canberra"])
    expect(live.ask("read https://example.com and tell me in one sentence what the page says"), "read_webpage", [("example", "illustrative", "documentation")])


def test_tools_that_are_only_offered_when_needed(live):
    expect(live.ask("what's on my calendar today?"), "get_calendar_events", [("dentist", "stand-up")])
    expect(live.ask("draft an email to maria@example.com saying I agree with Friday at 15:00"), "draft_email")
    expect(live.ask("run my Morning Routine shortcut"), "run_shortcut")
    expect(live.ask("every weekday at 8:00 tell me the weather in Sofia"), "schedule_task")


def test_questions_about_a_document(live):
    doc = live.tmp / "rental contract.txt"
    doc.write_text("RENTAL CONTRACT\n\nThe tenant pays a security deposit equal to two monthly rents before moving in.\n"
                   "The monthly rent is 950 euro, due on the fifth day of each month.\nPets are allowed with written permission.\n")
    docs.library().add_file(str(doc))
    expect(live.ask("what does my rental contract say about the deposit?"), "search_documents", [("two monthly rents", "two months", "two month")])


def test_two_steps_in_one_request(live):
    row = live.ask("check the weather in Sofia and save it as a note")
    expect(row, "get_weather"); assert "save_note" in row["tools"], row["tools"]


def test_running_code(live):
    expect(live.ask("use python to compute the 30th Fibonacci number (F1 = F2 = 1) and tell me the result"), "execute_python_code", [("832040", "832,040", "832 040")])


def test_a_quick_session_stays_quick(live):
    """Five short requests one after another, as a person would - none may take long, whatever the allowance says."""
    rows = [live.ask(q, pace=False) for q in ("hi", "what's my battery level?", "open Notes", "what is 12 squared?", "thanks")]
    for r in rows: expect(r, None, max_secs=25)
    print("\nquick session:", [(r["ask"], r["secs"], r["model"].split("/")[-1]) for r in rows])

"""Scheduled tasks: repeating reminders and requests sent at set times."""
import datetime, json
import pytest
import schedule as sched, tools, paths, storage

D = datetime.datetime


def test_times_and_days_are_understood():
    assert [sched.parse_time(x) for x in ("8", "8:30", "08:30", "8.30", "8am", "8:30 pm", "12am", "12pm", "20:15")] == \
        ["08:00", "08:30", "08:30", "08:30", "08:00", "20:30", "00:00", "12:00", "20:15"]
    for bad in ("25:00", "8:75", "soon", "", "8 o'clock"):
        with pytest.raises(sched.ScheduleError): sched.parse_time(bad)
    assert sched.parse_days("") == "daily" and sched.parse_days("Every Day") == "daily" and sched.parse_days("weekdays") == "weekdays"
    assert sched.parse_days("mon,wed,fri") == "mon,wed,fri" and sched.parse_days("Friday and Monday") == "mon,fri"
    assert sched.parse_days("sat sun") == "sat,sun" and sched.parse_days("mon,tue,wed,thu,fri,sat,sun") == "daily"
    assert sched.parse_days("понеделник, петък") == "mon,fri" and sched.parse_days("once") == "once"
    with pytest.raises(sched.ScheduleError): sched.parse_days("whenever")


def test_descriptions():
    mk = lambda days, **k: dict({"time": "08:00", "days": days}, **k)
    assert sched.describe(mk("daily")) == "every day at 08:00" and sched.describe(mk("weekdays")) == "every weekday at 08:00"
    assert sched.describe(mk("mon,fri")) == "every Mon, Fri at 08:00" and sched.describe(mk("once", date="2026-10-09")) == "once on 2026-10-09 at 08:00"


def test_due_respects_days_time_and_runs_once_per_slot():
    daily = sched.make("ask", "news please", "08:00")
    wk = sched.make("reminder", "stand up", "17:30", "weekdays")
    tasks = [daily, wk]
    fri = D(2026, 10, 9)                                                      # a Friday
    assert sched.due(tasks, fri.replace(hour=7, minute=59)) == []
    assert sched.due(tasks, fri.replace(hour=8, minute=0)) == [daily]
    tasks = sched.mark_run(tasks, daily, fri.replace(hour=8, minute=0))
    assert sched.due(tasks, fri.replace(hour=8, minute=1)) == []              # not twice in the same slot
    assert sched.due(tasks, fri.replace(hour=17, minute=30)) == [wk]
    sat = D(2026, 10, 10, 17, 31)
    assert sched.due(tasks, sat) == []                                        # weekday task rests at the weekend…
    assert sched.due(tasks, sat.replace(hour=8, minute=5)) == [daily]         # …the daily one runs again next day
    off = dict(daily, enabled=False, last_run="")
    assert sched.due([off], fri.replace(hour=9)) == []


def test_missed_tasks_catch_up_only_for_a_few_hours():
    t = sched.make("ask", "morning briefing", "08:00")
    day = D(2026, 10, 9)
    assert sched.due([t], day.replace(hour=9, minute=30)) == [t]              # NOVA opened at 9:30: still worth doing
    assert sched.due([t], day.replace(hour=14, minute=0)) == [t]
    assert sched.due([t], day.replace(hour=14, minute=1)) == []               # more than 6 h late: skipped today
    assert sched.next_run(t, day.replace(hour=14, minute=1)) == D(2026, 10, 10, 8, 0)


def test_one_time_tasks_run_once_and_disappear():
    today = datetime.date(2026, 10, 9)
    t = sched.make("reminder", "call the bank", "15:00", "once", "2026-10-09", today=today)
    assert t["days"] == "once" and t["date"] == "2026-10-09"
    assert sched.due([t], D(2026, 10, 8, 15, 0)) == [] and sched.due([t], D(2026, 10, 9, 15, 0)) == [t]
    assert sched.mark_run([t], t, D(2026, 10, 9, 15, 0)) == []
    assert sched.expired([t], D(2026, 10, 10, 9, 0)) == [] and sched.expired([t], D(2026, 10, 9, 23, 0)) == [t]
    with pytest.raises(sched.ScheduleError): sched.make("ask", "x", "8:00", "once", "next week")
    with pytest.raises(sched.ScheduleError): sched.make("ask", "   ", "8:00")
    auto = sched.make("reminder", "x", "00:00", "once")                       # no date given: the next time that hour comes
    assert auto["date"] in (datetime.date.today().isoformat(), (datetime.date.today() + datetime.timedelta(days=1)).isoformat())


def test_next_run_for_chosen_days():
    t = sched.make("ask", "x", "09:00", "mon,thu")
    assert sched.next_run(t, D(2026, 10, 9, 10, 0)) == D(2026, 10, 12, 9, 0)   # Friday -> Monday
    assert sched.next_run(t, D(2026, 10, 12, 8, 0)) == D(2026, 10, 12, 9, 0)
    assert sched.next_run(dict(t, enabled=False), D(2026, 10, 9, 10, 0)) is None


# ── tools ──────────────────────────────────────────────────────────
def test_schedule_tools_roundtrip(data_dir):
    assert tools.list_scheduled_tasks() == "Nothing is scheduled."
    out = tools.schedule_task("give me news and the weather", "8", "daily")
    assert "Scheduled request saved" in out and "every day at 08:00" in out and "while NOVA is open" in out
    assert "Reminder saved" in tools.schedule_task("stretch", "17:30", "weekdays", "reminder")
    listing = tools.list_scheduled_tasks()
    assert "[ask] give me news and the weather — every day at 08:00" in listing and "[reminder] stretch — every weekday at 17:30" in listing
    saved = json.load(open(paths.SCHEDULE_FILE))
    assert [t["kind"] for t in saved["tasks"]] == ["ask", "reminder"]
    assert isinstance(tools.schedule_task("x", "25:99"), tools.ToolFailure)
    tools.schedule_task("stretch again", "18:00", kind="reminder")
    assert "More than one" in tools.cancel_scheduled_task("stretch")
    assert "Cancelled" in tools.cancel_scheduled_task("stretch again") and isinstance(tools.cancel_scheduled_task("nothing like it"), tools.ToolFailure)
    assert "schedule_task" in tools.SIDE_EFFECT_TOOLS                         # a web page cannot quietly schedule things


def test_schedule_is_encrypted_with_the_rest(data_dir):
    tools.schedule_task("secret plan", "9:00")
    storage.convert_all(True)
    assert b"secret plan" not in open(paths.SCHEDULE_FILE, "rb").read() and "secret plan" in tools.list_scheduled_tasks()
    storage.convert_all(False)


# ── in the window ──────────────────────────────────────────────────
def _put(tasks):
    sched.save(paths.SCHEDULE_FILE, tasks)


def test_window_runs_a_due_request_like_a_typed_message(win, monkeypatch):
    from gui_support import FakeCompletions, _wait_idle
    FakeCompletions.script = [["Here is your briefing."]]
    t = sched.make("ask", "give me the news", "08:00")
    _put([t])
    win._check_schedule(D(2026, 10, 9, 7, 0)); assert len(win.messages) == 1                 # not yet
    win._check_schedule(D(2026, 10, 9, 8, 0)); _wait_idle(win)
    assert [m["content"] for m in win.messages[1:]] == ["give me the news", "Here is your briefing."]
    win._check_schedule(D(2026, 10, 9, 8, 1)); assert len(win.messages) == 3                  # once per day
    assert sched.load(paths.SCHEDULE_FILE)[0]["last_run"] == "2026-10-09 08:00"


def test_window_shows_reminders_and_waits_with_requests_while_busy(win, monkeypatch):
    import platform_utils as plat
    notes = []
    monkeypatch.setattr(plat, "notify", lambda title, msg, ms=5000: notes.append(msg))
    shown = []
    monkeypatch.setattr(win, "_on_reminder", lambda text: shown.append(text))
    monkeypatch.setattr(win, "_start_ai", lambda *a, **k: pytest.fail("NOVA is busy: the request must wait"))
    _put([sched.make("reminder", "drink water", "10:00"), sched.make("ask", "summarise my day", "10:00"),
          sched.make("reminder", "one-off", "10:00", "once", "2026-10-09"), sched.make("reminder", "old one-off", "10:00", "once", "2026-10-01")])
    win._busy = True
    win._check_schedule(D(2026, 10, 9, 10, 0))
    assert shown == ["drink water", "one-off"] and notes == ["drink water", "one-off"]
    left = sched.load(paths.SCHEDULE_FILE)
    assert [t["text"] for t in left] == ["drink water", "summarise my day"]                 # one-offs are gone (run / out of date)
    assert left[1]["last_run"] == ""                                                         # the request is still waiting
    win._busy = False
    started = []
    monkeypatch.setattr(win, "_start_ai", lambda *a, **k: started.append(win.messages[-1]["content"]))
    win._check_schedule(D(2026, 10, 9, 10, 1))
    assert started == ["summarise my day"]


def test_schedule_window(app, data_dir, monkeypatch):
    import dialogs, themes, threading
    d = dialogs.ScheduleDialog(themes.THEMES["nova"], paths.SCHEDULE_FILE, threading.RLock())
    assert d.listw.item(0).text() == "Nothing is scheduled"
    monkeypatch.setattr(dialogs.ScheduleDialog, "_ask", lambda self: sched.make("ask", "weather please", "07:45", "weekdays"))
    d._add()
    assert d.listw.count() == 1 and "weather please" in d.listw.item(0).text() and "every weekday at 07:45" in d.listw.item(0).text()
    d.listw.setCurrentRow(0); d._toggle()
    assert sched.load(paths.SCHEDULE_FILE)[0]["enabled"] is False and "turned off" in d.listw.item(0).text()
    d.listw.setCurrentRow(0); d._toggle(); assert "next:" in d.listw.item(0).text()
    d.listw.setCurrentRow(0); d._delete(); assert sched.load(paths.SCHEDULE_FILE) == []


def test_new_task_form(app):
    import dialogs, themes
    f = dialogs.ScheduleEditDialog(themes.THEMES["nova"])
    f._ok(); assert f.task is None and "needs some text" in f.problem.text()                # empty: explained, stays open
    f.text.setText("back up my notes"); f.kind.setCurrentIndex(f.kind.findData("reminder"))
    f.repeat.setCurrentIndex(f.repeat.findData("custom"))
    assert all(cb.isEnabled() for cb in f.day_boxes)
    for i, cb in enumerate(f.day_boxes): cb.setChecked(i in (0, 2))
    from PySide6.QtCore import QTime
    f.time.setTime(QTime(21, 15)); f._ok()
    assert f.task["kind"] == "reminder" and f.task["days"] == "mon,wed" and f.task["time"] == "21:15"
    assert dialogs.schedule_when(f.task) == "every Mon, Wed at 21:15"

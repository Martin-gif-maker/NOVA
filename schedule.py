# schedule.py — things NOVA does by itself at set times.
#
#   reminder   shows a reminder (and a notification)                "every weekday at 17:30: stand up and stretch"
#   ask        sends a request to the AI as if you had typed it      "every day at 08:00: give me news and the weather"
#
# Tasks only run while NOVA is open. If NOVA was closed at the set time, a task still runs when you open it
# later the same day - but only within CATCH_UP_HOURS, so a morning briefing does not arrive at night.
import re, time, datetime
import storage

CATCH_UP_HOURS = 6
MAX_TASKS = 50
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_WORDS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
              "понеделник": 0, "вторник": 1, "сряда": 2, "четвъртък": 3, "петък": 4, "събота": 5, "неделя": 6}


class ScheduleError(Exception):
    pass


# ── parsing what the user / the AI says ────────────────────────────
def parse_time(text) -> str:
    """'8', '8:30', '08:30', '8.30', '8am', '8:30 pm', '20:15' -> 'HH:MM'."""
    s = str(text or "").strip().lower().replace(".", ":")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
    if not m: raise ScheduleError(f"I could not read the time {text!r}. Use the form 08:00 or 17:30.")
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h < 12: h += 12
    if ap == "am" and h == 12: h = 0
    if not (0 <= h <= 23 and 0 <= mi <= 59): raise ScheduleError(f"{text!r} is not a time of day.")
    return f"{h:02d}:{mi:02d}"


def parse_days(spec) -> str:
    """'daily' | 'weekdays' | 'weekends' | 'once' | 'mon,wed,fri' (also full names, EN/BG) -> canonical form."""
    s = str(spec or "daily").strip().lower()
    if s in ("", "daily", "every day", "everyday", "each day", "all", "всеки ден", "ежедневно"): return "daily"
    if s in ("weekdays", "weekday", "workdays", "work days", "делници", "работни дни"): return "weekdays"
    if s in ("weekends", "weekend", "уикенд", "почивни дни"): return "weekends"
    if s in ("once", "one time", "one-time", "never", "no", "none", "веднъж"): return "once"
    picked = set()
    for word in re.split(r"[,\s/&+]+|\band\b", s):
        word = word.strip(". ")
        if not word or word in ("every", "each", "on", "and", "и", "всеки", "всяка"): continue
        if word in _DAY_WORDS: picked.add(_DAY_WORDS[word])
        elif word[:3] in DAY_NAMES: picked.add(DAY_NAMES.index(word[:3]))
        else: raise ScheduleError(f"I could not read the days {spec!r}. Use daily, weekdays, weekends, once, or days like mon,wed,fri.")
    if not picked: raise ScheduleError(f"I could not read the days {spec!r}.")
    if picked == set(range(7)): return "daily"
    return ",".join(DAY_NAMES[d] for d in sorted(picked))


def _day_set(days: str) -> set:
    if days in ("daily", "once"): return set(range(7))
    if days == "weekdays": return {0, 1, 2, 3, 4}
    if days == "weekends": return {5, 6}
    return {DAY_NAMES.index(d) for d in days.split(",") if d in DAY_NAMES}


def describe_parts(task: dict):
    """(template, arguments) - so the interface can translate the template."""
    days, at = task.get("days", "daily"), task.get("time", "?")
    fixed = {"daily": "every day at {}", "weekdays": "every weekday at {}", "weekends": "at weekends at {}"}
    if days in fixed: return fixed[days], (at,)
    if days == "once": return "once on {} at {}", (task.get("date", "?"), at)
    return "every {} at {}", (", ".join(d.capitalize() for d in days.split(",")), at)


def describe(task: dict) -> str:
    template, args = describe_parts(task)
    return template.format(*args)


# ── the list ───────────────────────────────────────────────────────
def make(kind: str, text: str, at, days="daily", date: str = "", today: datetime.date = None) -> dict:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text: raise ScheduleError("What should happen? The task needs some text.")
    kind = "reminder" if str(kind or "").lower().startswith("rem") else "ask"
    hhmm, days = parse_time(at), parse_days(days)
    today = today or datetime.date.today()
    if days == "once":
        if date:
            try: date = datetime.date.fromisoformat(str(date)[:10]).isoformat()
            except ValueError: raise ScheduleError(f"I could not read the date {date!r}. Use the form 2026-10-09.")
        else:                                           # no date: the next time that hour comes round
            h, m = map(int, hhmm.split(":"))
            now = datetime.datetime.now()
            date = (today if (now.date() != today or (h, m) > (now.hour, now.minute)) else today + datetime.timedelta(days=1)).isoformat()
    else:
        date = ""
    return {"id": f"{time.time():.6f}", "kind": kind, "text": text[:600], "time": hhmm, "days": days, "date": date,
            "enabled": True, "last_run": "", "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}


def load(path: str) -> list:
    try:
        data = storage.read_json(path)
    except (OSError, ValueError):
        return []
    items = data.get("tasks", []) if isinstance(data, dict) else []
    return [t for t in items if isinstance(t, dict) and t.get("text") and t.get("time")]


def save(path: str, tasks: list) -> None:
    storage.write_json(path, {"version": 1, "tasks": tasks[-MAX_TASKS:]})


def _slot(task: dict, day: datetime.date) -> datetime.datetime:
    h, m = map(int, task["time"].split(":"))
    return datetime.datetime.combine(day, datetime.time(h, m))


def due(tasks: list, now: datetime.datetime = None) -> list:
    """Tasks whose moment has come (today, not yet run for that moment, and not more than CATCH_UP_HOURS late)."""
    now = now or datetime.datetime.now()
    out = []
    for t in tasks:
        if not t.get("enabled", True): continue
        if t.get("days") == "once":
            try: day = datetime.date.fromisoformat(t.get("date", ""))
            except ValueError: continue
            if day != now.date(): continue
        elif now.weekday() not in _day_set(t.get("days", "daily")):
            continue
        slot = _slot(t, now.date())
        if now < slot or (now - slot) > datetime.timedelta(hours=CATCH_UP_HOURS): continue
        if (t.get("last_run") or "") >= slot.strftime("%Y-%m-%d %H:%M"): continue
        out.append(t)
    return out


def mark_run(tasks: list, task: dict, now: datetime.datetime = None) -> list:
    """Record that a task ran. One-time tasks are removed. Returns the new list."""
    now = now or datetime.datetime.now()
    if task.get("days") == "once":
        return [t for t in tasks if t.get("id") != task.get("id")]
    for t in tasks:
        if t.get("id") == task.get("id"): t["last_run"] = now.strftime("%Y-%m-%d %H:%M")
    return tasks


def expired(tasks: list, now: datetime.datetime = None) -> list:
    """Drop one-time tasks whose day has passed without NOVA being open."""
    today = (now or datetime.datetime.now()).date().isoformat()
    return [t for t in tasks if not (t.get("days") == "once" and (t.get("date") or "") < today)]


def next_run(task: dict, now: datetime.datetime = None):
    """When the task will run next (None if it never will)."""
    now = now or datetime.datetime.now()
    if not task.get("enabled", True): return None
    if task.get("days") == "once":
        try: slot = _slot(task, datetime.date.fromisoformat(task.get("date", "")))
        except ValueError: return None
        return slot if slot >= now and not task.get("last_run") else None
    days = _day_set(task.get("days", "daily"))
    for add in range(8):
        day = now.date() + datetime.timedelta(days=add)
        slot = _slot(task, day)
        if day.weekday() in days and slot > now: return slot
    return None


def find(tasks: list, which: str) -> list:
    """Tasks matching an id or a piece of their text."""
    w = str(which or "").strip().lower()
    if not w: return []
    return [t for t in tasks if t.get("id") == which or w in t.get("text", "").lower()]

# mac_apps.py — the Mac's own apps as tools: Calendar, Reminders, Mail, the browser, Shortcuts.
#
#   Calendar / Reminders  EventKit, in a helper process (eventkit_helper.py). macOS asks you once per kind.
#   Mail / browsers       AppleScript. macOS asks once per app ("NOVA wants to control Mail").
#   Shortcuts             the `shortcuts` command that ships with macOS.
# Text that goes INTO a script is always passed as an argument (`on run argv`), never pasted into the
# script source - so nothing in an email, title or page can change what the script does.
# NOVA never sends mail: it opens a draft and you press Send.
import os, re, sys, json, time, datetime, subprocess
import paths

BROWSERS = ("Safari", "Google Chrome", "Arc", "Brave Browser", "Microsoft Edge", "Vivaldi", "Opera", "Chromium")
EVENTKIT_MARK = "@@NOVA-EVENTKIT@@"


class AppError(Exception):
    """Something the user (or the AI) can act on - the message is shown as it is."""


# ── plumbing ───────────────────────────────────────────────────────
def _osa(script: str, *args, timeout: int = 20) -> str:
    """Run AppleScript with arguments (available as `argv` inside `on run argv`). Returns its text result."""
    try:
        r = subprocess.run(["osascript", "-", *[str(a) for a in args]], input=script, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AppError("The app did not answer in time (is a permission question waiting on screen?).")
    except OSError as e:
        raise AppError(f"AppleScript is not available: {e}")
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if "-1743" in err or "Not authorized" in err or "not allowed" in err.lower():
            raise AppError("macOS blocked this. Allow NOVA under System Settings → Privacy & Security → Automation, then try again.")
        raise AppError(err.split("execution error:")[-1].strip()[:300] or "AppleScript failed.")
    return r.stdout.rstrip("\n")


def _running(app: str) -> bool:
    try:
        import psutil
        return any((p.info["name"] or "") == app for p in psutil.process_iter(["name"]))
    except Exception:
        return True                      # cannot tell: let the script try


def _helper_command() -> list:
    if paths.IS_FROZEN:
        return [sys.executable, "--eventkit-helper"]
    return [sys.executable, "-I", os.path.join(paths.CODE_DIR, "eventkit_helper.py")]


def _eventkit(request: dict, timeout: int = 130) -> dict:
    """Ask the EventKit helper. Raises AppError with a message that says what to do."""
    try:
        r = subprocess.run(_helper_command(), input=json.dumps(request), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AppError("Calendar did not answer in time (is a permission question waiting on screen?).")
    except OSError as e:
        raise AppError(f"Could not reach Calendar: {e}")
    for line in reversed(r.stdout.splitlines()):
        if line.startswith(EVENTKIT_MARK):
            try: answer = json.loads(line[len(EVENTKIT_MARK):])
            except ValueError: break
            if not answer.get("ok"): raise AppError(answer.get("error", "Calendar refused the request."))
            return answer
    # no answer at all: macOS stopped the helper because the app that started NOVA may not ask for this
    raise AppError("macOS does not let the app that started NOVA ask for Calendar / Reminders access. "
                   "Start NOVA from the NOVA app (or Terminal) and try again.")


def parse_when(text: str, default: datetime.datetime = None) -> datetime.datetime:
    """'2026-10-09T15:00', '2026-10-09 15:00', '2026-10-09' -> datetime (local time)."""
    s = str(text or "").strip()
    if not s:
        if default is None: raise AppError("A date and time is needed, e.g. 2026-10-09T15:00.")
        return default
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", ""))
    except ValueError:
        raise AppError(f"I could not read the date {s!r}. Use the form 2026-10-09T15:00.")
    return dt.replace(tzinfo=None) if dt.tzinfo is None else dt.astimezone().replace(tzinfo=None)


def _fmt(ts: float, with_date: bool = True) -> str:
    d = datetime.datetime.fromtimestamp(ts)
    return d.strftime("%a %d %b %H:%M" if with_date else "%H:%M")


# ── Calendar ───────────────────────────────────────────────────────
def calendar_events(start: str = "", end: str = "") -> str:
    """Events between two moments (default: today). Repeating events are included."""
    today = datetime.datetime.combine(datetime.date.today(), datetime.time())
    d1 = parse_when(start, today)
    d2 = parse_when(end, d1.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1))
    if d2 <= d1: d2 = d1 + datetime.timedelta(days=1)
    events = _eventkit({"op": "events", "start": d1.timestamp(), "end": d2.timestamp()})["events"]
    span = f"{d1:%a %d %b %H:%M} – {d2:%a %d %b %H:%M}"
    if not events: return f"No events in your calendar for {span}."
    lines = [f"Calendar, {span}:"]
    for e in events:
        when = "all day " + datetime.datetime.fromtimestamp(e["start"]).strftime("%a %d %b") if e["all_day"] \
            else f"{_fmt(e['start'])}–{_fmt(e['end'], False)}"
        where = f" @ {e['location']}" if e.get("location") else ""
        lines.append(f"• {when}  {e['title']}{where}  [{e['calendar']}]")
    return "\n".join(lines)


def add_calendar_event(title: str, start: str, end: str = "", all_day: bool = False, location: str = "",
                       notes: str = "", calendar: str = "") -> str:
    title = (title or "").strip()
    if not title: raise AppError("The event needs a title.")
    d1 = parse_when(start)
    d2 = parse_when(end, d1 + datetime.timedelta(hours=1))
    if d2 <= d1: d2 = d1 + datetime.timedelta(hours=1)
    if all_day:
        d1 = d1.replace(hour=0, minute=0, second=0, microsecond=0); d2 = max(d2, d1 + datetime.timedelta(hours=23, minutes=59))
    a = _eventkit({"op": "add_event", "title": title, "start": d1.timestamp(), "end": d2.timestamp(), "all_day": bool(all_day),
                   "location": location, "notes": notes, "calendar": calendar})
    when = f"{d1:%a %d %b} (all day)" if all_day else f"{d1:%a %d %b %H:%M}–{d2:%H:%M}"
    return f"Added to your calendar “{a.get('calendar', '')}”: {title}, {when} ✓"


# ── Reminders (the Mac's Reminders app - syncs with iPhone) ────────
def list_reminders() -> str:
    a = _eventkit({"op": "reminders", "limit": 50})
    items = a["reminders"]
    if not items: return "No open reminders."
    lines = [f"Open reminders ({a.get('total', len(items))}):"]
    for r in items:
        due = f"  — due {_fmt(r['due'])}" if r.get("due") else ""
        lines.append(f"• {r['title']}{due}  [{r['list']}]")
    return "\n".join(lines)


def add_reminder(title: str, due: str = "", notes: str = "", list_name: str = "") -> str:
    title = (title or "").strip()
    if not title: raise AppError("The reminder needs a title.")
    when = parse_when(due) if str(due or "").strip() else None
    a = _eventkit({"op": "add_reminder", "title": title, "due": when.timestamp() if when else None, "notes": notes, "list": list_name})
    return f"Added to Reminders “{a.get('list', '')}”: {title}" + (f", due {when:%a %d %b %H:%M}" if when else "") + " ✓"


# ── Mail ───────────────────────────────────────────────────────────
_SELECTED_MAIL = '''
tell application "Mail"
    set sel to selection
    if (count of sel) is 0 then return "NONE"
    set m to item 1 of sel
    set d to ""
    try
        set d to ((date received of m) as «class isot» as string)
    end try
    return (sender of m) & linefeed & (subject of m) & linefeed & d & linefeed & (content of m)
end tell
'''

_DRAFT_MAIL = '''
on run argv
    set theSubject to item 1 of argv
    set theBody to item 2 of argv
    tell application "Mail"
        set msg to make new outgoing message with properties {subject:theSubject, content:theBody, visible:true}
        repeat with i from 3 to (count of argv)
            tell msg to make new to recipient at end of to recipients with properties {address:(item i of argv)}
        end repeat
        activate
    end tell
    return "OK"
end run
'''


def selected_email() -> dict:
    """The message selected in Mail: {'sender', 'address', 'subject', 'date', 'body'}."""
    if not _running("Mail"): raise AppError("Mail is not open. Open Mail and select a message first.")
    out = _osa(_SELECTED_MAIL, timeout=25)
    if out.strip() == "NONE": raise AppError("No message is selected in Mail. Click the message first.")
    sender, subject, date, body = (out.split("\n", 3) + ["", "", "", ""])[:4]
    m = re.search(r"<([^<>\s]+@[^<>\s]+)>", sender) or re.search(r"([^\s<>]+@[^\s<>]+)", sender)
    return {"sender": sender.strip(), "address": m.group(1) if m else "", "subject": subject.strip(),
            "date": date.strip().replace("T", " ")[:16], "body": body.strip()}


def read_selected_email(max_chars: int = 6000) -> str:
    e = selected_email()
    body = e["body"][:max_chars] + ("\n[… message shortened]" if len(e["body"]) > max_chars else "")
    return f"From: {e['sender']}\nSubject: {e['subject']}\nDate: {e['date']}\n\n{body}"


def _addresses(to) -> list:
    raw = to if isinstance(to, (list, tuple)) else re.split(r"[,;\s]+", str(to or ""))
    out = [a.strip() for a in raw if a and a.strip()]
    bad = [a for a in out if not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", a)]
    if bad: raise AppError(f"That does not look like an email address: {', '.join(bad)}")
    return out


def draft_email(to: str = "", subject: str = "", body: str = "") -> str:
    """Open a new message in Mail, filled in. It is NOT sent - the user reviews it and presses Send."""
    if not (subject or body): raise AppError("The draft needs a subject or some text.")
    people = _addresses(to)
    _osa(_DRAFT_MAIL, subject or "", body or "", *people, timeout=25)
    return "Draft opened in Mail" + (f" to {', '.join(people)}" if people else "") + " — review it and press Send yourself ✓"


def draft_email_reply(body: str) -> str:
    """Open a reply to the message selected in Mail (not sent), with the original quoted underneath."""
    if not (body or "").strip(): raise AppError("The reply needs some text.")
    e = selected_email()
    if not e["address"]: raise AppError("I could not find the sender's address in the selected message.")
    subject = e["subject"] if e["subject"].lower().startswith("re:") else "Re: " + e["subject"]
    quoted = "\n".join("> " + l for l in e["body"][:4000].splitlines())
    full = f"{body.strip()}\n\nOn {e['date']}, {e['sender']} wrote:\n{quoted}"
    _osa(_DRAFT_MAIL, subject, full, e["address"], timeout=25)
    return f"Reply to {e['sender']} opened in Mail — review it and press Send yourself ✓"


# ── Browser ────────────────────────────────────────────────────────
_SAFARI_TAB = '''
tell application "Safari"
    if (count of documents) is 0 then return "NONE"
    set d to front document
    set t to ""
    try
        set t to text of d
    end try
    return (URL of d) & linefeed & (name of d) & linefeed & t
end tell
'''

# {app} is filled in from the fixed BROWSERS list (never from outside), so the script is compiled against
# that browser's own vocabulary.
_CHROMIUM_TAB = '''
tell application "{app}"
    if (count of windows) is 0 then return "NONE"
    set t to active tab of front window
    return (URL of t) & linefeed & (title of t)
end tell
'''


def frontmost_browser(preferred: str = "") -> str:
    """The browser to read: the app you were last in if it is one, otherwise the first one that is running."""
    if preferred in BROWSERS and _running(preferred): return preferred
    for b in BROWSERS:
        if _running(b): return b
    raise AppError("No supported browser is open (Safari, Chrome, Arc, Brave, Edge, Vivaldi, Opera).")


def browser_tab(preferred: str = "") -> dict:
    """{'browser', 'url', 'title', 'text'} of the tab in front. `text` is '' when the browser does not hand it out."""
    app = frontmost_browser(preferred)
    if app == "Safari":
        out = _osa(_SAFARI_TAB, timeout=20)
    else:
        out = _osa(_CHROMIUM_TAB.format(app=app), timeout=20)
    if out.strip() == "NONE": raise AppError(f"{app} has no open page.")
    url, title, text = (out.split("\n", 2) + ["", "", ""])[:3]
    return {"browser": app, "url": url.strip(), "title": title.strip(), "text": text.strip()}


# ── Shortcuts ──────────────────────────────────────────────────────
SHORTCUTS_BIN = "/usr/bin/shortcuts"


def shortcuts_available() -> bool:
    return os.access(SHORTCUTS_BIN, os.X_OK)


def list_shortcuts() -> list:
    if not shortcuts_available(): raise AppError("The Shortcuts app is not available on this Mac.")
    try:
        r = subprocess.run([SHORTCUTS_BIN, "list"], capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        raise AppError("Shortcuts did not answer in time.")
    if r.returncode != 0: raise AppError((r.stderr or "Shortcuts failed.").strip()[:300])
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


def run_shortcut(name: str, text: str = "", timeout: int = 120) -> str:
    """Run one of the user's Shortcuts, optionally with text as its input. Returns what the shortcut output."""
    name = (name or "").strip()
    names = list_shortcuts()
    match = next((n for n in names if n == name), None) or next((n for n in names if n.lower() == name.lower()), None)
    if match is None:
        close = [n for n in names if name.lower() in n.lower()][:5]
        raise AppError(f"There is no shortcut called “{name}”." + (f" Did you mean: {', '.join(close)}?" if close else ""))
    import tempfile
    with tempfile.TemporaryDirectory(prefix="nova_sc_") as tmp:
        cmd = [SHORTCUTS_BIN, "run", match, "--output-path", os.path.join(tmp, "out.txt")]
        if text:
            src = os.path.join(tmp, "in.txt")
            with open(src, "w", encoding="utf-8") as f: f.write(text)
            cmd += ["--input-path", src]
        started = time.time()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AppError(f"The shortcut “{match}” was still running after {timeout} seconds; NOVA stopped waiting.")
        if r.returncode != 0:
            raise AppError(f"The shortcut “{match}” failed: {(r.stderr or r.stdout).strip()[:300] or 'no details'}")
        out = ""
        try:
            with open(os.path.join(tmp, "out.txt"), encoding="utf-8", errors="replace") as f: out = f.read().strip()
        except OSError:
            pass
    took = time.time() - started
    return f"Shortcut “{match}” finished in {took:.1f}s." + (f" Output:\n{out[:3000]}" if out else "")

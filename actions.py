# actions.py — how a finished tool call is shown to a person: an icon, what was done, and to what.
#
# The chat shows each thing NOVA did as one neat row ("Opened Maps   Paris, France   ✓") instead of the
# tool's programming name. describe() turns a tool name and its arguments into that row.
import os
from urllib.parse import urlparse
from i18n import tr


def _base(path) -> str:
    p = str(path or "").rstrip("/")
    return os.path.basename(p) or p


def _host(url) -> str:
    u = str(url or "")
    return (urlparse(u if "//" in u else "https://" + u).hostname or u)[:60]


def _cut(text, n: int = 60) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


_FILE_ACTIONS = {"delete": ("trash", "Moved to Trash"), "move": ("folder", "Moved"), "copy": ("copy", "Copied"),
                 "rename": ("edit", "Renamed"), "list": ("folder", "Listed folder"), "create_folder": ("folder", "Created folder")}
_VOLUME = {"up": "Volume up", "down": "Volume down", "mute": "Muted", "unmute": "Unmuted", "set": "Volume set", "get": "Checked volume"}
_SYSTEM = {"shutdown": "Shutting down", "restart": "Restarting", "sleep": "Sleep", "hibernate": "Sleep", "lock": "Locked the screen",
           "cancel": "Cancelled shutdown"}
_SPOTIFY = {"play_pause": "Play / pause", "next": "Next track", "prev": "Previous track"}

# tool -> (icon, title, function(args) -> detail)
_TABLE = {
    "open_application":     ("app", "Opened app", lambda a: a.get("app_name", "")),
    "open_url":             ("globe", "Opened page", lambda a: _host(a.get("url"))),
    "open_maps":            ("pin", "Opened Maps", lambda a: a.get("location", "")),
    "search_web":           ("search", "Searched Google", lambda a: a.get("query", "")),
    "search_web_and_read":  ("search", "Searched the web", lambda a: a.get("query", "")),
    "read_webpage":         ("globe", "Read page", lambda a: _host(a.get("url"))),
    "run_shell_command":    ("terminal", "Ran command", lambda a: a.get("command", "")),
    "execute_python_code":  ("terminal", "Ran Python", lambda a: str(a.get("code", "")).strip().split("\n")[0]),
    "take_screenshot":      ("image", "Took screenshot", lambda a: _base(a.get("save_path", ""))),
    "type_text_keyboard":   ("keyboard", "Typed text", lambda a: a.get("text", "")),
    "empty_recycle_bin":    ("trash", "Emptied Trash", lambda a: ""),
    "get_system_stats":     ("stats", "Checked system", lambda a: ""),
    "save_note":            ("note", "Saved note", lambda a: a.get("text") or a.get("title") or a.get("content") or ""),
    "read_notes":           ("note", "Read notes", lambda a: ""),
    "set_reminder":         ("bell", "Reminder", lambda a: " · ".join(x for x in (
                                (f"{a.get('minutes'):g} min" if isinstance(a.get("minutes"), (int, float)) else ""),
                                str(a.get("text") or a.get("message") or "")) if x)),
    "save_memory":          ("bookmark", "Remembered", lambda a: a.get("fact", "")),
    "read_memory":          ("bookmark", "Checked memory", lambda a: ""),
    "delete_memory":        ("bookmark", "Forgot", lambda a: a.get("keyword", "")),
    "write_file":           ("edit", "Wrote file", lambda a: _base(a.get("path"))),
    "search_files":         ("search", "Searched files", lambda a: a.get("query", "")),
    "read_file":            ("file", "Read file", lambda a: _base(a.get("path"))),
    "open_in_explorer":     ("folder", "Showed in Finder", lambda a: _base(a.get("path"))),
    "get_clipboard":        ("clipboard", "Read clipboard", lambda a: ""),
    "set_clipboard":        ("clipboard", "Copied to clipboard", lambda a: a.get("text", "")),
    "list_processes":       ("chip", "Listed running apps", lambda a: a.get("filter_name", "")),
    "kill_process":         ("cross", "Stopped app", lambda a: a.get("name_or_pid", "")),
    "get_battery":          ("battery", "Checked battery", lambda a: ""),
    "get_network_info":     ("wifi", "Checked network", lambda a: ""),
    "send_notification":    ("bell", "Sent notification", lambda a: a.get("title", "")),
    "get_weather":          ("cloud", "Weather", lambda a: a.get("location", "")),
    "set_wallpaper":        ("wallpaper", "Set wallpaper", lambda a: _base(a.get("path"))),
    "list_shortcuts":       ("layers", "Listed shortcuts", lambda a: ""),
    "run_shortcut":         ("layers", "Ran shortcut", lambda a: a.get("name", "")),
    "schedule_task":        ("clock", "Scheduled", lambda a: " · ".join(str(x) for x in (a.get("at"), a.get("what")) if x)),
    "list_scheduled_tasks": ("clock", "Checked schedule", lambda a: ""),
    "cancel_scheduled_task": ("clock", "Cancelled task", lambda a: a.get("which", "")),
    "search_documents":     ("book", "Searched documents", lambda a: a.get("query", "")),
    "list_documents":       ("book", "Listed documents", lambda a: ""),
    "add_document":         ("book", "Added document", lambda a: _base(a.get("path"))),
    "remove_document":      ("book", "Removed document", lambda a: a.get("name", "")),
    "get_calendar_events":  ("calendar", "Checked calendar", lambda a: str(a.get("start") or "")[:10]),
    "add_calendar_event":   ("calendar", "Added event", lambda a: " · ".join(str(x) for x in (a.get("title"), str(a.get("start") or "").replace("T", " ")[:16]) if x)),
    "list_apple_reminders": ("bell", "Checked reminders", lambda a: ""),
    "add_apple_reminder":   ("bell", "Added reminder", lambda a: a.get("title", "")),
    "read_selected_email":  ("mail", "Read email", lambda a: ""),
    "draft_email":          ("mail", "Drafted email", lambda a: a.get("subject") or a.get("to") or ""),
    "draft_email_reply":    ("mail", "Drafted reply", lambda a: ""),
    "read_browser_tab":     ("globe", "Read browser page", lambda a: ""),
}

HIDDEN = {"more_tools"}        # plumbing between the AI and NOVA: not something NOVA "did" for you

# while a tool is still running: what NOVA is busy with
_DOING = {
    "search_web_and_read": "Searching the web", "search_web": "Searching the web", "read_webpage": "Reading the page",
    "read_browser_tab": "Reading the page", "get_weather": "Checking the weather", "read_file": "Reading the file",
    "search_files": "Looking through your files", "search_documents": "Searching your documents", "add_document": "Reading the document",
    "run_shell_command": "Running a command", "execute_python_code": "Running code", "get_calendar_events": "Checking your calendar",
    "list_apple_reminders": "Checking your reminders", "read_selected_email": "Reading the email", "run_shortcut": "Running the shortcut",
    "take_screenshot": "Taking a screenshot",
}
DOING = sorted(set(_DOING.values()) | {"Working"})


def doing(name: str) -> str:
    """"Searching the web…" - shown while that tool runs."""
    return tr(_DOING.get(name, "Working")) + "…"

# every title that can appear (for the translations check)
TITLES = sorted({v[1] for v in _TABLE.values()} | {v[1] for v in _FILE_ACTIONS.values()} | set(_VOLUME.values()) |
                set(_SYSTEM.values()) | set(_SPOTIFY.values()) | {"Spotify", "Volume", "System", "Files", "Used tool"})


def describe(name: str, args) -> tuple:
    """(icon name, title, detail) for one tool call. `args` is the tool's arguments as a dict (anything else is
    treated as no arguments)."""
    a = args if isinstance(args, dict) else {}
    if name == "manage_files":
        icon, title = _FILE_ACTIONS.get(str(a.get("action", "")), ("folder", "Files"))
        detail = _base(a.get("source"))
        if a.get("destination") and a.get("action") in ("move", "copy", "rename"): detail += " → " + _base(a.get("destination"))
        return icon, tr(title), _cut(detail)
    if name == "control_volume":
        act = str(a.get("action", "")).lower()
        level = f"{a.get('level')}%" if act == "set" and a.get("level") is not None else ""
        return "volume", tr(_VOLUME.get(act, "Volume")), level
    if name == "control_system":
        return "power", tr(_SYSTEM.get(str(a.get("action", "")).lower(), "System")), ""
    if name == "control_spotify":
        return "music", "Spotify", tr(_SPOTIFY.get(str(a.get("action", "")).lower(), "Spotify"))
    if name.startswith("mcp__"):                                    # a connected tool server: "server · tool"
        parts = name.split("__")
        return "plug", parts[1] if len(parts) > 1 else name, _cut(parts[2] if len(parts) > 2 else "")
    if name in _TABLE:
        icon, title, detail = _TABLE[name]
        try: text = detail(a)
        except Exception: text = ""
        return icon, tr(title), _cut(text)
    return "plug", tr("Used tool"), name                            # a plugin's tool

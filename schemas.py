# schemas.py — tool definitions sent to the model.
import tools as computer_tools
import logging

log = logging.getLogger("nova")

# Extend with any plugin tools loaded at startup
_PLUGIN_SCHEMAS = computer_tools.PLUGIN_SCHEMAS

def _schema(name, desc, props, required=None):
    return {"type":"function","function":{
        "name":name,"description":desc,
        "parameters":{"type":"object","properties":props,"required":required or []}}}

TOOLS_SCHEMA = [
    _schema("open_application","Opens an app.",{"app_name":{"type":"string"}},["app_name"]),
    _schema("open_url","Opens URL.",{"url":{"type":"string"}},["url"]),
    _schema("open_maps","Opens Google Maps.",{"location":{"type":"string"}},["location"]),
    _schema("search_web","Opens a Google search in the browser ('search google for …'). For an answer: search_web_and_read.",
            {"query":{"type":"string"}},["query"]),
    _schema("manage_files","Files and folders: list (what is in a folder), create_folder (source = the new folder, "
            "e.g. ~/Desktop/Projects), copy, move, rename, delete (to the Trash).",
            {"action":{"type":"string","enum":["delete","move","copy","rename","list","create_folder"]},
             "source":{"type":"string"},"destination":{"type":"string"}},["action","source"]),
    _schema("run_shell_command","Runs shell.",{"command":{"type":"string"}},["command"]),
    _schema("take_screenshot","Takes screenshot.",{"save_path":{"type":"string"}}),
    _schema("type_text_keyboard","Types text.",{"text":{"type":"string"},"press_enter":{"type":"boolean"}},["text"]),
    _schema("control_volume","Volume. up/down: a step louder/quieter ('louder', 'turn it up'; level = step); set: an exact level 0-100.",
        {"action":{"type":"string","enum":["up","down","set","mute","unmute","get"]},"level":{"type":"integer"}},["action"]),
    _schema("control_system","System actions.",{"action":{"type":"string","enum":["lock","sleep","shutdown","restart","cancel"]}},["action"]),
    _schema("empty_recycle_bin","Empties the Trash.",{}),
    _schema("get_system_stats","CPU/RAM/disk.",{}),
    _schema("control_spotify","Play/pause or skip a song in Spotify. To open an app use open_application.",{"action":{"type":"string","enum":["play_pause","next","prev"]}},["action"]),
    _schema("read_webpage","Reads a web page.",{"url":{"type":"string"}},["url"]),
    _schema("save_note","Saves a note.",{"text":{"type":"string"}},["text"]),
    _schema("read_notes","Reads notes.",{}),
    _schema("execute_python_code","Runs Python in a separate process (10 s limit, needs user approval).",{"code":{"type":"string"}},["code"]),
    _schema("set_reminder","Reminder in N minutes (fractions allowed). A time of day or repeating: schedule_task.",
            {"text":{"type":"string"},"minutes":{"type":"number"}},["text","minutes"]),
    _schema("save_memory","Saves a lasting fact the user tells you about themselves.",
            {"fact":{"type":"string"},
             "category":{"type":"string","description":"one of: about_me, preference, work, people, task, other"},
             "expires_in_days":{"type":"number","description":"forget it after this many days; omit or 0 = keep"}},["fact"]),
    _schema("read_memory","Reads every saved memory (only the relevant ones are in your prompt).",{}),
    _schema("delete_memory","Forgets memory facts containing the keyword ('forget that ...').",{"keyword":{"type":"string"}},["keyword"]),
    _schema("search_web_and_read","Searches the web and returns titles, links and text snippets of the top results.",
            {"query":{"type":"string"},"num_results":{"type":"integer"}},["query"]),
    _schema("write_file","Writes or appends content to a file.",
            {"path":{"type":"string"},"content":{"type":"string"},"mode":{"type":"string","enum":["w","a"]}},["path","content"]),
    _schema("search_files","Searches for files by name or content.",
            {"query":{"type":"string"},"folder":{"type":"string"},"content_search":{"type":"boolean"}},["query"]),
    _schema("read_file","Reads a local file: text, PDF, Word, PowerPoint, Excel, Numbers or a picture of text (first 8000 chars).",
            {"path":{"type":"string"},"max_chars":{"type":"integer"}},["path"]),
    _schema("open_in_explorer","Shows a file or folder in Finder.",
            {"path":{"type":"string","description":"File or folder path"}},["path"]),
    _schema("get_clipboard",     "Read the current clipboard text",                   {}),
    _schema("set_clipboard",     "Write text to the clipboard",
            {"text": {"type": "string"}}, ["text"]),
    _schema("list_processes",    "List running processes (optional name filter)",
            {"filter_name": {"type": "string"}}),
    _schema("kill_process",      "Quit an app (as ⌘Q: it may ask to save) or end a process, by name or PID. "
                                 "force: kill at once, unsaved work is lost (only when asked to force quit)",
            {"name_or_pid": {"type": "string"}, "force": {"type": "boolean"}}, ["name_or_pid"]),
    _schema("get_battery",       "Get battery level and charging status",             {}),
    _schema("get_network_info",  "Get WiFi/network connection information",           {}),
    _schema("send_notification", "Show a desktop notification",
            {"title": {"type": "string"}, "message": {"type": "string"}}, ["title", "message"]),
    _schema("get_weather",       "Current weather and today's forecast for a city (empty = the user's home city)",
            {"location": {"type": "string"}}),
    _schema("set_wallpaper",     "Set the desktop wallpaper from an image file path",
            {"path": {"type": "string"}}, ["path"]),
    # ── Apple Shortcuts ──
    _schema("list_shortcuts", "Lists the user's Apple Shortcuts.", {}),
    _schema("run_shortcut", "Runs one of the user's Apple Shortcuts (Bulgarian: пряк път); optional text is its input.",
            {"name": {"type": "string"}, "text": {"type": "string"}}, ["name"]),
    # ── scheduled tasks ──
    _schema("schedule_task", "Does something at a time of day, once or repeating. kind ask = send `what` to you then "
            "(e.g. daily news); kind reminder = just show `what`.",
            {"what": {"type": "string"}, "at": {"type": "string", "description": "24h time, e.g. 08:00"},
             "repeat": {"type": "string", "description": "daily, weekdays, weekends, once, or mon,wed,fri"},
             "kind": {"type": "string", "enum": ["ask", "reminder"]},
             "date": {"type": "string", "description": "for once: YYYY-MM-DD"}}, ["what", "at"]),
    _schema("list_scheduled_tasks", "Lists scheduled tasks.", {}),
    _schema("cancel_scheduled_task", "Cancels a scheduled task by part of its text.", {"which": {"type": "string"}}, ["which"]),
    # ── the document library ──
    _schema("search_documents", "Finds passages in the user's indexed documents. Use it for any question about them.",
            {"query": {"type": "string"},
             "also": {"type": "string", "description": "2-4 other wordings: synonyms, and the document's language; separated by ;"},
             "document": {"type": "string", "description": "only documents whose name contains this"},
             "max_results": {"type": "integer"}}, ["query"]),
    _schema("list_documents", "Lists the indexed documents.", {}),
    _schema("add_document", "Indexes a file (PDF, Word, Excel, text) or a folder for search_documents.", {"path": {"type": "string"}}, ["path"]),
    _schema("remove_document", "Removes a document from the index (not the file).", {"name": {"type": "string"}}, ["name"]),
    # ── the Mac's own apps ──
    _schema("get_calendar_events", "Events from the user's Calendar between two ISO date-times (default: today).",
            {"start": {"type": "string"}, "end": {"type": "string"}}),
    _schema("add_calendar_event", "Adds an event to the user's Calendar. Times are ISO, e.g. 2026-10-09T15:00.",
            {"title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
             "all_day": {"type": "boolean"}, "location": {"type": "string"}, "notes": {"type": "string"},
             "calendar": {"type": "string"}}, ["title", "start"]),
    _schema("list_apple_reminders", "Open items in the Mac's Reminders app.", {}),
    _schema("add_apple_reminder", "Adds a to-do to the Mac's Reminders app (syncs to iPhone). `due` is an ISO date-time. "
            "For 'remind me in N minutes' use set_reminder.",
            {"title": {"type": "string"}, "due": {"type": "string"}, "notes": {"type": "string"}, "list_name": {"type": "string"}},
            ["title"]),
    _schema("read_selected_email", "Reads the message selected in the Mail app.", {}),
    _schema("draft_email", "Opens a filled-in draft in Mail. Never sends: the user presses Send.",
            {"to": {"type": "string", "description": "addresses, comma separated"}, "subject": {"type": "string"},
             "body": {"type": "string"}}, ["subject", "body"]),
    _schema("draft_email_reply", "Opens a reply draft to the message selected in Mail. Never sends.",
            {"body": {"type": "string"}}, ["body"]),
    _schema("read_browser_tab", "Reads the web page open in the user's browser.", {}),
] + _PLUGIN_SCHEMAS


# ── Which tools go with a request ──────────────────────────────────
# Every tool definition is sent with every request and counts against the provider's limits, so the tools for
# calendar, mail, browser, documents, schedules, Shortcuts and connected MCP servers are only included when the
# conversation is about them. If the model needs a group that is not there it calls `more_tools` (one cheap
# extra step) and gets it.
# Every tool definition is sent with every request and counts against the provider's allowance, so only a small
# everyday set always travels (open things, the web, weather, remember, remind, note). Everything else comes
# along when the request is about it (the "words"), stays on for the rest of the chat once used, and can be
# switched on by the model itself with more_tools.
GROUPS = {
    "files":     {"tools": ("manage_files", "read_file", "write_file", "search_files", "open_in_explorer", "empty_recycle_bin"),
                  "about": "files and folders, the Trash",
                  "words": ("file", "folder", "director", "desktop", "downloads", "delete", "rename", "move ", "copy ", "trash",
                            "finder", ".txt", "pdf", ".doc", "docx", "xlsx", ".csv", ".md", ".py", ".json", ".png", ".jpg", "~/", " /", "path",
                            "файл", "папк", "изтрий", "изтри", "премест", "преимен", "копир", "кошче", "работния плот", "изтеглян")},
    "system":    {"tools": ("control_volume", "control_system", "get_system_stats", "get_battery", "get_network_info",
                            "list_processes", "kill_process", "take_screenshot", "set_wallpaper", "send_notification"),
                  "about": "volume, lock/sleep/shutdown, battery, CPU/RAM, network, running apps, screenshot, wallpaper, notifications",
                  "words": ("volume", "mute", "louder", "quieter", "sound", "battery", "charg", "cpu", "ram", "memory usage", "disk",
                            "storage", "wifi", "wi-fi", "network", "ip address", "internet", "process", "running", "kill", "quit ",
                            "close ", "force", "screenshot", "screen shot", "wallpaper", "lock", "sleep", "shut", "restart", "reboot",
                            "notif", "system", "звук", "заглуш", "по-силно", "по-тихо", "усили", "намали", "батери", "зареден",
                            "процес", "мрежа", "интернет", "заключ", "изключи", "рестарт", "заспи", "приспи", "снимка на екрана",
                            "скрийншот", "тапет", "известие", "затвори", "спри ")},
    "clipboard": {"tools": ("get_clipboard", "set_clipboard", "type_text_keyboard"),
                  "about": "clipboard, typing into the front app",
                  "words": ("clipboard", "copy", "paste", "type ", "typing", "copied", "клипборд", "копир", "постав", "напиши в", "въведи")},
    "music":     {"tools": ("control_spotify",),
                  "about": "Spotify playback",
                  "words": ("song", "music", "spotify", "track", "play", "pause", "skip", "песен", "песн", "музик", "пусни", "пауза", "следващ", "предишн")},
    "notes":     {"tools": ("read_notes", "read_memory", "delete_memory"),
                  "about": "read notes, list or delete memories",
                  "words": ("note", "forget", "memory", "memories", "know about me", "бележк", "забрави", "памет",
                            "знаеш за мен", "помниш")},
    "code":      {"tools": ("run_shell_command", "execute_python_code"),
                  "about": "shell commands, Python code",
                  "words": ("command", "terminal", "shell", "python", "script", "code", "run ", "execute", "compute", "calculat",
                            "brew ", "git ", "npm ", "pip ", "команда", "терминал", "код", "скрипт", "изпълни", "изчисли", "пресметни")},
    "calendar":  {"tools": ("get_calendar_events", "add_calendar_event", "list_apple_reminders", "add_apple_reminder"),
                  "about": "calendar events and the Reminders app",
                  "words": ("calendar", "meeting", "appointment", "event", "agenda", "remind", "to-do", "todo list", "birthday",
                            "календар", "среща", "срещи", "събити", "напомн", "ангажимент", "рожден")},
    "mail":      {"tools": ("read_selected_email", "draft_email", "draft_email_reply"),
                  "about": "selected email, drafts",
                  "words": ("mail", "inbox", "reply to", "имейл", "мейл", "поща", "писмо")},
    "browser":   {"tools": ("read_browser_tab",),
                  "about": "the page open in the browser",
                  "words": ("this page", "the page", "web page", "webpage", " tab", "browser", "article", "website", "this site",
                            "safari", "chrome", "страница", "сайт", "браузър", "статия", "таб")},
    "documents": {"tools": ("search_documents", "list_documents", "add_document", "remove_document"),
                  "about": "the user's indexed documents",
                  "words": ("document", "pdf", "docx", "my files", "contract", "handbook", "manual", "index ", "документ", "договор",
                            "наръчник")},
    "schedule":  {"tools": ("schedule_task", "list_scheduled_tasks", "cancel_scheduled_task"),
                  "about": "things at a time of day, repeating",
                  "words": ("every ", "each ", "daily", "weekly", "weekday", "schedul", "recurring", "repeat", "o'clock",
                            "всеки ", "всяка ", "всяко ", "ежедневн", "планира", "насроч")},
    "shortcuts": {"tools": ("list_shortcuts", "run_shortcut"),
                  "about": "Apple Shortcuts",
                  "words": ("shortcut", "пряк път", "прекия път", "преки пътища", "шорткът")},
}
_GROUP_OF = {t: g for g, spec in GROUPS.items() for t in spec["tools"]}
import re as _re
_AT_TIME = _re.compile(r"\b(?:at|в|от)\s+\d{1,2}(?::\d\d)?\s*(?:am|pm|ч)?\b")


def group_of(tool_name: str):
    """The on-demand group a tool belongs to (None = always available)."""
    if tool_name in _GROUP_OF: return _GROUP_OF[tool_name]
    m = computer_tools.MCP_TOOLS.get(tool_name)
    return ("mcp:" + m["server"]) if m else None


def _mcp_groups() -> dict:
    out = {}
    for m in computer_tools.MCP_TOOLS.values():
        out.setdefault("mcp:" + m["server"], []).append(m["tool"])
    return out


def groups_for(text: str, sticky=()) -> set:
    """Groups a request should carry: the ones already in use in this chat plus the ones the text is about."""
    low = " " + (text or "").lower() + " "
    active = {g for g in sticky}
    for g, spec in GROUPS.items():
        if any(w in low for w in spec["words"]): active.add(g)
    if _AT_TIME.search(low) and any(w in low for w in ("remind", "напомн", "tell me", "send me", "give me", "кажи ми", "дай ми")):
        active.add("schedule")
    for g in _mcp_groups():
        if g[4:].lower().replace("_", " ") in low or g[4:].lower() in low: active.add(g)
    try:
        import docs
        if docs.library().names(): active.add("documents")       # the prompt already tells the model to search them
    except Exception as e: log.debug("document library not readable while choosing tools: %s", e)
    return active


def _more_tools_schema(active: set):
    """The fallback tool that switches a group on - only listing what is not on already."""
    choices = [f"{g} ({spec['about']})" for g, spec in GROUPS.items() if g not in active]
    names = [g for g in GROUPS if g not in active]
    for g, tool_names in _mcp_groups().items():
        if g not in active:
            names.append(g[4:]); choices.append(f"{g[4:]} (connected server: {', '.join(tool_names[:6])}{' …' if len(tool_names) > 6 else ''})")
    if not names: return None
    return _schema("more_tools", "Enables tools not in your list yet. Call it when the task needs: " + "; ".join(choices) + ".",
                   {"group": {"type": "string", "enum": names}}, ["group"])


def select_tools(text: str, sticky=()) -> tuple:
    """(tool definitions for this request, the groups that are on)."""
    active = groups_for(text, sticky)
    out = [s for s in TOOLS_SCHEMA if (group_of(s["function"]["name"]) or "") in active or group_of(s["function"]["name"]) is None]
    meta = _more_tools_schema(active)
    if meta: out.append(meta)
    return out, active

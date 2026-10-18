# tools.py — the tools the AI can use, and the rules for using them.
#
# The tools themselves live in themed modules and are gathered here:
#   tools_apps.py    open apps, web addresses, maps, Finder        tools_web.py    read pages, search, weather
#   tools_system.py  volume, power, clipboard, processes …         tools_files.py  files, notes, shell, Python
# This file keeps the tools that need NOVA's own state (memory, reminders, documents, schedule, MCP, the Mac's
# apps), the table of all tools, and everything about safety: what needs your approval, "always allow",
# what counts as outside content, the activity log, and plugins.
import os, json, re, time, threading, logging
import platform_utils as plat
import paths
import storage
import ledger
import memory as mem
import sandbox
import mac_apps
import docs
import schedule as sched
import mcp_client
import toolbase
from toolbase import HOME, UNTRUSTED_NOTE, ToolFailure, fail
from tools_apps import open_application, open_url, open_maps, search_web, open_in_explorer
from tools_system import (take_screenshot, type_text_keyboard, control_volume, control_system, empty_recycle_bin,
                          get_system_stats, control_spotify, get_clipboard, set_clipboard, list_processes, kill_process,
                          get_battery, get_network_info, send_notification, set_wallpaper)
from tools_web import read_webpage, search_web_and_read, get_weather
from tools_files import (manage_files, run_shell_command, save_note, read_notes, execute_python_code, write_file,
                         search_files, read_file)

log = logging.getLogger("nova")

# ── Hooks set by the GUI ──────────────────────────────────────────
# CONFIRM_HOOK(description) -> bool   asks the user before a risky action runs.
# REMINDER_HOOK(text)                 shows a fired reminder inside the app.
# PRE_TYPE_HOOK()                     hands keyboard focus to another app before typing.
CONFIRM_HOOK = None
REMINDER_HOOK = None
PRE_TYPE_HOOK = None



# ── TOOL: set_reminder ────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REMINDERS_FILE = paths.REMINDERS_FILE
_rem_lock = threading.Lock()

def _read_reminders() -> list:
    try:
        items = storage.read_json(REMINDERS_FILE)
        return items if isinstance(items, list) else []
    except Exception:
        return []

def _write_reminders(items: list):
    try:
        storage.write_json(REMINDERS_FILE, items, indent=None)
    except Exception as e: log.warning("reminders could not be saved: %s", e)

def _fire_reminder(rid: str, text: str):
    with _rem_lock:
        _write_reminders([r for r in _read_reminders() if r.get("id") != rid])
    plat.notify("NOVA Reminder", text, ms=8000)
    if REMINDER_HOOK:
        try: REMINDER_HOOK(text)
        except Exception as e: log.warning("a reminder could not be shown: %s", e)

def _schedule_reminder(rid: str, text: str, delay: float):
    t = threading.Timer(max(0.0, delay), _fire_reminder, args=(rid, text))
    t.daemon = True
    t.start()

def restore_reminders():
    """Re-arm reminders saved by a previous run (called once the GUI is ready)."""
    now = time.time()
    for r in _read_reminders():
        _schedule_reminder(r["id"], r["text"], r["due"] - now)

def set_reminder(text: str = None, minutes: float = None, message: str = None, seconds: float = None) -> str:
    text = text or message
    if not text: return fail("What should I remind you about?")
    if minutes is None and seconds is None: return fail("When? Give minutes (or seconds).")
    try:
        minutes = float(minutes) if minutes is not None else float(seconds) / 60.0
    except (TypeError, ValueError):
        return fail("Invalid time.")
    minutes = max(0.0, minutes)
    rid = f"{time.time():.6f}"
    with _rem_lock:
        items = _read_reminders(); items.append({"id": rid, "text": text, "due": time.time() + minutes * 60})
        _write_reminders(items)
    _schedule_reminder(rid, text, minutes * 60)
    t = (f"{round(minutes*60)} sec" if minutes < 1
         else f"{round(minutes)} min" if minutes < 60
         else f"{minutes/60:.1f} hr")
    return f"Reminder set for {t}: '{text}' ✓"

# ── TOOL: save_memory ────────────────────────────────────────────
# Storage, categories, expiry and "which memories matter for this question" live in memory.py.
MEMORY_FILE  = paths.MEMORY_FILE
_mem_lock = threading.Lock()

def memory_items() -> list:
    """Every live memory as a dict (text / category / created / expires), oldest first."""
    with _mem_lock:
        return mem.load(MEMORY_FILE)

def replace_memory_items(items: list) -> None:
    with _mem_lock:
        mem.save(MEMORY_FILE, items)

def _load_facts() -> list:
    return [mem.to_display(it) for it in mem.load(MEMORY_FILE)]

def list_memories() -> list:
    """The memories as display strings ('[07.10.2026] likes tea')."""
    return [mem.to_display(it) for it in memory_items()]

def replace_memories(facts: list) -> None:
    """Accepts memory dicts or old-style strings."""
    replace_memory_items([f for f in facts if (f.get("text") if isinstance(f, dict) else str(f)).strip()])

REQUESTED_GROUPS = set()      # tool groups the model switched on with more_tools during this request

def more_tools(group: str) -> str:
    """The model asks for a group of tools that was not sent with the request (see schemas.select_tools)."""
    import schemas
    g = str(group or "").strip().lower()
    key = g if g in schemas.GROUPS else next((k for k in schemas._mcp_groups() if k[4:].lower() == g), None)
    if key is None:
        known = list(schemas.GROUPS) + [k[4:] for k in schemas._mcp_groups()]
        return fail(f"There is no tool group '{group}'. Groups: {', '.join(known)}.")
    REQUESTED_GROUPS.add(key)
    names = list(schemas.GROUPS[key]["tools"]) if key in schemas.GROUPS else \
        [tid for tid, m in MCP_TOOLS.items() if "mcp:" + m["server"] == key]
    return "Enabled: " + ", ".join(names) + ". Call the one you need now."

TAG_HOOK = None               # called (no arguments) after a memory was saved, so the GUI can fetch keywords for it

def set_memory_tags(tags_by_text: dict) -> int:
    """Store keywords for memories that have none yet. Returns how many were updated."""
    n = 0
    with _mem_lock:
        items = mem.load(MEMORY_FILE)
        for it in items:
            if not it.get("tags") and tags_by_text.get(it["text"]):
                it["tags"] = str(tags_by_text[it["text"]])[:400]; n += 1
        if n: mem.save(MEMORY_FILE, items)
    return n

def memory_prompt(query: str = "") -> str:
    """The memories worth sending with this request (see memory.relevant)."""
    try: return mem.prompt_text(memory_items(), query)
    except Exception: return ""

def save_memory(fact: str, category: str = "", expires_in_days: float = 0) -> str:
    fact = (fact or "").strip()
    if not fact: return fail("Nothing to remember.")
    try:
        with _mem_lock:
            items = mem.add(mem.load(MEMORY_FILE), fact, category, expires_in_days)
            mem.save(MEMORY_FILE, items)
            saved = items[-1]
        note = f" (until {saved['expires']})" if saved["expires"] else ""
        if TAG_HOOK:
            try: TAG_HOOK()
            except Exception as e: log.info("memory keywords were not requested: %s", e)
        return f"Remembered: {fact} \u2713{note}"
    except Exception as e:
        return fail(f"Error saving memory: {e}")

def read_memory() -> str:
    try:
        items = memory_items()
        if not items: return "No saved memories."
        return "Saved memories:\n" + "\n".join(mem.line(it) for it in items[-60:])
    except Exception as e:
        return fail(f"Error: {e}")

def delete_memory(keyword: str) -> str:
    keyword = (keyword or "").strip()
    if len(keyword) < 2:
        return fail("Give a keyword of at least 2 characters (refusing to delete everything).")
    try:
        with _mem_lock:
            items = mem.load(MEMORY_FILE)
            kept = mem.remove(items, keyword)
            if len(kept) == len(items):
                near = mem.closest(items, keyword)
                if not near: return fail(f"No facts containing '{keyword}'. Nothing was deleted.")
                return fail(f"No facts contain '{keyword}', so nothing was deleted. The closest: "
                            + "; ".join(f"“{it['text']}”" for it in near)
                            + ". If one of these is meant, call delete_memory again with a word from it.")
            mem.save(MEMORY_FILE, kept)
        return f"Deleted {len(items) - len(kept)} fact(s) containing '{keyword}' \u2713"
    except Exception as e:
        return fail(f"Error: {e}")

# ── MCP servers (tool servers the user connected) ────────────────
MCP = None                    # mcp_client.Manager, created by the GUI
MCP_TOOLS = {}                # tool id the AI sees -> {"server", "tool"}
MAX_MCP_TOOLS = 80            # every tool's description is sent with every request: keep the total sane

def _mcp_tool(tid: str):
    def call(**kwargs):
        info = MCP_TOOLS.get(tid)
        if info is None or MCP is None: return fail("That tool's server is no longer connected.")
        srv = MCP.servers.get(info["server"])
        if srv is not None and not srv.is_http:                  # (web servers are recorded by the transport itself)
            ledger.record("(mcp) " + info["server"], "MCP tool", ledger.size_of(kwargs), info["tool"])
        try:
            text, is_error = MCP.call(info["server"], info["tool"], kwargs)
        except mcp_client.MCPError as e:
            return fail(f"{info['server']}: {e}")
        return fail(text) if is_error else UNTRUSTED_NOTE + text
    return call

def register_mcp_server(server) -> list:
    """Make a connected server's tools callable. Returns the schemas to hand to the AI."""
    unregister_mcp_server(server.name)
    schemas = []
    for t in server.tools:
        if len(MCP_TOOLS) >= MAX_MCP_TOOLS:
            log.warning("MCP: tool limit reached - %s tools beyond %d are not offered", server.name, MAX_MCP_TOOLS); break
        tid = mcp_client.tool_id(server.name, t["name"])
        if tid in TOOL_FUNCTIONS: continue
        MCP_TOOLS[tid] = {"server": server.name, "tool": t["name"]}
        TOOL_FUNCTIONS[tid] = _mcp_tool(tid)
        schemas.append({"type": "function", "function": {
            "name": tid, "description": f"[{server.name}] {t['description']}"[:1024], "parameters": t["schema"]}})
    return schemas

def unregister_mcp_server(name: str) -> list:
    """Forget a server's tools. Returns the tool ids that were removed."""
    gone = [tid for tid, info in MCP_TOOLS.items() if info["server"] == name]
    for tid in gone:
        MCP_TOOLS.pop(tid, None); TOOL_FUNCTIONS.pop(tid, None)
    return gone

# ── TOOLS: scheduled tasks (repeating reminders, requests at set times) ──
_sched_lock = threading.RLock()

def schedule_task(what: str, at: str, repeat: str = "daily", kind: str = "ask", date: str = "") -> str:
    """kind 'ask' = send `what` to the assistant at that time; 'reminder' = just show it."""
    try:
        task = sched.make(kind, what, at, repeat, date)
    except sched.ScheduleError as e:
        return fail(str(e))
    with _sched_lock:
        tasks = sched.load(paths.SCHEDULE_FILE)
        if len(tasks) >= sched.MAX_TASKS: return fail(f"There are already {sched.MAX_TASKS} scheduled tasks. Cancel some first.")
        tasks.append(task); sched.save(paths.SCHEDULE_FILE, tasks)
    what_kind = "Reminder" if task["kind"] == "reminder" else "Scheduled request"
    return f"{what_kind} saved: “{task['text']}” — {sched.describe(task)}. It runs while NOVA is open ✓"

def list_scheduled_tasks() -> str:
    with _sched_lock: tasks = sched.load(paths.SCHEDULE_FILE)
    if not tasks: return "Nothing is scheduled."
    lines = ["Scheduled:"]
    for t in tasks:
        state = "" if t.get("enabled", True) else "  (turned off)"
        lines.append(f"• [{t['kind']}] {t['text']} — {sched.describe(t)}{state}")
    return "\n".join(lines)

def cancel_scheduled_task(which: str) -> str:
    with _sched_lock:
        tasks = sched.load(paths.SCHEDULE_FILE)
        hits = sched.find(tasks, which)
        if not hits: return fail(f"Nothing scheduled matches '{which}'.")
        if len(hits) > 1:
            return fail("More than one task matches - say which: " + "; ".join(f"“{t['text']}” ({sched.describe(t)})" for t in hits[:6]))
        sched.save(paths.SCHEDULE_FILE, [t for t in tasks if t.get("id") != hits[0]["id"]])
    return f"Cancelled: “{hits[0]['text']}” ({sched.describe(hits[0])}) ✓"

# ── TOOLS: the document library ("ask about your documents") ─────
def search_documents(query: str, also: str = "", document: str = "", max_results: int = 6) -> str:
    """The passages of the user's indexed documents that best match a question. `also` = other wordings of it."""
    lib = docs.library()
    if not lib.names():
        return fail("No documents are indexed yet. The user can drop a file or folder onto NOVA, or you can call add_document.")
    try: lib.refresh()                                   # a file that changed since it was indexed is read again first
    except Exception as e: log.info("document refresh skipped: %s", e)
    queries = [query] + [q for q in re.split(r"[;\n|]+", str(also or "")) if q.strip()]
    material = docs.answer_material(queries, max(1, min(int(max_results or 6), 10)), document or "")
    if not material:
        return f"Nothing in the indexed documents matches '{query}'. Documents: {', '.join(lib.names()[:30])}"
    return UNTRUSTED_NOTE + f"Passages from the user's documents for: '{query}'\n\n" + material

def list_documents() -> str:
    info = docs.library().info()
    if not info: return "No documents are indexed."
    return "Indexed documents:\n" + "\n".join(f"• {d['name']}  ({d['parts']} passages, added {d['added']})" for d in info)

def add_document(path: str) -> str:
    """Index a file, or every supported file in a folder, so its content can be searched."""
    p = toolbase.user_path(path)
    try:
        if os.path.isdir(p):
            r = docs.library().add_folder(p)
            msg = f"Indexed {len(r['added'])} document(s) from {p} ✓"
            if r["skipped"]: msg += f" — skipped {len(r['skipped'])}: " + "; ".join(f"{n} ({why})" for n, why in r["skipped"][:5])
            if r["more"]: msg += f" — {r['more']} more files were left out (limit {docs.MAX_FOLDER_FILES} per folder)"
            return msg if r["added"] else fail(msg if r["skipped"] else f"No readable documents found in {p}.")
        d = docs.library().add_file(p)
        return f"Indexed {d['name']} ({d['parts']} passages) ✓" + (" — it is very long, so only the first part was indexed" if d["cut"] else "")
    except docs.DocError as e:
        return fail(str(e))

def remove_document(name: str) -> str:
    return f"Removed {name} from the document library ✓" if docs.library().remove(str(name or "")) \
        else fail(f"There is no indexed document called '{name}'.")

# ── TOOLS: the Mac's own apps (Calendar, Reminders, Mail, browser, Shortcuts) ──
def _app_tool(fn):
    """Turn mac_apps.AppError into a normal tool failure with its plain message."""
    def tool(**kw):
        if not plat.IS_MAC: return fail("This works on macOS only.")
        try:
            return fn(**kw)
        except mac_apps.AppError as e:
            return fail(str(e))
    tool.__name__ = fn.__name__
    return tool

def read_browser_tab() -> str:
    """The page open in the user's browser: its address, title and text."""
    if not plat.IS_MAC: return fail("This works on macOS only.")
    try:
        tab = mac_apps.browser_tab(_typing_target())
    except mac_apps.AppError as e:
        return fail(str(e))
    text = tab["text"]
    if not text and tab["url"].startswith(("http://", "https://")):
        # Chrome-family browsers do not hand out the page text; fetch the address instead (public pages only)
        fetched = read_webpage(tab["url"])
        if isinstance(fetched, ToolFailure):
            return (UNTRUSTED_NOTE + f"Browser tab ({tab['browser']}): {tab['title']}\n{tab['url']}\n\n"
                    f"[The text of this page could not be read: {fetched}. Ask the user to paste the part they mean.]")
        text = str(fetched).replace(UNTRUSTED_NOTE, "", 1) + "\n[Fetched separately from the address - a page that needs your login may look different.]"
    return UNTRUSTED_NOTE + f"Browser tab ({tab['browser']}): {tab['title']}\n{tab['url']}\n\n{text[:6000]}"

def list_shortcuts() -> str:
    """The user's Shortcuts (from the Shortcuts app)."""
    if not plat.IS_MAC: return fail("This works on macOS only.")
    try:
        names = mac_apps.list_shortcuts()
    except mac_apps.AppError as e:
        return fail(str(e))
    return ("Shortcuts:\n" + "\n".join("• " + n for n in names[:150])) if names else "There are no shortcuts in the Shortcuts app."

TOOL_FUNCTIONS = {
    "more_tools":          more_tools,
    "list_shortcuts":      list_shortcuts,
    "run_shortcut":        _app_tool(mac_apps.run_shortcut),
    "schedule_task":       schedule_task,
    "list_scheduled_tasks": list_scheduled_tasks,
    "cancel_scheduled_task": cancel_scheduled_task,
    "search_documents":    search_documents,
    "list_documents":      list_documents,
    "add_document":        add_document,
    "remove_document":     remove_document,
    "get_calendar_events": _app_tool(mac_apps.calendar_events),
    "add_calendar_event":  _app_tool(mac_apps.add_calendar_event),
    "list_apple_reminders": _app_tool(mac_apps.list_reminders),
    "add_apple_reminder":  _app_tool(mac_apps.add_reminder),
    "read_selected_email": _app_tool(mac_apps.read_selected_email),
    "draft_email":         _app_tool(mac_apps.draft_email),
    "draft_email_reply":   _app_tool(mac_apps.draft_email_reply),
    "read_browser_tab":    read_browser_tab,
    "open_application":    open_application,
    "open_url":            open_url,
    "open_maps":           open_maps,
    "search_web":          search_web,
    "search_web_and_read": search_web_and_read,
    "manage_files":        manage_files,
    "run_shell_command":   run_shell_command,
    "take_screenshot":     take_screenshot,
    "type_text_keyboard":  type_text_keyboard,
    "control_volume":      control_volume,
    "control_system":      control_system,
    "empty_recycle_bin":   empty_recycle_bin,
    "get_system_stats":    get_system_stats,
    "control_spotify":     control_spotify,
    "read_webpage":        read_webpage,
    "save_note":           save_note,
    "read_notes":          read_notes,
    "execute_python_code": execute_python_code,
    "set_reminder":        set_reminder,
    "save_memory":         save_memory,
    "read_memory":         read_memory,
    "delete_memory":       delete_memory,
    "write_file":          write_file,
    "search_files":        search_files,
    "get_clipboard":       get_clipboard,
    "set_clipboard":       set_clipboard,
    "list_processes":      list_processes,
    "kill_process":        kill_process,
    "get_battery":         get_battery,
    "get_network_info":    get_network_info,
    "send_notification":   send_notification,
    "get_weather":         get_weather,
    "set_wallpaper":       set_wallpaper,
    "read_file":           read_file,
    "open_in_explorer":    open_in_explorer,
}

# ── Prompt-injection defence ──────────────────────────────────────
# Once a request has read web pages / search results / file contents, those texts may contain
# hidden instructions. From then on, every tool that has side effects (or could leak data, e.g.
# by opening a crafted URL) needs explicit approval, and "always allow" is disabled.
UNTRUSTED_SOURCES = {"read_webpage", "search_web_and_read", "read_file", "get_clipboard",
                     # other people write these: an invitation title or an email can carry hidden instructions
                     "get_calendar_events", "list_apple_reminders", "read_selected_email", "read_browser_tab",
                     "search_documents"}
SIDE_EFFECT_TOOLS = {"open_url", "open_maps", "search_web", "open_application", "open_in_explorer",
                     "set_clipboard", "save_memory", "delete_memory", "save_note", "set_reminder",
                     "send_notification", "take_screenshot", "set_wallpaper", "manage_files",
                     "control_volume", "control_spotify",
                     "add_calendar_event", "add_apple_reminder", "draft_email", "draft_email_reply",
                     "remove_document", "schedule_task", "cancel_scheduled_task", "run_shortcut"}
PLUGIN_TOOLS = set()                       # names registered by user plugins (always ask)
SETTINGS = {}                              # the app's live config dict (set by the GUI)
_PARAM_SCHEMAS = {}                        # tool name -> JSON-schema "parameters" (set via set_schemas)

def set_schemas(schemas: list):
    """Register the tool definitions so execute_tool can validate the model's arguments."""
    for s in schemas:
        f = s.get("function", {})
        if f.get("name"): _PARAM_SCHEMAS[f["name"]] = f.get("parameters", {})

# Words models reach for instead of the exact value a tool expects. They mean the same, so NOVA accepts them
# rather than sending the model round again (seen with the real AI: "increase" for the volume, "write" for a file).
_SAME_AS = {
    ("control_volume", "action"): {"increase": "up", "raise": "up", "louder": "up", "volume_up": "up", "decrease": "down", "lower": "down",
                                   "quieter": "down", "volume_down": "down", "silence": "mute", "toggle_mute": "mute", "status": "get"},
    ("control_system", "action"): {"hibernate": "sleep", "suspend": "sleep", "reboot": "restart", "shut down": "shutdown", "shut_down": "shutdown",
                                   "power_off": "shutdown", "poweroff": "shutdown", "lock_screen": "lock", "lock screen": "lock", "abort": "cancel"},
    ("control_spotify", "action"): {"play": "play_pause", "pause": "play_pause", "toggle": "play_pause", "playpause": "play_pause",
                                    "resume": "play_pause", "stop": "play_pause", "skip": "next", "next_track": "next", "forward": "next",
                                    "previous": "prev", "previous_track": "prev", "back": "prev"},
    ("write_file", "mode"): {"write": "w", "overwrite": "w", "create": "w", "replace": "w", "w+": "w", "wt": "w",
                             "append": "a", "add": "a", "a+": "a", "at": "a"},
    ("schedule_task", "kind"): {"request": "ask", "question": "ask", "prompt": "ask", "task": "ask", "remind": "reminder", "notification": "reminder"},
}


def validate_args(tool_name: str, args: dict):
    """(clean_args, error). Fixes harmless type slips ("5" -> 5) and reports real problems to the model."""
    schema = _PARAM_SCHEMAS.get(tool_name)
    args = dict(args or {})
    if not schema: return args, ""
    props, required = schema.get("properties", {}), schema.get("required", [])
    if not props:                                  # a tool without parameters: small models still send things like {"": {}}
        return {}, ""
    args = {k: v for k, v in args.items() if str(k).strip()}       # an empty key is never meant
    unknown = [k for k in args if k not in props]
    if unknown: return args, f"unknown argument(s): {', '.join(unknown)}. Allowed: {', '.join(props) or 'none'}"
    missing = [k for k in required if k not in args or args[k] in (None, "")]
    if missing: return args, f"missing required argument(s): {', '.join(missing)}"
    for k, v in list(args.items()):
        spec = props.get(k, {}); typ = spec.get("type")
        try:
            if typ == "integer" and not isinstance(v, bool): args[k] = int(float(v))
            elif typ == "number" and not isinstance(v, bool): args[k] = float(v)
            elif typ == "boolean" and isinstance(v, str): args[k] = v.strip().lower() in ("true", "1", "yes")
            elif typ == "string" and not isinstance(v, str): args[k] = str(v)
        except (TypeError, ValueError):
            return args, f"argument '{k}' must be a {typ}, got {v!r}"
        if "enum" in spec and args[k] not in spec["enum"]:
            same = _SAME_AS.get((tool_name, k), {}).get(str(args[k]).strip().lower())
            if same is None and isinstance(args[k], str) and args[k].strip().lower() in spec["enum"]: same = args[k].strip().lower()
            if same in spec["enum"]: args[k] = same
            else: return args, f"argument '{k}' must be one of {spec['enum']}, got {args[k]!r}"
    return args, ""
_taint = {"on": False, "src": ""}

def begin_request(user_text: str = ""):
    """Call at the start of every user request: forget what the previous one read. `user_text` (what the user wrote
    in this conversation) gives the web addresses NOVA may open later without asking."""
    _taint["on"] = False; _taint["src"] = ""
    REQUESTED_GROUPS.clear()
    toolbase.SEEN_URLS.clear(); toolbase.note_urls(user_text or "")

def taint(source: str) -> None:
    """Mark this request as having read content someone else wrote (a file, a page, text selected in another app)."""
    _taint["on"] = True; _taint["src"] = source

def is_tainted() -> bool:
    return _taint["on"]

TAINT_WARNING = ("⚠️ NOVA read web or file content earlier in this request, and such content can hide "
                 "instructions. Approve only if this is what YOU asked for.\n\n")

# Actions that must be approved by the user before they run.
def needs_confirmation(tool_name: str, args: dict) -> str:
    """Return a human-readable description if this call is risky, else ''."""
    desc = _needs_confirmation(tool_name, args)
    if not desc and _taint["on"] and tool_name == "read_webpage":
        url = str((args or {}).get("url", ""))
        if toolbase.norm_url(url) not in toolbase.SEEN_URLS:          # an address nobody gave NOVA: it could carry data out
            desc = f"Open a web address that did not come from you or from what NOVA read:\n{url[:300]}"
    if not desc and _taint["on"] and tool_name in SIDE_EFFECT_TOOLS:
        shown = ", ".join(f"{k}={str(v)[:120]}" for k, v in (args or {}).items())
        desc = f"{tool_name}({shown})"
    if desc and _taint["on"]:
        desc = TAINT_WARNING + desc
    return desc

def _needs_confirmation(tool_name: str, args: dict) -> str:
    a = args or {}
    if tool_name == "run_shortcut":                             # a shortcut can do anything its author built into it
        text = str(a.get("text") or "")
        return f"Run your shortcut “{a.get('name', '')}”" + (f" with this text:\n{text[:300]}" if text else "")
    if tool_name in MCP_TOOLS:
        m = MCP_TOOLS[tool_name]
        shown = ", ".join(f"{k}={str(v)[:120]}" for k, v in a.items()) or "no arguments"
        return f"Use the connected server “{m['server']}”: {m['tool']}\n{shown[:500]}"
    if tool_name in PLUGIN_TOOLS:
        info = PLUGIN_INFO.get(tool_name, {})
        if info.get("sandboxed") and not info.get("permissions"):
            return ""                              # sealed in the sandbox with no network and no files: nothing to approve
        how = ("sandboxed: " + ", ".join(info["permissions"])) if info.get("sandboxed") else "NOT sandboxed - full access"
        return f"Run plugin tool '{tool_name}' ({how}) with {str(a)[:300]}"
    if SETTINGS.get("confirm_memory") and tool_name in ("save_memory", "delete_memory"):
        return ("Remember: " if tool_name == "save_memory" else "Forget memories containing: ") + str(
            a.get("fact") or a.get("keyword") or "")[:300]
    if tool_name == "run_shell_command":
        return f"Run shell command:\n{a.get('command', '')}"
    if tool_name == "execute_python_code":
        return f"Run Python code:\n{str(a.get('code', ''))[:600]}"
    if tool_name == "manage_files" and a.get("action") == "copy" and _copy_replaces(a):
        return f"copy file(s), replacing what is there:\n{a.get('source', '')}\n→ {a.get('destination', '')}"
    if tool_name == "manage_files" and a.get("action") in ("delete", "move", "rename"):
        return f"{a.get('action')} file(s):\n{a.get('source', '')}" + (
            f"\n→ {a.get('destination')}" if a.get("destination") else "")
    if tool_name == "write_file":
        p = toolbase.user_path(a.get("path", ""))
        verb = "Append to" if a.get("mode") == "a" else ("Overwrite" if os.path.exists(p) else "Create")
        return f"{verb} file:\n{p}"
    if tool_name == "kill_process":
        return f"Kill process: {a.get('name_or_pid', '')}"
    if tool_name == "control_system" and str(a.get("action", "")).lower() in ("shutdown", "restart", "sleep", "hibernate"):
        return f"System action: {a.get('action')}"
    if tool_name == "empty_recycle_bin":
        return "Permanently empty the Trash"
    if tool_name == "type_text_keyboard":
        return f"Type into {_typing_target() or 'the active app'}:\n{str(a.get('text', ''))[:300]}"
    return ""

def _copy_replaces(a: dict) -> bool:
    """Would copying `source` to `destination` replace something that is already there?"""
    src, dest = _expand(a.get("source", "")), _expand(a.get("destination", "") or "")
    if not dest: return False
    final = os.path.join(dest, os.path.basename(src)) if os.path.isdir(dest) else dest
    return os.path.lexists(final)


# ── Scoped "always allow" ─────────────────────────────────────────
# Instead of all-or-nothing, the user can pre-approve
#   • file changes inside ONE folder            key  files:dir:/Users/me/Documents/notes
#   • typing into ONE app                       key  type:app:Notes
#   • putting the Mac to sleep                  key  control_system:sleep
# Shell commands, Python, deleting, killing processes and shutdown can never be pre-approved.
TARGET_APP_HOOK = None          # () -> name of the app that will receive typed text (set by the GUI)

def _expand(path) -> str:
    return os.path.realpath(toolbase.user_path(path))

def _offerable_dir(directory: str) -> bool:
    """Only ordinary folders inside the home folder can be pre-approved - never the home folder itself,
    hidden folders (.ssh, .config …), ~/Library, or anything outside home."""
    home = os.path.realpath(HOME)
    if not directory.startswith(home + os.sep): return False
    parts = directory[len(home) + 1:].split(os.sep)
    return bool(parts) and parts[0] != "Library" and not any(part.startswith(".") for part in parts)

def _affected_paths(tool_name: str, a: dict):
    """Files a call would change, or None if this call can never be pre-approved."""
    if tool_name == "write_file":
        return [_expand(a.get("path"))] if a.get("path") else None
    if tool_name == "manage_files" and a.get("action") in ("move", "rename") and a.get("source") and a.get("destination"):
        return [_expand(a["source"]), _expand(a["destination"])]
    if tool_name == "manage_files" and a.get("action") == "copy" and a.get("source") and a.get("destination"):
        dest, src = _expand(a["destination"]), _expand(a["source"])
        return [os.path.join(dest, os.path.basename(src)) if os.path.isdir(dest) else dest]
    return None

def _typing_target() -> str:
    try: return (TARGET_APP_HOOK() or "").strip() if TARGET_APP_HOOK else ""
    except Exception: return ""

def approval_key(tool_name: str, args: dict):
    """Key under which the user may choose 'always allow', or None if this action must always ask."""
    if _taint["on"] or tool_name in PLUGIN_TOOLS or tool_name in ("save_memory", "delete_memory"): return None
    a = args or {}
    if tool_name == "run_shortcut":
        name = str(a.get("name", "")).strip()
        return f"shortcut:{name}" if name else None
    if tool_name in MCP_TOOLS:                                 # one server tool at a time may be pre-approved
        return f"mcp:{MCP_TOOLS[tool_name]['server']}:{MCP_TOOLS[tool_name]['tool']}"
    if tool_name == "type_text_keyboard":
        app = _typing_target()
        return f"type:app:{app}" if app else None             # unknown target app: ask every time
    paths_ = _affected_paths(tool_name, a)
    if paths_:
        dirs = {os.path.dirname(p_) for p_ in paths_}
        if len(dirs) == 1 and _offerable_dir(next(iter(dirs))):
            return "files:dir:" + next(iter(dirs))
        return None
    if tool_name == "control_system" and str(a.get("action", "")).lower() == "sleep": return "control_system:sleep"
    return None                       # shell, Python, delete, kill, shutdown ... are always asked

def approval_label_parts(key: str):
    """(template, argument) for the 'always' button of an approval key - the UI translates the template."""
    home = os.path.realpath(HOME)
    if key.startswith("files:dir:"):
        d = key[len("files:dir:"):]
        return "Always allow in {}", ("~" + d[len(home):] if d.startswith(home) else d)
    if key.startswith("type:app:"): return "Always allow typing in {}", key[len("type:app:"):]
    if key.startswith("mcp:"):
        _p, server, tool = (key.split(":", 2) + ["", ""])[:3]
        return "Always allow {}", f"{tool} ({server})"
    if key.startswith("shortcut:"): return "Always allow the shortcut “{}”", key[len("shortcut:"):]
    if key == "control_system:sleep": return "Always allow sleep", ""
    return "Always allow this kind", ""

def approval_label(key: str) -> str:
    """Button text for the 'always' choice of an approval key."""
    template, arg = approval_label_parts(key)
    return template.format(arg)

def describe_allowance_parts(key: str):
    """(template, argument) describing one stored allowance (shown in Settings → Privacy)."""
    legacy = {"type_text_keyboard": "Typing into any app", "write_file:new_or_append": "Creating new files / appending, anywhere"}
    if key in legacy: return legacy[key], ""
    template, arg = approval_label_parts(key)
    return {"Always allow in {}": "File changes in {}", "Always allow typing in {}": "Typing into {}",
            "Always allow sleep": "Putting the Mac to sleep", "Always allow {}": "Connected server tool: {}",
            "Always allow the shortcut “{}”": "Running the shortcut “{}”"}.get(template, key), arg

def describe_allowance(key: str) -> str:
    template, arg = describe_allowance_parts(key)
    return template.format(arg)

def is_pre_approved(tool_name: str, args: dict) -> bool:
    """True if the user's stored allowances already cover this exact call."""
    if _taint["on"] or tool_name in PLUGIN_TOOLS: return False
    allowed = list(SETTINGS.get("always_allow", []) or [])
    if not allowed: return False
    a = args or {}
    if tool_name == "type_text_keyboard":
        app = _typing_target()
        return "type_text_keyboard" in allowed or bool(app and f"type:app:{app}" in allowed)
    paths_ = _affected_paths(tool_name, a)
    if paths_:
        dirs = [k[len("files:dir:"):] for k in allowed if k.startswith("files:dir:")]
        if all(any(p_ == d or p_.startswith(d + os.sep) for d in dirs) for p_ in paths_): return True
        if tool_name == "write_file" and "write_file:new_or_append" in allowed:              # older, broader choice
            return a.get("mode") == "a" or not os.path.exists(paths_[0])
        return False
    key = approval_key(tool_name, a)
    return bool(key and key in allowed)

_act_lock = threading.Lock()

def _log_activity(tool_name: str, args: dict, outcome: str, result: str = "", ok: bool = True):
    """Append one line to the activity log (what ran, what was approved, how it ended)."""
    try:
        short = {k: (str(v)[:200] + "…" if len(str(v)) > 200 else v) for k, v in (args or {}).items()}
        line = json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": tool_name, "args": short,
                           "outcome": outcome, "ok": bool(ok), "result": str(result)[:200]}, ensure_ascii=False)
        with _act_lock:
            if os.path.exists(paths.ACTIVITY_FILE) and os.path.getsize(paths.ACTIVITY_FILE) > 1_000_000:
                os.replace(paths.ACTIVITY_FILE, paths.ACTIVITY_FILE + ".1")
            storage.append_line(paths.ACTIVITY_FILE, line)
    except Exception as e: log.info("the activity log could not be written: %s", e)

DETAILS_MARK = "\n\x1e"          # separates "what NOVA wants to do" from the preview of the change (see change_preview)
_PREVIEW_LINES = 60


def _clip(lines: list, limit: int = _PREVIEW_LINES) -> list:
    lines = [l if len(l) <= 160 else l[:157] + "…" for l in lines]
    return lines if len(lines) <= limit else lines[:limit] + [f"… {len(lines) - limit} more lines"]


def change_preview(tool_name: str, args: dict) -> str:
    """What exactly would change on disk, shown in the approval prompt: a diff for an overwrite, the text for a
    new file or an append, and what is affected for delete / move / rename. '' when there is nothing to show."""
    a = args or {}
    try:
        if tool_name == "write_file":
            path = _expand(a.get("path", "")); new = str(a.get("content", ""))
            if a.get("mode") == "a":
                return "\n".join(["Added at the end:"] + _clip(["+ " + l for l in new.splitlines()] or ["+ "]))
            if not os.path.exists(path):
                lines = new.splitlines()
                return "\n".join([f"New file, {len(lines)} lines:"] + _clip(["+ " + l for l in lines]))
            if os.path.getsize(path) > 400_000: return "The file is too large to show the changes."
            with open(path, "rb") as f: raw = f.read()
            if b"\x00" in raw[:4096]: return "This is not a text file - its whole content would be replaced."
            import difflib
            old = raw.decode("utf-8", errors="replace")
            diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "now", "after", n=2, lineterm=""))
            if not diff: return "No changes: the file already has exactly this content."
            added = sum(1 for l in diff[2:] if l.startswith("+")); removed = sum(1 for l in diff[2:] if l.startswith("-"))
            return "\n".join([f"Changes: {added} lines added, {removed} removed"] + _clip(diff[2:]))
        if tool_name == "manage_files":
            action, src = a.get("action"), _expand(a.get("source", ""))
            targets = [src] if os.path.lexists(src) else []
            def what(p):
                if os.path.isdir(p):
                    n = sum(len(fs) for _r, _d, fs in os.walk(p))
                    return f"{p}/   (folder with {n} files)"
                return f"{p}   ({os.path.getsize(p):,} bytes)"
            if action == "delete" and targets:
                return "\n".join(["Goes to the Trash:"] + _clip([what(t) for t in targets], 30))
            if action in ("move", "rename", "copy") and targets:
                dest = _expand(a.get("destination", "") or "")
                final = os.path.join(dest, os.path.basename(targets[0])) if os.path.isdir(dest) else dest
                lines = [f"{what(targets[0])}\n→ {final}"]
                if dest and os.path.exists(final) and os.path.abspath(final) != os.path.abspath(targets[0]):
                    lines.append("⚠️ Something with that name is already there and would be replaced.")
                return "\n".join(lines)
    except Exception as e:
        log.info("no change preview for %s: %s", tool_name, e)
    return ""


def execute_tool(tool_name: str, args: dict) -> str:
    """Validate, ask for approval if needed, run, log. Returns the result text; failures are `ToolFailure`."""
    func = TOOL_FUNCTIONS.get(tool_name)
    if func is None: return fail(f"Unknown tool: {tool_name}")
    args, problem = validate_args(tool_name, args)
    if problem:
        _log_activity(tool_name, args, "invalid", problem, ok=False)
        return fail(f"Error: invalid arguments for {tool_name}: {problem}. Call it again with correct arguments.")
    desc = needs_confirmation(tool_name, args)
    outcome = "auto"
    if desc and is_pre_approved(tool_name, args):
        desc = ""; outcome = "pre-approved"
    if desc:
        approved = False
        if CONFIRM_HOOK:
            preview = change_preview(tool_name, args)
            try: approved = bool(CONFIRM_HOOK(desc + (DETAILS_MARK + preview if preview else ""), approval_key(tool_name, args)))
            except Exception: approved = False
        if not approved:
            _log_activity(tool_name, args, "declined", ok=False)
            return fail("The user declined (or could not be asked about) this action, so it was NOT run.")
        outcome = "approved"
    try:
        result = func(**(args or {}))
        if not isinstance(result, str): result = str(result)
    except TypeError as e: result = fail(f"Bad arguments for {tool_name}: {e}")
    except Exception as e: result = fail(f"Error in {tool_name}: {e}")
    if tool_name in UNTRUSTED_SOURCES or tool_name in MCP_TOOLS:      # whatever a connected server returns is outside text
        _taint["on"] = True; _taint["src"] = tool_name
        if isinstance(result, str): toolbase.note_urls(result)             # its links may be followed
    _log_activity(tool_name, args, outcome + (" (tainted)" if _taint["on"] else ""), result, ok=not isinstance(result, ToolFailure))
    return result


class ToolResult:
    """What one tool call produced, in a form both the model and the UI can rely on."""
    __slots__ = ("name", "args", "ok", "text")
    def __init__(self, name, args, ok, text): self.name, self.args, self.ok, self.text = name, args, ok, text
    def for_model(self) -> str:
        """Compact JSON the model reads: {"ok": true, "result": …} or {"ok": false, "error": …}."""
        return json.dumps({"ok": True, "result": self.text} if self.ok else {"ok": False, "error": self.text}, ensure_ascii=False)


def run_tool(tool_name: str, args: dict) -> ToolResult:
    text = execute_tool(tool_name, args)
    clean, problem = validate_args(tool_name, args)          # report what was really used ("increase" became "up")
    return ToolResult(tool_name, (clean if not problem else args) or {}, not isinstance(text, ToolFailure), str(text))


# ── Plugin loader ─────────────────────────────────────────────────
PENDING_PLUGINS = []                       # (filename, path, sha256) waiting for the user's consent

def _plugin_hash(path: str) -> str:
    import hashlib
    with open(path, "rb") as f: return hashlib.sha256(f.read()).hexdigest()

def _plugin_settings(key: str) -> dict:
    try:
        with open(paths.CONFIG_FILE, encoding="utf-8") as f: return json.load(f).get(key, {}) or {}
    except (OSError, ValueError):
        return {}

def read_manifest(path: str):
    """The plugin's MANIFEST, read WITHOUT running the file.  Returns
         None                        - no manifest: an old-style plugin (runs inside NOVA, full access)
         {"name", "description", "permissions": [...]}   - a sandboxed plugin
       Raises ValueError when a manifest exists but is not valid."""
    import ast
    with open(path, encoding="utf-8") as f: source = f.read()
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"the file has a syntax error (line {e.lineno})")
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "MANIFEST" for t in node.targets):
            try: m = ast.literal_eval(node.value)
            except Exception: raise ValueError("MANIFEST must be a plain dictionary of constants")
            if not isinstance(m, dict): raise ValueError("MANIFEST must be a dictionary")
            perms = m.get("permissions", [])
            if not isinstance(perms, (list, tuple)) or not all(isinstance(x, str) for x in perms):
                raise ValueError('MANIFEST["permissions"] must be a list of strings')
            unknown = [x for x in perms if x not in sandbox.PERMISSIONS]
            if unknown:
                raise ValueError(f"unknown permission(s): {', '.join(unknown)} (allowed: {', '.join(sandbox.PERMISSIONS)})")
            return {"name": str(m.get("name") or os.path.basename(path)[:-3])[:60],
                    "description": str(m.get("description", ""))[:300], "permissions": sorted(set(perms))}
    return None

PLUGIN_INFO = {}                           # tool name -> {"file", "sandboxed", "permissions"}

def _sandboxed_tool(path: str, perms: list, name: str):
    """A function that runs one plugin tool in its own sandboxed process."""
    def call(**kwargs):
        if "network" in perms:
            ledger.record("(plugin) " + os.path.basename(path), "plugin with internet access",
                          ledger.size_of(kwargs), f"tool {name}")
        r = sandbox.run(path, perms, ["call", name], json.dumps(kwargs, ensure_ascii=False, default=str))
        if not r.get("ok"): return fail(f"Plugin error: {r.get('error', 'unknown')}")
        return str(r.get("result", ""))[:8000]
    return call

def load_plugin(path: str) -> list:
    """Load ONE plugin file (the caller has already obtained consent). Returns its tool schemas.
    With a MANIFEST the plugin runs sandboxed in its own process; without one it is imported into NOVA."""
    import importlib.util
    schemas = []
    fname = os.path.basename(path)
    try:
        manifest = read_manifest(path)
        if manifest is not None:
            perms = manifest["permissions"]
            r = sandbox.run(path, perms, ["describe"])
            if not r.get("ok"): raise RuntimeError(r.get("error", "could not read the plugin's tools"))
            tools_ = [dict(t, function=_sandboxed_tool(path, perms, t["name"])) for t in r.get("tools", [])]
        else:
            spec = importlib.util.spec_from_file_location(fname[:-3], path)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            tools_ = getattr(mod, "TOOLS", [])
        for tool in tools_:
            if tool["name"] in TOOL_FUNCTIONS and tool["name"] not in PLUGIN_TOOLS:
                log.warning("plugin %s: tool %r would replace a built-in tool - skipped", fname, tool["name"]); continue
            TOOL_FUNCTIONS[tool["name"]] = tool["function"]
            PLUGIN_TOOLS.add(tool["name"])
            PLUGIN_INFO[tool["name"]] = {"file": fname, "sandboxed": manifest is not None,
                                         "permissions": manifest["permissions"] if manifest else None}
            schemas.append({"type": "function", "function": {
                "name": tool["name"], "description": tool.get("description", ""),
                "parameters": {"type": "object", "properties": tool.get("params", {}),
                               "required": tool.get("required", [])}}})
    except Exception as ex:
        log.warning("Plugin %s failed to load: %s", fname, ex)
    return schemas

def _load_plugins() -> list:
    """Load plugins the user has approved (matched by file hash). Others wait in PENDING_PLUGINS."""
    plugins_dir = paths.PLUGINS_DIR
    os.makedirs(plugins_dir, exist_ok=True)
    allowed, denied = _plugin_settings("plugins_allowed"), _plugin_settings("plugins_denied")
    schemas = []
    for fname in sorted(os.listdir(plugins_dir)):
        if not fname.endswith(".py"): continue
        path = os.path.join(plugins_dir, fname)
        try: h = _plugin_hash(path)
        except OSError: continue
        if allowed.get(fname) == h: schemas += load_plugin(path)
        elif denied.get(fname) != h: PENDING_PLUGINS.append((fname, path, h))
    return schemas




PLUGIN_SCHEMAS = _load_plugins()

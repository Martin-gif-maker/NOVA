"""The tools that act on the Mac (tools_system.py) and open things (tools_apps.py).

Nothing real happens here: AppleScript, subprocesses, the browser, timers and psutil are all stand-ins, so no
volume changes, nothing is opened, and certainly nothing shuts down or gets killed."""
import os, types
import pytest
import tools, tools_apps, tools_system, platform_utils as plat


@pytest.fixture
def mac(monkeypatch):
    """Records what would have been done. `scripts` = AppleScript run, `runs` = programs started, `opened` = web addresses."""
    if not plat.IS_MAC: pytest.skip("checks what NOVA tells macOS to do (the Windows side is in test_windows.py)")
    rec = types.SimpleNamespace(scripts=[], runs=[], opened=[], answer=(0, ""), timers=[])
    monkeypatch.setattr(plat, "run_osascript", lambda script, timeout=10: (rec.scripts.append(script), rec.answer)[1])
    done = types.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(plat.subprocess, "run", lambda cmd, **k: (rec.runs.append(cmd), done)[1])
    monkeypatch.setattr(plat.subprocess, "Popen", lambda cmd, **k: rec.runs.append(cmd))
    monkeypatch.setattr(tools_apps.webbrowser, "open", lambda url: rec.opened.append(url))

    class FakeTimer:                                   # a shutdown countdown that never reaches zero
        def __init__(self, secs, fn): self.secs, self.fn, self.cancelled, self.started = secs, fn, False, False; rec.timers.append(self)
        def start(self): self.started = True
        def cancel(self): self.cancelled = True
        def is_alive(self): return self.started and not self.cancelled
        daemon = False
    monkeypatch.setattr(tools_system.threading, "Timer", FakeTimer)
    monkeypatch.setattr(tools_system, "_pending_power", None)
    return rec


# ── volume ─────────────────────────────────────────────────────────
def test_volume_is_read_set_and_stepped(mac):
    mac.answer = (0, "40")
    assert tools.control_volume("get") == "Volume: 40%"
    assert tools.control_volume("set", 250) == "Volume set to 100% ✓" and mac.scripts[-1] == "set volume output volume 100"
    assert tools.control_volume("up") == "Volume: 50% ✓" and mac.scripts[-1] == "set volume output volume 50"
    assert tools.control_volume("down", 30) == "Volume: 10% ✓"
    assert tools.control_volume("mute") == "Muted ✓" and mac.scripts[-1] == "set volume output muted true"
    assert tools.control_volume("unmute") == "Unmuted ✓"
    assert isinstance(tools.control_volume("explode"), tools.ToolFailure)


def test_volume_on_a_device_without_software_volume(mac):
    mac.answer = (0, "missing value")                  # e.g. an HDMI display
    assert "no software volume" in tools.control_volume("get") and "no software volume" in tools.control_volume("up")
    mac.answer = (1, "error")
    assert isinstance(tools.control_volume("set", 30), tools.ToolFailure) and isinstance(tools.control_volume("mute"), tools.ToolFailure)


# ── power ──────────────────────────────────────────────────────────
def test_shutdown_waits_ten_seconds_and_can_be_cancelled(mac):
    assert tools.control_system("cancel") == "Nothing to cancel."
    out = tools.control_system("shutdown")
    assert out.startswith("Shutting down in 10 s") and len(mac.timers) == 1 and mac.timers[0].secs == 10 and mac.timers[0].started
    assert mac.scripts == []                                                   # nothing was sent to the system yet
    assert tools.control_system("restart").startswith("Restarting in 10 s") and mac.timers[0].cancelled      # replaces the first
    assert tools.control_system("cancel") == "Cancelled ✓" and mac.timers[1].cancelled
    mac.timers[1].fn()                                                         # what the countdown would have run
    assert mac.scripts == ['tell application "System Events" to restart']


def test_sleep_and_lock(mac):
    assert tools.control_system("sleep") == "Sleep mode ✓" and mac.runs[-1] == ["pmset", "sleepnow"]
    assert tools.control_system("lock") == "Locked ✓" and "keystroke \"q\" using {control down, command down}" in mac.scripts[-1]
    mac.answer = (1, "not allowed")                                            # no Accessibility permission
    assert "Display put to sleep" in tools.control_system("lock") and mac.runs[-1] == ["pmset", "displaysleepnow"]
    assert isinstance(tools.control_system("self-destruct"), tools.ToolFailure)


def test_risky_system_tools_ask_first(monkeypatch):
    monkeypatch.setattr(tools, "SETTINGS", {"always_allow": []})
    for name, args in (("control_system", {"action": "shutdown"}), ("empty_recycle_bin", {}), ("kill_process", {"name_or_pid": "Safari"}),
                       ("type_text_keyboard", {"text": "hi"})):
        assert tools.needs_confirmation(name, args), name
    assert tools.needs_confirmation("control_volume", {"action": "up"}) == "" and tools.needs_confirmation("get_battery", {}) == ""


# ── Trash, Spotify, wallpaper, notifications ───────────────────────
def test_trash_spotify_and_wallpaper(mac, tmp_path, monkeypatch):
    assert tools.empty_recycle_bin() == "Trash emptied ✓" and mac.scripts[-1] == 'tell application "Finder" to empty the trash'
    mac.answer = (0, "ok")
    assert tools.control_spotify("next") == "Next track ✓" and 'tell application "Spotify" to next track' in mac.scripts[-1]
    assert 'if application "Spotify" is running' in mac.scripts[-1]            # asking never launches Spotify
    mac.answer = (0, "not running")
    assert tools.control_spotify("play_pause") == "Spotify is not running."
    assert isinstance(tools.control_spotify("rewind"), tools.ToolFailure)
    picture = tmp_path / 'my "best" photo.jpg'; picture.write_bytes(b"jpg")
    mac.answer = (0, "")
    assert tools.set_wallpaper(str(picture)).startswith("Wallpaper set to:") and 'my \\"best\\" photo.jpg' in mac.scripts[-1]
    assert isinstance(tools.set_wallpaper(str(tmp_path / "missing.jpg")), tools.ToolFailure)
    shown = []
    monkeypatch.setattr(plat, "notify", lambda title, message, ms=5000: shown.append((title, message)))
    assert tools.send_notification("Tea", "is ready") == "Notification sent: Tea" and shown == [("Tea", "is ready")]


# ── battery, processes, statistics ─────────────────────────────────
def test_battery_and_statistics_read_like_sentences(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "sensors_battery", lambda: types.SimpleNamespace(percent=81.4, power_plugged=False, secsleft=2 * 3600 + 300))
    assert tools.get_battery() == "Battery: 81% (discharging, ~2h 5m remaining)"
    monkeypatch.setattr(psutil, "sensors_battery", lambda: types.SimpleNamespace(percent=100, power_plugged=True, secsleft=-2))
    assert tools.get_battery() == "Battery: 100% (charging)"
    monkeypatch.setattr(psutil, "sensors_battery", lambda: None)
    assert tools.get_battery() == "No battery (this Mac runs on mains power)."
    stats = tools.get_system_stats()
    assert stats.startswith("CPU: ") and "RAM: " in stats and "Disk: " in stats


def test_processes_are_listed_and_the_system_ones_cannot_be_killed(monkeypatch):
    import psutil
    killed = []
    class P:
        def __init__(self, pid, name, mb): self.info = {"pid": pid, "name": name, "memory_info": types.SimpleNamespace(rss=mb * 1024 * 1024)}
        def kill(self): killed.append(self.info["pid"])
    procs = [P(1, "launchd", 20), P(500, "Safari", 900), P(501, "Finder", 150), P(os.getpid(), "NOVA", 300), P(777, "Notes", 80)]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: list(procs))
    listing = tools.list_processes()
    assert listing.splitlines()[0] == "Safari (PID 500, 900 MB)" and tools.list_processes("note") == "Notes (PID 777, 80 MB)"
    assert tools.kill_process("Notes") == "Killed: Notes (777)" and killed == [777]
    for protected in ("launchd", "Finder", str(os.getpid())):                  # the system, Finder, and NOVA itself
        out = tools.kill_process(protected)
        assert isinstance(out, tools.ToolFailure) and "protected" in out
    assert killed == [777] and isinstance(tools.kill_process("NoSuchApp"), tools.ToolFailure)


# ── screenshot and typing need the Mac's permission ────────────────
def test_screenshot_and_typing_explain_a_missing_permission(monkeypatch):
    monkeypatch.setattr(tools_system, "PYAUTOGUI_AVAILABLE", True)
    monkeypatch.setattr(plat, "screen_capture_allowed", lambda request=False: False)
    assert "Screen Recording permission is missing" in tools.take_screenshot()
    monkeypatch.setattr(plat, "accessibility_trusted", lambda prompt=False: False)
    assert "Accessibility permission is missing" in tools.type_text_keyboard("hello")


def test_typing_pastes_the_text_and_puts_the_clipboard_back(monkeypatch):
    import sys
    events = []
    fake_gui = types.SimpleNamespace(hotkey=lambda *keys: events.append(("keys",) + keys), press=lambda key: events.append(("press", key)),
                                     write=lambda text, interval=0: events.append(("typed", text)))
    monkeypatch.setattr(tools_system, "pyautogui", fake_gui); monkeypatch.setattr(tools_system, "PYAUTOGUI_AVAILABLE", True)
    monkeypatch.setattr(plat, "accessibility_trusted", lambda prompt=False: True)
    monkeypatch.setattr(tools_system.time, "sleep", lambda s: None)
    clipboard = {"text": "what I copied before"}
    monkeypatch.setattr(plat, "get_clipboard_text", lambda: clipboard["text"])
    monkeypatch.setattr(plat, "set_clipboard_text", lambda t: (clipboard.update(text=t), events.append(("clipboard", t)))[1])
    monkeypatch.setitem(sys.modules, "pyperclip", types.SimpleNamespace(copy=lambda t: events.append(("copied", t))))
    monkeypatch.setattr(tools, "PRE_TYPE_HOOK", lambda: events.append(("focus other app",)))
    assert tools.type_text_keyboard("Здравей", press_enter=True) == "Typed 7 characters ✓"
    assert events == [("focus other app",), ("copied", "Здравей"), ("keys", "command", "v"), ("press", "enter"),
                      ("clipboard", "what I copied before")]


# ── opening things ─────────────────────────────────────────────────
def test_web_addresses_maps_and_searches_open_in_the_browser(mac):
    assert tools.open_url("example.com/page") == "Opened https://example.com/page ✓" and mac.opened[-1] == "https://example.com/page"
    assert tools.open_url("http://plain.example") == "Opened http://plain.example ✓"
    assert tools.open_maps("Paris, France") == "Opened Google Maps for 'Paris, France' ✓"
    assert mac.opened[-1] == "https://www.google.com/maps/search/Paris%2C%20France"
    assert tools.search_web("най-добрите филми 2026").startswith("Searching for")
    assert mac.opened[-1].startswith("https://www.google.com/search?q=%D0%BD%D0%B0%D0%B9")


def test_an_app_is_found_by_its_everyday_name(monkeypatch, mac):
    tried = []
    def fake_open(target, is_path=False):
        tried.append((target, is_path)); return target in ("Google Chrome", "/Applications/Affinity Photo 2.app", "System Settings")
    monkeypatch.setattr(plat, "open_app", fake_open)
    monkeypatch.setattr(tools_apps, "_SCANNED_APPS", {"affinity photo 2": "/Applications/Affinity Photo 2.app"})
    assert tools.open_application("Chrome") == "Opened Chrome ✓" and tried == [("Google Chrome", False)]
    assert tools.open_application("control panel") == "Opened control panel ✓"          # old habits: it means System Settings here
    assert tools.open_application("affinity") == "Opened affinity photo 2 ✓" and tried[-1] == ("/Applications/Affinity Photo 2.app", True)
    assert tools.open_application("browser") == "Opened browser ✓" and mac.opened[-1] == "https://www.google.com"
    monkeypatch.setattr(tools_apps.shutil, "which", lambda name: None)
    assert isinstance(tools.open_application("NoSuchApp123"), tools.ToolFailure) and tools.open_application("  ") == "No app name given."


@pytest.mark.skipif(not plat.IS_MAC, reason="indexes .app bundles")
def test_installed_apps_are_indexed_by_name(monkeypatch, tmp_path):
    apps = tmp_path / "Applications"; apps.mkdir()
    for name in ("Pixelmator Pro.app", "Notes.app", "readme.txt"): (apps / name).mkdir()
    monkeypatch.setattr(tools_apps, "HOME", str(tmp_path)); monkeypatch.setattr(tools_apps, "_SCANNED_APPS", {})
    tools_apps._scan_apps()
    assert tools_apps._SCANNED_APPS["pixelmator pro"] == str(apps / "Pixelmator Pro.app") and "readme.txt" not in tools_apps._SCANNED_APPS


@pytest.mark.skipif(not plat.IS_MAC, reason="Finder")
def test_show_in_finder(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(tools_apps.subprocess, "Popen", lambda cmd, **k: started.append(cmd))
    f = tmp_path / "report.pdf"; f.write_bytes(b"x")
    assert tools.open_in_explorer(str(f)) == f"Opened Finder and selected: {f} ✓" and started[-1] == ["open", "-R", str(f)]
    assert tools.open_in_explorer(str(tmp_path)) == f"Opened folder: {tmp_path} ✓" and started[-1] == ["open", str(tmp_path)]
    assert isinstance(tools.open_in_explorer(str(tmp_path / "gone")), tools.ToolFailure)


def test_network_info_goes_through_the_platform_layer(monkeypatch):
    monkeypatch.setattr(plat, "network_info", lambda: "Wi-Fi: Home\nen0: 192.168.1.20")
    assert tools.get_network_info() == "Wi-Fi: Home\nen0: 192.168.1.20"


def test_quitting_an_app_asks_it_to_quit_as_cmd_q_does(monkeypatch):
    import psutil
    asked, killed = [], []
    monkeypatch.setattr(plat, "quit_app", lambda name: (asked.append(name), ["Safari"])[1] if name.lower() == "safari" else [])
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [types.SimpleNamespace(
        info={"pid": 500, "name": "Safari"}, kill=lambda: killed.append(500))])
    out = tools.kill_process("safari")
    assert f"Asked Safari to quit ({plat.QUIT_HOW}" in out and "save" in out and asked == ["safari"] and killed == []
    assert tools.kill_process("Safari", force=True) == "Killed: Safari (500)" and killed == [500]   # "force quit"
    assert tools.kill_process("500") == "Killed: Safari (500)"                                       # a PID: the process
    assert tools.needs_confirmation("kill_process", {"name_or_pid": "Safari"}) == "Quit: Safari"         # what you approve
    assert "unsaved work is lost" in tools.needs_confirmation("kill_process", {"name_or_pid": "Safari", "force": True})


def test_a_windows_program_name_needs_no_exe(monkeypatch):
    import psutil, tools_system
    killed = []
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [types.SimpleNamespace(
        info={"pid": 700, "name": "chrome.exe"}, kill=lambda: killed.append(700))])
    assert tools.kill_process("Chrome", force=True) == "Killed: chrome.exe (700)" and killed == [700]
    assert tools_system._same_program("notepad.exe", "Notepad.EXE") and not tools_system._same_program("notepad", "note")


def test_tests_can_never_quit_a_real_app():
    assert plat.quit_app("Finder") == [] and plat.quit_app("Safari") == [] and plat.quit_app("notepad") == []

# tools_system.py — tools that act on the Mac itself: screenshot, typing, volume, power, Trash, Spotify,
# clipboard, processes, battery, network, notifications, wallpaper.
import os, time, threading, subprocess
import platform_utils as plat
from toolbase import HOME, PYAUTOGUI_AVAILABLE, load_pyautogui, fail, user_path
import logging

log = logging.getLogger("nova")
pyautogui = None                           # loaded on first use (see toolbase.py)


def _gui():
    global pyautogui
    if pyautogui is None: pyautogui = load_pyautogui()
    return pyautogui

# ── TOOL: take_screenshot ─────────────────────────────────────────
def take_screenshot(save_path: str = None) -> str:
    if not PYAUTOGUI_AVAILABLE: return fail("pyautogui not installed.")
    if not plat.screen_capture_allowed(request=True):
        return fail("Screen Recording permission is missing. Allow it in System Settings → "
                    "Privacy & Security → Screen Recording, then restart NOVA.")
    try:
        if not save_path:
            save_path = os.path.join(HOME, "Desktop", f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png")
        save_path = user_path(save_path)
        _gui().screenshot().save(save_path)
        return f"Screenshot saved: {save_path} ✓"
    except Exception as e: return fail(f"Error: {e}")

# ── TOOL: type_text_keyboard ──────────────────────────────────────
def type_text_keyboard(text: str, press_enter: bool = False) -> str:
    if not PYAUTOGUI_AVAILABLE: return fail("pyautogui not installed.")
    if not plat.accessibility_trusted(prompt=True):
        return fail("Accessibility permission is missing, so NOVA cannot type. Allow it in System "
                    "Settings → Privacy & Security → Accessibility, then restart NOVA.")
    old_clip = None
    try:
        import tools
        if tools.PRE_TYPE_HOOK:           # move focus away from NOVA's own window
            tools.PRE_TYPE_HOOK()
        time.sleep(0.6)
        # Paste via the clipboard so non-ASCII (Bulgarian, etc.) works, then restore it.
        try:
            try: old_clip = plat.get_clipboard_text()
            except Exception: old_clip = None
            import pyperclip
            pyperclip.copy(text)
            _gui().hotkey("command", "v")
            time.sleep(0.3)
        except ImportError:
            _gui().write(text, interval=0.04)
        if press_enter: _gui().press("enter")
        return f"Typed {len(text)} characters ✓"
    except Exception as e: return fail(f"Error: {e}")
    finally:
        if old_clip is not None:
            try: plat.set_clipboard_text(old_clip)
            except Exception as e: log.info("the clipboard could not be restored after typing: %s", e)

# ── TOOL: control_volume ──────────────────────────────────────────
def control_volume(action: str, level: int = None) -> str:
    """Actions: mute, unmute, up, down, set (0-100), get"""
    def current():
        rc, out = plat.run_osascript("output volume of (get volume settings)")
        return int(out) if rc == 0 and out.strip().isdigit() else None
    def setv(n):
        n = max(0, min(100, int(n)))
        rc, _ = plat.run_osascript(f"set volume output volume {n}")
        return n if rc == 0 else None
    a = action.lower()
    if a == "get":
        v = current()
        return f"Volume: {v}%" if v is not None else "This output device has no software volume."
    if a == "set" and level is not None:
        n = setv(level); return f"Volume set to {n}% ✓" if n is not None else fail("Cannot control volume.")
    if a in ("up", "down"):
        v = current()
        if v is None: return "This output device has no software volume."
        step = level or 10
        n = setv(v + step if a == "up" else v - step)
        return f"Volume: {n}% ✓" if n is not None else fail("Cannot control volume.")
    if a in ("mute", "unmute"):
        rc, _ = plat.run_osascript(f"set volume output muted {'true' if a == 'mute' else 'false'}")
        return ("Muted ✓" if a == "mute" else "Unmuted ✓") if rc == 0 else fail("Cannot control volume.")
    return fail(f"Unknown action: {action}")

# ── TOOL: control_system ─────────────────────────────────────────
_pending_power = None   # delayed shutdown / restart timer (so "cancel" works)

def control_system(action: str) -> str:
    """Actions: shutdown, restart, sleep, lock, hibernate, cancel"""
    global _pending_power
    a = action.lower()
    if a in ("shutdown", "restart"):
        verb = "shut down" if a == "shutdown" else "restart"
        if _pending_power: _pending_power.cancel()
        _pending_power = threading.Timer(
            10, lambda: plat.run_osascript(f'tell application "System Events" to {verb}'))
        _pending_power.daemon = True
        _pending_power.start()
        return f"{'Shutting down' if a == 'shutdown' else 'Restarting'} in 10 s ✓ (say 'cancel' to abort)"
    if a == "cancel":
        if _pending_power and _pending_power.is_alive():
            _pending_power.cancel(); return "Cancelled ✓"
        return "Nothing to cancel."
    if a in ("sleep", "hibernate"):
        subprocess.run(["pmset", "sleepnow"]); return "Sleep mode ✓"
    if a == "lock":
        # Ctrl+Cmd+Q is the real "Lock Screen" shortcut (needs Accessibility permission);
        # fall back to sleeping the display, which locks if a password is required on wake.
        rc, _ = plat.run_osascript(
            'tell application "System Events" to keystroke "q" using {control down, command down}')
        if rc != 0:
            subprocess.run(["pmset", "displaysleepnow"])
            return ("Display put to sleep (the Lock Screen shortcut needs Accessibility permission; "
                    "the Mac only locks if a password is required after sleep).")
        return "Locked ✓"
    return fail(f"Unknown action: {action}")

# ── TOOL: empty_recycle_bin ───────────────────────────────────────
def empty_recycle_bin() -> str:
    """Empty the Trash (the tool keeps its original name)."""
    rc, out = plat.run_osascript('tell application "Finder" to empty the trash', timeout=60)
    return "Trash emptied ✓" if rc == 0 else fail(f"Error: {out}")

# ── TOOL: get_system_stats ────────────────────────────────────────
def get_system_stats() -> str:
    try:
        import psutil
        cpu  = psutil.cpu_percent(interval=0.5)
        ram  = psutil.virtual_memory()
        disk = psutil.disk_usage("/System/Volumes/Data" if os.path.exists("/System/Volumes/Data") else "/")
        return (
            f"CPU: {cpu}%\n"
            f"RAM: {ram.used/1024**3:.1f}GB / {ram.total/1024**3:.1f}GB ({ram.percent}%)\n"
            f"Disk: {disk.used/1024**3:.1f}GB / {disk.total/1024**3:.1f}GB ({disk.percent}%)"
        )
    except ImportError: return fail("Install psutil: pip install psutil --break-system-packages")
    except Exception as e: return fail(f"Error: {e}")

# ── TOOL: control_spotify ─────────────────────────────────────────
def control_spotify(action: str) -> str:
    """Actions: play_pause, next, prev"""
    cmds = {"play_pause": "playpause", "next": "next track", "prev": "previous track"}
    c = cmds.get(action.lower())
    if not c: return fail(f"Unknown action: {action}")
    rc, out = plat.run_osascript(
        'if application "Spotify" is running then\n'
        f'tell application "Spotify" to {c}\n'
        'return "ok"\nend if\nreturn "not running"')
    if rc != 0: return fail(f"Error: {out}")
    if out == "not running": return "Spotify is not running."
    labels = {"play_pause": "Play/Pause", "next": "Next track", "prev": "Previous track"}
    return f"{labels.get(action.lower(), action)} ✓"


def get_clipboard() -> str:
    """Read current clipboard text."""
    try: return plat.get_clipboard_text() or "(clipboard is empty)"
    except Exception as e: return fail(f"Error: {e}")


def set_clipboard(text: str) -> str:
    """Write text to clipboard."""
    try: plat.set_clipboard_text(text); return f"Copied to clipboard: {text[:80]} ✓"
    except Exception as e: return fail(f"Error: {e}")


def list_processes(filter_name: str = "") -> str:
    """List running processes, optionally filtered by name."""
    try:
        import psutil as _ps
        rows = []
        for p in sorted(_ps.process_iter(["pid","name","memory_info"]),
                        key=lambda x: x.info["memory_info"].rss if x.info["memory_info"] else 0,
                        reverse=True):
            name = p.info["name"] or ""
            if filter_name and filter_name.lower() not in name.lower():
                continue
            mem = (p.info["memory_info"].rss // 1024 // 1024) if p.info["memory_info"] else 0
            rows.append(f"{name} (PID {p.info['pid']}, {mem} MB)")
        return "\n".join(rows[:30]) if rows else "No processes found."
    except Exception as e:
        return fail(f"Error: {e}")

_NEVER_KILL = {"launchd", "kernel_task", "windowserver", "loginwindow", "systemd", "init", "system",
               "finder", "dock", "systemuiserver"}

def kill_process(name_or_pid: str) -> str:
    """Kill a process by name or PID."""
    try:
        import psutil as _ps
        target = str(name_or_pid).strip()
        mine = {os.getpid(), os.getppid()}
        killed, failed = [], []
        for p in _ps.process_iter(["pid","name"]):
            nm = p.info["name"] or ""
            if str(p.info["pid"]) == target or nm.lower() == target.lower():
                if p.info["pid"] in mine or nm.lower() in _NEVER_KILL:
                    failed.append(f"{nm} (protected)"); continue
                try:
                    p.kill(); killed.append(f"{nm} ({p.info['pid']})")
                except Exception as e:
                    failed.append(f"{nm} ({p.info['pid']}): {type(e).__name__}")
        msg = f"Killed: {', '.join(killed)}" if killed else f"No process killed for: {target}"
        if failed: msg += f"\nCould not kill: {', '.join(failed)}"
        return msg if killed else fail(msg)
    except Exception as e:
        return fail(f"Error: {e}")

def get_battery() -> str:
    """Get battery level and charging status."""
    try:
        import psutil as _ps
        b = _ps.sensors_battery()
        if not b: return "No battery (this Mac runs on mains power)."
        status = "charging" if b.power_plugged else "discharging"
        time_str = ""
        if b.secsleft and b.secsleft > 0:
            h, m = divmod(b.secsleft // 60, 60)
            time_str = f", ~{h}h {m}m remaining"
        return f"Battery: {b.percent:.0f}% ({status}{time_str})"
    except Exception as e:
        return fail(f"Error: {e}")

def get_network_info() -> str:
    """Get WiFi/network connection info."""
    return plat.network_info()


def send_notification(title: str, message: str) -> str:
    """Show a notification in Notification Center."""
    try:
        plat.notify(title, message)
        return f"Notification sent: {title}"
    except Exception as e:
        return fail(f"Error: {e}")

def set_wallpaper(path: str) -> str:
    """Set the desktop picture (on every desktop)."""
    try:
        path = user_path(path)
        if not os.path.exists(path):
            return fail(f"File not found: {path}")
        p = plat.as_quote(os.path.abspath(path))
        rc, out = plat.run_osascript(
            f'tell application "System Events" to tell every desktop to set picture to POSIX file "{p}"')
        return f"Wallpaper set to: {path}" if rc == 0 else fail(f"Error: {out}")
    except Exception as e:
        return fail(f"Error: {e}")

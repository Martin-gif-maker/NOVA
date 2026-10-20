# plat_mac.py — everything NOVA asks of macOS itself: notifications, sound, the clipboard, launch at
# login, global hotkeys, selected text, permissions, app activation, network and Spotify information, and
# what the tools need from the system (volume, power, Trash, wallpaper, opening apps, the shell).
# Reached as `platform_utils`; plat_windows.py offers the same names for Windows.
import os, sys, time, socket, subprocess, plistlib, shutil, json, threading
import logging

log = logging.getLogger("nova")

IS_MAC = sys.platform == "darwin"          # the tests also import this module on other systems
IS_WINDOWS = False
OS_NAME = "macOS"
NATIVE_VOICE_EXT = ".aiff"                 # what synth_native writes
QUIET_PROCESS = {}                         # extra subprocess arguments so a helper program opens no window (Windows needs some)

# ── Labels shown in the UI ────────────────────────────────────────
KEYSTORE_NAME = "macOS Keychain"
LOGIN_LABEL   = "Launch at login"
MOD_NAME      = "⌘"                        # Qt maps its "Ctrl" to ⌘ on macOS by itself

# Global "show/hide NOVA" hotkey: ⌘⇧Space (Ctrl+Space and Ctrl+Opt+Space belong to input-source switching).
HOTKEY_LABEL = "⌘⇧Space"
_MAC_HOTKEY_KEYCODE = 49                   # 49 = Space
_MAC_HOTKEY_MODS    = ("cmd", "shift")     # any of: cmd, shift, ctrl, opt

# Qt point sizes come out about a quarter smaller on macOS than the sizes the interface was designed with.
# Tweak this single number to scale all text.
_FONT_SCALE = 1.33
UI_FONT = "Helvetica Neue"


def shortcut_label(key: str) -> str:
    """'N' -> '⌘N'"""
    return f"⌘{key}"


def ui_font(size, weight=None):
    """The interface font at a design size (scaled for macOS, see _FONT_SCALE)."""
    from PySide6.QtGui import QFont
    px = max(1, int(round(size * _FONT_SCALE)))
    return QFont(UI_FONT, px) if weight is None else QFont(UI_FONT, px, weight)


# ──────────────────────────────────────────────────────────────────
#  AppleScript helpers
# ──────────────────────────────────────────────────────────────────
def as_quote(s: str) -> str:
    """Escape a string for use inside an AppleScript "..." literal."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")


def run_osascript(script: str, timeout: int = 10):
    """Run AppleScript. Returns (returncode, output_or_error)."""
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=timeout)
        out = r.stdout if r.returncode == 0 else (r.stderr or r.stdout)
        return r.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 1, "timed out"
    except Exception as e:
        return 1, str(e)


# ──────────────────────────────────────────────────────────────────
#  Notifications
# ──────────────────────────────────────────────────────────────────
def notify(title: str, message: str, ms: int = 5000) -> None:
    """Show a desktop notification (non-blocking)."""
    title = str(title)[:100]
    message = str(message)
    try:
        if IS_MAC:
            tn = shutil.which("terminal-notifier")
            if tn:
                subprocess.Popen([tn, "-title", title, "-message", message],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                script = f'display notification "{as_quote(message)}" with title "{as_quote(title)}"'
                subprocess.Popen(["osascript", "-e", script],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["notify-send", title, message],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e: log.info("a notification could not be shown: %s", e)


# ──────────────────────────────────────────────────────────────────
#  Audio  (TTS playback)
# ──────────────────────────────────────────────────────────────────
_audio_proc = None     # the afplay / say process that is speaking right now


def stop_audio() -> None:
    """Stop whatever TTS audio is currently playing (also the `say` fallback)."""
    p = _audio_proc
    if p is not None and p.poll() is None:
        try: p.terminate()
        except Exception as e: log.debug("stopping the sound: %s", e)


def play_audio_file(path: str) -> None:
    """Play an mp3 file and block until it finishes (call from a worker thread)."""
    global _audio_proc
    import shutil
    if IS_MAC:
        cmd = ["afplay", path]                     # ships with macOS, plays mp3
    else:
        player = (shutil.which("mpg123") and ["mpg123", "-q", path]) or \
                 (shutil.which("ffplay") and ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path])
        if not player:
            raise RuntimeError("no audio player found")
        cmd = player
    _audio_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _audio_proc.wait()


def synth_native(text: str, path: str) -> bool:
    """Write the Mac's own voice to an audio file instead of speaking it (so NOVA knows exactly what it plays)."""
    if not IS_MAC: return False
    try:
        r = subprocess.run(["/usr/bin/say", "-o", path], input=text.encode("utf-8"), capture_output=True, timeout=60)
        return r.returncode == 0 and os.path.getsize(path) > 4096
    except (OSError, subprocess.SubprocessError):
        return False


def speak_native(text: str) -> None:
    """Offline fallback voice (used when edge-tts is unavailable)."""
    global _audio_proc
    try:
        if IS_MAC:
            # text goes via stdin so a leading "-" can't be parsed as an option
            _audio_proc = subprocess.Popen(["say"], stdin=subprocess.PIPE)
            _audio_proc.communicate(text.encode("utf-8"))
        else:
            subprocess.Popen(["spd-say", text])
    except Exception as e: log.info("the Mac's voice could not speak: %s", e)


# ──────────────────────────────────────────────────────────────────
#  Clipboard
# ──────────────────────────────────────────────────────────────────
def _utf8_env():
    env = dict(os.environ)
    env["LANG"] = "en_US.UTF-8"      # pbcopy/pbpaste fall back to MacRoman without this
    return env


def get_clipboard_text() -> str:
    if IS_MAC:
        r = subprocess.run(["pbpaste"], capture_output=True, timeout=5, env=_utf8_env())
        return r.stdout.decode("utf-8", "replace").strip()
    import pyperclip
    return (pyperclip.paste() or "").strip()


def set_clipboard_text(text: str) -> None:
    if IS_MAC:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), timeout=5, env=_utf8_env())
        return
    import pyperclip
    pyperclip.copy(text)


# ──────────────────────────────────────────────────────────────────
#  Launch at login
# ──────────────────────────────────────────────────────────────────
# GUI-launched apps get a minimal PATH; add the usual Homebrew locations.
_GUI_PATH = ":".join(["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin",
                      "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
_LAUNCH_AGENT = os.path.expanduser("~/Library/LaunchAgents/com.nova.assistant.plist")


def autostart_enabled() -> bool:
    """True if NOVA is currently registered to start at login."""
    try:
        if IS_MAC:
            return os.path.exists(_LAUNCH_AGENT)
    except Exception as e: log.debug("launch-at-login state unknown: %s", e)
    return False


def autostart_hidden() -> bool:
    """True if the login start is set up to stay in the menu bar (macOS)."""
    try:
        with open(_LAUNCH_AGENT, "rb") as f:
            return "--hidden" in (plistlib.load(f).get("ProgramArguments") or [])
    except Exception:
        return False


def set_autostart(enabled: bool, script: str, hidden: bool = True) -> bool:
    """Register / unregister NOVA to start at login. `hidden` = start in the menu bar without opening the window.
    Returns True on success."""
    try:
        if IS_MAC:
            # A LaunchAgent is picked up at the next login (we deliberately don't
            # `launchctl load` it now — that would start a second NOVA).
            if enabled:
                os.makedirs(os.path.dirname(_LAUNCH_AGENT), exist_ok=True)
                with open(_LAUNCH_AGENT, "wb") as f:
                    args = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, script]
                    if hidden: args.append("--hidden")
                    plistlib.dump({
                        "Label": "com.nova.assistant",
                        "ProgramArguments": args,
                        "WorkingDirectory": os.path.expanduser("~") if getattr(sys, "frozen", False) else os.path.dirname(script),
                        "RunAtLoad": True,
                        "ProcessType": "Interactive",
                        "EnvironmentVariables": {"PATH": _GUI_PATH},
                    }, f)
            elif os.path.exists(_LAUNCH_AGENT):
                os.remove(_LAUNCH_AGENT)
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────
#  Global hotkey
# ──────────────────────────────────────────────────────────────────
_hotkey_refs = []      # keep event monitors alive
_hotkeys = []          # [(keycode, ("cmd", "shift"), callback)] - every global shortcut NOVA listens for
_tap_started = False

SELECTION_HOTKEY_LABEL   = "⌃⇧Space"            # act on the text selected in any app
_SELECTION_HOTKEY_KEY    = 49                   # Space
_SELECTION_HOTKEY_MODS   = ("ctrl", "shift")


def _start_mac_event_tap() -> bool:
    """Install a session-wide key-down tap that consumes NOVA's hotkeys. False if macOS refuses
    (needs Accessibility permission)."""
    try:
        import Quartz
        flag = {"cmd": Quartz.kCGEventFlagMaskCommand, "shift": Quartz.kCGEventFlagMaskShift,
                "ctrl": Quartz.kCGEventFlagMaskControl, "opt": Quartz.kCGEventFlagMaskAlternate}
        all_mods = sum(flag.values())
        holder = {}

        def _cb(_proxy, etype, event, _refcon):
            if etype in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                Quartz.CGEventTapEnable(holder["tap"], True)          # macOS switches slow taps off
                return event
            if etype == Quartz.kCGEventKeyDown:
                code = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
                mods = Quartz.CGEventGetFlags(event) & all_mods
                for keycode, names, callback in list(_hotkeys):
                    if code == keycode and mods == sum(flag[m] for m in names):
                        try: callback()            # emits a Qt signal - safe from this thread
                        except Exception as e: log.warning("a global hotkey's action failed: %s", e)
                        return None                # swallow: other apps never see the keystroke
            return event

        tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                      Quartz.kCGEventTapOptionDefault, 1 << Quartz.kCGEventKeyDown, _cb, None)
        if tap is None:
            return False
        holder["tap"] = tap
        src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)

        def _run():
            Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), src, Quartz.kCFRunLoopCommonModes)
            Quartz.CGEventTapEnable(tap, True)
            Quartz.CFRunLoopRun()
        threading.Thread(target=_run, daemon=True, name="hotkey-tap").start()
        _hotkey_refs.append((tap, src, _cb))
        return True
    except Exception:
        return False


def _start_mac_monitors() -> bool:
    """Fallback without Accessibility permission: NSEvent monitors can only *observe* keys in other apps.
    They run on the main thread through Qt's own Cocoa run loop, so no extra thread is needed."""
    try:
        from AppKit import (NSEvent, NSEventMaskKeyDown,
                            NSEventModifierFlagCommand, NSEventModifierFlagShift,
                            NSEventModifierFlagControl, NSEventModifierFlagOption,
                            NSEventModifierFlagDeviceIndependentFlagsMask)
        flag = {"cmd": NSEventModifierFlagCommand, "shift": NSEventModifierFlagShift,
                "ctrl": NSEventModifierFlagControl, "opt": NSEventModifierFlagOption}
        mask_all = (NSEventModifierFlagCommand | NSEventModifierFlagShift |
                    NSEventModifierFlagControl | NSEventModifierFlagOption)

        def _match(ev):
            mods = ev.modifierFlags() & NSEventModifierFlagDeviceIndependentFlagsMask & mask_all
            for keycode, names, callback in list(_hotkeys):
                if ev.keyCode() == keycode and mods == sum(flag[m] for m in names):
                    return callback
            return None

        def _global(ev):                      # NOVA is in the background
            cb = _match(ev)
            if cb: cb()

        def _local(ev):                       # NOVA is focused
            cb = _match(ev)
            if cb:
                cb()
                return None                   # swallow
            return ev

        _hotkey_refs.append(NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, _global))
        _hotkey_refs.append(NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, _local))
        return True
    except Exception:
        return False


def add_global_hotkey(keycode: int, mods, callback) -> None:
    """Register one more global shortcut. Takes effect at once if the listener is already running."""
    _hotkeys.append((int(keycode), tuple(mods), callback))


def remove_global_hotkey(callback) -> None:
    _hotkeys[:] = [h for h in _hotkeys if h[2] is not callback]


def start_global_hotkey(callback) -> bool:
    """Call `callback()` when the global show/hide hotkey is pressed."""
    global _tap_started
    if IS_MAC:
        add_global_hotkey(_MAC_HOTKEY_KEYCODE, _MAC_HOTKEY_MODS, callback)
        if _tap_started: return True
        # Preferred: a Quartz event tap *swallows* the hotkey so the app in front never sees it.
        # Without Accessibility permission, fall back to monitors that can only observe it.
        _tap_started = _start_mac_event_tap() or _start_mac_monitors()
        return _tap_started
    return False


# ──────────────────────────────────────────────────────────────────
#  The text selected in another app
# ──────────────────────────────────────────────────────────────────
def nova_is_frontmost() -> bool:
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app is not None and int(app.processIdentifier()) == os.getpid()
    except Exception:
        return False


def _ax_selected_text() -> str:
    """Ask the focused control for its selection (works in most native apps and Safari)."""
    try:
        from ApplicationServices import (AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue,
                                         kAXFocusedUIElementAttribute, kAXSelectedTextAttribute)
        err, focused = AXUIElementCopyAttributeValue(AXUIElementCreateSystemWide(), kAXFocusedUIElementAttribute, None)
        if err or focused is None: return ""
        err, value = AXUIElementCopyAttributeValue(focused, kAXSelectedTextAttribute, None)
        return str(value) if not err and value else ""
    except Exception:
        return ""


def _press_cmd(keycode: int) -> None:
    """Press ⌘ + one key for the user (a real keystroke in whatever app is in front)."""
    import Quartz
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
        Quartz.CGEventSetFlags(ev, Quartz.kCGEventFlagMaskCommand)            # ⌘ only, whatever is physically held
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def press_paste() -> bool:
    """Press ⌘V in the app in front. Needs Accessibility permission; False if it could not be done."""
    if not IS_MAC or not accessibility_trusted() or nova_is_frontmost(): return False
    try:
        _press_cmd(9); return True                                            # 9 = the V key
    except Exception:
        return False


def frontmost_pid() -> int:
    """Process id of the app in front (0 if unknown)."""
    if not IS_MAC: return 0
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app is not None else 0
    except Exception:
        return 0


def quit_app(name: str) -> list:
    """Ask the apps called `name` to quit the way ⌘Q does - they may ask to save first. Returns the names of the apps
    asked ([] when no app with a Dock icon has that name)."""
    try:
        from AppKit import NSWorkspace
    except ImportError:
        return []
    want = name.strip().lower().removesuffix(".app")
    mine = {os.getpid(), os.getppid()}
    return [a.localizedName() for a in NSWorkspace.sharedWorkspace().runningApplications()
            if (a.localizedName() or "").lower() == want and a.activationPolicy() == 0          # 0: a regular app
            and a.processIdentifier() not in mine and a.terminate()]


def activate_pid(pid: int) -> bool:
    """Bring another running app back to the front."""
    if not IS_MAC or not pid or pid == os.getpid(): return False
    try:
        from AppKit import NSRunningApplication
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None or app.isTerminated(): return False
        return bool(app.activateWithOptions_(1 << 1))                         # NSApplicationActivateIgnoringOtherApps
    except Exception:
        return False


def _copy_selection(wait: float = 0.5) -> str:
    """Fallback for apps that do not answer the question above (Chrome, Electron apps): press ⌘C for the user,
    read the clipboard, then put back exactly what was on it before."""
    try:
        from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
        pb = NSPasteboard.generalPasteboard()
        saved = []
        for item in pb.pasteboardItems() or []:
            saved.append([(t, item.dataForType_(t)) for t in item.types() or []])
        before = pb.changeCount()
        _press_cmd(8)                                                         # 8 = the C key
        end = time.time() + wait
        while pb.changeCount() == before and time.time() < end:
            time.sleep(0.02)
        text = str(pb.stringForType_(NSPasteboardTypeString) or "") if pb.changeCount() != before else ""
        if pb.changeCount() != before:                                        # restore the user's clipboard
            pb.clearContents()
            items = []
            for pairs in saved:
                it = NSPasteboardItem.alloc().init()
                for t, data in pairs:
                    if data is not None: it.setData_forType_(data, t)
                items.append(it)
            if items: pb.writeObjects_(items)
        return text
    except Exception:
        return ""


def selected_text(copy_fallback: bool = True) -> str:
    """The text selected in the app in front ('' if none). Needs Accessibility permission."""
    if not IS_MAC or nova_is_frontmost(): return ""
    text = _ax_selected_text()
    if not text.strip() and copy_fallback and accessibility_trusted():
        text = _copy_selection()
    return text.strip()



# ──────────────────────────────────────────────────────────────────
#  macOS permissions + app activation
# ──────────────────────────────────────────────────────────────────
def _cdll(name):
    import ctypes
    return ctypes.CDLL(f"/System/Library/Frameworks/{name}.framework/{name}")


def accessibility_trusted(prompt: bool = False) -> bool:
    """macOS: may this process send/observe keystrokes? (always True elsewhere)"""
    if not IS_MAC:
        return True
    try:
        if prompt:
            from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
            return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
    except Exception as e: log.debug("could not ask for Accessibility permission: %s", e)
    try:
        return bool(_cdll("ApplicationServices").AXIsProcessTrusted())
    except Exception:
        return True      # can't tell - don't block the feature


def screen_capture_allowed(request: bool = False) -> bool:
    """macOS: does this process have Screen Recording permission?"""
    if not IS_MAC:
        return True
    try:
        cg = _cdll("CoreGraphics")
        ok = bool(cg.CGPreflightScreenCaptureAccess())
        if not ok and request:
            cg.CGRequestScreenCaptureAccess()
        return ok
    except Exception:
        return True


def microphone_status():
    """'granted' | 'denied' | 'undetermined' | 'restricted' on macOS, else None (unknown)."""
    if not IS_MAC:
        return None
    try:
        import AVFoundation as av
        st = av.AVCaptureDevice.authorizationStatusForMediaType_(av.AVMediaTypeAudio)
        return {0: "undetermined", 1: "restricted", 2: "denied", 3: "granted"}.get(int(st))
    except Exception:
        return None


def request_microphone() -> None:
    """Show the system microphone prompt (no-op if already decided)."""
    if not IS_MAC:
        return
    try:
        import AVFoundation as av
        av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(av.AVMediaTypeAudio, lambda ok: None)
    except Exception as e: log.info("could not ask for microphone permission: %s", e)


def frontmost_other_app():
    """Name of the app in front, or '' if that is NOVA itself / unknown. (macOS)"""
    if not IS_MAC:
        return ""
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None or int(app.processIdentifier()) == os.getpid():
            return ""
        return str(app.localizedName() or "")
    except Exception:
        return ""


def brand_process(name: str) -> None:
    """macOS: a script run by `python main.py` is called "Python" in the menu bar and Dock. Rename it."""
    if not IS_MAC or getattr(sys, "frozen", False):
        return
    try:
        from Foundation import NSBundle
        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info is not None:
            info["CFBundleName"] = name; info["CFBundleDisplayName"] = name
    except Exception as e: log.debug("could not set the process name: %s", e)


def activate_app() -> None:
    """Bring this app to the front (macOS needs an explicit request)."""
    if not IS_MAC:
        return
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception as e: log.debug("could not bring NOVA to the front: %s", e)


def enable_window_shadow(win_id: int) -> None:
    """macOS: give a frameless translucent window a real drop shadow (it has none by default)."""
    if not IS_MAC or not win_id:
        return
    try:
        import ctypes, objc
        view = objc.objc_object(c_void_p=ctypes.c_void_p(win_id))
        win = view.window()
        if win is not None:
            win.setHasShadow_(True); win.invalidateShadow()
    except Exception as e: log.debug("window shadow not set: %s", e)


def hide_app() -> None:
    """Hide this app so focus returns to the previously active app (macOS)."""
    if not IS_MAC:
        return
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().hide_(None)
    except Exception as e: log.debug("could not hide NOVA: %s", e)

# ──────────────────────────────────────────────────────────────────
#  Spotify "now playing"
# ──────────────────────────────────────────────────────────────────
_SPOTIFY_MAC = '''
if application "Spotify" is running then
    tell application "Spotify"
        if player state is playing then
            return (artist of current track) & " - " & (name of current track)
        end if
    end tell
end if
return ""
'''


def spotify_now_playing() -> str:
    """Return 'Artist - Title' of the current Spotify track, or ''."""
    if IS_MAC:
        rc, out = run_osascript(_SPOTIFY_MAC, timeout=4)   # `is running` never launches Spotify
        return out if rc == 0 else ""
    return ""


# ──────────────────────────────────────────────────────────────────
#  Network info
# ──────────────────────────────────────────────────────────────────
def _mac_wifi_name() -> str:
    try:
        hp = subprocess.run(["networksetup", "-listallhardwareports"],
                            capture_output=True, text=True, timeout=5).stdout
        dev, seen_wifi = None, False
        for line in hp.splitlines():
            if line.startswith("Hardware Port:"):
                seen_wifi = "wi-fi" in line.lower() or "airport" in line.lower()
            elif seen_wifi and line.startswith("Device:"):
                dev = line.split(":", 1)[1].strip(); break
        if not dev:
            return ""
        out = subprocess.run(["networksetup", "-getairportnetwork", dev],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        if out.startswith("Current Wi-Fi Network:"):
            return out.split(":", 1)[1].strip()
        # Recent macOS versions no longer answer networksetup; ask system_profiler instead.
        raw = subprocess.run(["system_profiler", "SPAirPortDataType", "-json"],
                             capture_output=True, text=True, timeout=15).stdout
        data = json.loads(raw)
        for entry in data.get("SPAirPortDataType", []):
            for iface in entry.get("spairport_airport_interfaces", []):
                cur = iface.get("spairport_current_network_information") or {}
                name = cur.get("_name", "")
                if name and "redacted" not in name.lower():
                    return name
        return ""
    except Exception:
        return ""


def network_info() -> str:
    lines = []
    if IS_MAC:
        ssid = _mac_wifi_name()
        if ssid: lines.append(f"Wi-Fi: {ssid}")
    try:
        import psutil
        stats = psutil.net_if_stats()
        skip = ("lo", "utun", "awdl", "llw", "bridge", "gif", "stf", "anpi", "ap1", "docker", "veth")
        for name, addrs in psutil.net_if_addrs().items():
            st = stats.get(name)
            if not st or not st.isup or name.startswith(skip):
                continue
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    lines.append(f"{name}: {a.address}")
    except Exception as e:
        lines.append(f"(interface list unavailable: {e})")
    return "\n".join(lines) or "No network info available."


# ──────────────────────────────────────────────────────────────────
#  What the tools ask of the system (see tools_system.py, tools_files.py, tools_apps.py)
# ──────────────────────────────────────────────────────────────────
FILE_MANAGER = "Finder"
TRASH_NAME   = "Trash"
SHELL_HINT   = "Use macOS commands (open, osascript, pbcopy). Write the home folder as ~ (~/Downloads)."
SHELL_PREFIX = ""                          # put in front of every shell command (Windows needs one for UTF-8 output)
PYTHON_FLAGS = ()                          # extra interpreter options for "run this Python code" (Windows: UTF-8 output)
QUIT_HOW     = "as with ⌘Q"              # how "quit Safari" closes an app (kill_process without force)
TOOL_GROUPS_HINT   = "files, system, clipboard, music, calendar, mail"       # for the AI: what more_tools can switch on
UNAVAILABLE_GROUPS: tuple[str, ...] = ()  # groups of tools (schemas.GROUPS) that cannot work on this system
NEVER_KILL   = {"launchd", "kernel_task", "windowserver", "loginwindow", "systemd", "init", "system",
                "finder", "dock", "systemuiserver"}
SEARCH_SKIP_DIRS   = {"Library", "Applications", "Movies", "Music", "Pictures", ".Trash"}
SEARCH_SKIP_SUFFIX = (".app", ".photoslibrary", ".musiclibrary", ".tvlibrary", ".framework", ".bundle")
NO_SCREEN_PERMISSION = ("Screen Recording permission is missing. Allow it in System Settings → "
                        "Privacy & Security → Screen Recording, then restart NOVA.")
NO_TYPING_PERMISSION = ("Accessibility permission is missing, so NOVA cannot type. Allow it in System "
                        "Settings → Privacy & Security → Accessibility, then restart NOVA.")
NO_PYTHON = ("Python is not installed on this Mac. Install it from python.org or with "
             "`brew install python`, or run `xcode-select --install`, then try again.")
NO_BATTERY = "No battery (this Mac runs on mains power)."
PASTE_KEYS = ("command", "v")              # for pyautogui


def volume_get():
    """Output volume 0-100, or None if this output device has no software volume."""
    rc, out = run_osascript("output volume of (get volume settings)")
    return int(out) if rc == 0 and out.strip().isdigit() else None


def volume_set(n):
    """Set the output volume; returns the value set, or None if it could not be done."""
    n = max(0, min(100, int(n)))
    rc, _ = run_osascript(f"set volume output volume {n}")
    return n if rc == 0 else None


def volume_mute(muted: bool) -> bool:
    rc, _ = run_osascript(f"set volume output muted {'true' if muted else 'false'}")
    return rc == 0


def power_off(restart: bool = False) -> None:
    """Shut down or restart now (the 10-second countdown is the caller's)."""
    run_osascript(f'tell application "System Events" to {"restart" if restart else "shut down"}')


def sleep_now(hibernate: bool = False) -> None:
    subprocess.run(["pmset", "sleepnow"])          # a Mac has one kind of sleep


def lock_screen() -> str:
    """Lock the screen; returns what to tell the user."""
    # Ctrl+Cmd+Q is the real "Lock Screen" shortcut (needs Accessibility permission);
    # fall back to sleeping the display, which locks if a password is required on wake.
    rc, _ = run_osascript(
        'tell application "System Events" to keystroke "q" using {control down, command down}')
    if rc != 0:
        subprocess.run(["pmset", "displaysleepnow"])
        return ("Display put to sleep (the Lock Screen shortcut needs Accessibility permission; "
                "the Mac only locks if a password is required after sleep).")
    return "Locked ✓"


def empty_trash():
    """Empty the Trash for good. Returns (ok, error text)."""
    rc, out = run_osascript('tell application "Finder" to empty the trash', timeout=60)
    return rc == 0, out


def media_control(action: str):
    """Tell Spotify to play_pause / next / prev. Returns (status, error): status is "ok", "not running" or "error"."""
    c = {"play_pause": "playpause", "next": "next track", "prev": "previous track"}[action]
    rc, out = run_osascript(
        'if application "Spotify" is running then\n'
        f'tell application "Spotify" to {c}\n'
        'return "ok"\nend if\nreturn "not running"')
    if rc != 0: return "error", out
    return ("not running" if out == "not running" else "ok"), ""


def set_wallpaper(path: str):
    """Set the desktop picture (on every desktop). Returns (ok, error text)."""
    p = as_quote(os.path.abspath(path))
    rc, out = run_osascript(
        f'tell application "System Events" to tell every desktop to set picture to POSIX file "{p}"')
    return rc == 0, out


def stats_disk() -> str:
    """The folder whose disk the "disk space" figure describes."""
    return "/System/Volumes/Data" if os.path.exists("/System/Volumes/Data") else "/"


def protected_paths(home: str) -> set:
    """Folders the delete tool refuses to remove whatever it is told."""
    return {os.path.realpath(p) for p in (
        "/", home, os.path.join(home, "Desktop"), os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"), os.path.join(home, "Library"), "/System", "/Users",
        "/Applications", "/usr", "/bin", "/etc", "/var")}


def move_to_trash(path: str, home: str) -> str:
    """Move to the Trash instead of deleting for good."""
    trash = os.path.join(home, ".Trash")
    if not os.path.isdir(trash):
        raise OSError("Trash folder not found")
    name = os.path.basename(path.rstrip("/")) or "item"
    dest = os.path.join(trash, name)
    n = 1
    while os.path.exists(dest):
        stem, ext = os.path.splitext(name)
        dest = os.path.join(trash, f"{stem} {n}{ext}"); n += 1
    shutil.move(path, dest)
    return dest


def shell_env() -> dict:
    env = dict(os.environ)                 # a GUI app starts with a bare PATH: add Homebrew and the usual folders
    have = env.get("PATH", "").split(":")
    env["PATH"] = ":".join(_GUI_PATH.split(":") + [p for p in have if p and p not in _GUI_PATH])
    return env


def extra_path_dirs(home: str) -> list:
    """Where command-line tools usually live that a GUI app's bare PATH does not include."""
    return ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", os.path.join(home, ".local", "bin")]


def find_python():
    """A real Python interpreter for a packaged NOVA (None if this Mac has none)."""
    for cand in ("/opt/homebrew/bin/python3", "/usr/local/bin/python3"):
        if os.access(cand, os.X_OK): return cand
    cand = shutil.which("python3") or "/usr/bin/python3"
    if cand == "/usr/bin/python3":
        # /usr/bin/python3 is only a stub that opens an installer dialog unless the developer tools exist
        if subprocess.run(["xcode-select", "-p"], capture_output=True).returncode != 0:
            return None
    return cand


# what people call an app -> the app names to try, in order, with `open -a`
APP_MAP = {
    "chrome": ["Google Chrome"], "google chrome": ["Google Chrome"],
    "firefox": ["Firefox"], "safari": ["Safari"],
    "edge": ["Microsoft Edge"], "microsoft edge": ["Microsoft Edge"],
    "notepad": ["TextEdit"], "textedit": ["TextEdit"], "wordpad": ["TextEdit"],
    "calculator": ["Calculator"], "calc": ["Calculator"],
    "explorer": ["Finder"], "file explorer": ["Finder"], "finder": ["Finder"], "files": ["Finder"],
    "task manager": ["Activity Monitor"], "activity monitor": ["Activity Monitor"],
    "settings": ["System Settings", "System Preferences"],
    "control panel": ["System Settings", "System Preferences"],
    "system settings": ["System Settings", "System Preferences"],
    "system preferences": ["System Settings", "System Preferences"],
    "cmd": ["Terminal"], "command prompt": ["Terminal"], "powershell": ["Terminal"], "terminal": ["Terminal"],
    "snipping tool": ["Screenshot"], "screenshot": ["Screenshot"],
    "paint": ["Preview"], "preview": ["Preview"],
    "word": ["Microsoft Word"], "excel": ["Microsoft Excel"],
    "powerpoint": ["Microsoft PowerPoint"], "outlook": ["Microsoft Outlook"],
    "spotify": ["Spotify"], "discord": ["Discord"], "steam": ["Steam"], "vlc": ["VLC"],
    "vscode": ["Visual Studio Code"], "vs code": ["Visual Studio Code"],
    "visual studio code": ["Visual Studio Code"],
    "telegram": ["Telegram"], "whatsapp": ["WhatsApp"], "zoom": ["zoom.us"],
    "obs": ["OBS"], "obs studio": ["OBS"],
    "code": ["Visual Studio Code"], "pycharm": ["PyCharm", "PyCharm CE"],
    "notes": ["Notes"], "messages": ["Messages"], "mail": ["Mail"], "calendar": ["Calendar"],
    "music": ["Music"], "photos": ["Photos"], "maps": ["Maps"], "app store": ["App Store"],
}


def scan_apps(home: str) -> dict:
    """Installed apps: lower-case name -> path of the .app, so 'open <name>' can find them."""
    found = {}
    dirs = ["/Applications", "/Applications/Utilities",
            "/System/Applications", "/System/Applications/Utilities",
            os.path.join(home, "Applications")]
    for d in dirs:
        try:
            for entry in os.listdir(d):
                if entry.endswith(".app"):
                    found[entry[:-4].lower()] = os.path.join(d, entry)
        except OSError:
            pass
    return found


def open_app(target: str, is_path: bool = False) -> bool:
    """Open an app by name (`open -a`) or by the path found by scan_apps."""
    args = ["open", target] if is_path else ["open", "-a", target]
    try:
        return subprocess.run(args, capture_output=True, timeout=8).returncode == 0
    except Exception:
        return False


def reveal_path(path: str) -> None:
    """Show a file in Finder (selected), or open a folder."""
    subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])


def open_path(path: str) -> None:
    """Open a file, folder or settings address with whatever the system uses for it."""
    subprocess.Popen(["open", path])


OWN_REGION_PICKER = False                  # True where NOVA has to show its own "select part of the screen" overlay


def capture_region(path: str) -> None:
    """Let the user drag out part of the screen; the picture is written to `path` (nothing if they press Esc)."""
    subprocess.run(["/usr/sbin/screencapture", "-i", "-x", path], timeout=180)   # -i: drag to select, Esc cancels


def audio_to_wav(src: str, dst: str, rate: int) -> bool:
    """Decode an audio file (mp3 / aiff / wav) to 16-bit mono WAV at `rate`. Uses afconvert, which ships with macOS."""
    r = subprocess.run(["/usr/bin/afconvert", "-f", "WAVE", "-d", f"LEI16@{rate}", "-c", "1", src, dst],
                       capture_output=True, timeout=20)
    return r.returncode == 0

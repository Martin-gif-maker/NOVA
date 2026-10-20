# plat_windows.py — everything NOVA asks of Windows itself: notifications, sound, the clipboard, start with
# Windows, global hotkeys, selected text, app activation, network and Spotify information, and what the tools
# need from the system (volume, power, Recycle Bin, wallpaper, opening apps, the shell).
# Reached as `platform_utils`; plat_mac.py offers the same names for macOS.
#
# Nothing here needs an extra package: the system is reached through ctypes, the registry module and a hidden
# PowerShell for the few things only .NET offers (speech, the notification balloon, the list of Start apps).
# Windows libraries are only touched inside functions, so the module can be imported (and its plain logic
# tested) on any system.
import os, re, sys, time, socket, subprocess, shutil, threading, tempfile
import logging

log = logging.getLogger("nova")

IS_MAC = False
IS_WINDOWS = True
OS_NAME = "Windows"
NATIVE_VOICE_EXT = ".wav"                  # what synth_native writes
QUIET_PROCESS = {"creationflags": 0x08000000}      # CREATE_NO_WINDOW: a helper program must not flash a console window

# ── Labels shown in the UI ────────────────────────────────────────
KEYSTORE_NAME = "Windows Credential Manager"
LOGIN_LABEL   = "Launch at login"          # shown in Windows' words ("Start with Windows") by i18n
MOD_NAME      = "Ctrl"

# Global "show/hide NOVA" hotkey. Win+Space and Alt+Shift switch the keyboard language, Ctrl+Space and
# Ctrl+Shift+Space belong to editors (completion), Alt+Space is the window menu - Ctrl+Alt+Space is usually free.
HOTKEY_LABEL = "Ctrl+Alt+Space"
_HOTKEY_KEYCODE = 0x20                     # VK_SPACE
_HOTKEY_MODS    = ("ctrl", "alt")          # any of: ctrl, alt, shift, win

SELECTION_HOTKEY_LABEL = "Ctrl+Alt+Shift+Space"     # act on the text selected in any app
_SELECTION_HOTKEY_KEY  = 0x20
_SELECTION_HOTKEY_MODS = ("ctrl", "alt", "shift")

# Qt point sizes on Windows already are the sizes the interface was designed with.
_FONT_SCALE = 1.0
UI_FONT = "Segoe UI"

_KEY_C, _KEY_V = 0x43, 0x56                # virtual-key codes
_VK_CONTROL, _VK_SHIFT, _VK_ALT, _VK_LWIN, _VK_RWIN = 0x11, 0x10, 0x12, 0x5B, 0x5C


def shortcut_label(key: str) -> str:
    """'N' -> 'Ctrl+N'"""
    return f"Ctrl+{key}"


def ui_font(size, weight=None):
    """The interface font at a design size."""
    from PySide6.QtGui import QFont
    px = max(1, int(round(size * _FONT_SCALE)))
    return QFont(UI_FONT, px) if weight is None else QFont(UI_FONT, px, weight)


# ──────────────────────────────────────────────────────────────────
#  Windows libraries and PowerShell
# ──────────────────────────────────────────────────────────────────
_libs = {}


def _win(name: str):
    """A Windows system library, with the argument and result types of the calls NOVA makes declared
    (without them window handles and pointers are cut to 32 bits on 64-bit Windows)."""
    lib = _libs.get(name)
    if lib is not None: return lib
    import ctypes
    from ctypes import wintypes as w
    lib = ctypes.WinDLL(name, use_last_error=True)
    P = ctypes.POINTER
    if name == "user32":
        lib.GetForegroundWindow.restype = w.HWND
        lib.GetWindowThreadProcessId.argtypes = [w.HWND, P(w.DWORD)]; lib.GetWindowThreadProcessId.restype = w.DWORD
        lib.SetForegroundWindow.argtypes = [w.HWND]
        lib.BringWindowToTop.argtypes = [w.HWND]
        lib.IsWindowVisible.argtypes = [w.HWND]
        lib.IsIconic.argtypes = [w.HWND]
        lib.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
        lib.GetWindow.argtypes = [w.HWND, w.UINT]; lib.GetWindow.restype = w.HWND
        lib.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        lib.GetWindowTextLengthW.argtypes = [w.HWND]
        lib.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
        lib.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        lib.RegisterHotKey.argtypes = [w.HWND, ctypes.c_int, w.UINT, w.UINT]
        lib.UnregisterHotKey.argtypes = [w.HWND, ctypes.c_int]
        lib.GetMessageW.argtypes = [P(w.MSG), w.HWND, w.UINT, w.UINT]
        lib.PeekMessageW.argtypes = [P(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        lib.PostThreadMessageW.argtypes = [w.DWORD, w.UINT, w.WPARAM, w.LPARAM]
        lib.SendInput.argtypes = [w.UINT, ctypes.c_void_p, ctypes.c_int]; lib.SendInput.restype = w.UINT
        lib.GetAsyncKeyState.argtypes = [ctypes.c_int]; lib.GetAsyncKeyState.restype = ctypes.c_short
        lib.OpenClipboard.argtypes = [w.HWND]
        lib.EnumClipboardFormats.argtypes = [w.UINT]; lib.EnumClipboardFormats.restype = w.UINT
        lib.GetClipboardData.argtypes = [w.UINT]; lib.GetClipboardData.restype = ctypes.c_void_p
        lib.SetClipboardData.argtypes = [w.UINT, ctypes.c_void_p]; lib.SetClipboardData.restype = ctypes.c_void_p
        lib.GetClipboardSequenceNumber.restype = w.DWORD
        lib.SystemParametersInfoW.argtypes = [w.UINT, w.UINT, ctypes.c_void_p, w.UINT]
    elif name == "kernel32":
        lib.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]; lib.GlobalAlloc.restype = ctypes.c_void_p
        lib.GlobalLock.argtypes = [ctypes.c_void_p]; lib.GlobalLock.restype = ctypes.c_void_p
        lib.GlobalUnlock.argtypes = [ctypes.c_void_p]
        lib.GlobalSize.argtypes = [ctypes.c_void_p]; lib.GlobalSize.restype = ctypes.c_size_t
        lib.GlobalFree.argtypes = [ctypes.c_void_p]; lib.GlobalFree.restype = ctypes.c_void_p
        lib.GetCurrentThreadId.restype = w.DWORD
        lib.GetDriveTypeW.argtypes = [w.LPCWSTR]; lib.GetDriveTypeW.restype = w.UINT
    elif name == "shell32":
        lib.SHFileOperationW.argtypes = [ctypes.c_void_p]
        lib.SHEmptyRecycleBinW.argtypes = [w.HWND, w.LPCWSTR, w.DWORD]; lib.SHEmptyRecycleBinW.restype = ctypes.c_long
        lib.SetCurrentProcessExplicitAppUserModelID.argtypes = [w.LPCWSTR]
        lib.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    elif name == "winmm":
        lib.mciSendStringW.argtypes = [w.LPCWSTR, w.LPWSTR, w.UINT, w.HANDLE]; lib.mciSendStringW.restype = w.DWORD
    elif name == "ole32":
        lib.CoInitializeEx.argtypes = [ctypes.c_void_p, w.DWORD]; lib.CoInitializeEx.restype = ctypes.c_long
        lib.CLSIDFromString.argtypes = [w.LPCWSTR, ctypes.c_void_p]; lib.CLSIDFromString.restype = ctypes.c_long
        lib.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, P(ctypes.c_void_p)]
        lib.CoCreateInstance.restype = ctypes.c_long
    elif name == "powrprof":
        lib.SetSuspendState.argtypes = [w.BOOLEAN, w.BOOLEAN, w.BOOLEAN]; lib.SetSuspendState.restype = w.BOOLEAN
    _libs[name] = lib
    return lib


def _system_exe(name: str) -> str:
    """A program that ships with Windows, by its full path (never whatever of that name is first on PATH)."""
    root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR") or r"C:\Windows"
    sub = os.path.join("System32", "WindowsPowerShell", "v1.0") if name == "powershell.exe" else "System32"
    if name == "explorer.exe": sub = ""
    return os.path.join(root, sub, name)


def _powershell(script: str, env: dict = None, timeout: float = 20):
    """Run a short PowerShell script without a window. Returns (returncode, output). Values from outside reach
    the script as environment variables, never as part of its text."""
    full = dict(os.environ); full.update({k: str(v) for k, v in (env or {}).items()})
    try:
        r = subprocess.run([_system_exe("powershell.exe"), "-NoProfile", "-NonInteractive", "-Command",
                            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; " + script],
                           capture_output=True, timeout=timeout, env=full, stdin=subprocess.DEVNULL, **QUIET_PROCESS)
        out = r.stdout if r.returncode == 0 else (r.stderr or r.stdout)
        return r.returncode, out.decode("utf-8", "replace").strip()
    except subprocess.TimeoutExpired:
        return 1, "timed out"
    except Exception as e:
        return 1, str(e)


# ──────────────────────────────────────────────────────────────────
#  Notifications
# ──────────────────────────────────────────────────────────────────
NOTIFY_HOOK = None      # set by the window: callable(title, message, ms) -> bool, shows it through NOVA's own tray icon

_NOTIFY_PS = (
    "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
    "$n = New-Object System.Windows.Forms.NotifyIcon; "
    "try { $n.Icon = New-Object System.Drawing.Icon($env:NOVA_ICON) } catch { $n.Icon = [System.Drawing.SystemIcons]::Information }; "
    "$n.Text = 'NOVA'; $n.BalloonTipTitle = $env:NOVA_TITLE; $n.BalloonTipText = $env:NOVA_TEXT; $n.Visible = $true; "
    "$n.ShowBalloonTip([int]$env:NOVA_MS); Start-Sleep -Milliseconds ([int]$env:NOVA_MS + 1000); $n.Dispose()")


def notify(title: str, message: str, ms: int = 5000) -> None:
    """Show a desktop notification (non-blocking)."""
    title = str(title)[:63] or "NOVA"                       # Windows cuts a balloon title at 63 characters …
    message = str(message)[:255] or " "                     # … and its text at 255; an empty text is refused
    try:
        hook = NOTIFY_HOOK
        if hook and hook(title, message, ms): return
        env = dict(os.environ, NOVA_TITLE=title, NOVA_TEXT=message, NOVA_MS=str(int(ms)),
                   NOVA_ICON=os.path.join(os.path.dirname(os.path.abspath(__file__)), "nova.ico"))
        subprocess.Popen([_system_exe("powershell.exe"), "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                          "-Command", _NOTIFY_PS], env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **QUIET_PROCESS)
    except Exception as e: log.info("a notification could not be shown: %s", e)


# ──────────────────────────────────────────────────────────────────
#  Audio  (TTS playback)
# ──────────────────────────────────────────────────────────────────
_audio_proc = None                    # the PowerShell process that is speaking right now (system voice)
_audio_stop = threading.Event()       # tells the playback loop below to end


def stop_audio() -> None:
    """Stop whatever TTS audio is currently playing (also the system voice)."""
    _audio_stop.set()
    p = _audio_proc
    if p is not None and p.poll() is None:
        try: p.terminate()
        except Exception as e: log.debug("stopping the sound: %s", e)


def _mci(command: str) -> str:
    """Send one command to Windows' built-in media player (MCI); returns its answer. Raises if it refuses."""
    import ctypes
    buf = ctypes.create_unicode_buffer(128)
    err = _win("winmm").mciSendStringW(command, buf, 127, None)
    if err: raise RuntimeError(f"the sound could not be played (MCI error {err})")
    return buf.value


def play_audio_file(path: str) -> None:
    """Play an mp3 / wav file and block until it finishes or stop_audio() is called (call from a worker thread).
    Opening, watching and closing all happen on this one thread, as MCI requires."""
    alias = f"nova{threading.get_ident()}x{int(time.time() * 1000) % 1000000}"
    _audio_stop.clear()
    _mci(f'open "{path}" type mpegvideo alias {alias}')
    try:
        _mci(f"play {alias}")
        started = time.time()
        while not _audio_stop.is_set():
            mode = _mci(f"status {alias} mode")
            if mode == "stopped" and time.time() - started > 0.15: break
            time.sleep(0.04)
    finally:
        for cmd in (f"stop {alias}", f"close {alias}"):
            try: _mci(cmd)
            except RuntimeError: pass


_SPEAK_PS = ("Add-Type -AssemblyName System.Speech; "
             "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
             "$t = [System.IO.File]::ReadAllText($env:NOVA_IN, [System.Text.Encoding]::UTF8); ")


def _text_file(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="nova_say_")
    with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(text)
    return path


def synth_native(text: str, path: str) -> bool:
    """Write Windows' own voice to a WAV file instead of speaking it (so NOVA knows exactly what it plays)."""
    src = _text_file(text)
    try:
        rc, _ = _powershell(_SPEAK_PS + "$s.SetOutputToWaveFile($env:NOVA_OUT); $s.Speak($t); $s.Dispose()",
                            env={"NOVA_IN": src, "NOVA_OUT": path}, timeout=60)
        return rc == 0 and os.path.getsize(path) > 4096
    except OSError:
        return False
    finally:
        try: os.unlink(src)
        except OSError: pass


def speak_native(text: str) -> None:
    """Offline fallback voice (used when edge-tts is unavailable). Blocks until it has finished speaking."""
    global _audio_proc
    src = _text_file(text)
    try:
        env = dict(os.environ, NOVA_IN=src)
        _audio_proc = subprocess.Popen([_system_exe("powershell.exe"), "-NoProfile", "-NonInteractive", "-Command",
                                        _SPEAK_PS + "$s.Speak($t)"], env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **QUIET_PROCESS)
        _audio_proc.wait()
    except Exception as e: log.info("the Windows voice could not speak: %s", e)
    finally:
        try: os.unlink(src)
        except OSError: pass


def audio_to_wav(src: str, dst: str, rate: int) -> bool:
    """Decode an audio file to 16-bit mono WAV at `rate` (for telling NOVA's own voice from yours).
    WAV files (the system voice) are read directly; mp3 needs the optional `miniaudio` package or ffmpeg -
    without either NOVA falls back to a plain loudness threshold."""
    import wave
    try:
        with open(src, "rb") as f: head = f.read(12)
        if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            import numpy as np
            with wave.open(src, "rb") as w:
                width, channels, src_rate = w.getsampwidth(), w.getnchannels(), w.getframerate()
                if width != 2: return False
                data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
            if channels > 1: data = data[:len(data) // channels * channels].reshape(-1, channels).mean(axis=1)
            if src_rate != rate and len(data):
                n = int(len(data) * rate / src_rate)
                data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data)
            pcm = np.clip(data, -32768, 32767).astype(np.int16).tobytes()
        else:
            try:
                import miniaudio
                pcm = bytes(miniaudio.decode_file(src, output_format=miniaudio.SampleFormat.SIGNED16,
                                                  nchannels=1, sample_rate=rate).samples)
            except ImportError:
                ffmpeg = shutil.which("ffmpeg")
                if not ffmpeg: return False
                r = subprocess.run([ffmpeg, "-y", "-loglevel", "quiet", "-i", src, "-ac", "1", "-ar", str(rate),
                                    "-sample_fmt", "s16", dst], capture_output=True, timeout=20,
                                   stdin=subprocess.DEVNULL, **QUIET_PROCESS)
                return r.returncode == 0
        with wave.open(dst, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
        return True
    except Exception as e:
        log.info("the sound could not be decoded: %s", e); return False


# ──────────────────────────────────────────────────────────────────
#  Clipboard
# ──────────────────────────────────────────────────────────────────
def get_clipboard_text() -> str:
    import pyperclip
    return (pyperclip.paste() or "").strip()


def set_clipboard_text(text: str) -> None:
    import pyperclip
    pyperclip.copy(text)


# Formats whose content is a drawing handle, not a block of memory: Windows re-creates them from the others.
_HANDLE_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}        # bitmap, metafile, palette, enhanced metafile, owner display …


def _open_clipboard() -> bool:
    user32 = _win("user32")
    for _ in range(25):                                    # another program may hold it for a moment
        if user32.OpenClipboard(None): return True
        time.sleep(0.02)
    return False


def _clipboard_snapshot():
    """Everything on the clipboard as [(format, bytes)], or None if it could not be read."""
    import ctypes
    user32, kernel32 = _win("user32"), _win("kernel32")
    if not _open_clipboard(): return None
    try:
        items, fmt = [], 0
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if not fmt: break
            if fmt in _HANDLE_FORMATS or 0x300 <= fmt <= 0x3FF: continue
            handle = user32.GetClipboardData(fmt)
            if not handle: continue
            size = kernel32.GlobalSize(handle)
            ptr = kernel32.GlobalLock(handle) if size else None
            if not ptr: continue
            try: items.append((fmt, ctypes.string_at(ptr, size)))
            finally: kernel32.GlobalUnlock(handle)
        return items
    finally:
        user32.CloseClipboard()


def _clipboard_restore(items) -> None:
    """Put back what _clipboard_snapshot took."""
    import ctypes
    user32, kernel32 = _win("user32"), _win("kernel32")
    if not _open_clipboard(): return
    try:
        user32.EmptyClipboard()
        for fmt, data in items:
            handle = kernel32.GlobalAlloc(0x0002, len(data))                # GMEM_MOVEABLE
            ptr = kernel32.GlobalLock(handle) if handle else None
            if not ptr: continue
            ctypes.memmove(ptr, data, len(data)); kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(fmt, handle): kernel32.GlobalFree(handle)
    finally:
        user32.CloseClipboard()


# ──────────────────────────────────────────────────────────────────
#  Start with Windows
# ──────────────────────────────────────────────────────────────────
_RUN_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"        # per user: no administrator rights needed
_RUN_NAME = "NOVA"


def _run_command() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            return str(winreg.QueryValueEx(key, _RUN_NAME)[0])
    except (OSError, ImportError):
        return ""


def _windowless_python() -> str:
    """pythonw.exe next to python.exe, so a start from source opens no console window."""
    exe = sys.executable
    if os.path.basename(exe).lower() == "python.exe":
        cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(cand): return cand
    return exe


def autostart_command(script: str, hidden: bool = True) -> str:
    """The command line Windows runs at sign-in."""
    cmd = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{_windowless_python()}" "{script}"'
    return cmd + (" --hidden" if hidden else "")


def autostart_enabled() -> bool:
    """True if NOVA is currently registered to start when you sign in."""
    return bool(_run_command())


def autostart_hidden() -> bool:
    """True if the sign-in start is set up to stay in the notification area."""
    return "--hidden" in _run_command()


def set_autostart(enabled: bool, script: str, hidden: bool = True) -> bool:
    """Register / unregister NOVA to start at sign-in. `hidden` = start in the notification area without opening
    the window. Returns True on success."""
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, _RUN_NAME, 0, winreg.REG_SZ, autostart_command(script, hidden))
            else:
                try: winreg.DeleteValue(key, _RUN_NAME)
                except FileNotFoundError: pass
        return True
    except Exception:
        return False


_CLASSES_KEY = r"Software\Classes"          # per user


def register_url_scheme(command: str = None) -> bool:
    """Tell Windows that nova:// links open NOVA (for this user). A clicked link then arrives on NOVA's command line."""
    try:
        import winreg
        command = command or f'"{sys.executable}" "%1"'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _CLASSES_KEY + r"\nova") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:NOVA")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _CLASSES_KEY + r"\nova\shell\open\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
        return True
    except Exception as e:
        log.info("nova:// links could not be registered: %s", e); return False


# ──────────────────────────────────────────────────────────────────
#  Global hotkey
# ──────────────────────────────────────────────────────────────────
_hotkeys = []              # [(virtual key, ("ctrl", "alt"), callback)] - every global shortcut NOVA listens for
_hotkey_thread_id = 0      # the listener thread (0 = not running)
_hotkey_failed = set()     # (key, mods) Windows refused: some other program has that shortcut
_MOD_FLAGS = {"alt": 0x1, "opt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8, "cmd": 0x8}
_WM_HOTKEY, _WM_SYNC = 0x0312, 0x8000 + 77          # WM_APP + 77: "the list of hotkeys changed"


def _mod_mask(mods) -> int:
    mask = 0x4000                                       # MOD_NOREPEAT: holding the keys down fires once
    for m in mods: mask |= _MOD_FLAGS[m]
    return mask


def _hotkey_loop(ready: threading.Event) -> None:
    """Windows delivers a registered hotkey to the thread that registered it, so one thread registers them all
    and waits for them."""
    global _hotkey_thread_id
    import ctypes
    from ctypes import wintypes
    user32 = _win("user32")
    msg = wintypes.MSG()
    user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)        # gives this thread a message queue
    registered = {}                                              # id -> the callbacks of that shortcut

    def sync():
        for ident in list(registered): user32.UnregisterHotKey(None, ident)
        registered.clear(); _hotkey_failed.clear()
        combos = {}
        for key, mods, callback in list(_hotkeys):
            combos.setdefault((key, tuple(mods)), []).append(callback)
        for ident, (combo, callbacks) in enumerate(combos.items(), 1):
            if user32.RegisterHotKey(None, ident, _mod_mask(combo[1]), combo[0]): registered[ident] = callbacks
            else: _hotkey_failed.add(combo)

    sync()
    _hotkey_thread_id = _win("kernel32").GetCurrentThreadId()
    ready.set()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == _WM_HOTKEY:
            for callback in registered.get(int(msg.wParam), ()):
                try: callback()                     # emits a Qt signal - safe from this thread
                except Exception as e: log.warning("a global hotkey's action failed: %s", e)
        elif msg.message == _WM_SYNC:
            sync()


def _resync_hotkeys() -> None:
    if _hotkey_thread_id:
        _win("user32").PostThreadMessageW(_hotkey_thread_id, _WM_SYNC, 0, 0)


def add_global_hotkey(keycode: int, mods, callback) -> None:
    """Register one more global shortcut. Takes effect at once if the listener is already running."""
    _hotkeys.append((int(keycode), tuple(mods), callback))
    _resync_hotkeys()


def remove_global_hotkey(callback) -> None:
    before = len(_hotkeys)
    _hotkeys[:] = [h for h in _hotkeys if h[2] is not callback]
    if len(_hotkeys) != before: _resync_hotkeys()


def start_global_hotkey(callback) -> bool:
    """Call `callback()` when the global show/hide hotkey is pressed. False if another program already owns it."""
    add_global_hotkey(_HOTKEY_KEYCODE, _HOTKEY_MODS, callback)
    try:
        if not _hotkey_thread_id:
            ready = threading.Event()
            threading.Thread(target=_hotkey_loop, args=(ready,), daemon=True, name="hotkeys").start()
            if not ready.wait(3): return False
        else:
            time.sleep(0.05)                            # the listener is re-registering
        return (_HOTKEY_KEYCODE, _HOTKEY_MODS) not in _hotkey_failed
    except Exception:
        return False


def hotkey_taken(keycode: int, mods) -> bool:
    """True if Windows refused this shortcut because another program has it."""
    return (int(keycode), tuple(mods)) in _hotkey_failed


# ──────────────────────────────────────────────────────────────────
#  Key presses, the app in front, the text selected in another app
# ──────────────────────────────────────────────────────────────────
def _send_keys(keys) -> None:
    """Send key presses to whatever window has the keyboard: [(virtual key, True for down / False for up), …]."""
    import ctypes
    from ctypes import wintypes as w

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ctypes.c_void_p)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD), ("dwFlags", w.DWORD), ("time", w.DWORD),
                    ("dwExtraInfo", ctypes.c_void_p)]

    class _Union(ctypes.Union):                         # the mouse part gives the structure the size Windows expects
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", w.DWORD), ("u", _Union)]

    events = (INPUT * len(keys))()
    for ev, (vk, down) in zip(events, keys):
        ev.type = 1                                     # INPUT_KEYBOARD
        ev.u.ki = KEYBDINPUT(vk, 0, 0 if down else 0x0002, 0, None)        # 0x0002 = KEYEVENTF_KEYUP
    sent = _win("user32").SendInput(len(keys), ctypes.byref(events), ctypes.sizeof(INPUT))
    if sent != len(keys): raise OSError("Windows did not accept the key presses")


def _held(vk: int) -> bool:
    return bool(_win("user32").GetAsyncKeyState(vk) & 0x8000)


def _press_cmd(vk: int) -> None:
    """Press Ctrl + one key for the user (a real keystroke in whatever app is in front). The hotkey that led here
    may still be held down, so first wait for Alt / Shift / the Windows key to come up - and let go of them
    for the user if they do not - or the app would see Ctrl+Alt+Shift+C instead of Ctrl+C."""
    others = (_VK_ALT, _VK_SHIFT, _VK_LWIN, _VK_RWIN)
    end = time.time() + 0.7
    while time.time() < end and any(_held(k) for k in others):
        time.sleep(0.02)
    release = [(k, False) for k in others if _held(k)]
    _send_keys(release + [(_VK_CONTROL, True), (vk, True), (vk, False), (_VK_CONTROL, False)])


def frontmost_pid() -> int:
    """Process id of the app in front (0 if unknown)."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _win("user32")
        hwnd = user32.GetForegroundWindow()
        if not hwnd: return 0
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def nova_is_frontmost() -> bool:
    return frontmost_pid() == os.getpid()


def press_paste() -> bool:
    """Press Ctrl+V in the app in front. False if it could not be done."""
    if nova_is_frontmost(): return False
    try:
        _press_cmd(_KEY_V); return True
    except Exception:
        return False


def _windows_of(pid: int, hidden: bool = False) -> list:
    """The top-level windows of a process, front-most first (only the visible ones unless `hidden`)."""
    import ctypes
    from ctypes import wintypes
    user32 = _win("user32")
    found = []

    def _each(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and (hidden or (user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4))):   # 4 = GW_OWNER
            found.append(hwnd)
        return True
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(_each)
    user32.EnumWindows(proc, 0)
    return found


def quit_app(name: str) -> list:
    """Ask the programs called `name` to close the way their close button does - they may ask to save first. Returns
    the names of the programs asked ([] when no program of that name has a window)."""
    import psutil
    mine = {os.getpid(), os.getppid()}
    asked = []
    for p in psutil.process_iter(["pid", "name"]):
        nm = p.info["name"] or ""
        if nm.lower().removesuffix(".exe") != name.strip().lower().removesuffix(".exe") or p.info["pid"] in mine:
            continue
        windows = _windows_of(p.info["pid"])
        for hwnd in windows: _win("user32").PostMessageW(hwnd, 0x0010, 0, 0)             # WM_CLOSE
        if windows: asked.append(nm.removesuffix(".exe"))
    return asked


def _to_front(hwnd) -> bool:
    user32 = _win("user32")
    if user32.IsIconic(hwnd): user32.ShowWindow(hwnd, 9)                # SW_RESTORE
    if user32.SetForegroundWindow(hwnd): return True
    # Windows only lets the program you last used change what is in front. A tap on Alt counts as "used".
    try: _send_keys([(_VK_ALT, True), (_VK_ALT, False)])
    except OSError: pass
    return bool(user32.SetForegroundWindow(hwnd))


def activate_pid(pid: int) -> bool:
    """Bring another running app back to the front."""
    if not pid or pid == os.getpid(): return False
    try:
        windows = _windows_of(pid)
        return bool(windows) and _to_front(windows[0])
    except Exception:
        return False


def activate_app() -> None:
    """Bring this app to the front (Windows only flashes the taskbar button if merely asked politely)."""
    try:
        from PySide6.QtWidgets import QApplication
        win = QApplication.activeWindow() or next((w for w in QApplication.topLevelWidgets() if w.isVisible()), None)
        if win is not None: _to_front(int(win.winId()))
    except Exception as e: log.debug("could not bring NOVA to the front: %s", e)


def hide_app() -> None:
    """Nothing to do: when NOVA's window hides, Windows gives the keyboard back to the app behind it."""


def frontmost_other_app() -> str:
    """Name of the app in front, or '' if that is NOVA itself / unknown."""
    pid = frontmost_pid()
    if not pid or pid == os.getpid(): return ""
    try:
        import psutil
        name = psutil.Process(pid).name()
    except Exception:
        return ""
    return name[:-4] if name.lower().endswith(".exe") else name


def _copy_selection(wait: float = 0.6) -> str:
    """Press Ctrl+C for the user, read the clipboard, then put back exactly what was on it before."""
    try:
        user32 = _win("user32")
        saved = _clipboard_snapshot()
        before = user32.GetClipboardSequenceNumber()
        _press_cmd(_KEY_C)
        end = time.time() + wait
        while user32.GetClipboardSequenceNumber() == before and time.time() < end:
            time.sleep(0.02)
        if user32.GetClipboardSequenceNumber() == before: return ""
        time.sleep(0.05)                                    # the app may still be adding formats
        text = get_clipboard_text()
        if saved is not None: _clipboard_restore(saved)     # restore the user's clipboard
        return text
    except Exception:
        return ""


def selected_text(copy_fallback: bool = True) -> str:
    """The text selected in the app in front ('' if none). Windows has no general way to ask an app for its
    selection, so this presses Ctrl+C for you and restores the clipboard afterwards."""
    if nova_is_frontmost() or not copy_fallback: return ""
    return _copy_selection().strip()


# ──────────────────────────────────────────────────────────────────
#  Permissions (Windows asks for none of these, except the microphone privacy switch)
# ──────────────────────────────────────────────────────────────────
def accessibility_trusted(prompt: bool = False) -> bool:
    return True


def screen_capture_allowed(request: bool = False) -> bool:
    return True


_MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def microphone_status():
    """'granted' | 'denied' from Settings → Privacy → Microphone, or None if it cannot be told."""
    try:
        import winreg
        answers = []
        for sub in ("", r"\NonPackaged"):                  # the main switch, and the one for desktop apps
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _MIC_KEY + sub) as key:
                    answers.append(str(winreg.QueryValueEx(key, "Value")[0]).lower())
            except OSError: pass
        if "deny" in answers: return "denied"
        return "granted" if answers else None
    except Exception:
        return None


def request_microphone() -> None:
    """Windows has no prompt for desktop apps: open the Settings page where the switch is."""
    try: os.startfile("ms-settings:privacy-microphone")
    except Exception as e: log.info("could not open the microphone settings: %s", e)


def brand_process(name: str) -> None:
    """Give the process its own taskbar identity, so a start from source is not grouped under "Python"."""
    try: _win("shell32").SetCurrentProcessExplicitAppUserModelID(f"Martin.{name}")
    except Exception as e: log.debug("could not set the process name: %s", e)


def enable_window_shadow(win_id: int) -> None:
    """macOS only (the window draws its own edge on Windows)."""


# ──────────────────────────────────────────────────────────────────
#  Spotify "now playing"
# ──────────────────────────────────────────────────────────────────
def _spotify_pids() -> set:
    import psutil
    return {p.info["pid"] for p in psutil.process_iter(["pid", "name"]) if (p.info["name"] or "").lower() == "spotify.exe"}


def _window_title(hwnd) -> str:
    import ctypes
    user32 = _win("user32")
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0: return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def spotify_now_playing() -> str:
    """Return 'Artist - Title' of the current Spotify track, or ''. (While a song plays, Spotify shows exactly that
    as its window title; paused, the title is just "Spotify …".)"""
    try:
        for pid in _spotify_pids():
            for hwnd in _windows_of(pid, hidden=True):         # also when Spotify sits in the notification area
                title = _window_title(hwnd).strip()
                if " - " in title and not title.lower().startswith("spotify"): return title
    except Exception as e: log.debug("Spotify could not be asked: %s", e)
    return ""


# ──────────────────────────────────────────────────────────────────
#  Network info
# ──────────────────────────────────────────────────────────────────
def _wifi_name() -> str:
    try:
        r = subprocess.run([_system_exe("netsh.exe"), "wlan", "show", "interfaces"], capture_output=True, timeout=6,
                           stdin=subprocess.DEVNULL, **QUIET_PROCESS)
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            label, sep, value = line.partition(":")
            if sep and label.strip().upper() == "SSID" and value.strip():      # not the "BSSID" line
                return value.strip()
    except Exception as e: log.debug("no Wi-Fi name: %s", e)
    return ""


def network_info() -> str:
    lines = []
    ssid = _wifi_name()
    if ssid: lines.append(f"Wi-Fi: {ssid}")
    try:
        import psutil
        stats = psutil.net_if_stats()
        skip = ("loopback", "vethernet", "bluetooth", "local area connection*", "docker", "vmware", "virtualbox")
        for name, addrs in psutil.net_if_addrs().items():
            st = stats.get(name)
            if not st or not st.isup or name.lower().startswith(skip):
                continue
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith(("127.", "169.254.")):
                    lines.append(f"{name}: {a.address}")
    except Exception as e:
        lines.append(f"(interface list unavailable: {e})")
    return "\n".join(lines) or "No network info available."


# ──────────────────────────────────────────────────────────────────
#  What the tools ask of the system (see tools_system.py, tools_files.py, tools_apps.py)
# ──────────────────────────────────────────────────────────────────
FILE_MANAGER = "Explorer"
TRASH_NAME   = "Recycle Bin"
SHELL_HINT   = ("Use Windows commands (cmd: start, dir, copy, clip; or powershell -Command …), never macOS ones. "
                "Write the home folder as ~ (~\\Downloads).")
SHELL_PREFIX = "chcp 65001 >nul & "        # so the command's output arrives as UTF-8 (Cyrillic file names …)
PYTHON_FLAGS = ("-X", "utf8")              # …and so does what "run this Python code" prints
QUIT_HOW     = "as with its close button"  # how "quit Notepad" closes a program (kill_process without force)
TOOL_GROUPS_HINT   = "files, system, clipboard, music, documents, code"      # for the AI: what more_tools can switch on
# Groups of tools (schemas.GROUPS) that need Apple's Calendar, Reminders, Mail, AppleScript or Shortcuts. They are
# not offered to the AI on Windows, so it never promises something that would fail.
UNAVAILABLE_GROUPS: tuple[str, ...] = ("calendar", "mail", "browser", "shortcuts")
NEVER_KILL   = {"system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
                "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe", "fontdrvhost.exe",
                "sihost.exe", "memory compression"}
SEARCH_SKIP_DIRS   = {"AppData", "Application Data", "Windows", "Program Files", "Program Files (x86)", "ProgramData",
                      "$Recycle.Bin", "System Volume Information"}
SEARCH_SKIP_SUFFIX = ()
NO_SCREEN_PERMISSION = "The screen could not be captured."
NO_TYPING_PERMISSION = "NOVA could not type into the other app."
NO_PYTHON = ("Python is not installed on this PC. Install it from python.org (tick \"Add python.exe to PATH\"), "
             "then try again.")
NO_BATTERY = "No battery (this PC runs on mains power)."
PASTE_KEYS = ("ctrl", "v")                 # for pyautogui


def _com_method(pointer, index: int, *argtypes):
    """Method number `index` of a COM object, callable as method(pointer, …). Returns an HRESULT (0 = fine)."""
    import ctypes
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0]
    address = ctypes.cast(vtable, ctypes.POINTER(ctypes.c_void_p))[index]
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(address)


class _SpeakerVolume:
    """The volume control of the default loudspeakers (Windows' Core Audio), as a `with` block."""
    def __enter__(self):
        self._held = []
        try:
            return self._open()
        except Exception:
            self.__exit__()                                # let go of what was already opened
            raise

    def _open(self):
        import ctypes
        ole32 = _win("ole32")
        ole32.CoInitializeEx(None, 0)                      # fine if this thread already uses COM
        guid = lambda text: self._guid(ole32, text)
        enumerator, device, volume = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        if ole32.CoCreateInstance(guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}"), None, 0x17,     # the device list
                                  guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}"), ctypes.byref(enumerator)):
            raise OSError("no audio service")
        self._held.append(enumerator)
        get_default = _com_method(enumerator, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
        if get_default(enumerator, 0, 1, ctypes.byref(device)):               # 0 = playback, 1 = multimedia
            raise OSError("no loudspeaker")
        self._held.append(device)
        activate = _com_method(device, 3, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        if activate(device, guid("{5CDF2C82-841E-4546-9722-0CF74078229A}"), 0x17, None, ctypes.byref(volume)):
            raise OSError("no volume control")
        self._held.append(volume)
        self._volume = volume
        return self

    @staticmethod
    def _guid(ole32, text):
        import ctypes
        raw = (ctypes.c_ubyte * 16)()
        ole32.CLSIDFromString(text, ctypes.byref(raw))
        return ctypes.byref(raw)

    def __exit__(self, *exc):
        for pointer in reversed(self._held):
            try: _com_method(pointer, 2)(pointer)          # Release
            except Exception: pass
        return False

    def get(self) -> int:
        import ctypes
        level = ctypes.c_float()
        if _com_method(self._volume, 9, ctypes.POINTER(ctypes.c_float))(self._volume, ctypes.byref(level)): raise OSError("volume")
        return int(round(level.value * 100))

    def set(self, percent: int) -> None:
        import ctypes
        if _com_method(self._volume, 7, ctypes.c_float, ctypes.c_void_p)(self._volume, ctypes.c_float(percent / 100.0), None):
            raise OSError("volume")

    def mute(self, muted: bool) -> None:
        import ctypes
        if _com_method(self._volume, 14, ctypes.c_int, ctypes.c_void_p)(self._volume, 1 if muted else 0, None) < 0:
            raise OSError("mute")


def volume_get():
    """Output volume 0-100, or None if there is no loudspeaker to ask."""
    try:
        with _SpeakerVolume() as v: return v.get()
    except Exception as e:
        log.info("the volume could not be read: %s", e); return None


def volume_set(n):
    """Set the output volume; returns the value set, or None if it could not be done."""
    n = max(0, min(100, int(n)))
    try:
        with _SpeakerVolume() as v: v.set(n)
        return n
    except Exception as e:
        log.info("the volume could not be set: %s", e); return None


def volume_mute(muted: bool) -> bool:
    try:
        with _SpeakerVolume() as v: v.mute(muted)
        return True
    except Exception as e:
        log.info("the sound could not be muted: %s", e); return False


def power_off(restart: bool = False) -> None:
    """Shut down or restart now (the 10-second countdown is the caller's)."""
    subprocess.run([_system_exe("shutdown.exe"), "/r" if restart else "/s", "/t", "0"], **QUIET_PROCESS)


def sleep_now(hibernate: bool = False) -> None:
    _win("powrprof").SetSuspendState(bool(hibernate), False, False)


def lock_screen() -> str:
    """Lock the screen; returns what to tell the user."""
    if _win("user32").LockWorkStation(): return "Locked ✓"
    return "Windows did not lock the screen."


def empty_trash():
    """Empty the Recycle Bin for good. Returns (ok, error text)."""
    try:
        hr = _win("shell32").SHEmptyRecycleBinW(None, None, 0x7) & 0xFFFFFFFF      # no questions, no progress window, no sound
        if hr in (0, 0x8000FFFF): return True, ""                                  # 0x8000FFFF: it was already empty
        return False, f"Windows refused (code {hr:#010x})"
    except Exception as e:
        return False, str(e)


def media_control(action: str):
    """Press the keyboard's play/pause, next or previous key for Spotify. Returns (status, error): status is
    "ok", "not running" or "error"."""
    key = {"play_pause": 0xB3, "next": 0xB0, "prev": 0xB1}[action]
    try:
        if not _spotify_pids(): return "not running", ""
        _send_keys([(key, True), (key, False)])
        return "ok", ""
    except Exception as e:
        return "error", str(e)


def set_wallpaper(path: str):
    """Set the desktop picture. Returns (ok, error text)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(os.path.abspath(path))
        ok = _win("user32").SystemParametersInfoW(20, 0, buf, 3)      # SPI_SETDESKWALLPAPER, remembered + announced
        return (True, "") if ok else (False, "Windows refused the picture")
    except Exception as e:
        return False, str(e)


def stats_disk() -> str:
    """The folder whose disk the "disk space" figure describes."""
    return (os.environ.get("SYSTEMDRIVE") or "C:") + "\\"


def protected_paths(home: str) -> set:
    """Folders the delete tool refuses to remove whatever it is told."""
    env = os.environ.get
    drive = (env("SystemDrive") or "C:") + "\\"
    places = [drive, home, os.path.dirname(home), os.path.join(home, "Desktop"), os.path.join(home, "Documents"),
              os.path.join(home, "Downloads"), os.path.join(home, "AppData"), os.path.join(home, "OneDrive"),
              env("SystemRoot") or os.path.join(drive, "Windows"), env("ProgramFiles") or os.path.join(drive, "Program Files"),
              env("ProgramFiles(x86)") or os.path.join(drive, "Program Files (x86)"),
              env("ProgramData") or os.path.join(drive, "ProgramData")]
    return {os.path.normcase(os.path.realpath(p)) for p in places if p}


def move_to_trash(path: str, home: str = "") -> None:
    """Move to the Recycle Bin instead of deleting for good. Refuses where Windows has no Recycle Bin (a USB stick,
    a network drive) rather than letting the file vanish."""
    import ctypes
    from ctypes import wintypes as w
    path = os.path.abspath(path)
    root = os.path.splitdrive(path)[0] + "\\"
    if _win("kernel32").GetDriveTypeW(root) != 3:                       # 3 = a fixed disk
        raise OSError(f"{root} has no Recycle Bin, so nothing was deleted")

    class SHFILEOPSTRUCTW(ctypes.Structure):
        if ctypes.sizeof(ctypes.c_void_p) == 4: _pack_ = 1              # 32-bit Windows packs this one structure
        _fields_ = [("hwnd", w.HWND), ("wFunc", w.UINT), ("pFrom", w.LPCWSTR), ("pTo", w.LPCWSTR), ("fFlags", w.WORD),
                    ("fAnyOperationsAborted", w.BOOL), ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", w.LPCWSTR)]
    source = ctypes.create_unicode_buffer(path + "\0")                  # the list of files ends with two zero characters
    op = SHFILEOPSTRUCTW(None, 3, ctypes.cast(source, w.LPCWSTR), None,          # 3 = FO_DELETE
                         0x0040 | 0x0010 | 0x0004 | 0x0400, 0, None, None)       # to the bin, no questions, no windows
    result = _win("shell32").SHFileOperationW(ctypes.byref(op))
    if result or op.fAnyOperationsAborted or os.path.lexists(path):
        raise OSError(f"Windows could not move it to the Recycle Bin (code {result})")


def shell_env() -> dict:
    return dict(os.environ)


def extra_path_dirs(home: str) -> list:
    """Where command-line tools usually live that NOVA's PATH may not include."""
    appdata = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    return [os.path.join(appdata, "npm"), os.path.join(home, ".local", "bin")]


def find_python():
    """A real Python interpreter for a packaged NOVA (None if this PC has none)."""
    for name in ("py", "python", "python3"):
        exe = shutil.which(name)
        if not exe: continue
        try:                       # the "python" that ships with Windows is only a signpost to the Store: ask it who it is
            r = subprocess.run([exe, "-c", "import sys; print(sys.executable)"], capture_output=True, text=True,
                               timeout=10, stdin=subprocess.DEVNULL, **QUIET_PROCESS)
        except (OSError, subprocess.SubprocessError):
            continue
        real = (r.stdout or "").strip()
        if r.returncode == 0 and real and os.path.isfile(real): return real
    return None


# what people call an app -> what to try, in order: a name from the Start menu, a program name Windows knows,
# or a settings address (ends with ":")
APP_MAP = {
    "chrome": ["google chrome", "chrome"], "google chrome": ["google chrome", "chrome"],
    "firefox": ["firefox"], "edge": ["microsoft edge", "msedge"], "microsoft edge": ["microsoft edge", "msedge"],
    "notepad": ["notepad"], "textedit": ["notepad"], "wordpad": ["wordpad", "write"],
    "calculator": ["calculator", "calc"], "calc": ["calculator", "calc"],
    "explorer": ["explorer"], "file explorer": ["explorer"], "finder": ["explorer"], "files": ["explorer"],
    "task manager": ["taskmgr"], "activity monitor": ["taskmgr"],
    "settings": ["ms-settings:"], "system settings": ["ms-settings:"], "system preferences": ["ms-settings:"],
    "control panel": ["control"],
    "cmd": ["cmd"], "command prompt": ["cmd"], "powershell": ["powershell"], "terminal": ["terminal", "wt", "powershell"],
    "snipping tool": ["snipping tool", "snippingtool"], "screenshot": ["ms-screenclip:"],
    "paint": ["mspaint"], "preview": ["photos", "ms-photos:"],
    "word": ["word", "winword"], "excel": ["excel"], "powerpoint": ["powerpoint", "powerpnt"], "outlook": ["outlook"],
    "spotify": ["spotify", "spotify:"], "vlc": ["vlc media player", "vlc"],
    "vscode": ["visual studio code", "code"], "vs code": ["visual studio code", "code"],
    "visual studio code": ["visual studio code", "code"], "code": ["visual studio code", "code"],
    "pycharm": ["pycharm", "pycharm community edition"], "obs": ["obs studio"],
    "photos": ["photos", "ms-photos:"], "maps": ["maps", "bingmaps:"], "music": ["media player", "mswindowsmusic:"],
    "app store": ["microsoft store", "ms-windows-store:"], "store": ["microsoft store", "ms-windows-store:"],
    "clock": ["clock", "ms-clock:"], "camera": ["camera", "microsoft.windows.camera:"],
}

_ADDRESSES = {t for targets in APP_MAP.values() for t in targets if t.endswith(":")}      # ms-settings: and friends
_apps = {}                 # what scan_apps found: lower-case name -> what to start


def _start_menu_dirs() -> list:
    env = os.environ.get
    return [os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs")
            for base in (env("APPDATA"), env("ProgramData")) if base]


def scan_apps(home: str = "") -> dict:
    """Installed apps: lower-case name -> what to start. First the shortcuts in the Start menu folders, then
    (through PowerShell, about a second) everything the Start menu lists - which adds Store apps such as
    Calculator or Photos that have no shortcut file."""
    found = {}
    for base in _start_menu_dirs():
        for root, _dirs, files in os.walk(base):
            for f in files:
                name, ext = os.path.splitext(f)
                if ext.lower() == ".lnk" and "uninstall" not in name.lower():
                    found.setdefault(name.lower(), os.path.join(root, f))
    rc, out = _powershell('Get-StartApps | ForEach-Object { $_.Name + "`t" + $_.AppID }', timeout=30)
    if rc == 0:
        for line in out.splitlines():
            name, sep, app_id = line.partition("\t")
            if sep and name.strip() and app_id.strip() and "uninstall" not in name.lower():
                found.setdefault(name.strip().lower(), "shell:AppsFolder\\" + app_id.strip())
    _apps.update(found)
    return found


def _start(entry: str) -> bool:
    if entry.startswith("shell:"):
        subprocess.Popen([_system_exe("explorer.exe"), entry]); return True
    os.startfile(entry); return True


def _is_program(name: str) -> bool:
    """True if Windows knows a program of this name: registered under "App Paths" (chrome, winword …) or on PATH."""
    exe = name if name.lower().endswith(".exe") else name + ".exe"
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                winreg.CloseKey(winreg.OpenKey(hive, "Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + exe))
                return True
            except OSError: pass
    except ImportError: pass
    return bool(shutil.which(name))


def open_app(target: str, is_path: bool = False) -> bool:
    """Open an app: by what scan_apps found (is_path), by its Start menu name, by one of the settings addresses
    listed in APP_MAP, or by a plain program name Windows knows (notepad, chrome). Never a path or a web
    address - a name that came from the AI must not be able to start an arbitrary file."""
    try:
        if is_path: return _start(target)
        name = target.strip()
        known = _apps.get(name.lower())
        if known: return _start(known)
        if name in _ADDRESSES: return _start(name)
        if not re.fullmatch(r"[\w .+\-]{1,80}", name) or not _is_program(name): return False
        return _start(name)
    except OSError:
        return False


def reveal_path(path: str) -> None:
    """Show a file in Explorer (selected), or open a folder."""
    if os.path.isfile(path):
        subprocess.Popen(f'"{_system_exe("explorer.exe")}" /select,"{path}"')
    else:
        os.startfile(path)


def open_path(path: str) -> None:
    """Open a file, folder or settings address with whatever Windows uses for it."""
    os.startfile(path)


OWN_REGION_PICKER = True                   # Windows has no selection tool NOVA could wait for: see region_select.py


def capture_region(path: str) -> None:
    """Not used on Windows: the window shows its own "drag out a part of the screen" overlay."""
    raise NotImplementedError

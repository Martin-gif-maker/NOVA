"""NOVA on Windows.

The first part checks the Windows platform layer's own logic with stand-ins for Windows itself, so it runs on every
system (also on the Mac the code is written on). The second part runs only on Windows and asks the real system:
the registry, the clipboard, the Recycle Bin, the shell, the system voice. Nothing here presses keys, changes the
volume, shows a notification or touches the real "start with Windows" entry."""
import os, sys, types, wave
import pytest
import plat_windows as pw
import ipc, i18n, paths, tools, tools_system, tools_files, tools_apps, updater, whatsnew

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="asks Windows itself")
_REAL_PRESS = pw._press_cmd            # taken before the test session swaps the key presser for a refusal (see conftest)


class FakeLib:
    """Stands in for a Windows system library: every call is recorded and answers from `answers` (default 1)."""
    def __init__(self, **answers): self.calls = []; self.answers = answers
    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args))
            answer = self.answers.get(name, 1)
            return answer(*args) if callable(answer) else answer
        return call


@pytest.fixture
def libs(monkeypatch):
    """`libs["user32"] = FakeLib(...)` replaces that library for the test."""
    table = {}
    monkeypatch.setattr(pw, "_win", lambda name: table.setdefault(name, FakeLib()))
    return table


# ── labels, shortcuts, hotkeys ─────────────────────────────────────
def test_labels_are_windows_ones():
    assert pw.shortcut_label("N") == "Ctrl+N" and pw.MOD_NAME == "Ctrl" and pw.KEYSTORE_NAME == "Windows Credential Manager"
    assert pw.HOTKEY_LABEL == "Ctrl+Alt+Space" and pw.SELECTION_HOTKEY_LABEL == "Ctrl+Alt+Shift+Space"
    assert pw.UI_FONT == "Segoe UI" and pw.OS_NAME == "Windows" and pw.TRASH_NAME == "Recycle Bin" and pw.FILE_MANAGER == "Explorer"
    assert pw._mod_mask(("ctrl", "alt")) == 0x4003 and pw._mod_mask(("ctrl", "alt", "shift")) == 0x4007     # + "do not repeat"


def test_hotkeys_are_kept_in_one_list(monkeypatch):
    monkeypatch.setattr(pw, "_hotkeys", []); monkeypatch.setattr(pw, "_hotkey_thread_id", 0)
    a, b = (lambda: None), (lambda: None)
    pw.add_global_hotkey(0x20, ("ctrl", "alt"), a); pw.add_global_hotkey(0x20, ("ctrl", "alt", "shift"), b)
    assert [(k, m) for k, m, _ in pw._hotkeys] == [(0x20, ("ctrl", "alt")), (0x20, ("ctrl", "alt", "shift"))]
    pw.remove_global_hotkey(b)
    assert [cb for _k, _m, cb in pw._hotkeys] == [a]


def test_a_running_listener_is_told_when_the_list_changes(monkeypatch, libs):
    monkeypatch.setattr(pw, "_hotkeys", []); monkeypatch.setattr(pw, "_hotkey_thread_id", 4242)
    cb = lambda: None
    pw.add_global_hotkey(0x20, ("ctrl", "alt"), cb); pw.remove_global_hotkey(cb); pw.remove_global_hotkey(cb)
    posts = [args for name, args in libs["user32"].calls if name == "PostThreadMessageW"]
    assert posts == [(4242, pw._WM_SYNC, 0, 0)] * 2                       # once per real change, to the listener's thread


def test_ctrl_c_is_sent_only_after_the_hotkey_keys_are_up(monkeypatch):
    """The selection hotkey is Ctrl+Alt+Shift+Space: Alt and Shift must not still be down when Ctrl+C is pressed."""
    sent = []; held = {pw._VK_ALT: 3, pw._VK_SHIFT: 10**6}                # Alt comes up after a moment, Shift never does
    def is_held(vk):
        left = held.get(vk, 0)
        if left > 0: held[vk] = left - 1
        return left > 0
    monkeypatch.setattr(pw, "_held", is_held); monkeypatch.setattr(pw, "_send_keys", sent.append)
    monkeypatch.setattr(pw.time, "sleep", lambda s: None)
    clock = iter(x * 0.1 for x in range(1000)); monkeypatch.setattr(pw.time, "time", lambda: next(clock))
    _REAL_PRESS(pw._KEY_C)
    assert sent == [[(pw._VK_SHIFT, False), (pw._VK_CONTROL, True), (pw._KEY_C, True), (pw._KEY_C, False), (pw._VK_CONTROL, False)]]


def test_paste_never_goes_into_nova_itself(monkeypatch):
    pressed = []
    monkeypatch.setattr(pw, "_press_cmd", pressed.append)
    monkeypatch.setattr(pw, "nova_is_frontmost", lambda: True)
    assert pw.press_paste() is False and pw.selected_text() == "" and pressed == []
    monkeypatch.setattr(pw, "nova_is_frontmost", lambda: False)
    assert pw.press_paste() is True and pressed == [pw._KEY_V]


def test_selected_text_is_copied_and_the_clipboard_put_back(monkeypatch, libs):
    seq = {"n": 7}
    libs["user32"] = FakeLib(GetClipboardSequenceNumber=lambda: seq["n"])
    saved = [(13, b"o\x00l\x00d\x00\x00\x00")]; events = []
    monkeypatch.setattr(pw, "_clipboard_snapshot", lambda: saved)
    monkeypatch.setattr(pw, "_clipboard_restore", lambda items: events.append(("restore", items)))
    monkeypatch.setattr(pw, "_press_cmd", lambda vk: (events.append(("press", vk)), seq.update(n=8))[0])
    monkeypatch.setattr(pw, "get_clipboard_text", lambda: "the selected words")
    monkeypatch.setattr(pw, "nova_is_frontmost", lambda: False); monkeypatch.setattr(pw.time, "sleep", lambda s: None)
    assert pw.selected_text() == "the selected words"
    assert events == [("press", pw._KEY_C), ("restore", saved)]
    monkeypatch.setattr(pw, "_press_cmd", lambda vk: None)                 # nothing was selected: the clipboard never changes
    events.clear()
    assert pw.selected_text() == "" and events == []                       # …so there is nothing to put back


# ── start with Windows ─────────────────────────────────────────────
def test_the_sign_in_command_is_quoted(monkeypatch):
    monkeypatch.setattr(pw, "_windowless_python", lambda: r"C:\Program Files\Python314\pythonw.exe")
    assert pw.autostart_command(r"C:\My Apps\NOVA\main.py") == r'"C:\Program Files\Python314\pythonw.exe" "C:\My Apps\NOVA\main.py" --hidden'
    assert pw.autostart_command(r"C:\NOVA\main.py", hidden=False).endswith('main.py"')
    monkeypatch.setattr(pw.sys, "frozen", True, raising=False); monkeypatch.setattr(pw.sys, "executable", r"C:\Apps\NOVA\NOVA.exe")
    assert pw.autostart_command("ignored") == r'"C:\Apps\NOVA\NOVA.exe" --hidden'


# ── notifications and speech: outside text never becomes part of a command ──
def test_notification_text_travels_in_the_environment(monkeypatch):
    started = []
    monkeypatch.setattr(pw.subprocess, "Popen", lambda cmd, **k: started.append((cmd, k)))
    monkeypatch.setattr(pw, "NOTIFY_HOOK", None)
    evil = "'; Remove-Item C:\\ -Recurse; '" + "x" * 400
    pw.notify("T" * 100, evil, ms=3000)
    cmd, k = started[0]
    assert evil[:20] not in " ".join(cmd) and k["env"]["NOVA_TEXT"] == evil[:255] and k["env"]["NOVA_TITLE"] == "T" * 63
    assert k["env"]["NOVA_MS"] == "3000" and k["creationflags"] == 0x08000000
    pw.notify("", ""); assert started[1][1]["env"]["NOVA_TITLE"] == "NOVA" and started[1][1]["env"]["NOVA_TEXT"] == " "


def test_the_window_can_take_over_notifications(monkeypatch):
    shown = []
    monkeypatch.setattr(pw, "NOTIFY_HOOK", lambda title, text, ms: shown.append((title, text, ms)) or True)
    monkeypatch.setattr(pw.subprocess, "Popen", lambda *a, **k: pytest.fail("the tray icon already showed it"))
    pw.notify("NOVA", "tea is ready", 8000)
    assert shown == [("NOVA", "tea is ready", 8000)]


def test_system_voice_reads_the_text_from_a_file(monkeypatch, tmp_path):
    seen = {}
    def fake_ps(script, env=None, timeout=20):
        seen["script"] = script; seen["text"] = open(env["NOVA_IN"], encoding="utf-8").read(); seen["in"] = env["NOVA_IN"]
        with open(env["NOVA_OUT"], "wb") as f: f.write(b"\0" * 9000)
        return 0, ""
    monkeypatch.setattr(pw, "_powershell", fake_ps)
    out = tmp_path / "voice.wav"
    said = 'Здравей "$(calc)" `whoami`'
    assert pw.synth_native(said, str(out)) is True
    assert seen["text"] == said and "calc" not in seen["script"] and not os.path.exists(seen["in"])       # the text file is removed again
    monkeypatch.setattr(pw, "_powershell", lambda *a, **k: (1, "no voice"))
    assert pw.synth_native("x", str(tmp_path / "none.wav")) is False


def test_a_wav_is_brought_to_16_khz_mono(tmp_path):
    np = pytest.importorskip("numpy")
    src, dst = tmp_path / "voice.wav", tmp_path / "ref.wav"
    tone = (np.sin(np.linspace(0, 440 * 2 * np.pi, 22050)) * 12000).astype(np.int16)
    with wave.open(str(src), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(22050); w.writeframes(np.column_stack([tone, tone]).tobytes())
    assert pw.audio_to_wav(str(src), str(dst), 16000) is True
    with wave.open(str(dst), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000) and abs(w.getnframes() - 16000) <= 2
    import echo
    assert echo.envelope(np.frombuffer(open(dst, "rb").read()[44:], dtype=np.int16)).max() > 5000        # still the same loud tone
    junk = tmp_path / "junk.mp3"; junk.write_bytes(b"not audio at all")
    assert pw.audio_to_wav(str(junk), str(tmp_path / "x.wav"), 16000) is False


# ── apps ───────────────────────────────────────────────────────────
def test_start_menu_shortcuts_and_store_apps_are_indexed(monkeypatch, tmp_path):
    programs = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs"; (programs / "Tools").mkdir(parents=True)
    for name in ("Visual Studio Code.lnk", "Tools/OBS Studio.lnk", "Uninstall OBS.lnk", "readme.txt"): (programs / name).write_text("x")
    monkeypatch.setenv("APPDATA", str(tmp_path)); monkeypatch.delenv("ProgramData", raising=False)
    monkeypatch.setattr(pw, "_powershell", lambda script, **k: (0, "Calculator\tMicrosoft.WindowsCalculator_8wekyb3d8bbwe!App\n"
                                                                    "Visual Studio Code\tMicrosoft.VisualStudioCode\nUninstall X\tx\nbroken line"))
    monkeypatch.setattr(pw, "_apps", {})
    found = pw.scan_apps()
    assert found["visual studio code"] == str(programs / "Visual Studio Code.lnk")            # the shortcut file wins
    assert found["obs studio"].endswith("OBS Studio.lnk") and found["calculator"] == r"shell:AppsFolder\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"
    assert not any("uninstall" in name for name in found) and "readme" not in found and pw._apps == found


def test_an_app_name_can_never_start_an_arbitrary_file(monkeypatch):
    started = []
    monkeypatch.setattr(pw, "_start", lambda entry: started.append(entry) or True)
    monkeypatch.setattr(pw, "_apps", {"obs studio": r"C:\menu\OBS Studio.lnk"})
    monkeypatch.setattr(pw, "_is_program", lambda name: name in ("notepad", "chrome"))
    assert pw.open_app("OBS Studio") and pw.open_app("notepad") and pw.open_app("ms-settings:") and pw.open_app(r"C:\menu\x.lnk", True)
    assert started == [r"C:\menu\OBS Studio.lnk", "notepad", "ms-settings:", r"C:\menu\x.lnk"]
    started.clear()
    for bad in (r"C:\Windows\System32\cmd.exe", r"\\server\share\evil.exe", "https://example.com/x.exe", "calc & del x",
                "unknownthing", "javascript:alert(1)", "file:", "..\\..\\x", "a" * 200):
        assert pw.open_app(bad) is False, bad
    assert started == []


def test_everyday_names_open_windows_apps(monkeypatch):
    tried = []
    monkeypatch.setattr(pw, "open_app", lambda target, is_path=False: tried.append((target, is_path)) or target in ("chrome", "ms-settings:", r"C:\m\Affinity.lnk"))
    monkeypatch.setattr(tools_apps, "plat", pw)
    monkeypatch.setattr(tools_apps, "_SCANNED_APPS", {"affinity photo 2": r"C:\m\Affinity.lnk"})
    assert tools.open_application("Chrome") == "Opened Chrome ✓" and tried == [("google chrome", False), ("chrome", False)]
    assert tools.open_application("Settings") == "Opened Settings ✓"
    assert tools.open_application("affinity") == "Opened affinity photo 2 ✓" and tried[-1] == (r"C:\m\Affinity.lnk", True)


# ── what the tools ask of Windows ──────────────────────────────────
@pytest.fixture
def win_tools(monkeypatch):
    """The tools talk to the Windows layer (with its system calls replaced by a record of what was asked)."""
    rec = types.SimpleNamespace(volume=40, muted=None, did=[])
    for mod in (tools_system, tools_files, tools_apps): monkeypatch.setattr(mod, "plat", pw)
    monkeypatch.setattr(pw, "volume_get", lambda: rec.volume)
    monkeypatch.setattr(pw, "volume_set", lambda n: rec.__setattr__("volume", max(0, min(100, int(n)))) or rec.volume)
    monkeypatch.setattr(pw, "volume_mute", lambda m: rec.__setattr__("muted", m) or True)
    monkeypatch.setattr(pw, "power_off", lambda restart=False: rec.did.append("restart" if restart else "shutdown"))
    monkeypatch.setattr(pw, "sleep_now", lambda hibernate=False: rec.did.append("hibernate" if hibernate else "sleep"))
    monkeypatch.setattr(pw, "lock_screen", lambda: rec.did.append("lock") or "Locked ✓")
    monkeypatch.setattr(pw, "empty_trash", lambda: (True, ""))
    monkeypatch.setattr(tools_system, "_pending_power", None)
    return rec


def test_volume_power_and_recycle_bin_through_the_tools(win_tools, monkeypatch):
    assert tools.control_volume("get") == "Volume: 40%" and tools.control_volume("set", 250) == "Volume set to 100% ✓"
    assert tools.control_volume("down", 30) == "Volume: 70% ✓" and tools.control_volume("mute") == "Muted ✓" and win_tools.muted is True
    assert tools.control_system("sleep") == "Sleep mode ✓" and tools.control_system("hibernate") == "Sleep mode ✓"
    assert tools.control_system("lock") == "Locked ✓" and win_tools.did == ["sleep", "hibernate", "lock"]
    assert tools.empty_recycle_bin() == "Recycle Bin emptied ✓"

    class Timer:                                        # the ten seconds in which "cancel" still works
        made = []
        def __init__(self, secs, fn): self.secs, self.fn = secs, fn; Timer.made.append(self)
        def start(self): pass
        def cancel(self): pass
        def is_alive(self): return True
        daemon = False
    monkeypatch.setattr(tools_system.threading, "Timer", Timer)
    assert tools.control_system("restart").startswith("Restarting in 10 s") and win_tools.did[-1] == "lock"       # nothing yet
    Timer.made[0].fn(); assert win_tools.did[-1] == "restart" and Timer.made[0].secs == 10


def test_recycle_bin_answers(libs):
    libs["shell32"] = FakeLib(SHEmptyRecycleBinW=0);           assert pw.empty_trash() == (True, "")
    libs["shell32"] = FakeLib(SHEmptyRecycleBinW=-2147418113); assert pw.empty_trash() == (True, "")       # it was already empty
    libs["shell32"] = FakeLib(SHEmptyRecycleBinW=-2147024891)
    ok, why = pw.empty_trash(); assert ok is False and "0x80070005" in why


def test_nothing_is_deleted_where_there_is_no_recycle_bin(libs, tmp_path):
    f = tmp_path / "keep.txt"; f.write_text("precious")
    libs["kernel32"] = FakeLib(GetDriveTypeW=2)                           # a USB stick
    with pytest.raises(OSError, match="no Recycle Bin"): pw.move_to_trash(str(f))
    assert f.read_text() == "precious" and not any(name == "SHFileOperationW" for name, _ in libs.get("shell32", FakeLib()).calls)


def test_media_keys_only_when_spotify_runs(monkeypatch):
    sent = []
    monkeypatch.setattr(pw, "_send_keys", sent.append); monkeypatch.setattr(pw, "_spotify_pids", lambda: set())
    assert pw.media_control("next") == ("not running", "") and sent == []
    monkeypatch.setattr(pw, "_spotify_pids", lambda: {321})
    assert pw.media_control("play_pause") == ("ok", "") and sent == [[(0xB3, True), (0xB3, False)]]


def test_spotify_title_is_the_song_only_while_it_plays(monkeypatch):
    titles = {1: "Default IME", 2: "Spotify Premium", 3: "GDI+ Window"}
    monkeypatch.setattr(pw, "_spotify_pids", lambda: {321}); monkeypatch.setattr(pw, "_windows_of", lambda pid, hidden=False: list(titles))
    monkeypatch.setattr(pw, "_window_title", lambda hwnd: titles[hwnd])
    assert pw.spotify_now_playing() == ""
    titles[2] = "Daft Punk - Get Lucky"
    assert pw.spotify_now_playing() == "Daft Punk - Get Lucky"


def test_wifi_name_is_read_from_netsh(monkeypatch):
    out = ("\r\nThere is 1 interface on the system:\r\n\r\n    Name                   : Wi-Fi\r\n    State                  : connected\r\n"
           "    SSID                   : Home Wi-Fi: 5G\r\n    BSSID                  : aa:bb:cc:dd:ee:ff\r\n")
    monkeypatch.setattr(pw.subprocess, "run", lambda cmd, **k: types.SimpleNamespace(stdout=out.encode(), returncode=0))
    assert pw._wifi_name() == "Home Wi-Fi: 5G"
    monkeypatch.setattr(pw.subprocess, "run", lambda cmd, **k: (_ for _ in ()).throw(OSError("no wlan service")))
    assert pw._wifi_name() == ""


def test_the_store_signpost_is_not_taken_for_python(monkeypatch, tmp_path):
    real = tmp_path / "python.exe"; real.write_text("")
    monkeypatch.setattr(pw.shutil, "which", lambda name: {"py": None, "python": r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\python.exe",
                                                           "python3": str(real)}.get(name))
    def run(cmd, **k):
        if "WindowsApps" in cmd[0]: return types.SimpleNamespace(returncode=9009, stdout="Python was not found; run without arguments to install …")
        return types.SimpleNamespace(returncode=0, stdout=str(real) + "\n")
    monkeypatch.setattr(pw.subprocess, "run", run)
    assert pw.find_python() == str(real)
    monkeypatch.setattr(pw.shutil, "which", lambda name: None)
    assert pw.find_python() is None


# ── the rest of the app on Windows ─────────────────────────────────
def test_data_and_logs_go_to_the_windows_folders(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "win32"); monkeypatch.delenv("NOVA_DATA_DIR")
    monkeypatch.setenv("APPDATA", r"C:\Users\me\AppData\Roaming"); monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    assert paths._data_dir() == os.path.join(r"C:\Users\me\AppData\Roaming", "NOVA")
    assert paths._log_dir() == os.path.join(r"C:\Users\me\AppData\Local", "NOVA", "Logs")


def test_the_pipe_has_a_short_name_and_links_come_on_the_command_line(monkeypatch):
    monkeypatch.setattr(ipc, "IS_WINDOWS", True)
    name = ipc.server_name()
    assert name.startswith("nova-") and len(name) == 15 and "\\" not in name and "/" not in name
    assert ipc.url_arg(["NOVA.exe", "nova://ask?text=hello%20there"]) == "hello there"
    assert ipc.url_arg(["NOVA.exe", "--hidden"]) is None and ipc.url_arg(["NOVA.exe", "nova://delete?text=x"]) is None


def test_update_feed_gives_windows_its_own_download():
    feed = {"version": "9.9.9", "url": "https://x/NOVA.dmg", "sha256": "a" * 64, "notes": "new",
            "windows": {"url": "https://x/NOVA-setup.exe", "sha256": "b" * 64}}
    assert updater.for_this_system(feed, "darwin") == feed
    win = updater.for_this_system(feed, "win32")
    assert win["url"] == "https://x/NOVA-setup.exe" and win["sha256"] == "b" * 64 and win["notes"] == "new"
    mac_only_feed = {"version": "9.9.9", "url": "https://x/NOVA.dmg", "sha256": "a" * 64}
    assert not updater.is_newer(updater.for_this_system(mac_only_feed, "win32")["version"])        # a Mac disk image is never offered


def test_every_text_is_shown_in_windows_words():
    import re
    mac_words = re.compile(r"\bMac\b|Mac-а|macOS|Keychain|keychain|Finder|menu bar|лентата с менюта|⌘|⌃|Launch at login|Applications")
    only_on_a_mac = ("Accessibility", "Screen Recording")              # permission texts Windows never shows
    try:
        for lang in ("en", "bg"):
            i18n.set_language(lang)
            for key in i18n.BG:
                if any(w in key for w in only_on_a_mac): continue
                shown = i18n.local(i18n.BG[key], True) if key == "PRIVACY" else i18n.tr(key, windows=True)
                assert not mac_words.search(shown), (lang, key, shown)
        i18n.set_language("bg")
        assert i18n.tr("Launch at login", windows=True) == "Стартирай с Windows" and i18n.tr("Trash", windows=True) == "Кошче"
        assert i18n.tr("Showed in Finder", windows=True) == "Показано в Explorer"
        i18n.set_language("en")
        assert i18n.tr("Launch at login", windows=True) == "Start with Windows" and i18n.tr("Moved to Trash", windows=True) == "Moved to Recycle Bin"
        assert i18n.tr("Launch at login", windows=False) == "Launch at login" and i18n.local("this Mac", False) == "this Mac"
        for key, (en, bg) in i18n._WINDOWS_TEXTS.items():
            assert key in i18n.BG and key.count("{}") == en.count("{}") == bg.count("{}") or not en
    finally:
        i18n.set_language("en")


def test_whats_new_leaves_out_what_windows_does_not_have(monkeypatch):
    monkeypatch.setattr(i18n, "ON_WINDOWS", True)
    text = whatsnew.text("6.1")
    assert "calendar" not in text and "Apple Shortcuts" not in text and "Ctrl+Alt+Shift+Space" in text and "this PC" in text
    monkeypatch.setattr(i18n, "ON_WINDOWS", False)
    assert "calendar" in whatsnew.text("6.1") and "⌃⇧Space" in whatsnew.text("6.1")


def test_part_of_the_screen_uses_novas_own_picker(win, monkeypatch, tmp_path):
    import region_select, win_chat, platform_utils as plat
    from PIL import Image
    made = []

    class FakeOverlay:
        def __init__(self, path):
            self.path = path; self.done = types.SimpleNamespace(connect=lambda fn: setattr(self, "report", fn)); made.append(self)
        def start(self): self.started = True
    monkeypatch.setattr(plat, "OWN_REGION_PICKER", True); monkeypatch.setattr(region_select, "RegionOverlay", FakeOverlay)
    monkeypatch.setattr(plat, "capture_region", lambda path: pytest.fail("the macOS selector is not used here"))
    monkeypatch.setattr(plat, "screen_capture_allowed", lambda request=False: True)
    seen = []
    monkeypatch.setattr(win, "_start_vision", lambda q, image_path=None, image=None: seen.append((q, image.size)))
    monkeypatch.setattr(win_chat, "confirm_image_upload", lambda *a: True)
    win.show(); win.input_field.setText("what does this chart show?")
    win._take_region_vision()
    for _ in range(60):
        win._pump(30)
        if made: break
    assert made and made[0].started and not win.isVisible()               # NOVA is out of the way while you select
    Image.new("RGB", (40, 30), "red").save(made[0].path)                  # the user dragged a rectangle
    made[0].report(made[0].path); win._pump(100)
    assert seen == [("what does this chart show?", (40, 30))] and win.isVisible() and not os.path.exists(made[0].path)


# ══ only on Windows: the real system ═══════════════════════════════
@windows_only
def test_this_is_the_layer_in_use():
    import platform_utils as plat
    assert plat is pw and plat.IS_WINDOWS and not plat.IS_MAC


@windows_only
def test_sign_in_entry_is_written_read_and_removed():
    assert pw._RUN_KEY.startswith(r"Software\NOVA-tests")                 # the tests never touch the real entry
    assert pw.set_autostart(False, "") is True and pw.autostart_enabled() is False
    assert pw.set_autostart(True, r"C:\NOVA\main.py", hidden=True) is True
    assert pw.autostart_enabled() is True and pw.autostart_hidden() is True and "main.py" in pw._run_command()
    assert pw.set_autostart(True, r"C:\NOVA\main.py", hidden=False) is True and pw.autostart_hidden() is False
    assert pw.set_autostart(False, "") is True and pw.autostart_enabled() is False and pw.set_autostart(False, "") is True


@windows_only
def test_nova_links_are_registered_for_this_user():
    import winreg
    assert pw._CLASSES_KEY.startswith(r"Software\NOVA-tests")
    assert pw.register_url_scheme(r'"C:\Apps\NOVA\NOVA.exe" "%1"') is True
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, pw._CLASSES_KEY + r"\nova") as key:
        assert winreg.QueryValueEx(key, "URL Protocol")[0] == ""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, pw._CLASSES_KEY + r"\nova\shell\open\command") as key:
        assert winreg.QueryValueEx(key, "")[0] == r'"C:\Apps\NOVA\NOVA.exe" "%1"'


@windows_only
def test_clipboard_keeps_cyrillic_and_can_be_put_back():
    pw.set_clipboard_text("Здравей — clipboard ✓")
    assert pw.get_clipboard_text() == "Здравей — clipboard ✓"
    saved = pw._clipboard_snapshot()
    assert saved and any(fmt == 13 for fmt, _data in saved)                # 13 = text
    pw.set_clipboard_text("something else")
    pw._clipboard_restore(saved)
    assert pw.get_clipboard_text() == "Здравей — clipboard ✓"


@windows_only
def test_delete_really_goes_to_the_recycle_bin(tmp_path):
    f = tmp_path / "nova test file.txt"; f.write_text("precious")
    d = tmp_path / "nova test folder"; d.mkdir(); (d / "inside.txt").write_text("x")
    pw.move_to_trash(str(f)); pw.move_to_trash(str(d))
    assert not f.exists() and not d.exists()
    with pytest.raises(OSError): pw.move_to_trash(str(tmp_path / "never existed.txt"))


@windows_only
def test_file_tools_on_a_real_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(tools_files, "_PROTECTED_PATHS", pw.protected_paths(str(tmp_path)))
    f = tmp_path / "a.txt"; f.write_text("hello")
    out = tools.manage_files("delete", str(f))
    assert out == f"Moved to Recycle Bin: {f} ✓" and not f.exists()
    assert "protected" in tools.manage_files("delete", str(tmp_path))                 # the "home" folder itself
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    assert os.path.normcase(os.path.realpath(system_root)) in pw.protected_paths(os.path.expanduser("~"))
    assert "protected" in tools.manage_files("delete", system_root.upper())            # whatever the spelling


@windows_only
def test_shell_and_python_tools_speak_utf8():
    assert "здравей" in tools.run_shell_command("echo здравей")
    assert tools.execute_python_code("print('Здравей', 6 * 7)").strip() == "Здравей 42"
    exe = pw.find_python()
    assert exe and os.path.isfile(exe)


@windows_only
def test_questions_about_the_system_get_answers():
    assert isinstance(pw.frontmost_pid(), int) and isinstance(pw.nova_is_frontmost(), bool) and isinstance(pw.frontmost_other_app(), str)
    assert pw.microphone_status() in ("granted", "denied", None) and pw.accessibility_trusted() and pw.screen_capture_allowed()
    assert isinstance(pw.network_info(), str) and pw.network_info() and isinstance(pw._wifi_name(), str)
    assert isinstance(pw.spotify_now_playing(), str) and os.path.isdir(pw.stats_disk())
    assert "CPU" in tools.get_system_stats() and tools.get_battery() and "PID" in tools.list_processes("python")
    volume = pw.volume_get()                                             # a build machine may have no loudspeaker at all
    assert volume is None or 0 <= volume <= 100
    assert "Volume" in tools.control_volume("get") or "no software volume" in tools.control_volume("get")


@windows_only
def test_installed_apps_are_found():
    found = pw.scan_apps()
    assert isinstance(found, dict) and all(isinstance(k, str) and k == k.lower() for k in found)
    assert pw._is_program("notepad") or pw._is_program("cmd")
    assert pw.open_app(r"C:\Windows\System32\cmd.exe") is False           # a path is never accepted as an app name


@windows_only
def test_the_system_voice_writes_a_sound_file(tmp_path):
    out = tmp_path / "voice.wav"
    assert pw.synth_native("NOVA can speak on Windows.", str(out)) is True
    with wave.open(str(out), "rb") as w: assert w.getnframes() > 4000
    assert pw.audio_to_wav(str(out), str(tmp_path / "ref.wav"), 16000) is True


@windows_only
def test_hotkey_listener_starts(monkeypatch):
    monkeypatch.setattr(pw, "_hotkeys", [])
    pressed = []
    ok = pw.start_global_hotkey(lambda: pressed.append(1))
    assert isinstance(ok, bool) and pw._hotkey_thread_id != 0             # False only if another program owns the shortcut
    assert pw.hotkey_taken(pw._HOTKEY_KEYCODE, pw._HOTKEY_MODS) is (not ok)
    pw.remove_global_hotkey(pw._hotkeys[0][2]) if pw._hotkeys else None


@windows_only
def test_only_what_windows_can_do_is_offered_to_the_ai():
    import schemas, prompts
    names = {s["function"]["name"] for s in schemas.TOOLS_SCHEMA}
    assert not names & {"get_calendar_events", "draft_email", "read_browser_tab", "run_shortcut", "list_apple_reminders"}
    assert not set(schemas.GROUPS) & {"calendar", "mail", "browser", "shortcuts"} and "files" in schemas.GROUPS
    assert {"manage_files", "control_volume", "open_application", "search_documents"} <= names
    text = prompts._build_prompt("hello")
    assert "assistant on Windows" in text and "Windows commands" in text and "osascript" not in text and "calendar" not in text
    tools_offered, _groups = schemas.select_tools("what is on my calendar tomorrow?")
    assert "get_calendar_events" not in {t["function"]["name"] for t in tools_offered}


@windows_only
def test_text_recognition_answers_or_explains(tmp_path):
    """A build machine may have no recognition language installed: then the reason must be said plainly."""
    import docs, docs_windows
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 200), "white")
    try: font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 64)
    except OSError: font = ImageFont.load_default()
    ImageDraw.Draw(img).text((30, 60), "Invoice 2026 total", fill="black", font=font)
    f = tmp_path / "scan.png"; img.save(f)
    try:
        text = docs_windows.image_text(str(f))
    except docs.DocError as e:
        assert "text-recognition language" in str(e) or "No text was found" in str(e), str(e)
    else:
        assert "Invoice" in text or "2026" in text


def test_quit_closes_a_programs_windows_as_its_close_button_does(monkeypatch):
    import psutil
    procs = [types.SimpleNamespace(info={"pid": 10, "name": "notepad.exe"}),
             types.SimpleNamespace(info={"pid": 11, "name": "notepad.exe"}),          # a helper without a window
             types.SimpleNamespace(info={"pid": 12, "name": "chrome.exe"})]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: procs)
    monkeypatch.setattr(pw, "_windows_of", lambda pid, hidden=False: {10: [1001, 1002], 12: [1201]}.get(pid, []))
    posted = []
    monkeypatch.setattr(pw, "_win", lambda name: types.SimpleNamespace(PostMessageW=lambda *a: posted.append(a)))
    assert pw.quit_app("Notepad") == ["notepad"]
    assert posted == [(1001, 0x0010, 0, 0), (1002, 0x0010, 0, 0)]                     # WM_CLOSE to each window
    assert pw.quit_app("Paint") == [] and pw.QUIT_HOW == "as with its close button"


def test_a_github_release_offers_windows_its_setup_program():
    release = {"tag_name": "v6.7.0", "body": "Notes.", "assets": [
        {"name": "NOVA-6.7.0.dmg", "browser_download_url": "https://x/NOVA-6.7.0.dmg", "digest": "sha256:" + "a" * 64},
        {"name": "NOVA-6.7.0-setup.exe", "browser_download_url": "https://x/NOVA-6.7.0-setup.exe", "digest": "sha256:" + "b" * 64}]}
    win = updater.from_github_release(release, system="win32")
    assert win["version"] == "6.7.0" and win["url"].endswith("-setup.exe") and win["sha256"] == "b" * 64
    assert updater.from_github_release(release, machine="arm64")["url"].endswith(".dmg")          # the Mac: its image
    only_mac = dict(release, assets=release["assets"][:1])
    assert updater.from_github_release(only_mac, system="win32")["version"] == "0"              # never a .dmg on Windows

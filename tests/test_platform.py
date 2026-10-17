"""platform_utils: the pure helpers and the launch-at-login file (written to a temp folder, never the real one)."""
import plistlib, sys
import pytest
import platform_utils as plat

mac_only = pytest.mark.skipif(not plat.IS_MAC, reason="macOS only")


def test_labels_and_quoting():
    assert plat.shortcut_label("N") == "⌘N" and plat.HOTKEY_LABEL == "⌘⇧Space" and plat.KEYSTORE_NAME == "macOS Keychain"
    assert plat.as_quote('say "hi"\\ now\nplease') == 'say \\"hi\\"\\\\ now please'      # safe inside an AppleScript string


def test_the_prompt_is_written_for_macos():
    import prompts
    text = prompts._build_prompt("hello")
    assert "assistant on macOS" in text and "macOS commands" in text and "Windows 11" not in text and "PowerShell" not in text


@mac_only
def test_autostart_writes_and_removes_a_valid_launch_agent(monkeypatch, tmp_path):
    agent = tmp_path / "LaunchAgents" / "com.nova.assistant.plist"
    monkeypatch.setattr(plat, "_LAUNCH_AGENT", str(agent))
    assert plat.autostart_enabled() is False
    assert plat.set_autostart(True, "/Users/me/nova/main.py") is True and plat.autostart_enabled() is True
    data = plistlib.loads(agent.read_bytes())
    assert data["Label"] == "com.nova.assistant" and data["RunAtLoad"] is True
    assert data["ProgramArguments"] == [sys.executable, "/Users/me/nova/main.py", "--hidden"] and data["WorkingDirectory"] == "/Users/me/nova"
    assert plat.autostart_hidden() is True                                            # at login NOVA waits in the menu bar
    plat.set_autostart(True, "/Users/me/nova/main.py", hidden=False)
    assert plistlib.loads(agent.read_bytes())["ProgramArguments"] == [sys.executable, "/Users/me/nova/main.py"] and plat.autostart_hidden() is False
    plat.set_autostart(True, "/Users/me/nova/main.py")
    assert "/opt/homebrew/bin" in data["EnvironmentVariables"]["PATH"]
    assert plat.set_autostart(False, "/Users/me/nova/main.py") is True and not agent.exists()
    assert plat.set_autostart(False, "x") is True                                       # removing twice is fine


@mac_only
def test_autostart_reports_failure_instead_of_raising(monkeypatch, tmp_path):
    blocker = tmp_path / "file"; blocker.write_text("x")
    monkeypatch.setattr(plat, "_LAUNCH_AGENT", str(blocker / "sub" / "a.plist"))        # a file where a folder is needed
    assert plat.set_autostart(True, "/x/main.py") is False


@mac_only
def test_permission_probes_answer_without_prompting():
    assert isinstance(plat.accessibility_trusted(), bool)
    assert isinstance(plat.screen_capture_allowed(), bool)
    assert plat.microphone_status() in ("granted", "denied", "undetermined", "restricted", "unknown", None) or isinstance(plat.microphone_status(), str)
    name = plat.frontmost_other_app()
    assert name is None or isinstance(name, str)


# ── everything below runs against stand-ins: no sound, no notification, no real clipboard ─────────────────
import subprocess, types


@pytest.fixture
def shell(monkeypatch):
    """Records the programs that would have been started and plays back prepared answers."""
    rec = types.SimpleNamespace(started=[], ran=[], answers={}, inputs=[])
    class Proc:
        def __init__(self, cmd, **k): self.cmd = cmd; self.stopped = False; self.alive = True; rec.started.append(self)
        def poll(self): return None if self.alive else 0
        def terminate(self): self.stopped = True; self.alive = False
        def wait(self): self.alive = False
        def communicate(self, data=None): rec.inputs.append(data); self.alive = False
    def run(cmd, **k):
        rec.ran.append(cmd); rec.inputs.append(k.get("input"))
        out = rec.answers.get(cmd[0], "")
        if isinstance(out, Exception): raise out
        code = 1 if out == "FAIL" else 0
        return types.SimpleNamespace(returncode=code, stdout=out.encode() if not k.get("text") and isinstance(out, str) else out,
                                     stderr="it did not work" if code else "")
    monkeypatch.setattr(plat.subprocess, "Popen", Proc); monkeypatch.setattr(plat.subprocess, "run", run)
    monkeypatch.setattr(plat, "_audio_proc", None)
    return rec


@mac_only
def test_applescript_results_and_failures(shell):
    shell.answers["osascript"] = "  42 \n"
    assert plat.run_osascript("output volume of (get volume settings)") == (0, "42")
    assert shell.ran[-1] == ["osascript", "-e", "output volume of (get volume settings)"]
    shell.answers["osascript"] = "FAIL"
    assert plat.run_osascript("nonsense") == (1, "it did not work")
    shell.answers["osascript"] = subprocess.TimeoutExpired("osascript", 10)
    assert plat.run_osascript("slow") == (1, "timed out")
    shell.answers["osascript"] = OSError("no such program")
    assert plat.run_osascript("x") == (1, "no such program")


@mac_only
def test_notifications_quote_their_text(shell, monkeypatch):
    monkeypatch.setattr(plat.shutil, "which", lambda name: None)
    plat.notify('Reminder "tea"', 'It is "ready"\nnow')
    assert shell.started[-1].cmd == ["osascript", "-e", 'display notification "It is \\"ready\\" now" with title "Reminder \\"tea\\""']
    monkeypatch.setattr(plat.shutil, "which", lambda name: "/opt/homebrew/bin/terminal-notifier")
    plat.notify("T" * 300, "body")
    assert shell.started[-1].cmd == ["/opt/homebrew/bin/terminal-notifier", "-title", "T" * 100, "-message", "body"]
    monkeypatch.setattr(plat.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("blocked")))
    plat.notify("still", "no crash")                                   # a failed notification never breaks the caller


@mac_only
def test_playing_speaking_and_stopping_sound(shell, monkeypatch, tmp_path):
    plat.play_audio_file("/tmp/reply.mp3")
    assert shell.started[-1].cmd == ["afplay", "/tmp/reply.mp3"]
    plat.stop_audio(); assert shell.started[-1].stopped is False       # it had already finished: nothing to stop
    shell.started[-1].alive = True
    plat.stop_audio(); assert shell.started[-1].stopped is True
    plat.speak_native("- Hello")
    assert shell.started[-1].cmd == ["say"] and shell.inputs[-1] == b"- Hello"      # via stdin: a leading "-" is not an option
    out = tmp_path / "voice.aiff"
    def say_to_file(cmd, **k):
        out.write_bytes(b"x" * 9000); return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(plat.subprocess, "run", say_to_file)
    assert plat.synth_native("Hello", str(out)) is True
    out.write_bytes(b"tiny")
    monkeypatch.setattr(plat.subprocess, "run", lambda cmd, **k: types.SimpleNamespace(returncode=0))
    assert plat.synth_native("Hello", str(out)) is False               # an empty sound file does not count
    monkeypatch.setattr(plat.subprocess, "run", lambda cmd, **k: (_ for _ in ()).throw(OSError("no say")))
    assert plat.synth_native("Hello", str(out)) is False


@mac_only
def test_clipboard_is_read_and_written_as_utf8(shell):
    shell.answers["pbpaste"] = "  Здравей, свят  \n"
    assert plat.get_clipboard_text() == "Здравей, свят" and shell.ran[-1] == ["pbpaste"]
    plat.set_clipboard_text("Чай ☕")
    assert shell.ran[-1] == ["pbcopy"] and shell.inputs[-1] == "Чай ☕".encode()
    assert plat._utf8_env()["LANG"] == "en_US.UTF-8"


@mac_only
def test_spotify_track_and_network_summary(monkeypatch):
    monkeypatch.setattr(plat, "run_osascript", lambda script, timeout=10: (0, "Daft Punk - Get Lucky"))
    assert plat.spotify_now_playing() == "Daft Punk - Get Lucky"
    monkeypatch.setattr(plat, "run_osascript", lambda script, timeout=10: (1, "error"))
    assert plat.spotify_now_playing() == ""
    import psutil, socket
    monkeypatch.setattr(plat, "_mac_wifi_name", lambda: "Home Wi-Fi")
    up, down = types.SimpleNamespace(isup=True), types.SimpleNamespace(isup=False)
    addr = lambda ip: types.SimpleNamespace(family=socket.AF_INET, address=ip)
    monkeypatch.setattr(psutil, "net_if_stats", lambda: {"en0": up, "lo0": up, "utun3": up, "en5": down})
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {"en0": [addr("192.168.1.20")], "lo0": [addr("127.0.0.1")],
                                                         "utun3": [addr("10.8.0.2")], "en5": [addr("169.254.1.1")]})
    assert plat.network_info() == "Wi-Fi: Home Wi-Fi\nen0: 192.168.1.20"            # loopback, VPN tunnels and dead links are left out
    monkeypatch.setattr(plat, "_mac_wifi_name", lambda: "")
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {})
    assert plat.network_info() == "No network info available."


@mac_only
def test_wifi_name_from_the_system_tools(shell):
    ports = "Hardware Port: Ethernet\nDevice: en5\n\nHardware Port: Wi-Fi\nDevice: en0\n"
    def answer(cmd, **k):
        shell.ran.append(cmd)
        if cmd[1] == "-listallhardwareports": out = ports
        elif cmd[1] == "-getairportnetwork": out = shell.answers.get("airport", "")
        else: out = shell.answers.get("profiler", "{}")
        return types.SimpleNamespace(stdout=out, returncode=0)
    plat.subprocess.run = answer                                       # (the fixture restores subprocess.run afterwards)
    shell.answers["airport"] = "Current Wi-Fi Network: Home Wi-Fi\n"
    assert plat._mac_wifi_name() == "Home Wi-Fi" and shell.ran[-1] == ["networksetup", "-getairportnetwork", "en0"]
    shell.answers["airport"] = "You are not associated with an AirPort network.\n"          # newer macOS: ask the profiler
    shell.answers["profiler"] = '{"SPAirPortDataType": [{"spairport_airport_interfaces": [{"spairport_current_network_information": {"_name": "Cafe Net"}}]}]}'
    assert plat._mac_wifi_name() == "Cafe Net"
    shell.answers["profiler"] = '{"SPAirPortDataType": [{"spairport_airport_interfaces": [{"spairport_current_network_information": {"_name": "<redacted>"}}]}]}'
    assert plat._mac_wifi_name() == ""                                 # macOS hides the name without Location permission
    shell.answers["profiler"] = "not json"
    assert plat._mac_wifi_name() == ""

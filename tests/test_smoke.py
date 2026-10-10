"""Starts the real program in a child process (headless, temp profile, local provider) and quits it the
normal way. Catches import errors, startup crashes and unclean shutdowns that in-process tests cannot."""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(tmp_path, extra_env=None, args=()):
    (tmp_path / "config.json").write_text(json.dumps(
        {"onboarded": True, "consent": True, "schema": 2, "provider": "ollama", "keyless": True, "wake_word": False}))
    lockdir = tmp_path / "tmp"; lockdir.mkdir(exist_ok=True)      # own "one NOVA at a time" lock: never collides with your NOVA
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", NOVA_DATA_DIR=str(tmp_path), NOVA_NO_MIGRATE="1", TMPDIR=str(lockdir),
               **(extra_env or {}))
    env.pop("NOVA_STRICT_CONFIG", None)
    return subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), *args], env=env, capture_output=True, text=True, timeout=90)


def test_selftest_entry_point(tmp_path):
    r = _run(tmp_path, args=("--selftest",))
    assert r.returncode == 0 and "selftest ok" in r.stdout


def test_app_starts_and_quits_cleanly(tmp_path):
    r = _run(tmp_path, {"NOVA_QUIT_AFTER_MS": "2000"})
    assert r.returncode == 0, r.stderr[-800:]
    log = (tmp_path / "logs" / "nova.log").read_text()
    assert "starting" in log and "NOVA quit (code 0)" in log and "Traceback" not in log
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["provider"] == "ollama" and "groq_api_key" not in saved          # settings survived a full run


def test_second_instance_refuses_to_start(tmp_path):
    lockdir = tmp_path / "tmp"; lockdir.mkdir(exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", NOVA_DATA_DIR=str(tmp_path), NOVA_NO_MIGRATE="1", NOVA_QUIT_AFTER_MS="4000",
               TMPDIR=str(lockdir))
    env.pop("NOVA_STRICT_CONFIG", None)
    (tmp_path / "config.json").write_text(json.dumps({"onboarded": True, "consent": True, "schema": 2, "provider": "ollama", "keyless": True}))
    first = subprocess.Popen([sys.executable, os.path.join(ROOT, "main.py")], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        import time; time.sleep(2.0)
        second = subprocess.run([sys.executable, os.path.join(ROOT, "main.py")], env=env, capture_output=True, text=True, timeout=30)
        assert "already running" in second.stdout
    finally:
        first.wait(timeout=30)
    assert first.returncode == 0


# ── on the real display (opt-in: it briefly shows the NOVA window) ──
import pytest

real_display = pytest.mark.skipif(os.environ.get("NOVA_GUI_TESTS") != "1" or sys.platform != "darwin",
                                  reason="set NOVA_GUI_TESTS=1 to run the tests that open a real window")


def _run_visible(tmp_path, quit_ms="1800", program=None):
    (tmp_path / "config.json").write_text(json.dumps(
        {"onboarded": True, "consent": True, "schema": 2, "provider": "ollama", "keyless": True, "wake_word": False, "ax_prompted": True}))
    lockdir = tmp_path / "tmp"; lockdir.mkdir(exist_ok=True)          # own "one NOVA at a time" lock: works while your NOVA is open
    env = dict(os.environ, NOVA_DATA_DIR=str(tmp_path), NOVA_NO_MIGRATE="1", NOVA_QUIT_AFTER_MS=quit_ms, TMPDIR=str(lockdir))
    for k in ("QT_QPA_PLATFORM", "NOVA_STRICT_CONFIG"): env.pop(k, None)
    cmd = [program] if program else [sys.executable, os.path.join(ROOT, "main.py")]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)


@real_display
def test_quit_with_the_window_visible_does_not_crash(tmp_path):
    """On macOS, QApplication.quit() goes through NSApplication terminate:, which closes the windows; quitting again
    from inside closeEvent made AppKit call exit() and PySide crashed in its static destructors (exit code 139)."""
    r = _run_visible(tmp_path)
    assert r.returncode == 0, (r.returncode, r.stderr[-600:])
    log = (tmp_path / "logs" / "nova.log").read_text()
    assert "NOVA quit (code 0)" in log and "exit guard" not in log          # left through its own clean exit


@real_display
def test_packaged_app_quits_cleanly(tmp_path):
    app = os.path.join(ROOT, os.environ.get("NOVA_DIST", "dist"), "NOVA.app", "Contents", "MacOS", "NOVA")
    if not os.path.exists(app): pytest.skip("build the app first (packaging/build_mac.sh)")
    r = _run_visible(tmp_path, program=app)
    assert r.returncode == 0, (r.returncode, r.stderr[-600:])
    assert "NOVA quit (code 0)" in (tmp_path / "logs" / "nova.log").read_text()


def _system_quit(tmp_path, program=None):
    """Start NOVA on the real display, then ask it to quit the way the Dock's Quit / ⌘Q does (by process id)."""
    import time
    from AppKit import NSRunningApplication
    (tmp_path / "config.json").write_text(json.dumps(
        {"onboarded": True, "consent": True, "schema": 2, "provider": "ollama", "keyless": True, "wake_word": False, "ax_prompted": True}))
    lockdir = tmp_path / "tmp"; lockdir.mkdir(exist_ok=True)
    env = dict(os.environ, NOVA_DATA_DIR=str(tmp_path), NOVA_NO_MIGRATE="1", TMPDIR=str(lockdir))
    for k in ("QT_QPA_PLATFORM", "NOVA_STRICT_CONFIG", "NOVA_QUIT_AFTER_MS"): env.pop(k, None)
    cmd = [program] if program else [sys.executable, os.path.join(ROOT, "main.py")]
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        app = None
        for _ in range(60):                                    # wait until it is a running GUI app
            time.sleep(0.25)
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(p.pid)
            if app is not None and app.isFinishedLaunching(): break
        time.sleep(2.0)
        assert app is not None and app.terminate()             # the polite "please quit" request, to this process only
        return p.wait(timeout=30), (tmp_path / "logs" / "nova.log").read_text()
    finally:
        if p.poll() is None: p.kill()


@real_display
def test_system_quit_request_exits_cleanly(tmp_path):
    code, log = _system_quit(tmp_path)
    assert code == 0 and "NOVA quit (code 0)" in log and "exit guard" not in log


@real_display
def test_packaged_app_handles_system_quit(tmp_path):
    app = os.path.join(ROOT, os.environ.get("NOVA_DIST", "dist"), "NOVA.app", "Contents", "MacOS", "NOVA")
    if not os.path.exists(app): pytest.skip("build the app first (packaging/build_mac.sh)")
    code, log = _system_quit(tmp_path, app)
    assert code == 0 and "NOVA quit (code 0)" in log and "exit guard" not in log


def test_started_hidden_runs_without_showing_the_window(tmp_path):
    """`--hidden` (how the login item starts NOVA): it runs, stays out of sight, and quits cleanly."""
    r = _run(tmp_path, {"NOVA_QUIT_AFTER_MS": "2500", "NOVA_REPORT_VISIBLE": "1"}, args=("--hidden",))
    assert r.returncode == 0, r.stderr[-600:]
    log = (tmp_path / "logs" / "nova.log").read_text()
    assert "window visible at start: False" in log and "NOVA quit (code 0)" in log
    r = _run(tmp_path, {"NOVA_QUIT_AFTER_MS": "2000", "NOVA_REPORT_VISIBLE": "1"})
    assert "window visible at start: True" in (tmp_path / "logs" / "nova.log").read_text().split("NOVA quit")[-2]

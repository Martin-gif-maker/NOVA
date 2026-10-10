"""Requests handed to NOVA from outside: `--ask`, nova:// links, Apple Shortcuts."""
import json, os, subprocess, sys, time
import pytest
import ipc, tools, mac_apps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mac_only = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def test_links_and_command_line_are_parsed():
    assert ipc.text_from_url("nova://ask?text=hello%20there") == "hello there" and ipc.text_from_url("NOVA://ask?q=hi") == "hi"
    assert ipc.text_from_url("nova:ask?text=x") == "x" and ipc.text_from_url("nova://ask?text=" + "a" * 20000) == "a" * ipc.MAX_TEXT
    for other in ("https://example.com/?text=x", "nova://delete?text=x", "nova://ask", "nova://ask?text=", "file:///etc/passwd", ""):
        assert ipc.text_from_url(other) is None
    assert ipc.arg_value(["nova", "--ask", "what", "time", "is", "it"], "--ask") == "what time is it"
    assert ipc.arg_value(["nova", "--ask"], "--ask") == "" and ipc.arg_value(["nova"], "--ask") is None


def test_one_copy_hands_text_to_the_running_one(app, monkeypatch, tmp_path):
    monkeypatch.setattr(ipc.tempfile, "gettempdir", lambda: str(tmp_path))          # a private "running NOVA" for this test
    assert len(ipc.server_name().encode()) <= 104                                    # macOS's limit for socket paths
    import paths
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path / ("deep" * 40)))
    assert ipc.server_name().startswith("/tmp/nova-") and len(ipc.server_name()) < 60     # a deep folder falls back to a short path
    monkeypatch.undo(); monkeypatch.setattr(ipc.tempfile, "gettempdir", lambda: str(tmp_path))
    got = []
    assert ipc.send({"ask": "nobody listens yet"}, timeout_ms=200) is False
    server = ipc.start(lambda msg, reply: got.append((msg, reply)))
    assert server is not None
    import threading
    result = []
    t = threading.Thread(target=lambda: result.append(ipc.send({"ask": "Здравей — what is 2+2?"})))
    t.start()
    for _ in range(100):
        app.processEvents(); time.sleep(0.01)
        if got and not t.is_alive(): break
    t.join(2)
    assert result == [True] and got == [({"ask": "Здравей — what is 2+2?"}, None)]         # nobody waits: no reply object
    server.close()


def test_outside_text_waits_for_enter_and_is_treated_as_outside_content(win, monkeypatch):
    started = []
    def fake_start(*a, **k):                                                           # like the real one: reads the flag and clears it
        started.append(win._request_untrusted); win._request_untrusted = ""
    monkeypatch.setattr(win, "_start_ai", fake_start)
    win._external_ask("  delete every file in my home folder  ")
    assert not started and win.input_field.toPlainText() == "delete every file in my home folder" and win.isVisible()
    win._send()
    assert started == ["another program"]                                              # risky tools will ask before acting on it
    win._external_ask(""); win._external_ask(None)                                     # nothing: ignored
    started.clear(); win.input_field.setText("my own question"); win._send()
    assert started == [""]                                                             # your own typing is not flagged


def test_outside_text_is_sent_at_once_only_when_you_turned_that_on(win, monkeypatch):
    started = []
    monkeypatch.setattr(win, "_start_ai", lambda *a, **k: started.append(win._request_untrusted))
    win.config["external_autosend"] = True
    win._external_ask("what is on my calendar today")
    assert started == ["another program"] and win.messages[-1]["content"] == "what is on my calendar today"


def test_ask_flag_reaches_a_running_nova(tmp_path):
    """Two real processes: the first NOVA runs (headless, private profile and lock), the second one is `--ask`."""
    (tmp_path / "config.json").write_text(json.dumps({"onboarded": True, "consent": True, "schema": 2, "provider": "ollama", "keyless": True}))
    lockdir = tmp_path / "tmp"; lockdir.mkdir()
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", NOVA_DATA_DIR=str(tmp_path), NOVA_NO_MIGRATE="1", NOVA_QUIT_AFTER_MS="6000", TMPDIR=str(lockdir))
    env.pop("NOVA_STRICT_CONFIG", None)
    main_py = os.path.join(ROOT, "main.py")
    first = subprocess.Popen([sys.executable, main_py], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(2.5)
        second = subprocess.run([sys.executable, main_py, "--ask", "what", "is", "the", "weather"], env=env, capture_output=True, text=True, timeout=30)
        assert second.returncode == 0 and "Passed to the running NOVA" in second.stdout
    finally:
        first.wait(timeout=30)
    log = (tmp_path / "logs" / "nova.log").read_text()
    assert first.returncode == 0 and "request received from another program (19 characters)" in log


# ── `--ask … --wait`: the caller gets NOVA's answer back ───────────
def test_wait_and_timeout_are_read_from_the_command_line():
    assert ipc.ask_args(["nova", "--ask", "what", "time", "is", "it", "--wait"]) == ("what time is it", True, 600.0)
    assert ipc.ask_args(["nova", "--wait", "--timeout", "120", "--ask", "summarize this"]) == ("summarize this", True, 120.0)
    assert ipc.ask_args(["nova", "--ask", "what does --wait do"]) == ("what does --wait do", False, 600.0)   # inside the text: untouched
    assert ipc.ask_args(["nova", "--ask", "hi", "--timeout", "soon"]) == ("hi soon", False, 600.0)
    assert ipc.ask_args(["nova", "--ask", "hi", "--timeout", "1"])[2] == 5.0 and ipc.ask_args(["nova"]) == (None, False, 600.0)


@pytest.fixture
def listener(app, monkeypatch, tmp_path):
    """A private "running NOVA" socket; `ask(...)` calls it from another thread the way the second copy does."""
    import threading
    monkeypatch.setattr(ipc.tempfile, "gettempdir", lambda: str(tmp_path))
    got = []
    server = ipc.start(lambda msg, reply: got.append((msg, reply)))
    assert server is not None

    def ask(payload, until, secs=5):
        result = []
        t = threading.Thread(target=lambda: result.append(ipc.request(payload, secs)))
        t.start()
        for _ in range(600):
            app.processEvents(); time.sleep(0.01)
            if until(): break
        return t, result

    def finish(t):
        for _ in range(600):
            app.processEvents(); time.sleep(0.01)
            if not t.is_alive(): break
        t.join(2)
    yield got, ask, finish
    server.close()


def test_a_waiting_caller_gets_the_answer(listener):
    got, ask, finish = listener
    assert ipc.reachable() is True
    t, result = ask({"ask": "колко е 2+2?"}, lambda: bool(got))
    msg, reply = got[0]
    assert msg == {"ask": "колко е 2+2?"} and reply.alive()
    assert reply.send("Четири.\nFour.") is True and reply.send("again") is False and not reply.alive()      # answered exactly once
    finish(t)
    assert result == [("ok", "Четири.\nFour.")]


def test_a_waiting_caller_is_told_why_there_is_no_answer(listener):
    got, ask, finish = listener
    t, result = ask({"ask": "x"}, lambda: bool(got))
    got[0][1].fail("The request was cancelled in NOVA.")
    finish(t)
    assert result == [("error", "The request was cancelled in NOVA.")]


def test_a_caller_that_gives_up_is_noticed(listener, app):
    got, ask, finish = listener
    t, result = ask({"ask": "slow question"}, lambda: bool(got), secs=0.3)
    finish(t)
    assert result == [("timeout", "")]
    for _ in range(50): app.processEvents(); time.sleep(0.01)
    reply = got[0][1]
    assert not reply.alive() and reply.send("too late") is False


def test_no_nova_and_bad_messages(app, monkeypatch, tmp_path):
    import socket
    monkeypatch.setattr(ipc.tempfile, "gettempdir", lambda: str(tmp_path))
    assert ipc.reachable() is False and ipc.request({"ask": "anyone?"}, 1) == ("offline", "")
    got = []
    server = ipc.start(lambda msg, reply: got.append(msg))
    import threading
    def push(raw):
        s = socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect(ipc.server_name())
        try: s.sendall(raw)
        except OSError: pass                                      # the listener hangs up on an oversized message
        s.close()
    for raw in (b"this is not json\n", b'["a list"]\n', b'{"ask": "no line end, the old way"}', b"x" * (ipc.MAX_TEXT * 9)):
        t = threading.Thread(target=push, args=(raw,)); t.start()               # the listener lives on this thread: keep it turning
        for _ in range(400):
            app.processEvents(); time.sleep(0.01)
            if not t.is_alive(): break
        t.join(4)
        for _ in range(30): app.processEvents(); time.sleep(0.01)
    assert got == [{"ask": "no line end, the old way"}]
    server.close()
    assert ipc.reachable() is False                               # closing removes the socket


class Caller:
    """Stands in for the waiting copy of NOVA."""
    def __init__(self): self.got = None
    def alive(self): return self.got is None
    def send(self, text): self.got = ("reply", text); return True
    def fail(self, why): self.got = ("error", why); return True


def test_the_answer_goes_back_to_the_waiting_caller(win):
    from gui_support import FakeCompletions, _wait_idle
    win.config["external_autosend"] = True
    FakeCompletions.script = [["<think>easy</think>", "Four", "."]]
    caller = Caller()
    win._external_ask("what is 2+2", caller)
    _wait_idle(win)
    assert caller.got == ("reply", "Four.")                       # the model's hidden reasoning is not passed on
    win._external_finish("a second answer"); assert caller.got == ("reply", "Four.")
    FakeCompletions.script = [["mine"]]                           # your own next question answers nobody
    win.input_field.setText("my own question"); win._send(); _wait_idle(win)
    assert win._external_reply is None and not win._external_running


def test_by_default_the_caller_waits_until_you_press_enter(win):
    from gui_support import FakeCompletions, _wait_idle
    FakeCompletions.script = [["Sunny, 21°."]]
    caller = Caller()
    win._external_message({"ask": "weather in Sofia"}, caller)
    win._pump(100)
    assert caller.got is None and win.input_field.toPlainText() == "weather in Sofia" and not win._busy
    win._send(); _wait_idle(win)
    assert caller.got == ("reply", "Sunny, 21°.")


def test_the_caller_is_told_when_no_answer_will_come(win, monkeypatch):
    from gui_support import FakeCompletions
    win.config["external_autosend"] = True
    a = Caller(); win._external_ask("", a); assert a.got == ("error", "No text was given.")
    FakeCompletions.script = [["SLEEP", "SLEEP", "SLEEP", "never shown"]]                 # cancelled while it runs
    b = Caller(); win._external_ask("long job", b); win._pump(60); win._cancel_request()
    assert b.got == ("error", "The request was cancelled in NOVA.")
    c = Caller(); win._external_ask("= 6 * 7", c)                                         # the built-in calculator: no model reply
    assert c.got[0] == "error" and "its own window" in c.got[1]
    monkeypatch.setattr(win, "_start_ai", lambda *a, **k: None)
    d = Caller(); win._external_ask("first", d); e = Caller(); win._external_ask("second", e)
    assert d.got == ("error", "A newer request took its place.") and e.got is None
    win._external_running = True; win._on_error("Error code: 401 - invalid api key", "auth")
    assert e.got[0] == "error" and e.got[1]
    f = Caller(); win.client = None; win._external_ask("anything", f)
    assert f.got == ("error", "NOVA has no API key yet. Open NOVA and add one in Settings.")
    g = Caller(); win._external_reply = g; win._shutdown()
    assert g.got == ("error", "NOVA was closed before it answered.")


def _model_server(reply="The answer is 42."):
    """A stand-in model server (OpenAI-style, streaming) on a free local port. Returns (server, address, requests)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _json(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            self._json({"object": "list", "data": [{"id": "test-model", "object": "model"}]})
        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
            seen.append(req)
            if not req.get("stream"):
                return self._json({"id": "x", "object": "chat.completion", "model": "test-model", "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": reply}}]})
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for piece in (reply[:5], reply[5:]):
                chunk = {"id": "x", "object": "chat.completion.chunk", "model": "test-model",
                         "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n"); self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1", seen


def _profile(tmp_path, address, **extra):
    cfg = {"onboarded": True, "consent": True, "schema": 2, "provider": "ollama", "keyless": True, "ax_prompted": True,
           "base_url": address, "seen_version": "99.0.0", "external_autosend": True}
    cfg.update(extra)
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    lockdir = tmp_path / "tmp"; lockdir.mkdir()
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", NOVA_DATA_DIR=str(tmp_path), NOVA_NO_MIGRATE="1", TMPDIR=str(lockdir))
    env.pop("NOVA_STRICT_CONFIG", None)
    return env


def test_ask_and_wait_prints_the_answer_of_a_running_nova(tmp_path):
    """Two real processes and a stand-in model server: what a Shortcut's "Run Shell Script" would do."""
    server, address, seen = _model_server()
    env = dict(_profile(tmp_path, address), NOVA_QUIT_AFTER_MS="9000")
    main_py = os.path.join(ROOT, "main.py")
    first = subprocess.Popen([sys.executable, main_py], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(2.5)
        second = subprocess.run([sys.executable, main_py, "--ask", "what is six times seven", "--wait", "--timeout", "20"],
                                env=env, capture_output=True, text=True, timeout=40)
        assert (second.returncode, second.stdout, second.stderr) == (0, "The answer is 42.\n", "")      # the answer and nothing else
    finally:
        first.wait(timeout=30); server.shutdown()
    asked = [m["content"] for r in seen for m in r["messages"] if m["role"] == "user"]
    assert any("what is six times seven" in str(c) for c in asked) and first.returncode == 0


def test_ask_and_wait_starts_nova_when_it_is_not_running(tmp_path):
    server, address, seen = _model_server("Started and answered.")
    env = dict(_profile(tmp_path, address), NOVA_QUIT_AFTER_MS="12000")
    try:
        asked = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), "--wait", "--ask", "are", "you", "there"],
                               env=env, capture_output=True, text=True, timeout=60)
        assert (asked.returncode, asked.stdout) == (0, "Started and answered.\n")
    finally:
        log = tmp_path / "logs" / "nova.log"                       # the NOVA it started quits by itself (NOVA_QUIT_AFTER_MS)
        deadline = time.time() + 40
        while time.time() < deadline and not (log.exists() and "NOVA quit (code 0)" in log.read_text()):
            time.sleep(0.3)
        server.shutdown()
    text = log.read_text()
    assert "NOVA quit (code 0)" in text                           # the NOVA it started is gone again, cleanly
    assert "request received from another program (13 characters, waiting for the answer)" in text


def test_ask_and_wait_reports_what_went_wrong(tmp_path, monkeypatch):
    import io
    monkeypatch.setattr(ipc.tempfile, "gettempdir", lambda: str(tmp_path))
    out, err = io.StringIO(), io.StringIO()
    assert ipc.cli(["nova", "--ask", "--wait"], out, err) == ipc.EXIT_NO_ANSWER and "Usage" in err.getvalue()
    monkeypatch.setattr(ipc, "_start_nova", lambda: False)
    err = io.StringIO(); assert ipc.cli(["nova", "--ask", "hi", "--wait"], out, err) == ipc.EXIT_NO_NOVA
    assert err.getvalue() == "NOVA is not running and could not be started.\n"
    monkeypatch.setattr(ipc, "_start_nova", lambda: True)                      # "started", but it never listens
    err = io.StringIO(); assert ipc.cli(["nova", "--ask", "hi", "--wait"], out, err, start_secs=0.5) == ipc.EXIT_NO_NOVA
    assert err.getvalue() == "NOVA did not start in time.\n"
    monkeypatch.setattr(ipc, "reachable", lambda *a: True)
    for status, code, text in (("timeout", ipc.EXIT_TIMEOUT, "NOVA did not answer within 600 seconds.\n"),
                               ("error", ipc.EXIT_NO_ANSWER, "The request was cancelled in NOVA.\n"),
                               ("closed", ipc.EXIT_NO_NOVA, "NOVA closed before answering.\n")):
        monkeypatch.setattr(ipc, "request", lambda p, secs, s=status: (s, "The request was cancelled in NOVA." if s == "error" else ""))
        err = io.StringIO(); assert ipc.cli(["nova", "--ask", "hi", "--wait"], out, err) == code and err.getvalue() == text
    assert out.getvalue() == ""                                               # nothing but a real answer ever goes to stdout


# ── Apple Shortcuts as tools ───────────────────────────────────────
@pytest.fixture
def shortcuts(monkeypatch):
    calls = []
    class R:
        def __init__(self, out="", code=0, err=""): self.stdout = out; self.returncode = code; self.stderr = err
    state = {"names": "Morning Routine\nResize Image\nSend ETA\n", "fail": False}
    def fake_run(cmd, **k):
        calls.append(cmd)
        if cmd[1] == "list": return R(state["names"])
        if state["fail"]: return R("", 1, "The shortcut could not be run")
        out = cmd[cmd.index("--output-path") + 1]
        text = open(cmd[cmd.index("--input-path") + 1]).read() if "--input-path" in cmd else ""
        open(out, "w").write(("got: " + text) if text else "done")
        return R()
    monkeypatch.setattr(mac_apps.subprocess, "run", fake_run)
    monkeypatch.setattr(mac_apps, "shortcuts_available", lambda: True)
    return calls, state


@mac_only
def test_shortcuts_list_and_run(shortcuts, monkeypatch, tmp_path):
    import paths
    monkeypatch.setattr(paths, "ACTIVITY_FILE", str(tmp_path / "a.log"))
    calls, state = shortcuts
    assert tools.list_shortcuts() == "Shortcuts:\n• Morning Routine\n• Resize Image\n• Send ETA"
    out = mac_apps.run_shortcut("resize image", "photo.jpg")                    # the name is matched without regard to case
    assert "Shortcut “Resize Image” finished" in out and out.endswith("got: photo.jpg")
    run = calls[-1]
    assert run[:3] == ["/usr/bin/shortcuts", "run", "Resize Image"] and "--input-path" in run
    with pytest.raises(mac_apps.AppError, match="Did you mean: Send ETA"): mac_apps.run_shortcut("ETA")
    state["fail"] = True
    with pytest.raises(mac_apps.AppError, match="could not be run"): mac_apps.run_shortcut("Send ETA")


@mac_only
def test_running_a_shortcut_always_asks_and_can_be_allowed_per_shortcut(shortcuts, monkeypatch, tmp_path):
    import paths
    monkeypatch.setattr(paths, "ACTIVITY_FILE", str(tmp_path / "a.log"))
    tools.begin_request()
    asked = []
    monkeypatch.setattr(tools, "SETTINGS", {"always_allow": []})
    monkeypatch.setattr(tools, "CONFIRM_HOOK", lambda desc, key=None: (asked.append((desc, key)), False)[1])
    assert "declined" in tools.execute_tool("run_shortcut", {"name": "Send ETA", "text": "home"})
    assert asked == [("Run your shortcut “Send ETA” with this text:\nhome", "shortcut:Send ETA")]
    monkeypatch.setattr(tools, "SETTINGS", {"always_allow": ["shortcut:Send ETA"]})
    monkeypatch.setattr(tools, "CONFIRM_HOOK", lambda desc, key=None: pytest.fail("this shortcut was pre-approved"))
    assert "finished" in tools.execute_tool("run_shortcut", {"name": "Send ETA"})
    monkeypatch.setattr(tools, "CONFIRM_HOOK", lambda desc, key=None: False)
    assert "declined" in tools.execute_tool("run_shortcut", {"name": "Morning Routine"})      # allowed per shortcut, not for all
    assert tools.describe_allowance("shortcut:Send ETA") == "Running the shortcut “Send ETA”"

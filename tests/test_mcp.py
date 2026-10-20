"""MCP tool servers. NOVA's client is run against a real server built with the official `mcp` package (stdio and
HTTP) and against a hand-written one that misbehaves in the ways real servers do."""
import json, os, socket, subprocess, sys, time
import pytest
import mcp_client as mc
import tools, paths

HERE = os.path.dirname(os.path.abspath(__file__))
REAL = os.path.join(HERE, "mcp_real_server.py")
FAKE = os.path.join(HERE, "mcp_fake_server.py")
have_sdk = pytest.mark.skipif(__import__("importlib").util.find_spec("mcp") is None, reason="needs the official mcp package (dev dependency)")


def fake(mode, *extra):
    return mc.Server("fake", {"command": sys.executable, "args": [FAKE, mode, *extra]})


@pytest.fixture
def ledger_file(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "OUTBOUND_FILE", str(tmp_path / "out.log"))
    monkeypatch.setattr(paths, "ACTIVITY_FILE", str(tmp_path / "act.log"))


# ── against the official implementation ────────────────────────────
@have_sdk
def test_stdio_handshake_tools_calls_and_shutdown():
    s = mc.Server("real", {"command": sys.executable, "args": [REAL]})
    s.connect()
    try:
        assert s.status == "ready" and s.info.get("name") == "nova-test-server"
        by_name = {t["name"]: t for t in s.tools}
        assert set(by_name) == {"add", "shout", "explode"} and by_name["add"]["description"] == "Add two numbers."
        assert sorted(by_name["add"]["schema"]["properties"]) == ["a", "b"] and by_name["add"]["schema"]["type"] == "object"
        assert s.call("add", {"a": 2, "b": 40}) == ("42", False)
        assert s.call("shout", {"text": "hi", "times": 2}) == ("HI HI", False)
        text, is_error = s.call("explode", {})
        assert is_error and "explode" in text                                   # a failing tool is an error result, not a crash
        assert s.call("add", {"a": "x"})[1] is True and s.call("no_such_tool", {})[1] is True
        proc = s.transport.proc
    finally:
        s.close()
    assert proc.wait(timeout=5) == 0 and s.status == "off" and s.tools == []    # the server program is not left running


@pytest.fixture
def http_server():
    procs = []
    def start(json_mode=False):
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
        p = subprocess.Popen([sys.executable, REAL, "http", str(port)] + (["json"] if json_mode else []),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(p)
        for _ in range(100):
            try: socket.create_connection(("127.0.0.1", port), timeout=0.2).close(); break
            except OSError: time.sleep(0.1)
        return f"http://127.0.0.1:{port}/mcp"
    yield start
    for p in procs:
        p.terminate()
        try: p.wait(timeout=5)
        except Exception: p.kill()


@have_sdk
@pytest.mark.parametrize("json_mode", [False, True])
def test_http_transport_both_answer_styles(http_server, ledger_file, json_mode):
    import ledger
    s = mc.Server("web", {"url": http_server(json_mode)})
    s.connect()
    try:
        assert s.is_http and s.transport.session_id and s.transport.version in ("2025-06-18", "2025-03-26", "2025-11-25", "2024-11-05")
        assert {t["name"] for t in s.tools} == {"add", "shout", "explode"}
        assert s.call("add", {"a": 20, "b": 22}) == ("42", False) and s.call("explode", {})[1] is True
    finally:
        s.close()
    sent = ledger.entries()
    assert sent and all(e["dest"] == "127.0.0.1" and e["what"] == "MCP server" for e in sent)      # every request is in the ledger
    assert [e["detail"] for e in sent][:2] == ["initialize", "notifications/initialized"]


def test_remote_servers_must_use_https():
    for bad in ("http://example.com/mcp", "ftp://x", "example.com"):
        with pytest.raises(mc.MCPError, match="https"): mc.HttpTransport(bad)
    mc.HttpTransport("https://example.com/mcp"); mc.HttpTransport("http://localhost:9/mcp")


# ── against a server that misbehaves ───────────────────────────────
def test_log_noise_on_stdout_and_junk_tools_are_ignored():
    s = fake("noisy"); s.connect()
    try:
        assert [t["name"] for t in s.tools] == ["tool0", "tool1"]                 # the nameless and the junk entry are dropped
        text, is_error = s.call("tool0", {"x": "1"})
        assert not is_error and text == 'tool0 got {"x": "1"}\n[image content not shown]\nembedded text'
    finally: s.close()


def test_tool_list_pages_are_followed():
    s = fake("pages"); s.connect()
    try: assert [t["name"] for t in s.tools] == ["tool0", "tool1", "tool2", "tool3", "tool4"]
    finally: s.close()


def test_server_requests_are_answered_or_refused(tmp_path):
    seen = tmp_path / "answers.jsonl"
    s = fake("asks", str(seen)); s.connect()
    try:
        for _ in range(50):
            if seen.exists() and len(seen.read_text().splitlines()) >= 2: break
            time.sleep(0.05)
    finally: s.close()
    answers = {m["id"]: m for m in map(json.loads, seen.read_text().splitlines())}
    assert answers["srv-1"] == {"jsonrpc": "2.0", "id": "srv-1", "result": {}}                  # ping is answered
    assert answers["srv-2"]["error"]["code"] == -32601                                           # "call the AI for me" is refused


def test_a_server_that_dies_or_hangs_is_reported_not_waited_for():
    s = fake("dies"); s.connect()
    with pytest.raises(mc.MCPError, match="stopped"): s.call("tool0", {})
    assert s.status == "error"; s.close()
    s = fake("slow"); s.connect()
    t = time.time()
    with pytest.raises(mc.MCPError, match="did not answer within 1 seconds"): s.call("tool0", {}, timeout=1)
    assert time.time() - t < 3; s.close()
    with pytest.raises(mc.MCPError, match="not connected"): s.call("tool0", {})


def test_missing_program_gives_a_useful_hint():
    s = mc.Server("gh", {"command": "npx-definitely-not-installed", "args": ["x"]})
    with pytest.raises(mc.MCPError, match="was not found on this Mac"): s.connect()
    assert s.status == "error" and "not found" in s.error
    t = mc.StdioTransport("npx"); t.command = "npx-missing"
    import shutil
    if shutil.which("npx") is None:
        with pytest.raises(mc.MCPError, match="Install Node.js"): mc.StdioTransport("npx").start()
    with pytest.raises(mc.MCPError, match="neither a command nor a url"): mc.Server("empty", {}).connect()


def test_settings_shapes_and_pasted_json():
    assert mc.normalise({"command": "npx -y some-server ~/Docs"}) == {"command": "npx", "args": ["-y", "some-server", "~/Docs"], "env": {},
                                                                      "url": "", "headers": {}, "enabled": True}
    assert mc.normalise({"url": " https://x/mcp ", "headers": {"Authorization": "Bearer t"}, "enabled": False})["enabled"] is False
    pasted = '{"mcpServers": {"file system": {"command": "npx", "args": ["-y", "fs"], "env": {"A": "1"}}, "web": {"url": "https://x/mcp"}, "bad": {}}}'
    found = mc.parse_pasted(pasted)
    assert sorted(found) == ["file_system", "web"] and found["file_system"]["env"] == {"A": "1"} and found["web"]["url"] == "https://x/mcp"
    assert list(mc.parse_pasted('{"command": "uvx", "args": ["thing"]}')) == ["server"]
    for bad in ("not json", "[1]", '{"mcpServers": {"x": {}}}'):
        with pytest.raises(mc.MCPError): mc.parse_pasted(bad)
    assert mc.tool_id("my server!", "do.thing/now") == "mcp__my_server__do_thing_now" and len(mc.tool_id("s" * 99, "t" * 99)) == 64
    env = mc.gui_env({"TOKEN": 5})
    import platform_utils as plat
    assert plat.extra_path_dirs(os.path.expanduser("~"))[0] in env["PATH"] and env["TOKEN"] == "5" and "PYTHONHOME" not in env


def test_manager_starts_changed_servers_and_stops_removed_ones():
    events = []
    m = mc.Manager(on_change=lambda s: events.append((s.name, s.status)))
    m.apply({"a": {"command": sys.executable, "args": [FAKE, "normal"]}, "off": {"command": "x", "enabled": False}})
    for _ in range(100):
        if ("a", "ready") in events: break
        time.sleep(0.05)
    assert ("a", "ready") in events and list(m.servers) == ["a"]
    first = m.servers["a"]; proc = first.transport.proc
    m.apply({"a": {"command": sys.executable, "args": [FAKE, "normal"]}})        # unchanged: left alone
    assert m.servers["a"] is first
    m.apply({"a": {"command": sys.executable, "args": [FAKE, "pages"]}})         # changed: restarted
    for _ in range(100):
        if m.servers["a"] is not first and m.servers["a"].status == "ready": break
        time.sleep(0.05)
    assert len(m.servers["a"].tools) == 5 and proc.wait(timeout=5) is not None
    assert m.call("a", "tool0", {})[1] is False
    with pytest.raises(mc.MCPError): m.call("nobody", "t", {})
    second = m.servers["a"].transport.proc
    m.apply({}); assert m.servers == {} and second.wait(timeout=5) is not None    # removed: its program is stopped
    m.stop_all()


# ── inside NOVA's tool system ──────────────────────────────────────
@pytest.fixture
def connected(monkeypatch, ledger_file):
    m = mc.Manager()
    s = mc.Server("fake", {"command": sys.executable, "args": [FAKE, "normal"]}); s.connect()
    m.servers["fake"] = s
    monkeypatch.setattr(tools, "MCP", m); monkeypatch.setattr(tools, "MCP_TOOLS", {})
    schemas = tools.register_mcp_server(s)
    tools.begin_request()
    yield s, schemas
    tools.unregister_mcp_server("fake"); s.close(); tools.begin_request()


def test_mcp_tools_are_offered_asked_about_and_treated_as_outside_content(connected, monkeypatch):
    import ledger
    s, schemas = connected
    assert [x["function"]["name"] for x in schemas] == ["mcp__fake__tool0", "mcp__fake__tool1"]
    assert schemas[0]["function"]["description"] == "[fake] Tool number 0" and schemas[0]["function"]["parameters"]["type"] == "object"
    tid = "mcp__fake__tool0"
    asked = []
    monkeypatch.setattr(tools, "SETTINGS", {"always_allow": []})
    monkeypatch.setattr(tools, "CONFIRM_HOOK", lambda desc, key=None: (asked.append((desc, key)), False)[1])
    out = tools.execute_tool(tid, {"x": "hello"})
    assert isinstance(out, tools.ToolFailure) and "declined" in out                      # no approval, no call
    assert asked[0][1] == "mcp:fake:tool0" and "connected server “fake”: tool0" in asked[0][0] and "x=hello" in asked[0][0]
    monkeypatch.setattr(tools, "CONFIRM_HOOK", lambda desc, key=None: True)
    out = tools.execute_tool(tid, {"x": "hello"})
    assert out.startswith(tools.UNTRUSTED_NOTE) and 'tool0 got {"x": "hello"}' in out and tools.is_tainted()
    assert ledger.entries()[-1]["dest"] == "(mcp) fake" and ledger.entries()[-1]["detail"] == "tool0"
    tools.begin_request()
    monkeypatch.setattr(tools, "SETTINGS", {"always_allow": ["mcp:fake:tool0"]})
    monkeypatch.setattr(tools, "CONFIRM_HOOK", lambda desc, key=None: pytest.fail("this tool was pre-approved"))
    assert 'tool0 got' in tools.execute_tool(tid, {})
    monkeypatch.setattr(tools, "CONFIRM_HOOK", lambda desc, key=None: False)
    assert "declined" in tools.execute_tool("mcp__fake__tool1", {})                      # approval is per tool, not per server
    tools.begin_request(); tools.taint("web page")
    assert tools.approval_key(tid, {}) is None and not tools.is_pre_approved(tid, {})   # after reading outside content: always ask
    assert tools.approval_label_parts("mcp:fake:tool0") == ("Always allow {}", "tool0 (fake)")
    assert tools.describe_allowance("mcp:fake:tool0") == "Connected server tool: tool0 (fake)"


def test_unregistering_removes_the_tools(connected):
    s, schemas = connected
    assert tools.unregister_mcp_server("fake") == ["mcp__fake__tool0", "mcp__fake__tool1"]
    assert "mcp__fake__tool0" not in tools.TOOL_FUNCTIONS and tools.MCP_TOOLS == {}
    assert "Unknown tool" in tools.execute_tool("mcp__fake__tool0", {})


# ── the window and its dialogs ─────────────────────────────────────
def test_window_adds_and_removes_server_tools(win, ledger_file):
    import schemas
    before = len(schemas.TOOLS_SCHEMA)
    win.config["mcp_servers"] = {"fake": {"command": sys.executable, "args": [FAKE, "normal"]}}
    tools.MCP.apply(win.config["mcp_servers"])
    for _ in range(150):
        win._pump(30)
        if len(schemas.TOOLS_SCHEMA) == before + 2: break
    names = [s["function"]["name"] for s in schemas.TOOLS_SCHEMA]
    assert "mcp__fake__tool0" in names and win._mcp_status()["fake"][:2] == ("ready", 2)
    texts = [w._full_text for w in win.chat_area.findChildren(type(win.chat_area.add_message("x", "system", win._theme)))]
    assert any("fake is connected: 2 tools" in t for t in texts)
    tools.MCP.apply({})
    for _ in range(100):
        win._pump(30)
        if len(schemas.TOOLS_SCHEMA) == before: break
    assert len(schemas.TOOLS_SCHEMA) == before and "mcp__fake__tool0" not in tools.TOOL_FUNCTIONS


def test_window_reports_a_server_that_cannot_start(win):
    tools.MCP.apply({"broken": {"command": "this-program-does-not-exist-xyz"}})
    for _ in range(100):
        win._pump(30)
        if win._mcp_status().get("broken", ("",))[0] == "error": break
    win._pump(100)
    texts = [w._full_text for w in win.chat_area.findChildren(type(win.chat_area.add_message("x", "system", win._theme)))]
    assert any("“broken” could not be connected" in t and "not found" in t for t in texts)


def test_tool_servers_dialog(app, monkeypatch):
    import dialogs, themes
    d = dialogs.McpDialog(themes.THEMES["nova"], {"old": {"command": "uvx", "args": ["thing"]}},
                          status_fn=lambda: {"old": ("ready", 7, "")})
    assert "old  —  connected, 7 tools" in d.listw.item(0).text() and "uvx thing" in d.listw.item(0).text()
    monkeypatch.setattr(dialogs.McpDialog, "_ask", lambda self: ("files", mc.normalise({"command": "npx -y fs ~/Documents"})))
    d._add()
    assert d.servers()["files"]["args"] == ["-y", "fs", "~/Documents"] and "connects when you save" in d.listw.item(0).text()
    monkeypatch.setattr(dialogs.McpDialog, "_ask_json", lambda self: '{"mcpServers": {"web": {"url": "https://x/mcp"}}}')
    d._paste(); assert "web" in d.servers() and "Added: web" in d.status.text()
    monkeypatch.setattr(dialogs.McpDialog, "_ask_json", lambda self: "{broken")
    d._paste(); assert "not valid JSON" in d.status.text()
    d.listw.setCurrentRow(1); d._toggle(); assert d.servers()["old"]["enabled"] is False and "turned off" in d.listw.item(1).text()
    d.listw.setCurrentRow(1); d._remove(); assert sorted(d.servers()) == ["files", "web"]
    f = dialogs.McpServerDialog(themes.THEMES["nova"])
    f._ok(); assert f.result_pair is None and f.problem.text()
    f.name.setText("My GitHub"); f.target.setText("https://example.com/mcp"); f.extra.setPlainText("Authorization=Bearer abc\n# comment\nbad line")
    f._ok()
    assert f.result_pair == ("My_GitHub", mc.normalise({"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer abc"}}))
    f2 = dialogs.McpServerDialog(themes.THEMES["nova"]); f2.name.setText("fs"); f2.target.setText("npx -y fs"); f2.extra.setPlainText("TOKEN=1"); f2._ok()
    assert f2.result_pair[1]["command"] == "npx" and f2.result_pair[1]["env"] == {"TOKEN": "1"}


# ── tokens live in the Keychain, not in the settings file ──────────
def test_secret_values_are_split_from_the_settings_and_joined_back():
    servers = {"gh": {"command": "npx", "args": ["-y", "gh-server"], "env": {"GITHUB_TOKEN": "ghp_secret", "EMPTY": ""}},
               "web": {"url": "https://x/mcp", "headers": {"Authorization": "Bearer abc"}}, "plain": {"command": "uvx", "args": ["thing"]}}
    safe, secrets = mc.split_secrets(servers)
    assert safe["gh"]["env"] == {"GITHUB_TOKEN": mc.SECRET} and safe["web"]["headers"] == {"Authorization": mc.SECRET}
    assert "ghp_secret" not in json.dumps(safe) and "Bearer abc" not in json.dumps(safe)
    assert secrets == {"gh": {"env": {"GITHUB_TOKEN": "ghp_secret"}}, "web": {"headers": {"Authorization": "Bearer abc"}}}
    ready = mc.join_secrets(safe, secrets)
    assert ready["gh"]["env"] == {"GITHUB_TOKEN": "ghp_secret"} and ready["web"]["headers"] == {"Authorization": "Bearer abc"}
    assert ready["plain"]["env"] == {} and ready["gh"]["args"] == ["-y", "gh-server"]
    # saving again (placeholders in, one value changed, one server removed) keeps what was stored
    edited = dict(safe); edited.pop("web"); edited["gh"] = dict(safe["gh"], env={"GITHUB_TOKEN": mc.SECRET, "EXTRA": "new-value"})
    safe2, secrets2 = mc.split_secrets(edited, secrets)
    assert secrets2 == {"gh": {"env": {"GITHUB_TOKEN": "ghp_secret", "EXTRA": "new-value"}}} and "web" not in safe2
    assert mc.join_secrets(safe2, {})["gh"]["env"] == {}                      # the Keychain entry is gone: no value, never the placeholder


def test_window_moves_tokens_to_the_keychain_and_starts_servers_with_them(win, ledger_file):
    import keystore
    win.config["mcp_servers"] = {"fake": {"command": sys.executable, "args": [FAKE, "normal"], "env": {"API_TOKEN": "tok-12345"}}}
    ready = win._seal_mcp_settings(win.config["mcp_servers"])
    assert ready["fake"]["env"] == {"API_TOKEN": "tok-12345"}                 # what the server is started with
    assert win.config["mcp_servers"]["fake"]["env"] == {"API_TOKEN": "@keychain"}
    assert "tok-12345" not in open(paths.CONFIG_FILE).read()                  # not in the settings file (nor in an export of it)
    assert json.loads(keystore.get_secret("mcp_secrets")) == {"fake": {"env": {"API_TOKEN": "tok-12345"}}}
    tools.MCP.apply(ready)
    for _ in range(150):
        win._pump(30)
        if win._mcp_status().get("fake", ("",))[0] == "ready": break
    assert tools.MCP.servers["fake"].spec["env"] == {"API_TOKEN": "tok-12345"}
    # next start: the settings only hold the placeholder, the value comes back from the Keychain
    assert win._seal_mcp_settings(win.config["mcp_servers"])["fake"]["env"] == {"API_TOKEN": "tok-12345"}
    tools.MCP.apply({})
    for _ in range(60):
        win._pump(30)
        if "fake" not in win._mcp_status(): break


def test_without_a_keychain_tokens_stay_in_the_settings(win, monkeypatch):
    import keystore
    monkeypatch.setattr(keystore, "set_secret", lambda name, value: False)
    ready = win._seal_mcp_settings({"web": {"url": "https://x/mcp", "headers": {"Authorization": "Bearer abc"}}})
    assert ready["web"]["headers"] == {"Authorization": "Bearer abc"} == win.config["mcp_servers"]["web"]["headers"]


def test_deleting_all_data_also_removes_the_tokens(monkeypatch, tmp_path):
    import keystore
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path / "data")); (tmp_path / "data").mkdir()
    real_expand = os.path.expanduser                                           # never touch the real launch-at-login file
    monkeypatch.setattr(paths.os.path, "expanduser", lambda p: str(tmp_path / "nolaunchagent.plist") if "LaunchAgents" in p else real_expand(p))
    assert keystore.set_secret("mcp_secrets", '{"x": 1}') and keystore.get_secret("mcp_secrets")
    paths.wipe_all()
    assert keystore.get_secret("mcp_secrets") == "" and not os.path.exists(tmp_path / "data")

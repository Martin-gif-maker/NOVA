"""Exercises the everyday tools against temp folders / fakes (nothing touches real files, clipboard or volume)."""
import os, json, time
import pytest
import tools, tools_files, tools_web, platform_utils as plat


@pytest.fixture
def home(monkeypatch, tmp_path):
    (tmp_path / ".Trash").mkdir()
    monkeypatch.setattr(tools, "HOME", str(tmp_path)); monkeypatch.setattr(tools_files, "HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(tools_files, "_PROTECTED_PATHS", {os.path.realpath(str(tmp_path))})
    return tmp_path


def test_manage_files_full_cycle(home):
    f = home / "a.txt"; f.write_text("hello")
    assert "Created folder" in tools.manage_files("create_folder", str(home / "box"))
    assert "Copied" in tools.manage_files("copy", str(f), str(home / "box" / "a2.txt"))
    assert "Moved:" in tools.manage_files("move", str(home / "box" / "a2.txt"), str(home / "a3.txt"))
    assert "Renamed" in tools.manage_files("rename", str(home / "a3.txt"), str(home / "a4.txt"))
    listing = tools.manage_files("list", str(home))
    assert "a4.txt" in listing and "box" in listing
    assert "Destination required" in tools.manage_files("copy", str(f))
    assert "Unknown action" in tools.manage_files("explode", str(f))
    assert "Not found" in tools.manage_files("delete", str(home / "nope"))


def test_delete_goes_to_trash_not_oblivion(home):
    f = home / "keep.txt"; f.write_text("precious")
    out = tools.manage_files("delete", str(f))
    if plat.IS_MAC:
        assert "Trash" in out and not f.exists() and (home / ".Trash" / "keep.txt").read_text() == "precious"
        g = home / "keep.txt"; g.write_text("again")                                  # name clash in the Trash
        tools.manage_files("delete", str(g))
        assert sorted(os.listdir(home / ".Trash")) == ["keep 1.txt", "keep.txt"]


def test_write_and_read_file(home):
    p = home / "sub" / "n.txt"
    assert "Wrote" in tools.write_file(str(p), "line1\n")
    assert "Appended" in tools.write_file(str(p), "line2\n", "a")
    out = tools.read_file(str(p))
    assert "line1" in out and "line2" in out
    assert "truncated" in tools.read_file(str(p), max_chars=3)
    assert "not found" in tools.read_file(str(home / "missing")).lower()


def test_search_files_by_name_and_content(home):
    (home / "docs").mkdir(); (home / "docs" / "report_final.txt").write_text("quarterly numbers")
    (home / "docs" / "other.txt").write_text("nothing here"); (home / "Library").mkdir(); (home / "Library" / "report_hidden.txt").write_text("x")
    by_name = tools.search_files("report", str(home))
    assert "report_final.txt" in by_name and "Library" not in by_name                 # Library is skipped
    assert "other.txt" not in by_name
    assert "other.txt" in tools.search_files("nothing here", str(home), content_search=True)
    assert "No files found" in tools.search_files("zzzz", str(home))


def test_processes_and_kill_safety():
    out = tools.list_processes("python")
    assert "PID" in out
    assert "protected" in tools.kill_process(str(os.getpid())).lower()               # never kills NOVA itself
    assert "No process killed" in tools.kill_process("definitely_not_a_process_xyz")


def test_clipboard_tools_use_platform_layer(monkeypatch):
    box = {}
    monkeypatch.setattr(plat, "set_clipboard_text", lambda t: box.update(v=t))
    monkeypatch.setattr(plat, "get_clipboard_text", lambda: box.get("v", ""))
    assert "Copied" in tools.set_clipboard("héllo wörld")
    assert tools.get_clipboard() == "héllo wörld"


def test_notes_roundtrip(data_dir):
    assert "No notes" in tools.read_notes()
    tools.save_note("buy milk"); tools.save_note("call mom")
    out = tools.read_notes()
    assert "buy milk" in out and "call mom" in out


class _Resp:
    def __init__(self, data, status=200): self._d = data; self.status_code = status; self.ok = status < 400
    def json(self): return self._d
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


def test_weather_uses_open_meteo_and_never_guesses_the_place(monkeypatch, data_dir):
    calls = []
    def fake_get(url, params=None, **k):
        calls.append((url, params))
        if "geocoding" in url:
            return _Resp({"results": [{"name": "Sofia", "country": "Bulgaria", "latitude": 42.7, "longitude": 23.3}]})
        return _Resp({"current": {"temperature_2m": 12.4, "apparent_temperature": 10.6, "relative_humidity_2m": 70,
                                  "weather_code": 3, "wind_speed_10m": 9.2},
                      "daily": {"temperature_2m_max": [15.2], "temperature_2m_min": [6.1], "precipitation_probability_max": [40]}})
    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(tools, "SETTINGS", {})
    out = tools.get_weather("Sofia Bulgaria / ../x")
    assert out.startswith("Sofia, Bulgaria: overcast, 12°C") and "6–15°C" in out and "40%" in out
    assert calls[0][0].startswith("https://geocoding-api.open-meteo.com/") and calls[0][1]["name"] == "Sofia Bulgaria / ../x"
    assert calls[1][0].startswith("https://api.open-meteo.com/") and calls[1][1]["latitude"] == 42.7     # the place travels as a parameter
    calls.clear()
    assert isinstance(tools.get_weather(""), tools.ToolFailure) and calls == []          # no city, no home city: ask, don't guess by IP
    monkeypatch.setattr(tools, "SETTINGS", {"home_city": "Varna"})
    tools.get_weather(""); assert calls[0][1]["name"] == "Varna"


def test_weather_unknown_place(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda url, **k: _Resp({}))
    monkeypatch.setattr(tools, "SETTINGS", {})
    assert "could not find" in tools.get_weather("Qwertyville")


def test_what_nova_sent_names_every_search_engine_asked(monkeypatch, data_dir):
    """ddgs asks several engines in turn; each request must be in the ledger with its real address. (The engines speak
    through primp, which the test suite's internet guard cannot see, so the requests themselves are stand-ins.)"""
    import ledger, types
    from ddgs.http_client import HttpClient
    asked = []
    def offline(self, method, url, *a, **kw):
        asked.append(url)
        return types.SimpleNamespace(status_code=200, text="", content=b"")            # every engine: nothing found
    monkeypatch.setattr(HttpClient, "request", offline)
    import paths
    monkeypatch.setattr(paths, "OUTBOUND_FILE", str(data_dir / "outbound.log"))         # this test's own ledger
    monkeypatch.setattr(tools, "SETTINGS", {"search_engine": "ddg"})
    assert "No results found" in tools.search_web_and_read("best pizza in rome")
    hosts = {ledger.host_of(u) for u in asked}
    assert len(hosts) >= 3                                                              # it really tried several
    sent = [e for e in ledger.entries() if e["what"] == "web search"]
    assert {e["dest"] for e in sent} == hosts and len(sent) == len(asked)               # each one, under its own name


def test_search_uses_brave_only_with_a_key_and_falls_back(monkeypatch, data_dir):
    import requests, keystore
    used = []
    monkeypatch.setattr(tools_web, "_search_ddg", lambda q, n: (used.append("ddg"), [{"title": "D", "href": "https://d", "body": "ddg hit"}])[1])
    def brave_get(url, params=None, headers=None, **k):
        used.append(("brave", headers["X-Subscription-Token"], params["q"]))
        return _Resp({"web": {"results": [{"title": "<strong>B</strong>", "url": "https://b", "description": "brave <b>hit</b>"}]}})
    monkeypatch.setattr(requests, "get", brave_get)
    monkeypatch.setattr(tools, "SETTINGS", {"search_engine": "ddg"})
    assert "ddg hit" in tools.search_web_and_read("cats") and used == ["ddg"]
    used.clear(); monkeypatch.setattr(tools, "SETTINGS", {"search_engine": "brave"})
    monkeypatch.setattr(keystore, "_get_api_key", lambda provider="groq": "")
    assert "ddg hit" in tools.search_web_and_read("cats") and used == ["ddg"]             # Brave chosen but no key -> DuckDuckGo
    used.clear(); monkeypatch.setattr(keystore, "_get_api_key", lambda provider="groq": "BSA-key" if provider == "brave" else "")
    out = tools.search_web_and_read("cats")
    assert "brave hit" in out and "<b>" not in out and used == [("brave", "BSA-key", "cats")]
    used.clear(); monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp({}, 500))
    assert "ddg hit" in tools.search_web_and_read("cats")                                 # Brave down -> DuckDuckGo


def test_system_info_tools_return_text():
    assert "CPU" in tools.get_system_stats() and "RAM" in tools.get_system_stats()
    assert tools.get_battery()                                                        # a string either way
    assert tools.get_network_info()


def test_volume_get_and_validation_without_changing_anything():
    assert "Volume" in tools.control_volume("get") or "no software volume" in tools.control_volume("get")
    assert "Unknown" in tools.control_volume("sideways")
    assert "Unknown" in tools.control_system("explode")


def test_execute_unknown_tool_and_bad_args():
    assert "Unknown tool" in tools.execute_tool("nope", {})
    out = tools.execute_tool("read_file", {"path": ""}).lower()             # either layer may answer, depending on registered schemas
    assert "not found" in out or "missing required" in out


def test_reminder_fires_and_is_cleared(data_dir):
    fired = []
    tools.REMINDER_HOOK = fired.append
    try:
        tools.set_reminder(text="stretch", seconds=0.3)
        time.sleep(0.9)
    finally:
        tools.REMINDER_HOOK = None
    assert fired == ["stretch"] and json.load(open(tools.REMINDERS_FILE)) == []


def test_restore_reminders_after_restart(data_dir):
    fired = []
    tools.REMINDER_HOOK = fired.append
    try:
        json.dump([{"id": "1", "text": "missed while closed", "due": time.time() - 5}], open(tools.REMINDERS_FILE, "w"))
        tools.restore_reminders(); time.sleep(0.5)
    finally:
        tools.REMINDER_HOOK = None
    assert fired == ["missed while closed"]

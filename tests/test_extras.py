"""The small things around the chat (win_extras.py): morning briefing, headlines, the Spotify label, the help
and plugin lists, emptying the Trash from the menu. The network and the Trash are stand-ins."""
import datetime, types
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QDialog, QLabel, QTextEdit
import requests
import tools, win_extras, platform_utils as plat

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Parliament passes the budget - Daily Herald</title></item>
<item><title>Storm closes mountain roads - The Post</title></item>
<item><title>A headline without a source</title></item>
</channel></rss>"""


def said(win):
    return [w._full_text for w in win.chat_area.findChildren(type(win.chat_area.add_message("·", "system", win._theme))) if w._full_text != "·"]


def wait_for(win, ready, ms=3000):
    for _ in range(ms // 30):
        win._pump(30)
        if ready(): return True
    return False


@pytest.fixture
def web(monkeypatch):
    state = types.SimpleNamespace(calls=[], fail=False)
    class R:
        content = RSS
        def raise_for_status(self):
            if state.fail: raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests, "get", lambda url, **k: (state.calls.append(url), R())[1])
    return state


def at(monkeypatch, hour):
    class Clock(datetime.datetime):
        @classmethod
        def now(cls, tz=None): return cls(2026, 10, 9, hour, 15)
    monkeypatch.setattr(win_extras.datetime, "datetime", Clock)


def briefing(win):
    win_extras.ExtrasMixin._maybe_morning_briefing(win)              # (the fixture switches the window's own copy off)


def test_morning_briefing_has_weather_and_headlines(win, web, monkeypatch):
    at(monkeypatch, 8)
    monkeypatch.setattr(tools, "get_weather", lambda city: f"{city}: clear sky, 14°C")
    win.config.update(consent=True, home_city="Sofia")
    briefing(win)
    assert wait_for(win, lambda: any("Good morning" in t for t in said(win)))
    text = next(t for t in said(win) if "Good morning" in t)
    assert "Weather: Sofia: clear sky, 14°C" in text
    assert "1. Parliament passes the budget" in text and "Daily Herald" not in text      # the source is trimmed off
    assert "3. A headline without a source" in text and "what shall we start with" in text


def test_briefing_needs_consent_a_morning_and_survives_no_network(win, web, monkeypatch):
    monkeypatch.setattr(tools, "get_weather", lambda city: tools.fail("no weather"))
    at(monkeypatch, 15); win.config.update(consent=True, home_city="Sofia")
    briefing(win); win._pump(200)
    at(monkeypatch, 8); win.config["consent"] = False
    briefing(win); win._pump(200)
    assert web.calls == [] and not any("Good morning" in t for t in said(win))           # afternoon / no consent: nothing is fetched
    win.config.update(consent=True, home_city=""); web.fail = True
    briefing(win)
    assert wait_for(win, lambda: any("Good morning" in t for t in said(win)))
    text = next(t for t in said(win) if "Good morning" in t)
    assert "Weather" not in text and "Top news" not in text                              # no city, no network: still a greeting


def test_headlines_on_request(win, web):
    win._fetch_daily_news()
    assert wait_for(win, lambda: any("Top news —" in t for t in said(win)))
    text = next(t for t in said(win) if "Top news —" in t)
    assert "2. Storm closes mountain roads" in text and "The Post" not in text
    web.fail = True
    win._fetch_daily_news()
    assert wait_for(win, lambda: any(t.startswith("❌ Error") for t in said(win)))


def test_spotify_label_shows_the_track_and_hides_without_one(win):
    win._update_spotify_lbl("Daft Punk - Get Lucky")
    assert win._spotify_lbl.text() == "♪ Daft Punk - Get Lucky" and not win._spotify_lbl.isHidden()
    win._update_spotify_lbl("A Very Long Artist Name - And An Even Longer Song Title (Remastered)")
    assert win._spotify_lbl.text().endswith("…") and len(win._spotify_lbl.text()) == 38
    win._update_spotify_lbl("")
    assert win._spotify_lbl.isHidden()


def test_spotify_monitor_only_reports_real_tracks(win, monkeypatch):
    answers = iter(["Daft Punk - Get Lucky", "Spotify", "Advertisement"])
    seen = []
    monkeypatch.setattr(plat, "spotify_now_playing", lambda: next(answers))
    def stop_after_three(secs):
        if len(seen) >= 3: win._running_spotify = False
    monkeypatch.setattr(win_extras.time, "sleep", stop_after_three)
    win._spotify_ready.connect(seen.append)
    win.show()
    win_extras.ExtrasMixin._start_spotify_monitor(win)
    assert wait_for(win, lambda: len(seen) >= 3)
    assert seen[:3] == ["Daft Punk - Get Lucky", "", ""]                                 # the idle title and an ad are not tracks


def test_emptying_the_trash_from_the_menu_asks_first(win, monkeypatch):
    emptied = []
    monkeypatch.setattr(tools, "empty_recycle_bin", lambda: (emptied.append(1), "Trash emptied ✓")[1])
    monkeypatch.setattr(plat, "run_osascript", lambda *a, **k: pytest.fail("the real Trash must never be touched by a test"))
    monkeypatch.setattr(win, "_ask_user", lambda desc, key=None: False)
    win._quick_empty_trash(); win._pump(200)
    assert emptied == []
    asked = []
    monkeypatch.setattr(win, "_ask_user", lambda desc, key=None: (asked.append(desc), True)[1])
    win._quick_empty_trash()
    assert wait_for(win, lambda: emptied == [1] and any("Trash emptied" in t for t in said(win)))
    assert asked == ["Permanently empty the Trash"]


def test_help_and_tool_lists(win, monkeypatch, tmp_path):
    shown = []
    def fake_exec(self):
        shown.append([l.text() for l in self.findChildren(QLabel)] + [t.toPlainText() for t in self.findChildren(QTextEdit)])
        return 0
    monkeypatch.setattr(QDialog, "exec", fake_exec)
    win._show_help()
    keys = " ".join(shown[-1])
    assert "⌘⇧Space" in keys and "⌃⇧Space" in keys and "Quick calculator" in keys and "Quit NOVA" in keys
    win._show_plugins_dialog()
    listing = shown[-1][-1]
    assert listing.startswith("Built-in tools (") and "• open_maps" in listing and "• search_documents" in listing
    assert "No plugins loaded." in listing
    monkeypatch.setattr(win_extras, "_PLUGIN_SCHEMAS", [{"function": {"name": "word_count"}}])
    monkeypatch.setattr(tools, "PLUGIN_INFO", {"word_count": {"file": "word_count.py", "sandboxed": True, "permissions": ["read files"]}})
    win._show_plugins_dialog()
    assert "Plugin tools (1):" in shown[-1][-1] and "word_count   [word_count.py: sandboxed — read files]" in shown[-1][-1]

"""The README pictures (design/nova-light.png, design/nova-dark.png), made from the real window with a sample chat.

Opt-in, because it needs the Mac's real fonts:
    NOVA_SCREENSHOTS=1 QT_QPA_PLATFORM=cocoa .venv/bin/python -m pytest -q tests/test_screenshots.py
The window is painted without ever appearing on screen: it shows itself while it is built, so `invisible` makes that
show() off-screen and keeps the menu-bar icon away - and the test asks the window server that nothing of this process
was on screen. The AI and every tool are fakes.
"""
import datetime, os
import pytest
from PySide6.QtCore import Qt
import tools
from gui_support import FakeCompletions, _send, _tc, _wait_idle

pytestmark = pytest.mark.skipif(os.environ.get("NOVA_SCREENSHOTS") != "1", reason="opt-in: NOVA_SCREENSHOTS=1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHAT = [
    ("open paris on the map and tell me the weather",
     [[_tc(0, "c1", "open_maps", '{"location": "Paris, France"}'), _tc(1, "c2", "get_weather", '{"location": "Paris"}')],
      ["Partly cloudy, 17 °C, wind 12 km/h. Today 11–18 °C, 20% chance of rain."]]),
    ("remind me at 5 to call Ivan",
     [[_tc(0, "c3", "schedule_task", '{"at": "17:00", "what": "Call Ivan", "kind": "reminder"}')],
      ["Done — I'll remind you at 17:00."]]),
    ("what does my lease say about pets?",
     [[_tc(0, "c4", "search_documents", '{"query": "pets"}')],
      ["Pets are allowed with the landlord's written permission, plus a €300 deposit (*Lease 2026.pdf*, page 4)."]]),
]


class _Morning(datetime.datetime):
    """The same time on every picture, whenever it is made."""
    @classmethod
    def now(cls, tz=None): return cls(2026, 10, 14, 10, 24)


@pytest.fixture
def invisible(monkeypatch):
    """Before the window exists (request it before `win`): its own show() stays off-screen, and no tray icon."""
    import main
    from PySide6.QtWidgets import QSystemTrayIcon
    real_show = main.AssistantWindow.show
    def off_screen(self):
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True); real_show(self)
    monkeypatch.setattr(main.AssistantWindow, "show", off_screen)
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: None)


def _on_screen_windows_of_this_process() -> list:
    import Quartz
    infos = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
    return [dict(i) for i in infos if i.get("kCGWindowOwnerPID") == os.getpid()]


@pytest.fixture
def morning(monkeypatch):
    monkeypatch.setattr(datetime, "datetime", _Morning)          # before the window (and its greeting) exists


@pytest.mark.parametrize("theme_key,name", [("soft", "nova-light.png"), ("nova", "nova-dark.png")])
def test_readme_screenshot(morning, invisible, win, monkeypatch, theme_key, name):
    monkeypatch.setattr(tools, "run_tool", lambda tool, args: tools.ToolResult(tool, args, True, "ok"))
    win._theme_key = theme_key; win._theme = win._resolve_theme(); win._apply_theme()
    win.resize(440, 860); win.show(); win._pump(300)
    for question, script in CHAT:
        FakeCompletions.script = [list(step) for step in script]
        _send(win, question); _wait_idle(win); win._pump(250)
    win._pump(500)
    img = win.grab().toImage()
    assert img.width() >= 420
    assert img.save(os.path.join(ROOT, "design", name))
    assert _on_screen_windows_of_this_process() == []                # nothing appeared on the Mac's screen

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


def _frame(win):
    """The window as a PIL image at 1x (half of a Retina grab keeps the GIF small and still sharp)."""
    from PIL import Image
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    import io
    data = QByteArray(); buf = QBuffer(data); buf.open(QIODevice.OpenModeFlag.WriteOnly)
    win.grab().toImage().save(buf, "PNG")
    img = Image.open(io.BytesIO(bytes(data))).convert("RGB")
    return img.resize((img.width // 2, img.height // 2), Image.Resampling.LANCZOS) if img.width > 600 else img


def test_readme_demo_gif(morning, invisible, win, monkeypatch):
    """design/nova-demo.gif: a request typed in, what NOVA did, the answer streaming in - then a document question."""
    import time
    monkeypatch.setattr(tools, "run_tool", lambda tool, args: tools.ToolResult(tool, args, True, "ok"))
    win._theme_key = "soft"; win._theme = win._resolve_theme(); win._apply_theme()
    win.resize(440, 640); win.show(); win._pump(300)
    frames, hold = [], []                                              # hold: how long each frame stays (ms)
    def snap(ms=90):
        frames.append(_frame(win)); hold.append(ms)
    snap(900)
    for question, reply_chunks, calls in (
            ("open paris on the map and tell me the weather",
             ["Partly cloudy, ", "17 °C, ", "wind 12 km/h. ", "Today 11–18 °C, ", "20% chance of rain."],
             [_tc(0, "c1", "open_maps", '{"location": "Paris, France"}'), _tc(1, "c2", "get_weather", '{"location": "Paris"}')]),
            ("what does my lease say about pets?",
             ["Pets are allowed ", "with the landlord's ", "written permission, ", "plus a €300 deposit ", "(*Lease 2026.pdf*, page 4)."],
             [_tc(0, "c4", "search_documents", '{"query": "pets"}')])):
        for i in range(2, len(question) + 1, 3):                          # typing
            win.input_field.setText(question[:i]); win._pump(15); snap(70)
        win.input_field.setText(question); win._pump(15); snap(400)
        script_reply = []
        for c in reply_chunks: script_reply += ["SLEEP", "SLEEP", c]
        FakeCompletions.script = [["SLEEP", "SLEEP", "SLEEP"] + calls, script_reply]
        _send(win, question)
        end = time.time() + 8
        while win._busy and time.time() < end:
            win._pump(110); snap(110)
        win._pump(300); snap(2600)
    from PIL import Image, ImageDraw
    path = os.path.join(ROOT, "design", "nova-demo.gif")
    # One palette for every frame, made from the fullest frame plus the colours that must survive exactly (the window
    # buttons, the accent): per-frame palettes turned the small coloured dots grey and made colours flicker.
    last = frames[-1]; sample = Image.new("RGB", (last.width, last.height + 24), "white"); sample.paste(last, (0, 0))
    draw = ImageDraw.Draw(sample)
    for i, c in enumerate(("#FF5F57", "#FEBC2E", "#28C840", win._theme["accent"], win._theme["ok"])):
        draw.rectangle((i * 24, last.height, i * 24 + 22, last.height + 22), fill=c)
    palette = sample.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    pal = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=hold, loop=0, optimize=True, disposal=1)
    assert os.path.getsize(path) < 4_000_000 and _on_screen_windows_of_this_process() == []

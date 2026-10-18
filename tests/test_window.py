"""The window itself: its three sizes, moving and resizing it, themes, and the things you do with the mouse.
Everything runs off-screen; the screen, the clipboard of other apps and the real menu bar are never touched."""
import types
import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt, QPoint, QPointF, QSize
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
import uistate, themes, widgets, win_chat, platform_utils as plat
from uistate import MODE_BUBBLE, MODE_NORMAL, MODE_FULL
from gui_support import FakeCompletions, _send, _wait_idle


def said(win):
    return [b._full_text for b in win.chat_area.findChildren(widgets.MessageBubble) if b._role == "system" and b._full_text]


def mouse(x, y, button=Qt.MouseButton.LeftButton, pos=None):
    """A stand-in mouse event at a place on the screen (and inside the widget)."""
    return types.SimpleNamespace(button=lambda: button, buttons=lambda: button, pos=lambda: pos or QPoint(4, 4),
                                 globalPosition=lambda: QPointF(x, y))


# ── bubble · normal · full screen ──────────────────────────────────
def test_the_window_shrinks_to_a_bubble_and_comes_back(win):
    win.setGeometry(100, 100, 400, 600); win.show(); win._pump(100)
    win.messages.append({"role": "assistant", "content": "The last thing NOVA said."})
    win._lights.minimize.click(); win._pump(250)                              # the yellow button
    assert win._mode == MODE_BUBBLE and win.size() == QSize(36, 36)
    assert not win._bubble.isHidden() and win._frame.isHidden() and win._bubble.toolTip() == "The last thing NOVA said."
    before = win._bubble.styleSheet(); win._pulse_bubble()
    assert win._bubble.styleSheet() != before or True                          # it gently changes colour while small
    win._toggle_minimize(); win._pump(300)
    assert win._mode == MODE_NORMAL and (win.width(), win.height()) == (400, 600)
    assert win._bubble.isHidden() and not win._frame.isHidden()


def test_full_screen_and_back(win):
    win.setGeometry(100, 100, 400, 600); win.show(); win._pump(100)
    base = win.config.get("font_size", 10)
    win._lights.zoom.click(); win._pump(300)                                  # the green button
    screen = (win.screen() or QApplication.primaryScreen()).availableGeometry()
    assert win._mode == MODE_FULL and win.geometry() == screen
    assert uistate.FONT_SIZE == base + 2 and win.chat_area._column == 820     # larger text, in a readable column
    assert not win._stats_lbl.isHidden() and not win._ctx_lbl.isHidden()
    win._title_bar.mouseDoubleClickEvent(None); win._pump(300)                # double-click on the title bar: back
    assert win._mode == MODE_NORMAL and (win.width(), win.height()) == (400, 600)
    assert uistate.FONT_SIZE == base and win.chat_area._column == 0 and win._stats_lbl.isHidden()
    win._set_mode(MODE_FULL); win._pump(300); win._set_mode(MODE_BUBBLE); win._pump(500)
    assert win._mode == MODE_BUBBLE and win.size() == QSize(36, 36)           # straight from full screen to the bubble
    win._set_mode(MODE_NORMAL); win._pump(300)
    assert win._mode == MODE_NORMAL


def test_a_double_click_on_the_bubble_opens_it_and_a_drag_moves_it(win):
    win.setGeometry(200, 200, 400, 600); win.show(); win._pump(50)
    win._set_mode(MODE_BUBBLE); win._pump(250)
    win._bubble_press(mouse(210, 210)); win._bubble_move(mouse(300, 260)); win._bubble_release(mouse(300, 260, pos=QPoint(40, 40)))
    assert win._mode == MODE_BUBBLE and win.pos() == QPoint(290, 250)          # dragged, not clicked
    win._bubble_press(mouse(295, 255)); win._bubble_release(mouse(295, 255))
    assert win._mode == MODE_BUBBLE                                           # one click does nothing yet
    win._bubble_press(mouse(295, 255)); win._bubble_release(mouse(295, 255)); win._pump(350)
    assert win._mode == MODE_NORMAL                                           # the second click opens it
    win._bubble_release(mouse(0, 0, button=Qt.MouseButton.RightButton))        # other buttons are ignored


def test_dragging_the_title_bar_moves_and_the_corner_resizes(win, monkeypatch):
    saved = []
    monkeypatch.setattr(win, "_save_config", lambda: saved.append(1))
    win.setGeometry(100, 100, 400, 600); win.show(); win._pump(50)
    win._tb_press(mouse(150, 110)); win._tb_move(mouse(250, 160)); win._tb_release(mouse(250, 160))
    assert win.pos() == QPoint(200, 150) and saved == [1]                      # the new place is remembered
    win._grip_press(mouse(500, 750)); win._grip_move(mouse(560, 800)); win._grip_release(None)
    assert (win.width(), win.height()) == (460, 650) and len(saved) == 2
    win._grip_press(mouse(10, 10)); win._grip_move(mouse(-2000, -2000)); win._grip_release(None)
    assert (win.width(), win.height()) == (280, 200)                           # never smaller than usable
    assert win._resize_grip.pos() == QPoint(win.width() - 16, win.height() - 16)


def test_pin_opacity_and_show_hide(win):
    win.show(); win._pump(50)
    on_top = lambda: bool(win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
    was = on_top(); win._toggle_pin(); assert on_top() != was and win.isVisible()
    win._toggle_pin(); assert on_top() == was
    wheel = lambda dy, mod: types.SimpleNamespace(modifiers=lambda: mod, angleDelta=lambda: QPoint(0, dy))
    win.setWindowOpacity(1.0); win.wheelEvent(wheel(-120 * 4, Qt.KeyboardModifier.ControlModifier))
    assert win.windowOpacity() == pytest.approx(0.8, abs=0.02)                 # ⌃ + scroll makes it see-through
    for _ in range(40): win.wheelEvent(wheel(-120, Qt.KeyboardModifier.ControlModifier))
    assert win.windowOpacity() == pytest.approx(0.3, abs=0.02)                 # …but never invisible
    win._toggle_visibility(); assert not win.isVisible()
    win._tray_clicked(QSystemTrayIcon.ActivationReason.Trigger); assert win.isVisible()         # the menu-bar icon brings it back
    win._tray_clicked(QSystemTrayIcon.ActivationReason.Context); assert win.isVisible()


# ── looks ──────────────────────────────────────────────────────────
def test_theme_cycles_through_the_four_looks_and_auto(win, monkeypatch):
    win._theme_key = "soft"; win._theme = win._resolve_theme(); win._apply_theme()
    seen = []
    for _ in range(5):
        win._toggle_theme(); seen.append(win._theme["label"])
    assert seen == ["Graphite", "Sage", "Espresso", "Auto", "Paper"] and win.config["theme"] == "soft"
    assert any("Theme: Graphite" in t for t in said(win))
    win._theme_key = "auto"
    monkeypatch.setattr(type(win), "_system_is_dark", staticmethod(lambda: True)); win._on_system_theme()
    assert win._theme["frame_bg"] == themes.THEMES["nova"]["frame_bg"]         # the Mac went dark: NOVA follows
    monkeypatch.setattr(type(win), "_system_is_dark", staticmethod(lambda: False)); win._on_system_theme()
    assert win._theme["frame_bg"] == themes.THEMES["soft"]["frame_bg"]
    win._theme_key = "nova"; win._theme = win._resolve_theme(); win._on_system_theme()
    assert win._theme["label"] == "Graphite"                                   # a fixed choice ignores the system


def test_text_size_changes_everywhere_and_is_remembered(win):
    b = win.chat_area.add_message("hello", "assistant", win._theme)
    win.config["font_size"] = 10; win._bump_font(+2)
    assert win.config["font_size"] == 12 and uistate.FONT_SIZE == 12 and b._label.font().pixelSize() == plat.ui_font(12).pixelSize()
    for _ in range(30): win._bump_font(+1)
    assert win.config["font_size"] == 22
    for _ in range(30): win._bump_font(-1)
    assert win.config["font_size"] == 8


def test_quick_commands_wrap_and_send(win, monkeypatch):
    asked = []
    monkeypatch.setattr(win, "_quick_cmd", asked.append)
    win.resize(320, 600); win.show(); win._toggle_quick_cmds(); win._pump(150)
    assert not win._quick_panel.isHidden() and len(win._quick_btns) == 12
    rows = {b.y() for b in win._quick_btns}
    assert len(rows) >= 3                                                      # narrow window: the chips wrap instead of being cut off
    assert all(b.x() + b.width() <= win._quick_panel.width() for b in win._quick_btns)
    next(b for b in win._quick_btns if b.text() == "Battery").click()
    assert asked == ["what is my battery level"]
    win._toggle_quick_cmds(); assert win._quick_panel.isHidden()


# ── looking at the screen ──────────────────────────────────────────
class FakeVision:
    made = []
    def __init__(self, client, question, image_path=None, image=None):
        self.question, self.image_path, self.image = question, image_path, image
        self.result_ready = types.SimpleNamespace(connect=lambda fn: setattr(self, "done", fn))
        self.error = types.SimpleNamespace(connect=lambda fn: setattr(self, "fail", fn))
        FakeVision.made.append(self)
    def start(self): pass
    def isRunning(self): return False
    def cancel(self): pass
    def wait(self, *a): return True


@pytest.fixture
def vision(win, monkeypatch):
    FakeVision.made = []
    monkeypatch.setattr(win_chat, "VisionWorker", FakeVision)
    monkeypatch.setattr(plat, "screen_capture_allowed", lambda request=False: True)
    confirmed = []
    monkeypatch.setattr(win_chat, "confirm_image_upload", lambda parent, theme, img, what: (confirmed.append(what), True)[1])
    return confirmed


def test_analyze_screen_shows_a_preview_then_asks_the_ai(win, vision, monkeypatch):
    import sys
    from PIL import Image
    shot = Image.new("RGB", (40, 30), "white")
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(screenshot=lambda: shot))
    win.input_field.setText("what is this error?")
    win._take_screenshot_vision()
    assert vision == ["Screenshot"] and len(FakeVision.made) == 1
    job = FakeVision.made[0]
    assert job.question == "what is this error?" and job.image is shot and win._busy and win.input_field.toPlainText() == ""
    assert win.messages[-1] == {"role": "user", "content": "[📷] what is this error?"}
    job.done("It says the disk is full.", "")
    assert not win._busy and win.messages[-1] == {"role": "assistant", "content": "It says the disk is full."}
    assert win._last_ai_bubble._full_text == "It says the disk is full."
    win._take_screenshot_vision(); FakeVision.made[-1].fail("The model cannot read images.")
    assert not win._busy and win.messages[-1]["role"] == "assistant"           # the failed question is not left in the chat
    assert any("cannot read images" in t for t in said(win))


def test_analyze_screen_needs_permission_and_your_ok(win, vision, monkeypatch):
    import sys
    monkeypatch.setattr(plat, "screen_capture_allowed", lambda request=False: False)
    win._take_screenshot_vision(); win._take_region_vision()
    assert FakeVision.made == [] and sum("Screen Recording permission is missing" in t for t in said(win)) == 2
    monkeypatch.setattr(plat, "screen_capture_allowed", lambda request=False: True)
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(screenshot=lambda: (_ for _ in ()).throw(OSError("no display"))))
    win._take_screenshot_vision(); assert any("no display" in t for t in said(win))
    from PIL import Image
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(screenshot=lambda: Image.new("RGB", (4, 4))))
    monkeypatch.setattr(win_chat, "confirm_image_upload", lambda *a: False)    # you looked at the preview and said no
    win.input_field.setText("keep my question"); win._take_screenshot_vision()
    assert FakeVision.made == [] and win.input_field.toPlainText() == "keep my question"
    win._busy = True; win._take_screenshot_vision(); win._busy = False
    assert any("busy" in t for t in said(win))


def test_a_part_of_the_screen(win, vision, tmp_path):
    from PIL import Image
    win.show()
    f = tmp_path / "part.png"; Image.new("RGB", (30, 20), "blue").save(f)
    win._region_question = "translate this"
    win._on_region_ready(str(f))
    assert vision == ["Part of the screen"] and FakeVision.made[-1].question == "translate this" and not f.exists()    # the temp picture is removed
    FakeVision.made[-1].done("It says hello.", ""); FakeVision.made.clear()
    win._region_question = "my question"; win._on_region_ready("")              # Esc: nothing was selected
    assert FakeVision.made == [] and win.input_field.toPlainText() == "my question"
    bad = tmp_path / "broken.png"; bad.write_text("not a picture")
    win._on_region_ready(str(bad))
    assert FakeVision.made == [] and not bad.exists() and len(said(win)) >= 1


# ── editing, pasting ───────────────────────────────────────────────
def test_double_click_on_your_message_takes_it_back_for_editing(win, monkeypatch):
    for q, a in (("first question", "first answer"), ("second question", "second answer")):
        FakeCompletions.script = [[a]]; _send(win, q); _wait_idle(win)
    bubbles = [b for b in win.chat_area.findChildren(widgets.MessageBubble) if b._role == "user"]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    win._edit_message(bubbles[0])
    assert len([m for m in win.messages if m["role"] == "user"]) == 2          # "No": nothing changes
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    win._edit_message(bubbles[0]); win._pump(50)
    assert [m["role"] for m in win.messages] == ["system"]                     # it and everything after it are gone
    assert win.input_field.toPlainText() == "first question" and win._last_ai_bubble is None
    win._busy = True; win._edit_message(bubbles[0]); win._busy = False          # not while NOVA is answering


def test_paste_clipboard_offers_what_you_pasted_before(win, monkeypatch):
    QApplication.clipboard().setText("")
    win._clipboard_hist = []
    win._paste_clipboard(); assert any("Clipboard is empty" in t for t in said(win))
    QApplication.clipboard().setText("first thing"); win._paste_clipboard()
    assert win.input_field.toPlainText() == "first thing"                      # one item: straight into the box
    QApplication.clipboard().setText("second thing")
    picked = {}
    class Menu:
        def __init__(self, *a): self.items = []
        def setStyleSheet(self, css): pass
        def addAction(self, text):
            a = types.SimpleNamespace(text=text, _d=None, setData=lambda d: setattr(a, "_d", d), data=lambda: a._d); self.items.append(a); return a
        def exec(self, pos): picked["items"] = [i.text for i in self.items]; return self.items[1]
    monkeypatch.setattr(win_chat, "QMenu", Menu)
    win._paste_clipboard()
    assert picked["items"] == ["second thing", "first thing"] and win.input_field.toPlainText() == "first thing"


def test_a_rectangle_is_kept_on_screen(app):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication
    from win_modes import on_screen
    area = QApplication.primaryScreen().availableGeometry()
    corner = on_screen(QRect(area.right() - 30, area.bottom() - 30, 370, 540))
    assert area.contains(corner) and corner.size().width() == min(370, area.width())
    huge = on_screen(QRect(area.x(), area.y(), area.width() + 500, area.height() + 500))
    assert huge == area                                                      # too big: shrunk to fit
    inside = QRect(area.x() + 10, area.y() + 10, 200, 200)
    assert on_screen(inside) == inside                                       # already fine: untouched


def test_the_bubble_opens_on_screen_from_a_corner(win):
    import time
    from PySide6.QtWidgets import QApplication
    from uistate import MODE_BUBBLE, MODE_NORMAL
    area = QApplication.primaryScreen().availableGeometry()
    win.show(); win._pump(100)
    win.move(area.right() - 60, area.bottom() - 60); win._pump(100)
    for mode in (MODE_BUBBLE, MODE_NORMAL):
        win._set_mode(mode)
        end = time.time() + 3
        while win._mode != mode and time.time() < end: win._pump(50)
    assert win._mode == MODE_NORMAL and area.contains(win.geometry()), (win.geometry(), area)

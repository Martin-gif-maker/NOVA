"""The look of the window ("Crafted"): the pieces that are more than paint."""
import datetime
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QMenu
import icons, themes, widgets, win_build
from gui_support import FakeCompletions, _wait_idle, _send


def test_window_buttons_do_what_they_do_on_a_mac(win, monkeypatch):
    called = []
    lights = win_build.TrafficLights(lambda: called.append("hide"), lambda: called.append("small"), lambda: called.append("full"))
    for b in lights.buttons: b.click()
    assert called == ["hide", "small", "full"]
    assert [b.accessibleName() for b in lights.buttons] == ["Hide", "Minimize", "Fullscreen"]      # usable with VoiceOver
    lights.apply(themes.THEMES["soft"]); lights.apply(themes.THEMES["nova"])
    assert win._max_btn is win._lights.zoom                                   # green = full screen, as the window code expects
    win._max_btn.setText("❐"); assert "color:transparent" in win._max_btn.styleSheet()              # a label never shows on the dot


def test_every_icon_draws_in_any_colour(app):
    for name in icons.PATHS:
        pm = icons.pixmap(name, "#1F4FD8", 16)
        assert not pm.isNull() and pm.width() >= 32, name                     # at least 2× for Retina
        img = pm.toImage()
        assert any(img.pixelColor(x, y).alpha() > 0 for x in range(0, img.width(), 2) for y in range(0, img.height(), 2)), name
    assert icons.pixmap("no-such-icon", "#000000").isNull() is False          # an unknown name falls back, it does not crash
    assert icons.pixmap("send", "#ffffff") is icons.pixmap("send", "#ffffff")  # cached


def test_notices_lose_their_emoji_and_failures_are_marked(win):
    assert widgets.tidy_notice("📋  Copied — press ⌘V") == "Copied — press ⌘V"
    assert widgets.tidy_notice("⚠️  No API key.") == "No API key." and widgets.tidy_notice("Plain text") == "Plain text"
    assert widgets.tidy_notice("= 2+2 is fine") == "= 2+2 is fine" and widgets.tidy_notice("“quoted”") == "“quoted”"
    ok = win.chat_area.add_message("🎨  Theme: Paper", "system", win._theme)
    bad = win.chat_area.add_message("❌ The request failed", "system", win._theme)
    assert ok._label.text() == "Theme: Paper" and ok._full_text == "🎨  Theme: Paper"               # the original text is kept
    assert bad._label.text() == "The request failed" and win._theme["bad"] in bad._label.styleSheet()
    assert win._theme["bad"] not in ok._label.styleSheet()
    assert win_build._plain("📰  Daily news") == "Daily news" and win_build._plain("Keyboard shortcuts") == "Keyboard shortcuts"


def test_time_is_shown_between_groups_of_messages_not_on_each_one(win):
    win.chat_area.clear()
    stamps = lambda: [w for w in win.chat_area.widgets_from(win.chat_area._layout.itemAt(0).widget()) if isinstance(w, widgets.DayStamp)]
    win.chat_area.add_message("first", "user", win._theme); win.chat_area.add_message("answer", "assistant", win._theme)
    win.chat_area.add_message("a notice", "system", win._theme); win.chat_area.add_message("second", "user", win._theme)
    assert len(stamps()) == 1 and stamps()[0].text().startswith("Today, ")
    win.chat_area._last_stamp -= datetime.timedelta(minutes=30)               # half an hour of silence
    win.chat_area.add_message("later", "user", win._theme)
    assert len(stamps()) == 2
    now = datetime.datetime(2026, 10, 9, 22, 41)
    assert widgets.DayStamp.wording(datetime.datetime(2026, 10, 9, 8, 5), now) == "Today, 08:05"
    assert widgets.DayStamp.wording(datetime.datetime(2026, 10, 8, 23, 59), now) == "Yesterday, 23:59"
    assert widgets.DayStamp.wording(datetime.datetime(2026, 9, 30, 14, 2), now) == "30 Sep, 14:02"


def test_replies_are_plain_text_with_quiet_tools_and_yours_are_bubbles(win):
    win.resize(420, 620); win.show(); win._pump(150)
    mine = win.chat_area.add_message("hello", "user", win._theme)
    reply = win.chat_area.add_message("Hi **there**\n\n```python\nprint(1)\n```", "assistant", win._theme, markdown=True)
    assert win._theme["user_bg"] in mine.styleSheet() and "transparent" in reply.styleSheet()
    assert reply._who.text() == "NOVA" and [b.accessibleName() for b in reply._act_btns] == ["Copy response", "Read aloud"]
    assert not reply._code_copy_btn.isHidden() and all(not b.icon().isNull() for b in reply._act_btns)
    assert mine.maximumWidth() < reply.maximumWidth()                         # your bubble is narrower than NOVA's column
    win._last_ai_bubble = reply; win._show_regen_btn()
    assert reply._act_btns[-1].accessibleName() == "Regenerate"
    older = reply; newer = win.chat_area.add_message("newer", "assistant", win._theme)
    win._last_ai_bubble = newer; win._show_regen_btn(); win._pump(50)
    assert newer._act_btns[-1].accessibleName() == "Regenerate"               # only the newest reply offers it
    assert sum(1 for b in older._act_btns if b.accessibleName() == "Regenerate" and not b.isHidden()) == 0


def test_send_button_becomes_stop_while_nova_works(win):
    FakeCompletions.script = [["SLEEP", "SLEEP", "done"]]
    _send(win, "hi"); win._pump(60)
    assert win.send_btn.accessibleName() == "Stop" and not win.send_btn.icon().isNull()
    _wait_idle(win)
    assert win.send_btn.accessibleName() == "Send message" and win._theme["send_bg"] in win.send_btn.styleSheet()


def test_menus_have_icons_and_no_emoji(win, monkeypatch):
    shown = []
    class Quiet(QMenu):                                    # a menu that notes it was opened instead of waiting for a click
        def exec(self, *a): shown.append(self)
    def quiet_menu():
        m = Quiet(win); m.setStyleSheet(win._menu_css()); return m
    monkeypatch.setattr(win, "_menu", quiet_menu)
    win._show_plus_menu(); win._show_overflow_menu(); win._show_model_menu()
    plus, more, model = shown
    for menu in shown:
        for a in menu.actions():
            if a.isSeparator(): continue
            assert a.text()[0].isalnum() or a.text()[0] in "(/", a.text()       # no emoji in front
            assert not a.icon().isNull(), a.text()
    assert [a.text() for a in plus.actions() if not a.isSeparator()][:4] == ["Analyze file", "Analyze screen", "Analyze part of the screen", "Paste clipboard"]
    assert any(a.text().startswith("Theme: ") for a in more.actions()) and any(a.text() in ("Keep on top", "Do not keep on top") for a in more.actions())
    assert [a.text() for a in model.actions() if not a.isSeparator()][:5] == ["Assistant", "Coder", "Translator", "Tutor", "Writer"]


def test_four_palettes_two_light_two_dark_all_readable():
    labels = [themes.THEMES[k]["label"] for k in themes.THEME_ORDER]
    assert labels == ["Paper", "Graphite", "Sage", "Espresso"]
    assert [themes.THEMES[k]["dark"] for k in themes.THEME_ORDER] == [False, True, False, True]
    for t in themes.THEMES.values():
        assert themes.contrast(t["ai_fg"], t["frame_bg"]) >= 7 and themes.contrast(t["user_fg"], t["user_bg"]) >= 7
        assert themes.contrast(t["sys_fg"], t["frame_bg"]) >= 4.5 and themes.contrast(t["sys_fg"], t["ai_bg"]) >= 4.5
        assert themes.contrast(t["ok"], t["ai_bg"]) >= 3 and themes.contrast(t["bad"], t["ai_bg"]) >= 3     # the tick and the cross

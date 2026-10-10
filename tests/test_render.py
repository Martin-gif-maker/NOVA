"""Rendering checks: paint the real widgets off-screen and look at the pixels and the layout."""
import pytest
pytest.importorskip("PySide6")
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QAbstractButton, QComboBox
import settings_dialog, themes, dialogs, onboarding


def _colors(image, step=7):
    seen = set()
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            seen.add(image.pixel(x, y))
    return seen


def _close(a: QColor, b: QColor, tol=24) -> bool:
    return abs(a.red() - b.red()) <= tol and abs(a.green() - b.green()) <= tol and abs(a.blue() - b.blue()) <= tol


def _has_color(image, hex_color, step=5) -> bool:
    want = QColor(hex_color)
    return any(_close(QColor(image.pixel(x, y)), want) for y in range(0, image.height(), step) for x in range(0, image.width(), step))


@pytest.mark.parametrize("theme_key", themes.THEME_ORDER)
def test_main_window_paints_in_every_theme(win, theme_key):
    win._theme_key = theme_key; win._theme = win._resolve_theme(); win._apply_theme()
    win.chat_area.add_message("Hello NOVA, what can you do?", "user", win._theme)
    win.chat_area.add_message("I can **help** with `code`:\n\n```python\nprint('hi')\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |", "assistant", win._theme, markdown=True)
    win.resize(420, 620); win.show(); win._pump(250)
    img = win.grab().toImage()
    assert img.width() >= 400 and img.height() >= 600
    assert len(_colors(img)) > 25                                           # really painted, not one flat colour
    assert _has_color(img, win._theme["frame_bg"]) and _has_color(img, win._theme["ai_bg"])


def test_bubbles_are_not_clipped_and_stay_inside_the_window(win):
    long = "A long reply. " * 80
    b = win.chat_area.add_message(long, "assistant", win._theme, markdown=True)
    win.resize(380, 560); win.show(); win._pump(250)
    assert b.width() <= win.chat_area.viewport().width()                    # no horizontal overflow
    need = b._label.needed_height()
    assert need > 400 and need - 1 <= b._label.height() <= need + 4         # the whole text has room, and no more
    win.resize(900, 560); win._pump(300)                                    # wider window: the bubble gets shorter again
    wide = b._label.needed_height()
    assert wide < need and wide - 1 <= b._label.height() <= wide + 4
    u = win.chat_area.add_message("my question " * 120, "user", win._theme)
    win.resize(380, 560); win._pump(300)
    assert u._label.height() >= u._label.needed_height() - 1 and u.width() <= win.chat_area.viewport().width()


def test_streamed_reply_keeps_growing_to_fit(win):
    win.resize(380, 560); win.show(); win._pump(150)
    b = win.chat_area.add_message("", "assistant", win._theme)
    text = "Streaming words keep arriving. " * 90
    for i in range(0, len(text), 240):
        b.append_text(text[i:i + 240]); win._pump(90)
        assert b._label.height() >= b._label.needed_height() - 1            # never cut off mid-stream
    b.render_markdown(); win._pump(200)
    assert b._label.height() >= b._label.needed_height() - 1 > 400


@pytest.mark.parametrize("lang", ["en", "bg"])
def test_settings_tabs_render_and_nothing_is_cut_off(app, monkeypatch, lang):
    import i18n
    monkeypatch.setattr(settings_dialog.plat, "autostart_enabled", lambda: False)
    monkeypatch.setattr(i18n, "_LANG", lang)                                # longer Bulgarian text must fit too
    for key in ("nova", "soft"):
        d = settings_dialog.SettingsDialog({"always_allow": ["type:app:Notes"]}, themes.THEMES[key])
        d.show(); app.processEvents()
        for i in range(d.tabs.count()):
            d.tabs.setCurrentIndex(i)
            for _ in range(6): app.processEvents()                          # let wrapped labels settle
            img = d.grab().toImage()
            assert len(_colors(img)) > 12, d.tabs.tabText(i)
            page = d.tabs.widget(i)
            for cb in page.findChildren(QComboBox):
                if cb.isVisible() and not cb.isEditable():
                    assert cb.width() >= cb.sizeHint().width() - 2, (d.tabs.tabText(i), cb.currentText())  # choice text not cut off
            for w in page.findChildren(QLabel) + page.findChildren(QAbstractButton):
                if not w.isVisible() or not w.text(): continue
                assert w.geometry().right() <= page.width() + 1, (d.tabs.tabText(i), w.text()[:40])     # inside the page
                if isinstance(w, QAbstractButton) or not w.wordWrap():
                    assert w.width() >= w.sizeHint().width() - 2, (d.tabs.tabText(i), w.text())           # text not truncated
                else:
                    assert w.height() >= w.heightForWidth(w.width()) - 2, (d.tabs.tabText(i), w.text()[:40])   # wrapped text has room
        d.close()


def test_readable_text_contrast_in_every_theme():
    for key, t in themes.THEMES.items():
        for fg, bg in (("ai_fg", "ai_bg"), ("user_fg", "user_bg"), ("sys_fg", "frame_bg"), ("accent_fg", "frame_bg")):
            if fg in t and bg in t:
                assert themes.contrast(t[fg], t[bg]) >= 4.5, (key, fg, bg)


def test_dialogs_render(app, tmp_path):
    t = themes.THEMES["ember"]
    for d in (dialogs.MemoriesDialog(t, ["[01.01.2026] likes tea", "works at night"]), dialogs.SentDialog(t),
              dialogs.SessionsDialog(t, str(tmp_path)), onboarding.OnboardingDialog(t)):
        d.show(); app.processEvents()
        img = d.grab().toImage()
        assert img.width() > 200 and len(_colors(img)) > 6, type(d).__name__
        d.close()

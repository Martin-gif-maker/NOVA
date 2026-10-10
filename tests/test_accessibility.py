"""VoiceOver must be able to name every control: a button that is only an emoji, or an unlabeled field, fails here."""
import re
import pytest
pytest.importorskip("PySide6")
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QLineEdit, QTextEdit, QAbstractSpinBox, QListWidget, QTableWidget,
                               QTabWidget, QWidget)
import dialogs, onboarding, settings_dialog, themes

CONTROLS = (QAbstractButton, QComboBox, QLineEdit, QTextEdit, QAbstractSpinBox, QListWidget, QTableWidget, QTabWidget)
WORD = re.compile(r"[^\W\d_]{2,}", re.UNICODE)          # at least two letters in a row, in any alphabet


def spoken_name(w: QWidget) -> str:
    """What assistive technology announces for this widget."""
    iface = QAccessible.queryAccessibleInterface(w)
    name = (iface.text(QAccessible.Text.Name) if iface else "") or w.accessibleName()
    return name.strip()


def unnamed_controls(root: QWidget) -> list:
    bad = []
    for w in root.findChildren(QWidget):
        if not isinstance(w, CONTROLS): continue
        parent = w.parent()
        if isinstance(parent, (QComboBox, QAbstractSpinBox)) or w.objectName().startswith("qt_"):
            continue                                     # Qt's own inner parts (the text field inside a spin box …)
        if not WORD.search(spoken_name(w)):
            bad.append(f"{type(w).__name__}  text={getattr(w, 'text', lambda: '')()!r}  tooltip={w.toolTip()!r}")
    return bad


def test_main_window_controls_are_named(win):
    assert unnamed_controls(win) == []


def test_settings_controls_are_named(app, monkeypatch):
    monkeypatch.setattr(settings_dialog.plat, "autostart_enabled", lambda: False)
    d = settings_dialog.SettingsDialog({"always_allow": ["type:app:Notes"]}, themes.THEMES["nova"])
    assert unnamed_controls(d) == []


def test_wizard_controls_are_named(app):
    d = onboarding.OnboardingDialog(themes.THEMES["nova"])
    assert unnamed_controls(d) == []


def test_dialog_controls_are_named(app, tmp_path):
    t = themes.THEMES["nova"]
    for d in (dialogs.SessionsDialog(t, str(tmp_path)), dialogs.MemoriesDialog(t, ["[01.01.2026] likes tea"]),
              dialogs.MemoryEditDialog(t), dialogs.SentDialog(t), dialogs.TextViewDialog(t, "Activity log", "x")):
        assert unnamed_controls(d) == [], type(d).__name__


def test_message_bubble_buttons_are_named(win):
    b = win.chat_area.add_message("hello **there**", "assistant", win._theme, markdown=True)
    assert unnamed_controls(b) == []
    win._tool_log = [("read_file", {"path": "/tmp/x"}, True, "ok")]; win._show_tool_activity()      # the "what NOVA did" line
    assert win._last_tool_widget is not None and unnamed_controls(win.chat_area) == []

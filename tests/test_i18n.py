"""Every piece of interface text has a Bulgarian translation, and switching language really changes the UI."""
import ast, glob, os
import pytest
import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_FILES = {"i18n.py"}


def _literals():
    """Every string literal handed to tr() (or to the settings `_row` helper, which calls tr)."""
    found = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "*.py"))):
        name = os.path.basename(path)
        if name in SKIP_FILES: continue
        for node in ast.walk(ast.parse(open(path, encoding="utf-8").read())):
            if not isinstance(node, ast.Call): continue
            fn = node.func
            called = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            arg = node.args[0] if called == "tr" and node.args else node.args[1] if called == "_row" and len(node.args) >= 2 else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.strip():
                found.setdefault(arg.value, f"{name}:{node.lineno}")
    return found


def _dynamic():
    """Text that reaches tr() through a variable."""
    import memory, sandbox, dialogs, providers, tools
    out = list(memory.LABELS.values()) + list(sandbox.PERMISSIONS.values())
    out += [label for label, _ in dialogs.MemoryEditDialog.KEEP] + [label for label, _ in dialogs.SentDialog.PERIODS]
    out += [label for label, _ in dialogs.UsageDialog.PERIODS]
    import actions
    out += list(actions.TITLES) + list(actions.DOING)
    out += ["Tell me when there is a new version", "Install new versions by themselves", "Do not check", "Updates:"]
    import whatsnew
    out += [line for lines in whatsnew.NOTES.values() for line in lines]
    out += ["Genius! 🧠", "Magnificent! 🎉", "Impressive! 👏", "Splendid! 😊", "Great! 👍", "Phew! 😅", "Too low ⬆️", "Too high ⬇️"]      # games
    out += list(providers.FRIENDLY.values()) + [tools.TAINT_WARNING.strip()]
    out += ["Best model:", "Fast model:", "Third model:", "Fast (recommended)", "Balanced", "Deep (slowest)", "Auto-detect",
            "English", "Bulgarian", "German", "French", "Spanish", "Russian", "Short", "Normal", "Detailed"]
    out += ["chat", "image analysis", "model list", "speech-to-text", "read aloud", "web search", "read web page", "weather",
            "news headlines", "update check", "update download", "voice model download", "crash report", "plugin with internet access"]
    for key in ("files:dir:/x", "type:app:Notes", "control_system:sleep", "other", "type_text_keyboard", "write_file:new_or_append",
                "mcp:server:tool", "shortcut:My shortcut"):
        out += [tools.approval_label_parts(key)[0], tools.describe_allowance_parts(key)[0]]
    out += ["Run shell command", "Run Python code", "Create file", "Overwrite file", "Append to file", "Kill process", "System action",
            "Permanently empty the Trash", "delete file(s)", "move file(s)", "rename file(s)", "Remember", "Forget memories containing"]
    import win_selection, schedule
    out += [label for _k, label, _i, _c in win_selection.SELECTION_ACTIONS]
    out += [label for label, _v in dialogs.ScheduleEditDialog.REPEATS] + ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for days in ("daily", "weekdays", "weekends", "once", "mon,wed"):
        out.append(schedule.describe_parts({"days": days, "time": "08:00", "date": "2026-10-09"})[0])
    return [o for o in out if o not in ("other",)]


def test_every_interface_string_is_translated():
    missing = [f"{where}  {text!r}" for text, where in _literals().items() if not i18n.translated(text)]
    missing += [f"(dynamic)  {text!r}" for text in _dynamic() if not i18n.translated(text)]
    assert not missing, "no Bulgarian translation for:\n" + "\n".join(missing)


def test_placeholders_survive_translation():
    for en, bg in i18n.BG.items():
        if en == "PRIVACY": continue
        assert en.count("{}") == bg.count("{}"), en
        assert en.count("\n") == bg.count("\n"), en


def test_no_translation_is_defined_twice():
    tree = ast.parse(open(os.path.join(ROOT, "i18n.py"), encoding="utf-8").read())
    keys = [k.value for node in ast.walk(tree) if isinstance(node, ast.Dict) for k in node.keys if isinstance(k, ast.Constant)]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert not dupes, dupes


@pytest.fixture
def bulgarian():
    i18n.set_language("bg")
    yield
    i18n.set_language("en")


def test_lookup_keeps_decoration_and_falls_back(bulgarian):
    assert i18n.tr("Settings") == "Настройки" and i18n.tr("⚙  Settings") == "⚙  Настройки"
    assert i18n.tr("Home city:") == "Твоят град:" and i18n.tr("Totally unknown text") == "Totally unknown text"
    assert i18n.tr("Until {}").format("2026-12-01") == "До 2026-12-01"


def test_settings_window_is_bulgarian(bulgarian, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QLabel, QCheckBox, QPushButton
    import settings_dialog, themes
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_dialog.plat, "autostart_enabled", lambda: False)
    d = settings_dialog.SettingsDialog({"always_allow": ["type:app:Notes"]}, themes.THEMES["nova"])
    assert [d.tabs.tabText(i) for i in range(d.tabs.count())] == ["Общи", "AI", "Гласов вход", "Поверителност", "Данни"]
    assert d._allow_list.item(0).text() == "Въвеждане в Notes"
    import re
    english = []
    for w in d.findChildren(QLabel) + d.findChildren(QCheckBox) + d.findChildren(QPushButton):
        text = w.text().strip()
        if text and re.search(r"[A-Za-z]{4,}", text) and not re.search(r"[А-Яа-я]", text):
            english.append(text)
    allowed = {"Save", "Cancel"}                         # Qt's own dialog buttons follow the system language
    assert [t for t in english if t not in allowed and "NOVA" not in t and "API" not in t] == []


def test_approval_prompt_is_translated(bulgarian):
    import tools, win_approvals
    loc = win_approvals.ApprovalsMixin._localize_desc
    assert loc("Run shell command:\nls -la") == "Изпълни команда в терминала:\nls -la"
    assert loc(tools.TAINT_WARNING + "Overwrite file:\n/tmp/x").startswith("⚠️ По-рано в тази заявка")
    assert loc("Type into Notes:\nhello") == "Type into Notes:\nhello"          # unknown heading: left as it is
    template, arg = tools.approval_label_parts("files:dir:/tmp/proj")
    assert i18n.tr(template).format(arg) == "Винаги разрешавай в /tmp/proj"

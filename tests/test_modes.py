"""Modes (Coder, Translator, …, your own) and saved prompts (/name)."""
import modes, prompts


def test_slash_commands():
    P = {"tldr": "Summarize:", "Fix Code": "Fix this:"}
    assert modes.expand_slash("/tldr the long text", P) == ("expanded", "Summarize:\n\nthe long text")
    assert modes.expand_slash("/TLDR", P) == ("expanded", "Summarize:")
    assert modes.expand_slash("/fix-code\nprint(1)", P) == ("expanded", "Fix this:\n\nprint(1)")
    assert modes.expand_slash("/", P) == ("list", ["fix-code", "tldr"]) and modes.expand_slash("/nope", P)[0] == "list"
    for plain in ("/Users/me/file.txt what is this", "/etc/hosts", "//comment", "hello /tldr", "/nope and more words", "2/3 is a fraction"):
        assert modes.expand_slash(plain, P) == ("plain", plain)
    assert modes.expand_slash("/x", {}) == ("list", [])


def test_modes_table_and_names():
    table = modes.all_modes({"Lawyer": "Answer like a careful contract lawyer.", "coder": "tries to replace a built-in", "empty": "  "})
    assert list(table)[:5] == ["default", "coder", "translator", "tutor", "writer"] and "lawyer" in table and "empty" not in table
    assert table["coder"]["custom"] is False and "working, complete code" in table["coder"]["prompt"]      # built-ins cannot be overwritten
    assert table["lawyer"]["prompt"] == "MODE: LAWYER. Answer like a careful contract lawyer." and table["lawyer"]["custom"] is True
    assert modes.mode_prompt("nonsense") == "" and modes.mode_label("tutor") == "Tutor"
    assert modes.clean_name("  Fix My Code! ") == "fix-my-code" and modes.clean_name("Резюме") == "резюме"


def test_mode_text_sits_before_the_date_so_the_stable_part_can_be_cached(monkeypatch):
    monkeypatch.setattr(prompts, "MODE_PROMPT", "MODE: TUTOR. Teach.")
    p = prompts._build_prompt()
    assert p.index("MODE: TUTOR") < p.index("CURRENT DATE & TIME")
    monkeypatch.setattr(prompts, "MODE_PROMPT", "")
    assert "MODE:" not in prompts._build_prompt()


# ── in the window ──────────────────────────────────────────────────
def test_switching_mode_changes_prompt_label_and_is_saved(win):
    import json, paths
    assert "MODE:" not in win.messages[0]["content"] and "·" not in win._model_lbl.text()
    win._set_persona("coder")
    assert "MODE: CODER" in win.messages[0]["content"] and win._model_lbl.text().endswith("· Coder")
    assert json.load(open(paths.CONFIG_FILE))["mode"] == "coder"
    win._switch_model(); assert win._model_lbl.text().endswith("· Coder")              # the label keeps the mode
    win._set_persona("default")
    assert "MODE:" not in win.messages[0]["content"] and "·" not in win._model_lbl.text()
    win.config["mode"] = "deleted-custom-mode"; win._apply_persona()
    assert win.config["mode"] == "default"                                               # an unknown mode falls back safely
    prompts.MODE_PROMPT = ""


def test_slash_prompt_is_expanded_when_sending(win):
    from gui_support import FakeCompletions, _send, _wait_idle
    FakeCompletions.script = [["• one"]]
    _send(win, "/tldr The quick brown fox jumps over the lazy dog."); _wait_idle(win)
    user = [m for m in win.messages if m["role"] == "user"][-1]["content"]
    assert user == "Summarize the following in three short bullet points:\n\nThe quick brown fox jumps over the lazy dog."
    n = len(win.messages)
    _send(win, "/"); win._pump(50)
    assert len(win.messages) == n and not win._busy                                      # only a list was shown
    texts = [w._full_text for w in win.chat_area.findChildren(type(win._last_ai_bubble))]
    assert any("/tldr" in t and "/eli5" in t and "/fix" in t for t in texts)
    FakeCompletions.script = [["it is a folder"]]
    _send(win, "/Users/me/Documents what is in here"); _wait_idle(win)
    assert win.messages[-2]["content"] == "/Users/me/Documents what is in here"          # paths are left alone


def test_saved_prompt_from_the_menu_goes_into_the_box(win):
    win.input_field.setText("my code here")
    win._insert_saved_prompt("fix")
    assert win.input_field.toPlainText().startswith("Find and fix the problems") and win.input_field.toPlainText().endswith("my code here")


def test_mode_menu_lists_everything(win):
    from PySide6.QtWidgets import QMenu
    win.config["custom_modes"] = {"Lawyer": "Be precise."}
    menu = QMenu(); win._add_mode_menu(menu)
    subs = [a.menu() for a in menu.actions() if a.menu()]
    mode_items = [a.text().strip() for a in subs[0].actions()]
    assert mode_items == ["Assistant", "Coder", "Translator", "Tutor", "Writer", "Lawyer"]
    assert [a.text() for a in menu.actions() if a.menu()] == ["Mode", "Saved prompts"]              # no emoji in front any more
    prompt_items = [a.text() for a in subs[1].actions() if not a.isSeparator()]
    assert prompt_items[:3] == ["/eli5", "/fix", "/tldr"] and prompt_items[-1].startswith("Edit modes and prompts")


def test_prompts_dialog_add_edit_delete(app, monkeypatch):
    import dialogs, themes
    d = dialogs.PromptsDialog(themes.THEMES["nova"], {"Lawyer": "Be precise."}, {"tldr": "Summarize:"})
    answers = iter([("Email Reply", "Write a polite reply to this email:"), ("tldr", "Summarize in one line:"), ("Coder", "my own coder"), ("", "no name")])
    monkeypatch.setattr(dialogs.PromptsDialog, "_ask", lambda self, kind, name="", text="": next(answers))
    d._add("prompts")
    assert d.prompts_result() == {"tldr": "Summarize:", "email-reply": "Write a polite reply to this email:"}
    d.lists["prompts"].setCurrentRow(1); d._edit("prompts")
    assert d.prompts_result()["tldr"] == "Summarize in one line:"
    d._add("modes"); assert "Coder 2" in d.modes_result() and "Coder" not in d.modes_result()      # cannot shadow a built-in mode
    d._add("modes"); assert len(d.modes_result()) == 2                                             # a nameless entry is ignored
    d.lists["modes"].setCurrentRow(0); d._delete("modes"); assert len(d.modes_result()) == 1
    f = dialogs.NamedTextDialog(themes.THEMES["nova"], "t", "Name", "Text", " n ", " body ")
    assert f.values() == ("n", "body")

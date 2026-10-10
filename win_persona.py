# win_persona.py — modes (Coder, Translator, Tutor, Writer, your own) and saved prompts (/name).
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
import logging
from PySide6.QtWidgets import QDialog
import modes
import prompts
from i18n import tr
from models import MODELS
from prompts import _build_prompt
from dialogs import PromptsDialog

log = logging.getLogger("nova")


class PersonaMixin:
    # ── modes ────────────────────────────────────────────────────
    def _apply_persona(self):
        """Put the active mode's instructions into the system prompt (and the title bar)."""
        key = self.config.get("mode", modes.DEFAULT)
        table = modes.all_modes(self.config.get("custom_modes", {}))
        if key not in table:
            key = self.config["mode"] = modes.DEFAULT
        prompts.MODE_PROMPT = table[key]["prompt"]
        if getattr(self, "messages", None):
            self.messages[0] = {"role": "system", "content": _build_prompt()}
        self._refresh_model_label()

    def _refresh_model_label(self):
        if not hasattr(self, "_model_lbl"): return
        key = self.config.get("mode", modes.DEFAULT)
        label = MODELS[self._model_key][1]
        if key != modes.DEFAULT:
            label += " · " + tr(modes.mode_label(key, self.config.get("custom_modes", {})))
        self._model_lbl.setText(label)

    def _set_persona(self, key: str):
        if key == self.config.get("mode", modes.DEFAULT): return
        self.config["mode"] = key
        self._apply_persona(); self._save_config()
        self.chat_area.add_message(tr("🎭  Mode: {}").format(tr(modes.mode_label(self.config["mode"], self.config.get("custom_modes", {})))),
                                   "system", self._theme)

    def _add_mode_items(self, menu):
        """One line per mode (the current one ticked)."""
        import icons
        current = self.config.get("mode", modes.DEFAULT)
        for key, m in modes.all_modes(self.config.get("custom_modes", {})).items():
            a = menu.addAction(tr(m["label"]))
            a.setIcon(icons.icon("check", self._theme["ai_fg"] if key == current else "#00000000"))
            a.triggered.connect(lambda _=False, k=key: self._set_persona(k))

    def _add_mode_menu(self, menu):
        """Fill the Mode and Saved prompts sub-menus of the ＋ menu."""
        import icons
        from win_build import _plain
        sub = menu.addMenu(icons.icon("sliders", self._theme["ai_fg"]), _plain(tr("🎭  Mode"))); sub.setStyleSheet(menu.styleSheet())
        self._add_mode_items(sub)
        saved = self.config.get("saved_prompts", {})
        sub2 = menu.addMenu(icons.icon("lines", self._theme["ai_fg"]), _plain(tr("💬  Saved prompts"))); sub2.setStyleSheet(menu.styleSheet())
        for name in sorted(saved):
            sub2.addAction("/" + modes.clean_name(name)).triggered.connect(lambda _=False, n=name: self._insert_saved_prompt(n))
        if saved: sub2.addSeparator()
        sub2.addAction(tr("Edit modes and prompts") + "…").triggered.connect(self._show_prompts_dialog)

    # ── saved prompts ────────────────────────────────────────────
    def _insert_saved_prompt(self, name: str):
        text = str(self.config.get("saved_prompts", {}).get(name, "")).strip()
        if not text: return
        have = self.input_field.toPlainText().strip()
        self.input_field.setPlainText(text + ("\n\n" + have if have else " "))
        cursor = self.input_field.textCursor(); cursor.movePosition(cursor.MoveOperation.End); self.input_field.setTextCursor(cursor)
        self.input_field.setFocus()

    def _expand_slash(self, text: str):
        """Returns the text to send, or None if the message was a '/…' that only needed a list shown."""
        kind, value = modes.expand_slash(text, self.config.get("saved_prompts", {}))
        if kind == "plain": return text
        if kind == "expanded": return value
        names = "  ".join("/" + n for n in value) or tr("none yet")
        self.chat_area.add_message(tr("💬  Saved prompts: {}").format(names) + "\n" +
                                   tr("Type /name followed by your text. Add your own under ＋ → Saved prompts."), "system", self._theme)
        return None

    def _show_prompts_dialog(self, tab: str = ""):
        if tab: self._bring_to_front()                    # opened from the selected-text menu, perhaps while NOVA was hidden
        dlg = PromptsDialog(self._theme, self.config.get("custom_modes", {}), self.config.get("saved_prompts", {}), self,
                            self.config.get("selection_custom", {}), tab if isinstance(tab, str) else "")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.config["custom_modes"] = dlg.modes_result()
            self.config["saved_prompts"] = dlg.prompts_result()
            self.config["selection_custom"] = dlg.actions_result()
            self._apply_persona(); self._save_config()

# win_selection.py — act on text selected in any app: press the hotkey, pick Explain / Translate / Rewrite …
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
import os
import logging
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMenu
from PySide6.QtGui import QCursor
import platform_utils as plat
import i18n
from i18n import tr

log = logging.getLogger("nova")

MAX_SELECTION = 12000

# key, menu label, instruction sent to the AI, copy the answer to the clipboard afterwards?
SELECTION_ACTIONS = [
    ("explain",   "Explain",     "Explain this clearly and briefly:", False),
    ("summarize", "Summarize",   "Summarize this in a few short bullet points:", False),
    ("translate", "Translate",   "", True),
    ("rewrite",   "Rewrite",     "Rewrite this so it is clearer and reads well. Keep the meaning, the tone and the language. "
                                 "Reply with the rewritten text only:", True),
    ("grammar",   "Fix grammar", "Correct the spelling and grammar of this text. Change nothing else and keep the language. "
                                 "Reply with the corrected text only:", True),
]


def _translate_instruction() -> str:
    if i18n.language() == "bg":
        return "Translate this text to Bulgarian (if it is already Bulgarian, translate it to English). Reply with the translation only:"
    return "Translate this text to English (if it is already English, translate it to Bulgarian). Reply with the translation only:"


class SelectionMixin:
    def _selection_callback(self):
        """One stable callable for the hotkey (a signal's .emit is a new object on every access)."""
        cb = getattr(self, "_selection_cb", None)
        if cb is None:
            cb = self._selection_cb = self._bridge.selection_hotkey.emit
        return cb

    def _setup_selection_hotkey(self):
        plat.remove_global_hotkey(self._selection_callback())               # never registered twice
        if plat.IS_MAC and self.config.get("selection_actions", True):
            plat.add_global_hotkey(49, plat._SELECTION_HOTKEY_MODS, self._selection_callback())

    def _apply_selection_setting(self):
        self._setup_selection_hotkey()

    def _on_selection_hotkey(self):
        """The hotkey was pressed somewhere: fetch what is selected there and offer what to do with it."""
        source = plat.frontmost_pid()             # the app the text is in - before NOVA comes to the front
        self._selection_source = source if source != os.getpid() else 0
        text = plat.selected_text()
        if not text:
            plat.notify("NOVA", tr("Select some text first, then press {}.").format(plat.SELECTION_HOTKEY_LABEL))
            return
        self._selection_menu(text[:MAX_SELECTION]).popup(QCursor.pos())
        plat.activate_app()                       # so the menu takes clicks and Esc

    def _selection_menu(self, text: str) -> QMenu:
        t = self._theme
        menu = QMenu()                            # no parent: it may appear while the NOVA window is hidden
        menu.setStyleSheet(f"QMenu{{background:{t['bar_bg']};border:1px solid {t['ai_br']};border-radius:10px;"
                           f"color:{t['ai_fg']};font-size:12px;padding:6px;}}"
                           f"QMenu::item{{padding:7px 18px;border-radius:6px;}}"
                           f"QMenu::item:selected{{background:{t['frame_bg']};}}"
                           f"QMenu::item:disabled{{color:{t['sys_fg']};}}"
                           f"QMenu::separator{{height:1px;background:{t['ai_br']};margin:4px 8px;}}")
        snippet = " ".join(text.split())
        head = menu.addAction("“" + snippet[:48] + ("…" if len(snippet) > 48 else "") + "”"); head.setEnabled(False)
        menu.addSeparator()
        for key, label, _instruction, _copy in SELECTION_ACTIONS:
            menu.addAction(tr(label)).triggered.connect(lambda _=False, k=key: self._run_selection_action(k, text))
        mine = self._custom_selection_actions()
        if mine: menu.addSeparator()
        for name in mine:                         # your own actions, by the name you gave them
            menu.addAction(name).triggered.connect(lambda _=False, k="custom:" + name: self._run_selection_action(k, text))
        menu.addSeparator()
        menu.addAction(tr("Ask NOVA about it") + "…").triggered.connect(lambda: self._selection_to_input(text))
        menu.addAction(tr("My actions") + "…").triggered.connect(lambda: self._show_prompts_dialog("actions"))
        self._selection_menu_ref = menu           # keep it alive while it is on screen
        return menu

    def _selection_to_input(self, text: str):
        self._bring_to_front()
        self.input_field.setPlainText("\n\n“" + text + "”")
        cursor = self.input_field.textCursor(); cursor.setPosition(0); self.input_field.setTextCursor(cursor)
        self.input_field.setFocus()

    def _custom_selection_actions(self) -> dict:
        from dialogs import clean_actions
        return clean_actions(self.config.get("selection_custom", {}))

    def _run_selection_action(self, key: str, text: str):
        if key.startswith("custom:"):             # one of your own: the name is shown as you wrote it
            mine = self._custom_selection_actions().get(key[7:])
            action = (key, key[7:], mine["prompt"], mine["replace"]) if mine else None
            shown = key[7:]
        else:
            action = next((a for a in SELECTION_ACTIONS if a[0] == key), None)
            shown = tr(action[1]) if action else ""
        if action is None or not text.strip(): return
        _key, label, instruction, copy_back = action
        if key == "translate": instruction = _translate_instruction()
        self._bring_to_front()
        if not self.client:
            self.chat_area.add_message(tr("⚠️  No API key."), "system", self._theme); return
        if self._busy:
            self.chat_area.add_message(tr("Still working on your previous request - wait for it or press the stop button."), "system", self._theme); return
        self._last_user_msg = f"{instruction}\n\n{text}"
        self.chat_area.add_message(f"**{shown}:**\n\n{text}", "user", self._theme)
        self.messages.append({"role": "user", "content": f"{instruction}\n\n\"\"\"\n{text}\n\"\"\""})
        self._update_ctx_counter()
        self._refresh_prompt(text[:400])
        self._request_untrusted = "selected text"     # it came from another app: risky tools will ask first
        self._reply_hook = self._copy_reply if copy_back else None
        self._start_ai()

    # ── requests from other programs (Shortcuts, scripts, nova:// links) ──
    def _external_message(self, msg: dict, reply=None):
        """A message from another copy of NOVA (`--ask`). `reply` is set when that copy waits for the answer."""
        self._external_ask(msg.get("ask", ""), reply)

    def _external_ask(self, text: str, reply=None):
        """Text handed over from outside. It is only sent by itself if you turned that on; either way risky tools
        ask first, because NOVA cannot know who wrote the text. A caller that waits (`--wait`) gets the answer
        when there is one, or the reason there is none."""
        text = str(text or "").strip()[:8000]
        if not text:
            if reply: reply.fail("No text was given.")
            return
        log.info("request received from another program (%d characters%s)", len(text), ", waiting for the answer" if reply else "")
        self._external_finish(error="A newer request took its place.")       # one waiting caller at a time
        self._bring_to_front()
        self.input_field.setText(text)
        if reply and not self.client:
            reply.fail("NOVA has no API key yet. Open NOVA and add one in Settings."); reply = None
        self._external_reply = reply
        if self.config.get("external_autosend", False) and self.client and not self._busy:
            self._request_untrusted = "another program"
            self._send()
        else:
            self._pending_external = True
            self.input_field.setFocus()
            self.chat_area.add_message(tr("↪  Received from another app — check the text below and press Enter to send it."),
                                       "system", self._theme)

    def _external_finish(self, text: str = "", error: str = ""):
        """Answer the caller that is waiting for this request, if there is one."""
        reply, self._external_reply = getattr(self, "_external_reply", None), None
        self._external_running = False
        if reply is None or not reply.alive(): return
        if text.strip(): reply.send(text.strip())
        else: reply.fail(error or "NOVA gave no answer.")

    def _copy_reply(self, reply: str):
        """A rewrite / translation is ready: copy it - and, if you chose that in Settings, paste it over the selection."""
        QApplication.clipboard().setText(reply.strip())
        source, self._selection_source = getattr(self, "_selection_source", 0), 0
        front = plat.frontmost_pid()
        # Paste only where the text came from, and only if you are still there (or looking at NOVA): never into
        # some third app you have moved on to.
        if self.config.get("selection_paste", False) and source and front in (source, os.getpid()) and plat.activate_pid(source):
            QTimer.singleShot(350, lambda: self._paste_reply(source))
        else:
            self._say_copied()

    def _paste_reply(self, source: int):
        if plat.frontmost_pid() == source and plat.press_paste():
            self.chat_area.add_message(tr("📋  Pasted over your selection (it is also on the clipboard)."), "system", self._theme)
        else:
            self._say_copied()

    def _say_copied(self):
        self.chat_area.add_message(tr("📋  Copied — press {} in the other app to paste it over your selection.").format(plat.shortcut_label("V")),
                                   "system", self._theme)

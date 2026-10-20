# win_approvals.py — approval prompts for risky tools, plugin consent, reminders.
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
import html
import threading
import logging
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt, QTimer
import tools as computer_tools
import platform_utils as plat
import paths
import tts
import storage
import sandbox
from dialogs import TextViewDialog, SentDialog, format_activity
from i18n import tr
from schemas import TOOLS_SCHEMA

log = logging.getLogger("nova")


class ApprovalsMixin:
    # ── Tool hooks: confirmations, reminders, typing focus ───────
    def _install_hooks(self):
        computer_tools.CONFIRM_HOOK  = self._confirm_from_tool
        computer_tools.REMINDER_HOOK = self._bridge.reminder_fired.emit
        computer_tools.PRE_TYPE_HOOK = self._pre_type
        computer_tools.TARGET_APP_HOOK = lambda: self._last_other_app
        computer_tools.TAG_HOOK = self._bridge.memory_saved.emit
        self._front_timer = QTimer(self); self._front_timer.timeout.connect(self._note_front_app); self._front_timer.start(1500)
        computer_tools.SETTINGS = self.config
        computer_tools.set_schemas(TOOLS_SCHEMA)
        tts.STATE_CB = self._tts_state
        tts.PLAY_CB = self._tts_playing
        computer_tools.restore_reminders()

    def _review_plugins(self):
        """Each new or changed plugin file needs your explicit OK. Plugins with a MANIFEST run in the macOS
        sandbox with only the permissions they list; plugins without one run inside NOVA with full access."""
        for fname, path, h in list(computer_tools.PENDING_PLUGINS):
            computer_tools.PENDING_PLUGINS.remove((fname, path, h))
            try:
                with open(path, encoding="utf-8", errors="replace") as f: code = f.read(1500)
                manifest = computer_tools.read_manifest(path)
            except OSError:
                continue
            except ValueError as e:
                self.chat_area.add_message(tr("🔌  Plugin {} was not loaded: {}.").format(fname, e), "system", self._theme)
                continue
            if manifest is not None and not sandbox.available():       # never run a plugin unsealed that asked to be sealed
                self.chat_area.add_message(tr("🔌  Plugin {} was not loaded: {}.").format(
                    fname, tr("sandboxed plugins do not work on Windows yet")), "system", self._theme)
                continue
            box = QMessageBox(self)
            box.setWindowTitle(tr("NOVA — plugin wants to load"))
            if manifest is not None and sandbox.available():
                box.setIcon(QMessageBox.Icon.Question)
                wants = [sandbox.PERMISSIONS[p] for p in manifest["permissions"]]
                box.setText(tr("The plugin “{}” runs in a sandbox, separate from NOVA.").format(fname) + "\n\n" +
                            (tr("It asks for permission to:") + "\n" + "\n".join(f"  •  {tr(w)}" for w in wants) if wants
                             else tr("It asks for no permissions: no internet, no access to your files.")) + "\n\n" +
                            tr("It can never read NOVA's chats, memories or keys, your Library or hidden files, "
                               "or start other apps."))
            else:
                box.setIcon(QMessageBox.Icon.Warning)
                box.setText(tr("The plugin “{}” has no MANIFEST, so it is NOT sandboxed: it can run any code on your Mac "
                               "with your permissions.").format(fname) + "\n" +
                            tr("Only allow it if you wrote it or fully trust its source."))
            box.setInformativeText(f"{manifest['description']}\n\n" if manifest and manifest["description"] else "")
            box.setDetailedText(f"SHA-256 {h}\n\n{code}")
            allow = box.addButton(tr("Allow this plugin"), QMessageBox.ButtonRole.AcceptRole)
            deny = box.addButton(tr("Don't load"), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(deny); box.setEscapeButton(deny)
            box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            box.exec()
            if box.clickedButton() is allow:
                self.config.setdefault("plugins_allowed", {})[fname] = h
                new = computer_tools.load_plugin(path)
                TOOLS_SCHEMA.extend(new); computer_tools.set_schemas(new)
                self.chat_area.add_message(
                    (tr("🔌  Plugin loaded: {}").format(fname) + ("  (" + tr("sandboxed") + ")" if manifest is not None else "")) if new
                    else tr("🔌  Plugin {} could not be loaded - see the log.").format(fname), "system", self._theme)
            else:
                self.config.setdefault("plugins_denied", {})[fname] = h
            self._save_config()

    def _note_front_app(self):
        """Remember which other app the user was last in: that is where typed text will go."""
        name = plat.frontmost_other_app()
        if name: self._last_other_app = name

    @staticmethod
    def _preview_html(desc: str, preview: str) -> str:
        """The description plus the change preview, with added lines green and removed lines red."""
        rows = []
        for i, line in enumerate(preview.splitlines()[:45]):
            text = html.escape(line)
            if i == 0: rows.append(f"<b>{text}</b>")
            elif line.startswith("+"): rows.append(f'<span style="color:#2e9d4e">{text}</span>')
            elif line.startswith("-"): rows.append(f'<span style="color:#d04545">{text}</span>')
            elif line.startswith("@@"): rows.append(f'<span style="color:#888888">{text}</span>')
            else: rows.append(text)
        more = "" if preview.count("\n") < 45 else "<br><i>…</i>"
        return (html.escape(desc).replace("\n", "<br>") +
                '<br><br><pre style="font-family:Menlo,Consolas,monospace;font-size:11px;margin:0">' + "\n".join(rows) + "</pre>" + more)

    @staticmethod
    def _localize_desc(desc: str) -> str:
        """Translate the fixed parts of an approval text (the warning and the 'Run shell command' style heading)."""
        warn = ""
        if desc.startswith(computer_tools.TAINT_WARNING):
            warn = tr(computer_tools.TAINT_WARNING.strip()) + "\n\n"; desc = desc[len(computer_tools.TAINT_WARNING):]
        head, sep, rest = desc.partition(":")
        return warn + (tr(head) + sep + rest if sep and tr(head) != head else tr(desc))

    def _ask_user(self, desc: str, key: str = None) -> bool:
        """Modal approval box (GUI thread only). `key` enables an 'Always allow' choice."""
        if key and key in self.config.get("always_allow", []): return True
        if not self.isVisible(): self.show()
        self.raise_(); self.activateWindow(); plat.activate_app()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("NOVA — approve action?"))
        box.setText(tr("NOVA wants to:"))
        desc, _mark, preview = desc.partition(computer_tools.DETAILS_MARK)
        if preview:                                          # show exactly what would change (diff, new text, what is deleted)
            box.setTextFormat(Qt.TextFormat.RichText)
            box.setText("<b>" + html.escape(tr("NOVA wants to:")) + "</b>")
            box.setInformativeText(self._preview_html(self._localize_desc(desc)[:900], preview))
            box.setDetailedText(preview)
        else:
            box.setInformativeText(self._localize_desc(desc)[:900])
        allow = box.addButton(tr("Allow once"), QMessageBox.ButtonRole.AcceptRole)
        always = None
        if key:
            template, arg = computer_tools.approval_label_parts(key)
            always = box.addButton(tr(template).format(arg), QMessageBox.ButtonRole.AcceptRole)
        deny = box.addButton(tr("Deny"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(deny); box.setEscapeButton(deny)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.exec()
        clicked = box.clickedButton()
        if always is not None and clicked is always:
            self.config.setdefault("always_allow", []).append(key); self._save_config()
            return True
        return clicked is allow

    def _confirm_from_tool(self, desc: str, key: str = None) -> bool:
        """Called by tools.execute_tool - from the AI worker thread, or the GUI thread."""
        if threading.current_thread() is threading.main_thread():
            return self._ask_user(desc, key)
        holder = {"ev": threading.Event(), "ok": False, "key": key}
        with self._confirm_lock:                    # one dialog at a time
            self._bridge.confirm_request.emit(desc, holder)
            holder["ev"].wait(180)
        return holder["ok"]

    def _on_confirm_request(self, desc, holder):
        try:
            holder["ok"] = self._ask_user(desc, holder.get("key"))
        finally:
            holder["ev"].set()

    def _pre_type(self):
        """Worker thread: move focus off NOVA before keystrokes are sent."""
        holder = {"ev": threading.Event()}
        self._bridge.prepare_typing.emit(holder)
        holder["ev"].wait(3)

    def _on_prepare_typing(self, holder):
        try:
            self.hide(); plat.hide_app()
        finally:
            holder["ev"].set()

    def _on_reminder(self, text: str):
        if not self.isVisible(): self.show()
        self.chat_area.add_message(tr("⏰  Reminder: {}").format(text), "system", self._theme)

    def _reset_approvals(self):
        self.config["always_allow"] = []; self._save_config()
        self.chat_area.add_message(tr("🔒  All 'always allow' approvals were reset - NOVA will ask again."), "system", self._theme)

    def _open_activity_log(self, parent=None):
        """Every tool NOVA ran, newest first (decrypted here when the data is encrypted on disk)."""
        text = format_activity(storage.read_lines(paths.ACTIVITY_FILE)) or tr("Nothing yet.")
        TextViewDialog(self._theme, tr("Activity log"), text,
                       tr("Every action NOVA took for you, whether you approved it, and how it ended."), parent or self).exec()

    def _show_sent_today(self, parent=None):
        SentDialog(self._theme, parent or self).exec()

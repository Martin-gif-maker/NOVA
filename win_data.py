# win_data.py — settings file, chat history, saved chats, memories, export / delete, updates, diagnostics.
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
import os
import re
import json
import shutil
import threading
import datetime
import logging
import subprocess
from PySide6.QtWidgets import (QApplication, QVBoxLayout, QPushButton, QDialog, QFileDialog, QMessageBox, QTextEdit)
from PySide6.QtCore import QTimer
import tools as computer_tools
import platform_utils as plat
import paths
from settings import Settings
import tts
import updater
import diagnostics
from i18n import tr
from uistate import MODE_NORMAL
from prompts import _build_prompt
from chatutil import _plain_messages, _write_private_json, _write_data_json
import storage
import crash
import ledger
import memory
import whatsnew
import models as model_registry
from mdrender import _strip_think
from dialogs import SessionsDialog, MemoriesDialog, UsageDialog

log = logging.getLogger("nova")


class DataMixin:
    # ── Config ───────────────────────────────────────────────────
    def _load_config(self):
        """Read config.json, upgrade old formats, and return a validated `Settings` object."""
        raw = None
        if os.path.exists(paths.CONFIG_FILE):
            try:
                with open(paths.CONFIG_FILE,encoding="utf-8") as f: raw = json.load(f)
            except (OSError, ValueError): raw = None
            if not isinstance(raw, dict): raw = None
        if raw is None:
            raw = {}
        old = int(raw.get("schema", 0)) if isinstance(raw.get("schema", 0), (int, float)) else 0
        if raw and old < paths.SCHEMA_VERSION and os.path.exists(paths.CONFIG_FILE):
            try: shutil.copy2(paths.CONFIG_FILE, f"{paths.CONFIG_FILE}.bak-v{old}")        # one safety copy before upgrading
            except OSError: pass
        paths.upgrade_config(raw)
        return Settings(raw)

    def _save_config(self):
        if self._wiped: return
        self.config.update({
            "theme":self._theme_key,           # font_size lives in self.config (fullscreen uses a temporary size)
            "model_key":self._model_key,"tts":tts.ENABLED,
        })
        # Save window geometry ONLY in normal mode — never save fullscreen/bubble dimensions
        if self._mode == MODE_NORMAL:
            self.config.update({
                "win_x":self.x(),"win_y":self.y(),
                "win_w":self.width(),"win_h":self.height(),
            })
        # Never write the API key to disk — it lives in the OS keychain
        try: _write_private_json(paths.CONFIG_FILE, self.config.to_json())
        except OSError: pass

    # ── History ──────────────────────────────────────────────────
    def _load_history(self):
        if not self.config.get("save_history", True) or not os.path.exists(paths.HISTORY_FILE): return
        try:
            data=storage.read_json(paths.HISTORY_FILE)
            msgs=_plain_messages(data.get("messages",[]))
            if not msgs: return
            recent=msgs[-20:]; self.messages.extend(recent)
            uc=sum(1 for m in recent if m["role"]=="user")
            self.chat_area.add_message(tr("📂  Loaded {} messages from last session.").format(uc),"system",self._theme)
            QTimer.singleShot(100, self._update_ctx_counter)
            for m in recent[-6:]:
                p=m["content"]; p=p[:220]+"\u2026" if len(p)>220 else p
                self.chat_area.add_message(p,m["role"],self._theme)
        except (OSError, ValueError, KeyError): pass

    def _save_history(self):
        if self._wiped: return
        if not self.config.get("save_history", True):
            try: os.remove(paths.HISTORY_FILE)
            except OSError: pass
            return
        try: _write_data_json(paths.HISTORY_FILE, {"messages":_plain_messages(self.messages)[-50:]})
        except OSError: pass

    # ── Data & privacy ───────────────────────────────────────────
    @staticmethod
    def _reveal(path: str):
        os.makedirs(path, exist_ok=True)
        try: subprocess.Popen(["open", path])
        except OSError: pass

    def _export_data(self, parent=None):
        default = os.path.join(os.path.expanduser("~"), "Desktop",
                               f"NOVA-data-{datetime.date.today():%Y%m%d}.zip")
        dest, _ = QFileDialog.getSaveFileName(parent or self, tr("Export NOVA data"), default, "Zip (*.zip)")
        if not dest: return
        try:
            n = paths.export_zip(dest)
            self.chat_area.add_message(tr("💾  Exported {} files to {} (the API key is not included).").format(n, dest), "system", self._theme)
        except OSError as e:
            self.chat_area.add_message(tr("❌  Export failed: {}").format(e), "system", self._theme)

    def _wipe_data(self, dlg=None):
        r = QMessageBox.warning(dlg or self, tr("Delete all NOVA data"),
            tr("This permanently deletes your chats, memories, notes, reminders, settings and the saved "
               "API key from this Mac, then quits NOVA.\n\nThis cannot be undone. Export first if unsure."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes: return
        self._wiped = True
        paths.wipe_all()
        if dlg: dlg.reject()
        QMessageBox.information(self, "NOVA", tr("All NOVA data was deleted. NOVA will now quit."))
        self._quit_app()

    # ── memory keywords (matching memories by meaning) ───────────
    def _queue_memory_tags(self):
        """A memory was saved somewhere: fetch keywords for it shortly (several saves in a row become one request)."""
        if not hasattr(self, "_tag_timer"):
            self._tag_timer = QTimer(self); self._tag_timer.setSingleShot(True); self._tag_timer.timeout.connect(self._tag_memories)
        self._tag_timer.start(1500)

    def _tag_memories(self):
        """Ask the fast model once for search keywords for the memories that have none (in the background)."""
        if self._tagging or not self.client or not self.config.get("smart_memory", True): return
        todo = memory.untagged(computer_tools.memory_items(), limit=12)      # a dozen per request keeps the answer short
        if not todo: return
        self._tagging = True
        client, model = self.client, model_registry.fast_model_id()

        def _bg():
            try:
                # low effort: a "thinking" model would otherwise spend the whole answer budget on thinking
                r = client.chat.completions.create(model=model, max_tokens=2500, reasoning_effort="low",
                                                   messages=[{"role": "user", "content": memory.tagging_prompt(todo)}])
                found = memory.parse_tags(_strip_think(r.choices[0].message.content or ""), todo)
                if found:
                    n = computer_tools.set_memory_tags(found)
                    log.info("memory keywords added for %d memories", n)
            except Exception as e:
                log.info("memory keywords skipped: %s", e)
            finally:
                self._tagging = False
        threading.Thread(target=_bg, daemon=True).start()

    def _show_usage(self, parent=None):
        dlg = UsageDialog(self._theme, self.config.get("prices", {}), parent or self)
        dlg.exec()
        if dlg.prices() != self.config.get("prices", {}):
            self.config["prices"] = dlg.prices(); self._save_config()

    def _apply_encryption_setting(self):
        """The 'encrypt on disk' switch changed: re-write every stored file in the new format."""
        want = bool(self.config.get("encrypt_data", False))
        try:
            self._save_history()                                   # so the current chat is converted too
            n = storage.convert_all(want)
            self.chat_area.add_message(
                tr("🔒  Encryption is on — {} files are now encrypted. The key is in your Keychain.").format(n) if want
                else tr("🔓  Encryption is off — {} files were decrypted.").format(n), "system", self._theme)
        except Exception as e:
            self.config["encrypt_data"] = storage.enabled()
            log.warning("could not change the encryption setting: %s", e)
            self.chat_area.add_message(tr("⚠️  Could not change the encryption setting: {}").format(e), "system", self._theme)

    def _refresh_login_item(self):
        """A 'launch at login' entry made by an older NOVA opens the window at every login; bring it in line with
        the 'start in the menu bar' setting."""
        try:
            if plat.IS_MAC and plat.autostart_enabled() and plat.autostart_hidden() != bool(self.config.get("start_hidden", True)):
                plat.set_autostart(True, os.path.abspath(os.path.join(paths.CODE_DIR, "main.py")), self.config.get("start_hidden", True))
        except Exception as e:
            log.info("login item not refreshed: %s", e)

    def _maybe_whats_new(self):
        """After an update, say once what is new (people who just installed NOVA get the wizard instead)."""
        if whatsnew.should_show(self.config.get("seen_version", ""), self.config.get("onboarded", False)):
            self.chat_area.add_message(whatsnew.text(), "assistant", self._theme, markdown=True)
        if self.config.get("seen_version", "") != paths.__version__:
            self.config["seen_version"] = paths.__version__; self._save_config()

    def _show_whats_new(self):
        self.chat_area.add_message(whatsnew.text() or tr("Nothing new to report for this version."), "assistant", self._theme, markdown=True)

    def _startup_notices(self):
        """Things the user should hear once the window is up: encryption trouble, a crash last time."""
        if self._encryption_failed:
            self.config["encrypt_data"] = False
            self.chat_area.add_message(tr("⚠️  Encryption could not be turned on (the Keychain is unavailable) — "
                                          "new data is being stored unencrypted."), "system", self._theme)
        if not self.config.get("crash_reports", False): return
        new = crash.unseen()
        if not new: return
        self.chat_area.add_message(tr("⚠️  NOVA hit an unexpected error last time. A report (no chat content) was saved: {}")
                                   .format(new[-1]), "system", self._theme)
        url = self.config.get("crash_report_url", "")
        if url.lower().startswith("https://") and not os.environ.get("NOVA_QUIT_AFTER_MS"):
            QTimer.singleShot(800, lambda: self._offer_crash_report(new[-1], url))

    def _offer_crash_report(self, path: str, url: str):
        try:
            with open(path, encoding="utf-8") as f: body = f.read()
        except OSError:
            return
        box = QMessageBox(self); box.setWindowTitle(tr("Send crash report?"))
        box.setText(tr("Send this report to {}? This is everything that would be sent:").format(ledger.host_of(url)))
        box.setDetailedText(body); box.setInformativeText(body[:600] + ("…" if len(body) > 600 else ""))
        send = box.addButton(tr("Send"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Don't send"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is send:
            threading.Thread(target=lambda: self._sys_msg_ready.emit(crash.send(path, url)[1]), daemon=True).start()

    def _check_updates(self, quiet: bool = False):
        """Look for a newer NOVA. `quiet` (the automatic daily check) says nothing unless there is one."""
        feed = self.config.get("update_feed", "")
        if not feed:
            if not quiet:
                self.chat_area.add_message(tr("NOVA {}. No update feed is configured "
                                              "(set \"update_feed\" in config.json to an https JSON URL).").format(paths.__version__), "system", self._theme)
            return
        def _bg():
            try:
                info = updater.fetch_info(feed)
                if updater.is_newer(str(info.get("version", ""))): self._update_found.emit(dict(info, _quiet=quiet))
                elif not quiet: self._sys_msg_ready.emit(tr("✓ NOVA {} is up to date.").format(paths.__version__))
            except Exception as e:
                if quiet: log.info("automatic update check failed: %s", e)
                else: self._sys_msg_ready.emit(tr("❌  Update check failed: {}").format(e))
        threading.Thread(target=_bg, daemon=True).start()

    def _auto_update_check(self):
        """Once a day, if an update address is set and you did not turn checking off."""
        if self.config.get("auto_update", "notify") == "off" or not self.config.get("update_feed", ""): return
        today = datetime.date.today().isoformat()
        if self.config.get("update_checked", "") == today: return
        self.config["update_checked"] = today; self._save_config()
        self._check_updates(quiet=True)

    def _offer_update(self, info: dict):
        ver = info.get("version", "?")
        in_place, _why = updater.can_self_update()
        silent = bool(info.get("_quiet")) and in_place and self.config.get("auto_update", "notify") == "install"
        if not silent:
            ask = tr("Install it now? NOVA will restart.") if in_place else tr("Download it now?")
            r = QMessageBox.question(self, tr("NOVA update"), tr("NOVA {} is available (you have {}).").format(ver, paths.__version__)
                                     + f"\n\n{str(info.get('notes', ''))[:400]}\n\n" + ask,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            if r != QMessageBox.StandardButton.Yes: return
        self._sys_msg_ready.emit(tr("⬇️  Downloading NOVA {}…").format(ver))
        def _bg():
            try:
                path = updater.download(str(info.get("url", "")), str(info.get("sha256", "")))
                if not in_place:
                    updater.reveal(path)
                    self._sys_msg_ready.emit(tr("✓ Downloaded and verified: {} — drag NOVA to Applications to finish.").format(path))
                    return
                updater.install_from_dmg(path, updater.app_bundle())
                try: os.remove(path)
                except OSError: pass
                self._update_installed.emit(str(ver), not silent)
            except Exception as e:
                self._sys_msg_ready.emit(tr("❌  Update failed: {}").format(e))
        threading.Thread(target=_bg, daemon=True).start()

    def _on_update_installed(self, ver: str, restart_now: bool):
        if not restart_now:                                   # installed by itself in the background: do not interrupt
            self.chat_area.add_message(tr("✓ NOVA {} was installed. It is used the next time you start NOVA.").format(ver), "system", self._theme)
            return
        self.chat_area.add_message(tr("✓ NOVA {} is installed — restarting…").format(ver), "system", self._theme)
        updater.relaunch(updater.app_bundle())
        QTimer.singleShot(400, self._quit_app)

    # ── Diagnostics ──────────────────────────────────────────────
    def _copy_diagnostics(self):
        QApplication.clipboard().setText(diagnostics.build_diagnostics(self.config))
        self.chat_area.add_message(tr("📋  Diagnostics copied (no keys, no chat content) - paste it into your bug report."), "system", self._theme)

    # ── Export ───────────────────────────────────────────────────
    def _export_chat(self):
        desktop=os.path.join(os.path.expanduser("~"),"Desktop")
        stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path=os.path.join(desktop,f"nova_chat_{stamp}.txt")
        lines=[f"=== NOVA Chat — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n"]
        for m in _plain_messages(self.messages):
            lines.append(f"[{'You' if m['role']=='user' else 'NOVA'}]\n{m['content']}\n")
        try:
            with open(path,"w",encoding="utf-8") as f: f.write("\n".join(lines))
            self.chat_area.add_message(tr("💾  Saved: {}").format(path),"system",self._theme)
        except Exception as e:
            self.chat_area.add_message(f"❌  {e}","system",self._theme)

    # ── Session management ───────────────────────────────────────────
    def _get_session_title(self) -> str:
        if hasattr(self, "_session_title") and self._session_title:
            return self._session_title
        for m in self.messages:
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                return m["content"][:55].replace("\n", " ")
        return "Untitled"

    def _generate_session_title(self):
        """Title = the first thing you said (no API call)."""
        first = next((m["content"] for m in _plain_messages(self.messages) if m["role"] == "user"), "")
        title = re.sub(r"\s+", " ", first).strip()
        if title: self._title_ready.emit(title[:40] + ("…" if len(title) > 40 else ""))

    def _set_session_title(self, title: str):
        if not self._session_title:
            self._session_title = title
            self._name_lbl.setText(title)

    def _save_session(self):
        msgs = _plain_messages(self.messages)
        if not msgs or self._wiped or not self.config.get("save_history", True): return
        os.makedirs(paths.SESSIONS_DIR, exist_ok=True)
        # Auto-cleanup: keep only the 30 most recent sessions
        try:
            all_s = sorted([f for f in os.listdir(paths.SESSIONS_DIR) if f.endswith(".json")], reverse=True)
            for old in all_s[29:]:
                try: os.remove(os.path.join(paths.SESSIONS_DIR, old))
                except OSError: pass
        except OSError: pass
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe  = re.sub(r'[^\w \-.]', "", self._get_session_title()).strip()[:35] or "chat"
        path  = os.path.join(paths.SESSIONS_DIR, f"{stamp}_{safe}.json")
        try:
            _write_data_json(path, {"title": self._get_session_title(),
                                    "created": datetime.datetime.now().isoformat(),
                                    "messages": msgs[-50:]})
        except OSError: pass

    def _load_session(self, path: str):
        try:
            data = storage.read_json(path)
            msgs = _plain_messages(data.get("messages",[]))
            if not msgs: return
            if any(m["role"] == "user" for m in _plain_messages(self.messages)):
                self._save_session()                    # never throw the current chat away
            self._reset_chat_state()
            self._session_title = data.get("title", "") or ""
            self._name_lbl.setText(self._session_title[:40] or "NOVA")
            self.messages = [{"role":"system","content":_build_prompt()}] + msgs
            self.chat_area.clear()
            self.chat_area.add_message(tr("Loaded: {}").format(data.get('title','Session')), "system", self._theme)
            for m in msgs[-6:]:
                p = m["content"]; p = p[:220]+"…" if len(p)>220 else p
                self.chat_area.add_message(p, m["role"], self._theme)
            self._update_ctx_counter()
        except (OSError, ValueError) as e:
            self.chat_area.add_message(tr("Load error: {}").format(e), "system", self._theme)

    def _show_sessions_menu(self):
        dlg = SessionsDialog(self._theme, paths.SESSIONS_DIR, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_path:
            self._load_session(dlg.selected_path)

    def _new_chat(self):
        if any(m["role"] == "user" for m in _plain_messages(self.messages)):
            r = QMessageBox.question(self, tr("New chat"),
                tr("Start a new chat? Current conversation will be saved to Sessions."),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes: return
        self._save_session()   # persist current chat before clearing
        self._reset_chat_state()
        self._session_title = ""
        self._name_lbl.setText("NOVA")
        self.messages = [{"role":"system","content":_build_prompt()}]
        try:
            if os.path.exists(paths.HISTORY_FILE): os.remove(paths.HISTORY_FILE)
        except OSError: pass
        self.chat_area.clear()
        self._update_ctx_counter()
        self.chat_area.add_message(tr("New chat. Sessions saved in the + menu."), "system", self._theme)

    def _show_memories_dialog(self, parent=None):
        dlg = MemoriesDialog(self._theme, computer_tools.memory_items(), parent or self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            computer_tools.replace_memories(getattr(dlg, "items", None) or dlg.facts)
            self._queue_memory_tags()
            self.messages[0] = {"role": "system", "content": _build_prompt()}

    def _clear_memories(self, parent=None):
        r = QMessageBox.question(parent or self, tr("Clear memories"),
            tr("Delete all saved memories? This cannot be undone."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            try:
                computer_tools.replace_memories([])
                self.chat_area.add_message(tr("All memories cleared."), "system", self._theme)
                self.messages[0] = {"role": "system", "content": _build_prompt()}
            except Exception as e:
                self.chat_area.add_message(tr("Error clearing memories: {}").format(e), "system", self._theme)

    def _show_notes_dialog(self):
        """Show a dialog with all saved notes."""
        from tools_files import NOTES_FILE
        t = self._theme
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("NOVA — Notes"))
        dlg.setMinimumSize(440, 340)
        dlg.setStyleSheet(
            f"QDialog{{background:{t['frame_bg']};color:{t['ai_fg']};border-radius:12px;}}"
            f"QTextEdit{{background:{t['ai_bg']};color:{t['ai_fg']};border:1px solid {t['ai_br']};border-radius:8px;padding:6px;}}"
            f"QPushButton{{background:{t['send_bg']};color:#fff;border:none;border-radius:8px;padding:6px 14px;}}"
            f"QPushButton:hover{{background:{t['send_hv']};}}")
        vl = QVBoxLayout(dlg)
        view = QTextEdit(); view.setReadOnly(True)
        def _load():
            import os
            try:
                if os.path.exists(NOTES_FILE):
                    view.setPlainText(storage.read_text(NOTES_FILE).strip() or tr("No notes yet."))
                else:
                    view.setPlainText(tr("No notes yet."))
            except Exception as ex:
                view.setPlainText(f"Error reading notes: {ex}")
        _load()
        refresh_btn = QPushButton("⟳  " + tr("Refresh")); refresh_btn.clicked.connect(_load)
        vl.addWidget(view); vl.addWidget(refresh_btn)
        dlg.exec()

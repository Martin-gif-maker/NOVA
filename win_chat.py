# win_chat.py — the conversation: sending, streaming, tools, cancel, regenerate, edit, files and vision.
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
import os
import copy
import threading
import logging
from PySide6.QtWidgets import (QApplication, QWidget, QPushButton, QMenu, QMessageBox)
from PySide6.QtCore import Qt, QTimer
import tools as computer_tools
import platform_utils as plat
import providers
import schemas
import tts
from i18n import tr
from models import MODELS
from mdrender import _strip_think, safe_calculate
from prompts import _build_prompt
from chatutil import _strip_hints, _plain_messages, _LENGTH_HINTS
from workers import AIWorker, VisionWorker, _compact_history
from widgets import MessageBubble, ToolActivity
from dialogs import confirm_image_upload
from settings_dialog import _FlowLayout

log = logging.getLogger("nova")


class ChatMixin:
    # ── Calculator ───────────────────────────────────────────────
    def _try_calculate(self,text)->bool:
        if not text.strip().startswith("="): return False
        expr=text.strip()[1:].strip()
        try:
            r=safe_calculate(expr)
        except ZeroDivisionError:
            self.chat_area.add_message(tr("🧮  Cannot divide by zero."), "system",self._theme); return True
        except Exception:
            return False                      # not plain arithmetic -> let the AI answer
        if isinstance(r,float):
            r = int(r) if r.is_integer() else round(r,10)
        self.chat_area.add_message(f"`{expr}` = **{r}**","assistant",self._theme,markdown=True)
        return True

    # ── Shortcuts ────────────────────────────────────────────────
    def _check_shortcut(self,text)->bool:
        key=text.lower().strip()
        shortcuts=self.config.get("shortcuts",{})
        if key not in shortcuts: return False
        apps=shortcuts[key]
        if isinstance(apps,list):
            for a in apps: computer_tools.execute_tool("open_application",{"app_name":a})
            self.chat_area.add_message(tr("✅  «{}»: opening {}").format(key, ', '.join(apps)),"assistant",self._theme)
        else:
            self.chat_area.add_message(tr("⚠️  Shortcut «{}» must be a list of app names in config.json.").format(key),"system",self._theme)
        return True

    # ── AI request lifecycle ──────────────────────────────────────
    def _length_hint(self) -> str:
        return {"short":_LENGTH_HINTS[0], "normal":"", "detailed":_LENGTH_HINTS[1]}[self._resp_length]

    def _clear_thinking(self):
        self._think_timer.stop()
        if self._thinking_bubble:
            self.chat_area.remove_widget(self._thinking_bubble)
            self._thinking_bubble = None

    def _clear_transient_widgets(self):
        for attr in ("_regen_widget", "_followup_widget"):
            w = getattr(self, attr, None)
            if w:
                self.chat_area.remove_widget(w); setattr(self, attr, None)

    def _abandon_worker(self):
        """Cancel the running AI worker for good: it emits nothing more and keeps no UI state."""
        w = self._worker; self._worker = None
        if w is None: return
        w.cancel()
        for sig in (w.chunk_ready, w.response_ready, w.tool_executing, w.error_occurred, w.usage_ready, w.tool_finished):
            try: sig.disconnect()
            except (TypeError, RuntimeError): pass
        self._retire_thread(w)

    def _reset_chat_state(self):
        """Forget everything tied to the chat that is about to be replaced (new chat / load session)."""
        self._abandon_worker(); self._clear_thinking()
        self._streaming_bubble = None; self._regen_widget = None; self._followup_widget = None
        self._last_ai_bubble = None; self._busy = False; self._ai_retry_pending = False
        self._tool_log = []; self._last_tool_widget = None
        self._tool_groups = set(); self._group_turn = {}; self._turn_no = 0
        self._restore_send_btn()

    def _start_ai(self, model_id: str = None):
        """Start one AI request on a fresh worker (history is compressed inside the worker)."""
        if not self.client: return
        old = self._worker
        if old is not None and old.isRunning():
            old.cancel(); self._retire_thread(old)
        self._busy = True
        self._clear_transient_widgets()
        self._clear_thinking()
        self._streaming_bubble = None
        self.input_field.setEnabled(False)
        self._think_base = tr("Thinking")                      # what the line says NOVA is doing; the dots move
        self._thinking_bubble = self.chat_area.add_message(self._think_base + "…", "system", self._theme)
        self._think_dots = 0
        self._think_timer.start(420)
        hist = copy.deepcopy(_compact_history(self.messages))
        hint = self._length_hint()
        if hint and hist and hist[-1].get("role") == "user":
            hist[-1]["content"] += hint
        untrusted = getattr(self, "_request_untrusted", ""); self._request_untrusted = ""
        w = AIWorker(self.client, hist, model_id or MODELS[self._model_key][0],
                     max_tokens=self._resp_max_tokens(), reasoning=self.config.get("reasoning", "low"), untrusted=untrusted,
                     groups=self._tool_groups)
        w.chunk_ready.connect(self._on_chunk); w.response_ready.connect(self._on_response)
        w.tool_executing.connect(self._on_tool); w.error_occurred.connect(self._on_error)
        w.usage_ready.connect(self._on_usage); w.tool_finished.connect(self._on_tool_finished)
        self._tool_log = []
        self._worker = w
        w.start()
        self._set_send_btn_cancel()

    def _run_ai_direct(self):
        self._start_ai()

    def _resp_max_tokens(self) -> int:
        # reasoning models spend part of this budget on hidden "thinking", so keep it generous
        return {"short": 900, "normal": 1800, "detailed": 4000}.get(self._resp_length, 1800)

    def _cycle_resp_length(self):
        order = ["short","normal","detailed"]
        self._resp_length = order[(order.index(self._resp_length)+1) % len(order)]
        labels = {"short":tr("Short"),"normal":tr("Normal"),"detailed":tr("Detailed")}
        self._len_btn.setToolTip(tr("Response length") + f": {labels[self._resp_length]}")
        self._cycle_resp_length_style()

    def _cycle_resp_length_style(self):
        """The length button: few lines = short answers, all lines = detailed (in the accent colour when not Normal)."""
        import icons
        t = self._theme
        name = {"short": "lines", "normal": "lines", "detailed": "menu"}[self._resp_length]
        col = t["sys_fg"] if self._resp_length == "normal" else t["accent_fg"]
        self._len_btn.setIcon(icons.icon(name, col, 16, 1.5 if self._resp_length != "short" else 1.1))

    def _update_ctx_counter(self):
        """Refresh the title-bar counter: messages in context and tokens used this session."""
        if not hasattr(self, "_ctx_lbl"): return
        n = len(_plain_messages(self.messages))
        tok = self._tokens_in + self._tokens_out
        txt = f"{n} msgs" if n else ""
        if tok: txt += (" · " if txt else "") + (f"{tok/1000:.1f}k tok" if tok >= 1000 else f"{tok} tok")
        self._ctx_lbl.setText(txt)
        self._ctx_lbl.setToolTip(tr("Messages in context · tokens this session: {} in / {} out").format(self._tokens_in, self._tokens_out))

    def _on_usage(self, p: int, c: int):
        if self._from_stale_worker(): return
        self._tokens_in += p; self._tokens_out += c
        self._update_ctx_counter()

    def _cancel_request(self):
        """Cancel the running AI request: the worker stops, nothing more is shown or executed."""
        self._ai_retry_pending = False
        self._abandon_worker()
        self._busy = False
        self._clear_thinking()
        if self._streaming_bubble:
            self._streaming_bubble.render_markdown()
            self._streaming_bubble = None
        self._restore_send_btn()
        self._reply_has_bubble = False
        self._show_tool_activity()
        self.chat_area.add_message(tr("Cancelled."), "system", self._theme)
        if getattr(self, "_external_running", False): self._external_finish(error="The request was cancelled in NOVA.")
        if self._conversation: QTimer.singleShot(300, self._conversation_listen)

    def _set_send_btn_cancel(self):
        import icons
        t = self._theme
        self.send_btn.setIcon(icons.icon("stop", t["ai_fg"], 14)); self.send_btn.setAccessibleName(tr("Stop"))
        self.send_btn.setToolTip(tr("Stop"))
        self.send_btn.setStyleSheet(f"QPushButton{{background:{t['user_bg']};border:1px solid {t['ai_br']};border-radius:7px;}}"
                                    f"QPushButton:hover{{border-color:{t['sys_fg']};}}")
        try: self.send_btn.clicked.disconnect()
        except (TypeError, RuntimeError): pass
        self.send_btn.clicked.connect(self._cancel_request)
        self.send_btn.setEnabled(True)

    def _restore_send_btn(self):
        self._restore_send_look()
        self.send_btn.setAccessibleName(tr("Send message")); self.send_btn.setToolTip("")
        try: self.send_btn.clicked.disconnect()
        except (TypeError, RuntimeError): pass
        self.send_btn.clicked.connect(self._send)
        self.send_btn.setEnabled(True)
        self.input_field.setEnabled(True)

    def _retry_with_fast_model(self):
        """Retry the last AI request with the fast model."""
        if not self._ai_retry_pending or not self.client: return
        self._start_ai(model_id=MODELS["fast"][0])

    # ── Vision ───────────────────────────────────────────────────
    def _take_screenshot_vision(self):
        q=self.input_field.text().strip()
        if not self.client or self._busy:
            self.chat_area.add_message(tr("NOVA is busy - try again in a moment."), "system", self._theme); return
        if not plat.screen_capture_allowed(request=True):
            self.chat_area.add_message(tr("⚠️  Screen Recording permission is missing - allow it in System Settings → "
                                          "Privacy & Security → Screen Recording, then restart NOVA."), "system", self._theme); return
        try:
            import pyautogui
            img = pyautogui.screenshot()
        except Exception as e:
            self.chat_area.add_message(f"❌  {e}", "system", self._theme); return
        if self.config.get("confirm_uploads", True) and not confirm_image_upload(self, self._theme, img, "Screenshot"):
            return
        self.input_field.clear()
        self._start_vision(q, image=img)

    # ── Part of the screen ───────────────────────────────────────
    def _take_region_vision(self):
        """Let the user drag a rectangle (the macOS crosshair) and analyse just that part of the screen."""
        q = self.input_field.text().strip()
        if not self.client or self._busy:
            self.chat_area.add_message(tr("NOVA is busy - try again in a moment."), "system", self._theme); return
        if not plat.screen_capture_allowed(request=True):
            self.chat_area.add_message(tr("⚠️  Screen Recording permission is missing - allow it in System Settings → "
                                          "Privacy & Security → Screen Recording, then restart NOVA."), "system", self._theme); return
        self.input_field.clear()
        self._region_question = q
        self.hide()                                   # NOVA must not cover what you want to select

        def _bg():
            import tempfile, subprocess
            fd, path = tempfile.mkstemp(suffix=".png", prefix="nova_region_"); os.close(fd); os.unlink(path)
            try:
                subprocess.run(["/usr/sbin/screencapture", "-i", "-x", path], timeout=180)   # -i: drag to select, Esc cancels
            except Exception as e:
                log.info("region capture failed: %s", e)
            self._region_ready.emit(path if os.path.exists(path) and os.path.getsize(path) > 0 else "")
        QTimer.singleShot(200, lambda: threading.Thread(target=_bg, daemon=True).start())     # after the window is gone

    def _on_region_ready(self, path: str):
        self._bring_to_front()
        q = getattr(self, "_region_question", "")
        if not path:
            if q: self.input_field.setText(q)             # cancelled with Esc: give the question back
            return
        try:
            from PIL import Image as _Pil
            img = _Pil.open(path); img.load()
        except Exception as e:
            self.chat_area.add_message(f"❌  {e}", "system", self._theme); return
        finally:
            try: os.unlink(path)
            except OSError: pass
        if self.config.get("confirm_uploads", True) and not confirm_image_upload(self, self._theme, img, tr("Part of the screen")):
            return
        self._start_vision(q or "Explain what is shown here.", image=img)

    def _start_vision(self, question: str, image_path: str = None, image=None):
        if not self.client: return
        if self._busy:
            self.chat_area.add_message(tr("NOVA is busy - try again in a moment."), "system",self._theme); return
        q = question or ("Analyze this image." if image_path else "Analyze the screen.")
        note = f"[Image: {os.path.basename(image_path)}] {q}" if image_path else f"[📷] {q}"
        self.chat_area.add_message(("🖼 " + os.path.basename(image_path) + " — " if image_path else "📷 ") + q, "user", self._theme)
        self.messages.append({"role": "user", "content": note})
        self._busy = True; self.input_field.setEnabled(False)
        self._think_base = tr("Looking at the image")
        self._thinking_bubble = self.chat_area.add_message(self._think_base + "…", "system", self._theme)
        self._think_dots = 0; self._think_timer.start(420)
        w = VisionWorker(self.client, q, image_path, image)
        w.result_ready.connect(self._on_vision_done)
        w.error.connect(self._on_vision_error)
        self._vision_worker = w
        w.start()

    def _on_vision_error(self, err: str):
        self._clear_thinking(); self._busy = False; self.input_field.setEnabled(True)
        if self.messages and self.messages[-1].get("role") == "user" and self.messages[-1]["content"].startswith(("[📷]", "[Image:")):
            self.messages.pop()
        self.chat_area.add_message(f"❌  {err}", "system", self._theme)
        self._update_ctx_counter()

    def _on_vision_done(self, text: str, _note: str):
        self._clear_thinking(); self._busy = False; self.input_field.setEnabled(True)
        self.messages.append({"role": "assistant", "content": text})
        self._last_ai_bubble = self.chat_area.add_message(text, "assistant", self._theme, markdown=True)
        self._update_ctx_counter()
        self._notify_if_hidden(text); self._save_history()

    # ── Drag & drop ───────────────────────────────────────────────
    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls() or e.mimeData().hasText(): e.acceptProposedAction()

    def dropEvent(self, e):
        IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".heic"}
        if e.mimeData().hasUrls():
            for url in e.mimeData().urls():
                path = url.toLocalFile()
                if os.path.isdir(path):                                  # a folder: index every document in it
                    self._index_folder(path); return
                if not os.path.isfile(path): continue
                q = self.input_field.text().strip()
                if os.path.splitext(path)[1].lower() in IMAGE_EXT:
                    if self.config.get("confirm_uploads", True):
                        try:
                            from PIL import Image as _Pil
                            if not confirm_image_upload(self, self._theme, _Pil.open(path), os.path.basename(path)): return
                        except Exception as ex:
                            self.chat_area.add_message(f"❌ {ex}", "system", self._theme); return
                    self.input_field.clear()
                    self._start_vision(q, path); return
                if os.path.getsize(path) > 300_000_000:
                    self.chat_area.add_message(tr("❌ {} is too large (max 300 MB).").format(os.path.basename(path)),"system",self._theme); return
                self.input_field.clear()
                self._submit_file(path, q); return
        elif e.mimeData().hasText():
            self.input_field.insertPlainText(e.mimeData().text())

    # ── Send ─────────────────────────────────────────────────────
    def _send(self):
        text=self.input_field.toPlainText().strip()
        if not text: return
        if not self.client:
            self.chat_area.add_message(tr("⚠️  No API key."), "system",self._theme); return
        if self._busy:
            self.chat_area.add_message(tr("Still working on your previous request - wait for it or press the stop button."), "system",self._theme); return
        self.input_field.clear()
        outside = getattr(self, "_pending_external", False) or getattr(self, "_request_untrusted", "") == "another program"
        if self._try_calculate(text) or self._check_shortcut(text):
            if outside: self._external_finish(error="NOVA handled this in its own window; there is no answer to pass on.")
            return
        text = self._expand_slash(text)                 # /tldr … -> a saved prompt
        if text is None:
            if outside: self._external_finish(error="NOVA did not send this request.")
            return
        if getattr(self, "_pending_external", False):   # the box was filled by another program (Shortcut, nova:// link)
            self._pending_external = False; self._request_untrusted = "another program"
        self._external_running = outside and getattr(self, "_external_reply", None) is not None     # a caller waits for this answer

        self._last_user_msg=text
        self.chat_area.add_message(text,"user",self._theme)
        self.messages.append({"role":"user","content":text})
        self._update_ctx_counter()
        self.messages[0] = {"role": "system", "content": _build_prompt(text)}   # refresh date + the memories that fit this question
        self._next_turn()
        self._start_ai()

    GROUP_MEMORY = 2          # a tool group stays on for this many requests after it was last used

    def _next_turn(self):
        """A new request of yours: tool groups that have not been used for a while stop travelling with every
        request (each one costs tokens), and come back by themselves when the talk returns to them."""
        self._turn_no = getattr(self, "_turn_no", 0) + 1
        seen = getattr(self, "_group_turn", {})
        self._tool_groups = {g for g in self._tool_groups if self._turn_no - seen.get(g, self._turn_no) <= self.GROUP_MEMORY}

    def _animate_thinking(self):
        if not self._thinking_bubble:
            self._think_timer.stop(); return
        self._think_dots = (self._think_dots + 1) % 4
        try:                                       # keeps what NOVA is doing ("Opening Maps"), only the dots move
            self._thinking_bubble._label.setText(getattr(self, "_think_base", tr("Thinking")) + "." * self._think_dots)
        except RuntimeError:                       # bubble was deleted behind our back
            self._thinking_bubble = None; self._think_timer.stop()

    def _generate_followups(self):
        """Generate 3 short follow-up suggestions using the fast model (opt-in: costs an extra API call)."""
        if not self.client or not self.config.get("suggest_followups", False): return
        msgs = _plain_messages(self.messages)
        if len(msgs) < 2: return
        snippet = "\n".join(f"{m['role'].upper()}: {m['content'][:100]}" for m in msgs[-4:])
        client = self.client
        def _bg():
            try:
                resp = client.chat.completions.create(
                    model=MODELS["fast"][0],
                    messages=[{"role":"user","content":
                        f"Given this conversation, give exactly 3 short follow-up questions/actions "
                        f"the user might want. Each on its own line, max 8 words, no numbering, no quotes:\n\n{snippet}"}],
                    max_tokens=80, temperature=0.7)
                raw = _strip_think(resp.choices[0].message.content or "").strip()
                suggestions = [s.strip("•-– ").strip() for s in raw.splitlines() if s.strip()][:3]
                if suggestions:
                    self._followup_ready.emit(suggestions)         # signal -> GUI thread
            except Exception as e: log.info("follow-up suggestions were not made: %s", e)
        threading.Thread(target=_bg, daemon=True).start()

    def _show_followup_chips(self, suggestions: list):
        """Render follow-up suggestion chips below the last AI message."""
        if hasattr(self, "_followup_widget") and self._followup_widget:
            try: self.chat_area.remove_widget(self._followup_widget)
            except RuntimeError: pass                # the widget is already gone
        if not suggestions: return
        t = self._theme
        w = QWidget(); w.setStyleSheet("background:transparent;")
        hl = _FlowLayout(w, spacing=6); hl.setContentsMargins(2, 0, 2, 8)
        for s in suggestions:
            chip = QPushButton(s); chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFont(plat.ui_font(9))
            chip.setStyleSheet(
                f"QPushButton{{background:{t['ai_bg']};color:{t['ai_fg']};"
                f"border:1px solid {t['ai_br']};border-radius:6px;padding:4px 10px;}}"
                f"QPushButton:hover{{border-color:{t['sys_fg']};}}")
            def _send_suggestion(text=s):
                if hasattr(self, "_followup_widget") and self._followup_widget:
                    try: self.chat_area.remove_widget(self._followup_widget)
                    except RuntimeError: pass                # the widget is already gone
                    self._followup_widget = None
                if self._busy: return
                self.input_field.setText(text); self._send()
            chip.clicked.connect(_send_suggestion)
            hl.addWidget(chip)
        self._followup_widget = self.chat_area.add_widget(w)

    def _show_regen_btn(self):
        """Offer "regenerate" on the newest reply only (a quiet icon next to copy / read aloud)."""
        old = getattr(self, "_regen_widget", None)
        if old is not None:
            try: old.setVisible(False); old.deleteLater()
            except RuntimeError: pass                # the reply it belonged to is already gone
        self._regen_widget = None
        if self._last_ai_bubble is not None:
            self._regen_widget = self._last_ai_bubble.add_tool_button("refresh", tr("Regenerate"), self._regen_response)

    def _regen_response(self):
        """Drop the last AI answer (including its tool calls) and ask again."""
        if self._busy: return
        idx = next((i for i in range(len(self.messages)-1, 0, -1) if self.messages[i].get("role") == "user"), None)
        if idx is None: return
        self.messages = self.messages[:idx+1]
        if self._last_ai_bubble:
            self.chat_area.remove_widget(self._last_ai_bubble); self._last_ai_bubble = None
        if getattr(self, "_last_tool_widget", None):
            self.chat_area.remove_widget(self._last_tool_widget); self._last_tool_widget = None
        self._start_ai()

    def _on_tool_finished(self, name: str, args: str, ok: bool, result: str):
        if self._from_stale_worker(): return
        self._tool_log.append((name, args, ok, result))
        group = schemas.group_of(name)                           # a group that was used stays on for the next requests
        used = ({group} if group else set()) | set(computer_tools.REQUESTED_GROUPS)
        self._tool_groups |= used
        for g in used: self._group_turn[g] = self._turn_no

    def _show_tool_activity(self):
        """Show what NOVA did for this reply as neat rows: inside the reply (above its text) when there is one,
        otherwise on their own (the request failed or was cancelled after some actions)."""
        if getattr(self, "_tool_log", None):
            rows = ToolActivity(self._tool_log, self._theme)
            self._tool_log = []
            if not rows.rows: return
            bubble = self._last_ai_bubble if getattr(self, "_reply_has_bubble", False) else None
            if bubble is not None:
                bubble.set_actions(rows); self._last_tool_widget = None
            else:
                self._last_tool_widget = self.chat_area.add_widget(rows)

    def _from_stale_worker(self) -> bool:
        s = self.sender()
        return s is not None and s is not self._worker

    def _on_chunk(self, chunk: str):
        if self._from_stale_worker(): return
        if self._thinking_bubble: self._clear_thinking()
        if self._streaming_bubble is None:
            self._streaming_bubble = self.chat_area.add_message("", "assistant", self._theme)
            if getattr(self, "_tool_log", None):         # what NOVA already did goes above the text now, so the text
                rows = ToolActivity(list(self._tool_log), self._theme)        # does not jump down when the reply ends
                if rows.rows: self._streaming_bubble.set_actions(rows)
        self._streaming_bubble.append_text(chunk)

    def _on_response(self, text: str, updated: list):
        if self._from_stale_worker(): return
        self._busy = False
        self._ai_retry_pending = False
        self._clear_thinking()
        self._reply_has_bubble = bool(self._streaming_bubble) or bool(text.strip())
        if self._streaming_bubble:
            self._streaming_bubble.render_markdown()
            self._last_ai_bubble = self._streaming_bubble
            self._streaming_bubble = None
        elif text.strip():
            self._last_ai_bubble = self.chat_area.add_message(text, "assistant", self._theme, markdown=True)
        else:
            self.chat_area.add_message(tr("⚠️  The model returned an empty reply (it may have run out of "
                                          "tokens). Try again or switch to 'Detailed'."), "system", self._theme)
        self.messages = _strip_hints(updated)
        self._show_tool_activity()
        self._show_regen_btn()
        QTimer.singleShot(400, self._generate_followups)
        self._restore_send_btn()
        self.input_field.setFocus()
        self._update_ctx_counter()
        if not self._session_title and len(_plain_messages(self.messages)) >= 2:
            QTimer.singleShot(100, self._generate_session_title)
        if text.strip():
            spoken = tts.ENABLED and (self.config.get("tts_auto", False) or self._conversation)
            if spoken: tts.speak(text)
            elif self._conversation: QTimer.singleShot(400, self._conversation_listen)      # read-aloud is off: listen again
            self._notify_if_hidden(_strip_think(text))
        hook, self._reply_hook = getattr(self, "_reply_hook", None), None      # one-shot follow-up (e.g. copy a rewrite)
        if hook and text.strip():
            try: hook(_strip_think(text))
            except Exception as e: log.warning("reply hook failed: %s", e)
        if getattr(self, "_external_running", False):                          # `NOVA --ask … --wait` is waiting for this
            self._external_finish(_strip_think(text), error="The model returned an empty reply.")
        self._save_history()

    @staticmethod
    def _working_text(call: str) -> str:
        """What to show while a tool runs: what NOVA is busy with ("Searching the web…"), not the tool's name."""
        import re, actions
        if call and not call.lstrip().startswith("⚙"):                   # a notice from the worker ("Rate limit — retrying in 5s")
            from widgets import tidy_notice
            return tidy_notice(call)
        m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\(", call or "")
        if not m or m.group(1) in actions.HIDDEN: return tr("Thinking") + "…"
        return actions.doing(m.group(1))

    def _on_tool(self, name: str):
        if self._from_stale_worker(): return
        if self._thinking_bubble:
            text = self._working_text(name)
            self._think_base = text.rstrip("….")
            try: self._thinking_bubble._label.setText(text)
            except RuntimeError: self._thinking_bubble = None

    def _on_error(self, err: str, kind: str = ""):
        if self._from_stale_worker(): return
        self._clear_thinking()
        if self._streaming_bubble:
            self._streaming_bubble.render_markdown()
            self._streaming_bubble = None
        if not kind: kind, _ = providers.classify_error(Exception(err))
        log.warning("AI request failed (%s): %s", kind, err[:500])
        is_overload = kind in ("rate_limit", "server")
        if is_overload and not self._ai_retry_pending and self._model_key != "fast":
            self._ai_retry_pending = True            # stays 'busy': the retry starts in a moment
            self.chat_area.add_message(
                tr("⚡ {} is busy — retrying with {}...").format(MODELS[self._model_key][1], MODELS['fast'][1]),
                "system", self._theme)
            QTimer.singleShot(1200, self._retry_with_fast_model)
            return
        self._ai_retry_pending = False
        self._busy = False
        msg = tr(providers.FRIENDLY[kind]) if kind in providers.FRIENDLY else err[:300]
        shown = msg
        if kind == "auth":                                   # say who refused the key and where a new one comes from
            p = providers.info(self._provider()); url = p.get("key_url", "")
            if url and p.get("needs_key"):
                name, host = p["label"].split(" (")[0], url.split("//")[-1].rstrip("/")
                text = tr("{} did not accept the API key - it may have expired or been revoked. Get a new one at {}, "
                          "then choose ≡ → Change API key.")
                msg, shown = text.format(name, url), text.format(name, f'<a href="{url}">{host}</a>')
        self._reply_has_bubble = False
        self._show_tool_activity()
        self.chat_area.add_message(f"❌ {shown}", "system", self._theme)
        if getattr(self, "_external_running", False): self._external_finish(error=msg)
        self._restore_send_btn()
        if self._conversation: self._end_conversation()               # do not keep listening after a failure

    # ── Edit a sent message ──────────────────────────────────────
    def _edit_message(self, bubble):
        """Double-click on your message: remove it (and everything after) and put its text back to edit."""
        if self._busy: return
        try: text = bubble._full_text
        except RuntimeError: return
        tail = self.chat_area.widgets_from(bubble)
        n_user = sum(1 for w in tail if isinstance(w, MessageBubble) and w._role == "user")
        user_idx = [i for i, m in enumerate(self.messages) if m.get("role") == "user"]
        if not n_user or n_user > len(user_idx):
            self.input_field.setText(text); self.input_field.setFocus(); return
        r = QMessageBox.question(self, tr("Edit message"),
            tr("Edit this message? It and everything after it will be removed from this chat."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes: return
        self.messages = self.messages[:user_idx[-n_user]]
        for w in tail: self.chat_area.remove_widget(w)
        self._last_ai_bubble = None; self._regen_widget = None; self._followup_widget = None
        self._update_ctx_counter(); self._save_history()
        self.input_field.setText(text); self.input_field.setFocus()

    # ── Notifications ────────────────────────────────────────────
    def _notify_if_hidden(self, msg: str):
        if self.isVisible(): return
        plat.notify("NOVA", msg[:100])

    # ── Thread bookkeeping ───────────────────────────────────────
    def _retire_thread(self, th):
        """Keep a Python reference to a still-running QThread until it has finished."""
        if th is None or th.isFinished(): return
        self._zombies.append(th)
        def _done(t=th):
            if t in self._zombies: self._zombies.remove(t)
        th.finished.connect(_done)

    @staticmethod
    def _stop_thread(th, ms=2000):
        if th is not None and th.isRunning():
            if not th.wait(ms):
                th.terminate(); th.wait(500)

    def _quick_cmd(self,text):
        self.input_field.setText(text); self._send()

    # ── Clipboard history ────────────────────────────────────────
    def _paste_clipboard(self):
        text=QApplication.clipboard().text().strip()
        if text and (not self._clipboard_hist or self._clipboard_hist[0]!=text):
            self._clipboard_hist.insert(0,text); self._clipboard_hist=self._clipboard_hist[:8]
        if not self._clipboard_hist:
            self.chat_area.add_message(tr("📋  Clipboard is empty."), "system",self._theme); return
        if len(self._clipboard_hist)==1:
            self.input_field.setText(self._clipboard_hist[0]); self.input_field.setFocus(); return
        menu=QMenu(self); t=self._theme
        menu.setStyleSheet(f"QMenu{{background:{t['ai_bg']};border:1px solid {t['ai_br']};border-radius:8px;color:{t['ai_fg']};font-size:10px;padding:4px;}}QMenu::item{{padding:5px 14px;border-radius:4px;}}QMenu::item:selected{{background:{t['frame_br']};}}")
        for item in self._clipboard_hist:
            act=menu.addAction(item[:60]+"…" if len(item)>60 else item); act.setData(item)
        chosen=menu.exec(self._plus_btn.mapToGlobal(self._plus_btn.rect().bottomLeft()))
        if chosen: self.input_field.setText(chosen.data()); self.input_field.setFocus()

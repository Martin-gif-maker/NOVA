# settings_dialog.py — the Settings window, grouped into tabs: General · AI · Voice · Privacy · Data.
import os
import threading
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog, QFormLayout, QComboBox,
                               QCheckBox, QSpinBox, QDialogButtonBox, QColorDialog, QTabWidget, QWidget, QLineEdit,
                               QListWidget, QLayout, QSizePolicy)
from PySide6.QtCore import Qt, Signal, QRect, QSize, QPoint
from PySide6.QtGui import QFont, QColor
import platform_utils as plat
import paths
import providers
import speech
import tools as computer_tools
from i18n import tr, language
from models import MODELS, MODEL_ORDER
from themes import THEMES, THEMES_BASE, controls_css
from widgets import WrapLabel


class _FlowLayout(QLayout):
    """Lays widgets out left to right and wraps to a new line only when the row is full - so a row of
    buttons is never cut off, whatever the language or the window width."""
    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []; self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item): self._items.append(item)
    def count(self): return len(self._items)
    def itemAt(self, i): return self._items[i] if 0 <= i < len(self._items) else None
    def takeAt(self, i): return self._items.pop(i) if 0 <= i < len(self._items) else None
    def expandingDirections(self): return Qt.Orientation.Horizontal
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self._place(QRect(0, 0, width, 0), dry=True)

    def sizeHint(self):                                  # everything on one line
        hints = [it.sizeHint() for it in self._items]
        return QSize(sum(h.width() for h in hints) + self._gap * max(0, len(hints) - 1), max((h.height() for h in hints), default=0))

    def minimumSize(self):                               # at worst: one item per line
        hints = [it.sizeHint() for it in self._items]
        return QSize(max((h.width() for h in hints), default=0), max((h.height() for h in hints), default=0))

    def setGeometry(self, rect):
        super().setGeometry(rect); self._place(rect, dry=False)

    def _place(self, rect, dry: bool) -> int:
        lines: list = []; line: list = []; x = rect.x()
        for it in self._items:
            w = it.sizeHint().width()
            if line and x + w > rect.x() + rect.width():
                lines.append(line); line, x = [], rect.x()
            line.append((it, x)); x += w + self._gap
        if line: lines.append(line)
        y = rect.y()
        for i, items in enumerate(lines):
            line_h = max(it.sizeHint().height() for it, _ in items)
            if not dry:
                for it, x in items:                      # centred on the line: a button next to a taller menu
                    hint = it.sizeHint()
                    it.setGeometry(QRect(QPoint(x, y + (line_h - hint.height()) // 2),
                                         QSize(min(hint.width(), rect.width()), hint.height())))
            y += line_h + (self._gap if i < len(lines) - 1 else 0)
        return y - rect.y()


class _FlowRow(QWidget):
    """A widget wrapping a _FlowLayout (form layouts handle height-for-width of widgets reliably)."""
    def __init__(self, *widgets):
        super().__init__()
        flow = _FlowLayout(self)
        for w in widgets: flow.addWidget(w)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        sp = self.sizePolicy(); sp.setHeightForWidth(True); self.setSizePolicy(sp)

    def resizeEvent(self, e):                            # keep the row exactly as tall as its lines
        super().resizeEvent(e)
        h = self.layout().heightForWidth(self.width())
        if h != self.minimumHeight(): self.setFixedHeight(h)


class _ClickLabel(WrapLabel):
    """Text that behaves like a checkbox label: clicking it toggles the box next to it."""
    clicked = Signal()
    exact = True

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self.clicked.emit()
        super().mouseReleaseEvent(e)


class SettingsDialog(QDialog):
    VOICES = [
        ("en-US-AriaNeural",    "English — Aria (US)"),
        ("en-GB-SoniaNeural",   "English — Sonia (UK)"),
        ("bg-BG-KalinaNeural",  "Bulgarian — Kalina"),
        ("de-DE-KatjaNeural",   "German — Katja"),
        ("fr-FR-DeniseNeural",  "French — Denise"),
        ("es-ES-ElviraNeural",  "Spanish — Elvira"),
        ("ru-RU-SvetlanaNeural","Russian — Svetlana"),
    ]
    voice_progress  = Signal(float, str)     # (fraction done or -1, status text) from the download thread
    whisper_progress = Signal(float, str)    # the same for the speech model that knows every language
    connection_done = Signal(bool, str)
    local_state     = Signal(object)         # the models Ollama has (a set), or None when it is not running
    local_progress  = Signal(float, str)     # (fraction done or -1, status) while Ollama downloads the local model

    def __init__(self, config, theme, parent=None, available_models=None, key_lookup=None):
        super().__init__(parent)
        t = theme; self.t = t; self._config = config
        self._available = sorted(available_models or [])
        self._key_lookup = key_lookup or (lambda provider: "")        # how to read a stored API key (never shown)
        self._active_provider = config.get("provider", providers.DEFAULT_PROVIDER)
        self.setWindowTitle(tr("NOVA Settings"))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(640)
        self.setStyleSheet(f"""
            QDialog{{background:{t['frame_bg']};color:{t['ai_fg']};}}
            QLabel{{color:{t['ai_fg']};}}
            QLineEdit,QListWidget{{background:{t['ai_bg']};color:{t['ai_fg']};
                border:1px solid {t['ai_br']};border-radius:6px;padding:4px 8px;}}
            QPushButton{{background:{t['send_bg']};color:#ffffff;border:none;
                border-radius:6px;padding:5px 16px;}}
            QPushButton:hover{{background:{t['send_hv']};}}
            QTabWidget::pane{{border:1px solid {t['ai_br']};border-radius:8px;top:-1px;background:{t['frame_bg']};}}
            QTabBar::tab{{background:transparent;color:{t['sys_fg']};padding:7px 14px;border:none;}}
            QTabBar::tab:selected{{color:{t['ai_fg']};border-bottom:2px solid {t['accent']};}}
        """ + controls_css(t))
        layout = QVBoxLayout(self)
        layout.setSpacing(12); layout.setContentsMargins(18, 16, 18, 14)
        title = QLabel(tr("NOVA Settings"))
        title.setFont(plat.ui_font(12, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color:{t['ai_fg']};")
        layout.addWidget(title)

        self.tabs = QTabWidget(); self.tabs.setAccessibleName(tr("Settings sections"))
        layout.addWidget(self.tabs, 1)
        for name, build in ((tr("General"), self._tab_general), (tr("AI"), self._tab_ai), (tr("Voice"), self._tab_voice),
                            (tr("Privacy"), self._tab_privacy), (tr("Data"), self._tab_data)):
            page = QWidget(); form = QFormLayout(page); form.setSpacing(10); form.setContentsMargins(14, 14, 14, 14)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            build(form)
            filler = QWidget(); filler.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
            form.addRow(filler)                           # spare height goes below the last row, not between rows
            self.tabs.addTab(page, name)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        cancel = btns.button(QDialogButtonBox.StandardButton.Cancel)             # the quiet one of the two
        cancel.setStyleSheet(f"QPushButton{{background:{t['ai_bg']};color:{t['ai_fg']};border:1px solid {t['ai_br']};"
                             f"border-radius:6px;padding:5px 16px;}}QPushButton:hover{{border-color:{t['sys_fg']};}}")
        layout.addWidget(btns)
        self.voice_progress.connect(self._on_voice_progress)
        self.whisper_progress.connect(self._on_whisper_progress)
        self.connection_done.connect(self._on_connection_done)
        self.local_state.connect(self._on_local_state)
        self.local_progress.connect(self._on_local_progress)

    # ── small helpers ─────────────────────────────────────────────
    def _row(self, form, label, widget):
        """Add a labelled row and give the control a spoken name (VoiceOver)."""
        text = tr(label)
        if isinstance(widget, QWidget) and not isinstance(widget, QCheckBox):
            widget.setAccessibleName(text.rstrip(":"))
        form.addRow(text, widget)
        return widget

    def _check(self, form, label, text, checked):
        """A checkbox row whose description wraps instead of being cut off (long text, long translations)."""
        chk = QCheckBox(); chk.setChecked(bool(checked)); chk.setAccessibleName(text)
        desc = _ClickLabel(text); desc.setWordWrap(True); desc.clicked.connect(chk.toggle)
        desc.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        desc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(chk, 0, Qt.AlignmentFlag.AlignTop); row.addWidget(desc, 1, Qt.AlignmentFlag.AlignTop)
        form.addRow(tr(label), row)
        return chk

    def _small_btn(self, text):
        t = self.t
        b = QPushButton(text)
        b.setStyleSheet(f"QPushButton{{background:{t['frame_bg']};color:{t['ai_fg']};font-size:12px;"
                        f"border:1px solid {t['ai_br']};border-radius:6px;padding:3px 10px;}}"
                        f"QPushButton:hover{{background:{t['ai_br']};}}")
        return b

    def _hint(self, text):
        l = WrapLabel(text); l.exact = True; l.setWordWrap(True)
        l.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        l.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        l.setStyleSheet(f"color:{self.t['sys_fg']};font-size:11px;")
        return l

    @staticmethod
    def _hbox(*widgets):
        """A row of controls that wraps onto a second line instead of being cut off."""
        return _FlowRow(*widgets)

    @staticmethod
    def _select(combo, value):
        combo.setCurrentIndex(max(0, combo.findData(value)))

    # ── General ───────────────────────────────────────────────────
    def _tab_general(self, form):
        c, t = self._config, self.t
        self._theme_cb = QComboBox()
        self._theme_cb.addItem(tr("Auto (follow system)"), "auto")
        for k, v in THEMES.items(): self._theme_cb.addItem(v["label"], k)
        self._select(self._theme_cb, c.get("theme", "auto"))
        self._row(form, "Theme:", self._theme_cb)

        self._accent_preview = QPushButton(); self._accent_preview.setFixedSize(28, 22)
        self._accent_preview.setAccessibleName(tr("Pick accent color"))
        self._accent_color = c.get("accent_color", "")
        _ac = self._accent_color or t["accent"]
        paint = lambda col: self._accent_preview.setStyleSheet(
            f"QPushButton{{background:{col};border:1px solid {t['ai_br']};border-radius:4px;}}")
        paint(_ac)
        self._accent_reset = self._small_btn(tr("Reset"))
        _base_accent = THEMES_BASE.get(c.get("theme", "nova"), THEMES_BASE["nova"])["accent"]
        def _pick_accent():
            col = QColorDialog.getColor(QColor(_ac), self, tr("Pick accent color"))
            if col.isValid(): self._accent_color = col.name(); paint(col.name())
        def _reset_accent():
            self._accent_color = ""; paint(_base_accent)
        self._accent_preview.clicked.connect(_pick_accent); self._accent_reset.clicked.connect(_reset_accent)
        form.addRow(tr("Accent color:"), self._hbox(self._accent_preview, QLabel(tr("Click to pick color")), self._accent_reset))

        self._font_sb = QSpinBox(); self._font_sb.setRange(8, 22); self._font_sb.setValue(c.get("font_size", 10))
        self._row(form, "Font size:", self._font_sb)

        self._ui_lang_cb = QComboBox()
        for code, label in (("auto", tr("Auto (system)")), ("en", "English"), ("bg", "Български")):
            self._ui_lang_cb.addItem(label, code)
        self._select(self._ui_lang_cb, c.get("ui_lang", "auto"))
        self._ui_lang_cb.setToolTip(tr("Applies after restart"))
        self._row(form, "Interface language:", self._ui_lang_cb)

        self._city_edit = QLineEdit(c.get("home_city", ""))
        self._city_edit.setPlaceholderText(tr("e.g. Sofia — used for the weather"))
        self._row(form, "Home city:", self._city_edit)

        self._selection_chk = self._check(form, "Selected text:",
            tr("Press {} in any app to explain, translate or rewrite the selected text").format(plat.SELECTION_HOTKEY_LABEL),
            c.get("selection_actions", True))
        self._paste_chk = self._check(form, "", tr("Paste rewrites and translations straight over the selection "
                                                   "(otherwise they are only copied)"), c.get("selection_paste", False))
        self._auto_chk = self._check(form, "Autostart:", tr(plat.LOGIN_LABEL), plat.autostart_enabled())
        self._hidden_chk = self._check(form, "", tr("At login, start in the menu bar without opening the window "
                                                    "(scheduled tasks and the hotkey still work)"), c.get("start_hidden", True))

    # ── AI ────────────────────────────────────────────────────────
    def _tab_ai(self, form):
        c = self._config
        self._provider_cb = QComboBox()
        for pid, p in providers.PROVIDERS.items(): self._provider_cb.addItem(tr(p["label"]), pid)
        self._select(self._provider_cb, self._active_provider)
        self._row(form, "AI provider:", self._provider_cb)

        self._url_edit = QLineEdit(c.get("base_url", ""))
        self._row(form, "Server address:", self._url_edit)

        self._key_btn = self._small_btn(tr("Change API key") + "…")
        self._test_btn = self._small_btn(tr("Test connection"))
        self._conn_status = self._hint("")
        form.addRow(tr("API key:"), self._hbox(self._key_btn, self._test_btn))
        form.addRow("", self._conn_status)
        self._test_btn.clicked.connect(self._test_connection)

        # Ollama: get the recommended model with one click (shown only for a provider that runs on this computer)
        self._ai_form = form
        self._local_btn = self._small_btn(""); self._local_status = self._hint("")
        self._local_btn.setAccessibleName(tr("Local model"))
        self._local_btn.clicked.connect(self._local_model_clicked)
        self._local_job = None; self._local_models = None
        self._local_row = self._hbox(self._local_btn)
        form.addRow(tr("Local model:"), self._local_row)
        form.addRow("", self._local_status)

        self._model_cb = QComboBox()
        self._row(form, "Model:", self._model_cb)
        self._slot_cbs = {}
        for slot, label in (("smart", "Best model:"), ("fast", "Fast model:"), ("mix", "Third model:")):
            cb = QComboBox(); cb.setEditable(True)
            cb.setToolTip(tr("Pick from the list, or type any model id your provider offers"))
            self._slot_cbs[slot] = cb
            self._row(form, label, cb)
        form.addRow("", self._hint(tr("NOVA starts with the best model and switches to the fast one when it is rate-limited.")))

        self._reason_cb = QComboBox()
        for code, label in (("low", "Fast (recommended)"), ("medium", "Balanced"), ("high", "Deep (slowest)")):
            self._reason_cb.addItem(tr(label), code)
        self._select(self._reason_cb, c.get("reasoning", "low"))
        self._row(form, "Thinking:", self._reason_cb)
        self._followup_chk = self._check(form, "Follow-ups:", tr("Suggest follow-up questions (one extra request per reply)"), c.get("suggest_followups", False))

        self._search_cb = QComboBox()
        self._search_cb.addItem(tr("Several search engines (no key)"), "ddg")
        self._search_cb.addItem(tr("Brave Search (needs a key)"), "brave")
        self._search_cb.setToolTip(tr("Without a key NOVA asks several search engines in turn (DuckDuckGo, Yahoo, Wikipedia and others) through an "
                                    "unofficial library; What NOVA sent lists each one. Brave Search is an official API and needs your own key."))
        self._select(self._search_cb, c.get("search_engine", "ddg"))
        self._search_key_btn = self._small_btn(tr("Brave API key") + "…")
        form.addRow(tr("Web search:"), self._hbox(self._search_cb, self._search_key_btn))
        self._mcp_btn = self._small_btn(tr("Tool servers (MCP)") + "…")
        form.addRow(tr("More tools:"), self._hbox(self._mcp_btn))
        self._usage_btn = self._small_btn(tr("Usage and cost") + "…")
        form.addRow(tr("Usage:"), self._hbox(self._usage_btn))

        self._provider_cb.currentIndexChanged.connect(self._provider_changed)
        self._provider_changed(initial=True)

    def _provider_changed(self, *_a, initial=False):
        pid = self._provider_cb.currentData() or providers.DEFAULT_PROVIDER
        p = providers.info(pid)
        needs_url = bool(p.get("local") or p.get("needs_url"))
        self._url_edit.setEnabled(needs_url)
        self._url_edit.setPlaceholderText(p.get("base_url", "") or ("https://your-server/v1" if needs_url else tr("not needed")))
        self._key_btn.setEnabled(bool(p["needs_key"] or p.get("needs_url")))
        same = pid == self._active_provider
        current = dict(MODELS) if same else {k: tuple(v) for k, v in p["models"].items()}
        pinned = self._config.get("models_by_provider", {}).get(pid, {})
        self._model_cb.clear(); self._slot_initial = {}
        for slot in MODEL_ORDER:
            mid, lbl = current.get(slot, ("", slot.upper()))
            mid = pinned.get(slot) or mid
            self._model_cb.addItem(f"{lbl}  —  {mid or tr('not set')}", slot)
            cb = self._slot_cbs[slot]; cb.blockSignals(True); cb.clear()
            options = list(dict.fromkeys(([mid] if mid else []) + (self._available if same else []) + list(p.get("preferred", {}).get(slot, []))))
            cb.addItems(options); cb.setCurrentText(mid); cb.blockSignals(False)
            self._slot_initial[slot] = mid
        self._select(self._model_cb, self._config.get("model_key", "smart"))
        if not initial: self._conn_status.setText("")
        local = pid == "ollama"
        for w in (self._local_row, self._local_status): self._ai_form.setRowVisible(w, local)
        if local and not self._local_job: self._check_local()

    def _test_connection(self):
        pid = self._provider_cb.currentData(); url = self._url_edit.text().strip()
        self._test_btn.setEnabled(False); self._conn_status.setText(tr("Checking…"))
        lookup = self._key_lookup
        def _bg():
            ok, msg = providers.validate(pid, lookup(pid), url)
            self.connection_done.emit(ok, msg)
        threading.Thread(target=_bg, daemon=True).start()

    def _on_connection_done(self, ok, msg):
        self._test_btn.setEnabled(True); self._conn_status.setText(("✓ " if ok else "✗ ") + msg)

    # ── Ollama: the local model in one click ──────────────────────
    def _check_local(self):
        url = self._url_edit.text().strip()
        self._local_btn.setEnabled(False); self._local_status.setText(tr("Checking Ollama…"))
        def _bg():
            models = providers.ollama_models(url)
            try: self.local_state.emit(models)
            except RuntimeError: pass                          # Settings was closed meanwhile
        threading.Thread(target=_bg, daemon=True).start()

    def _on_local_state(self, models):
        m = providers.LOCAL_MODEL
        self._local_models = models; self._local_btn.setEnabled(True)
        if models is None:
            self._local_btn.setText(tr("Check again"))
            self._local_status.setText(tr("Ollama is not running on this Mac. Install it from ollama.com, start it, then check again."))
        elif m["id"] in models:
            self._local_btn.setText(tr("Use {}").format(m["name"]))
            self._local_status.setText(tr("{} is on this Mac ✓ - with it nothing you type leaves your computer.").format(m["name"]))
        else:
            gb = f"{m['gb']:g}".replace(".", "," if language() == "bg" else ".")       # 2,5 GB in Bulgarian
            self._local_btn.setText(tr("Download {} ({} GB)").format(m["name"], gb))
            self._local_status.setText(tr("Recommended: in NOVA's tests {} picked the right tool for 94 % of requests. "
                                          "Ollama downloads it once.").format(m["name"]))

    def _local_model_clicked(self):
        if self._local_job:                                     # downloading: the button is "Cancel"
            self._local_job["cancel"] = True; return
        m = providers.LOCAL_MODEL
        if self._local_models is None: self._check_local(); return
        if m["id"] in self._local_models: self._use_local_model(); return
        job = self._local_job = {"cancel": False}
        url = self._url_edit.text().strip()
        self._local_btn.setText(tr("Cancel"))
        def emit(frac, status):
            try: self.local_progress.emit(frac, status)
            except RuntimeError: pass                          # Settings was closed; Ollama goes on downloading
        def _bg():
            try:
                providers.ollama_pull(m["id"], url, lambda f: emit(f, ""), lambda: job["cancel"])
                emit(1.0, "ok")
            except Exception as e:
                emit(-1.0, str(e))
        threading.Thread(target=_bg, daemon=True).start()

    def _on_local_progress(self, frac, status):
        if status == "ok":
            self._local_job = None; self._local_models = (self._local_models or set()) | {providers.LOCAL_MODEL["id"]}
            self._use_local_model()
        elif frac < 0:
            self._local_job = None; self._on_local_state(self._local_models)
            if "cancelled" not in status: self._local_status.setText("✗ " + status)
        else:
            self._local_status.setText(tr("Downloading… {}%").format(int(frac * 100)))

    def _use_local_model(self):
        m = providers.LOCAL_MODEL
        for cb in self._slot_cbs.values(): cb.setCurrentText(m["id"])
        self._on_local_state(self._local_models)
        self._local_status.setText(tr("NOVA will use {} after you press Save - nothing you type will leave your computer.").format(m["name"]))

    # ── Voice ─────────────────────────────────────────────────────
    def _tab_voice(self, form):
        c = self._config
        self._tts_chk = self._check(form, "Voice (TTS):", tr("Enabled"), c.get("tts", True))
        self._tts_auto_chk = self._check(form, "Auto-read:", tr("Read every reply aloud"), c.get("tts_auto", False))
        self._tts_engine_cb = QComboBox()
        self._tts_engine_cb.addItem(tr("Online voices (Microsoft)"), "online")
        self._tts_engine_cb.addItem(tr("System voice (offline)"), "system")
        self._tts_engine_cb.setToolTip(tr("Online voices sound better but send the text to Microsoft's speech service (unofficial). The system voice works offline and nothing leaves this Mac."))
        self._select(self._tts_engine_cb, c.get("tts_engine", "online"))
        self._row(form, "Voice engine:", self._tts_engine_cb)
        self._voice_cb = QComboBox()
        for val, label in self.VOICES: self._voice_cb.addItem(tr(label), val)
        self._select(self._voice_cb, c.get("tts_voice", "en-US-AriaNeural"))
        self._row(form, "TTS voice:", self._voice_cb)

        self._stt_cb = QComboBox()
        for code, label in (("", "Auto-detect"), ("en", "English"), ("bg", "Bulgarian"), ("de", "German"),
                            ("fr", "French"), ("es", "Spanish"), ("ru", "Russian")):
            self._stt_cb.addItem(tr(label), code)
        self._select(self._stt_cb, c.get("stt_lang", ""))
        self._row(form, "Voice language:", self._stt_cb)
        self._stt_engine_cb = QComboBox()
        self._stt_engine_cb.addItem(tr("Automatic"), "auto")
        self._stt_engine_cb.addItem(tr("AI provider (best quality)"), "cloud")
        self._stt_engine_cb.addItem(tr("On this Mac (offline)"), "local")
        self._stt_engine_cb.setToolTip(tr("Automatic uses the speech model on this Mac when you have downloaded it (any language, nothing leaves the Mac), otherwise the AI provider's, otherwise the small English model. On this Mac never sends your voice anywhere."))
        self._select(self._stt_engine_cb, c.get("stt_engine", "auto"))
        self._row(form, "Speech recognition:", self._stt_engine_cb)

        self._whisper_btn = self._small_btn(""); self._whisper_status = self._hint("")
        self._whisper_btn.clicked.connect(self._toggle_whisper)
        self._whisper_job = None
        form.addRow(tr("Any language, on this Mac:"), self._hbox(self._whisper_btn))
        form.addRow("", self._whisper_status)
        self._refresh_whisper()

        self._voice_dl_btn = self._small_btn(""); self._voice_status = self._hint("")
        self._voice_dl_btn.clicked.connect(self._toggle_voice_model)
        form.addRow(tr("Wake word, on this Mac:"), self._hbox(self._voice_dl_btn))
        form.addRow("", self._voice_status)
        self._refresh_voice_model()

        self._autostop_chk = self._check(form, "Recording:", tr("Stop recording automatically when I stop talking"), c.get("voice_auto_stop", True))
        self._voice_autosend_chk = self._check(form, "Voice:", tr("Auto-send after voice input"), c.get("voice_auto_send", False))

        self._barge_chk = self._check(form, "Conversation:", tr("In a voice conversation, let me interrupt NOVA by talking"),
                                      c.get("voice_barge_in", True))
        self._wake_chk = self._check(form, "Wake word:", tr("Listen for “Hey NOVA”"), c.get("wake_word", False))
        self._wake_hint = self._hint(""); form.addRow("", self._wake_hint)
        self._wake_sb = QSpinBox(); self._wake_sb.setRange(200, 2000); self._wake_sb.setSingleStep(50)
        self._wake_sb.setValue(c.get("wake_thresh", 700))
        self._wake_sb.setToolTip(tr("Loudness threshold — lower = more sensitive (default 700). Not used by the on-device detector."))
        self._row(form, "Wake sensitivity:", self._wake_sb)
        self._refresh_wake_hint()

    def _refresh_wake_hint(self):
        self._wake_hint.setText(tr("On-device: the wake word is detected on this Mac and no audio is uploaded while listening.")
                                if speech.local_ready() else
                                tr("Without the offline voice model, short clips of speech are sent to the AI provider to detect the wake word."))

    def _refresh_voice_model(self):
        if not speech.vosk_installed():
            self._voice_dl_btn.setEnabled(False); self._voice_dl_btn.setText(tr("Not available"))
            self._voice_status.setText(tr("The on-device speech engine is not part of this build.")); return
        ready = speech.local_ready()
        self._voice_dl_btn.setEnabled(True)
        self._voice_dl_btn.setText(tr("Remove") if ready else tr("Download ({} MB)").format(speech.MODEL_MB))
        self._voice_status.setText(tr("Installed ✓ — the wake word (and English speech) work offline.") if ready else
                                   tr("Lets the “Hey NOVA” wake word (and English speech) work on this Mac, with no audio leaving it."))

    def _toggle_voice_model(self):
        if speech.local_ready():
            speech.remove_model(); self._refresh_voice_model(); self._refresh_wake_hint(); return
        self._voice_dl_btn.setEnabled(False)
        def _bg():
            try:
                speech.download_model(lambda f: self.voice_progress.emit(f, ""))
                self.voice_progress.emit(1.0, "ok")
            except Exception as e:
                self.voice_progress.emit(-1.0, str(e))
        threading.Thread(target=_bg, daemon=True).start()

    def _on_voice_progress(self, frac, status):
        if status == "ok" or frac < 0:
            self._refresh_voice_model(); self._refresh_wake_hint()
            if frac < 0: self._voice_status.setText("✗ " + status)
        else:
            self._voice_status.setText(tr("Downloading… {}%").format(int(frac * 100)))

    def _refresh_whisper(self):
        if not speech.whisper_installed():
            self._whisper_btn.setEnabled(False); self._whisper_btn.setText(tr("Not available"))
            self._whisper_status.setText(tr("The on-device speech engine is not part of this build.")); return
        ready = speech.whisper_ready()
        self._whisper_btn.setEnabled(True)
        self._whisper_btn.setText(tr("Remove") if ready else tr("Download ({} MB)").format(speech.WHISPER_MB))
        self._whisper_status.setText(
            tr("Installed ✓ — Bulgarian, English and 97 more languages are recognised on this Mac. Nothing you say leaves it.")
            if ready else
            tr("Recognises Bulgarian, English and 97 more languages on this Mac, as well as the cloud does (it is the same model), with no audio leaving it."))

    def _toggle_whisper(self):
        if self._whisper_job:                                   # downloading: the button is "Cancel"
            self._whisper_job["cancel"] = True; return
        if speech.whisper_ready():
            speech.remove_whisper(); self._refresh_whisper(); return
        job = self._whisper_job = {"cancel": False}
        self._whisper_btn.setText(tr("Cancel"))
        def emit(frac, status):
            try: self.whisper_progress.emit(frac, status)
            except RuntimeError: pass                          # Settings was closed; the download goes on
        def _bg():
            try:
                speech.download_whisper(lambda f: emit(f, ""), lambda: job["cancel"])
                emit(1.0, "ok")
            except Exception as e:
                emit(-1.0, str(e))
        threading.Thread(target=_bg, daemon=True).start()

    def _on_whisper_progress(self, frac, status):
        if status == "ok" or frac < 0:
            self._whisper_job = None; self._refresh_whisper()
            if frac < 0 and "cancelled" not in status: self._whisper_status.setText("✗ " + tr(status))
        else:
            self._whisper_status.setText(tr("Downloading… {}%").format(int(frac * 100)))

    # ── Privacy ───────────────────────────────────────────────────
    def _tab_privacy(self, form):
        c = self._config
        self._save_hist_chk = self._check(form, "History:", tr("Keep chat history on this Mac"), c.get("save_history", True))
        self._retention_sb = QSpinBox(); self._retention_sb.setRange(0, 3650); self._retention_sb.setSuffix(tr(" days (0 = forever)"))
        self._retention_sb.setValue(int(c.get("retention_days", 90)))
        self._row(form, "Delete saved chats after:", self._retention_sb)
        self._encrypt_chk = self._check(form, "Encryption:", tr("Encrypt chats and memories on disk (key kept in the Keychain)"), c.get("encrypt_data", False))
        self._confirm_up_chk = self._check(form, "Uploads:", tr("Preview screenshots, images and files before sending them to the AI"), c.get("confirm_uploads", True))
        self._external_chk = self._check(form, "Other apps:", tr("Send requests from Shortcuts and nova:// links right away, without me pressing Enter"),
                                         c.get("external_autosend", False))
        self._confirm_mem_chk = self._check(form, "Memory:", tr("Ask before NOVA saves or forgets a memory"), c.get("confirm_memory", False))
        self._smart_mem_chk = self._check(form, "", tr("Find memories by meaning (asks the AI once for keywords when a memory is saved)"),
                                          c.get("smart_memory", True))
        self._mem_view_btn = self._small_btn(tr("View memories")); self._mem_clear_btn = self._small_btn(tr("Clear all"))
        form.addRow(tr("Memories:"), self._hbox(self._mem_view_btn, self._mem_clear_btn))

        self._allow_list = QListWidget(); self._allow_list.setMaximumHeight(92); self._allow_list.setWordWrap(True)
        self._allow_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._allow_list.setAccessibleName(tr("Actions NOVA may do without asking"))
        self._allow_keys = list(c.get("always_allow", []) or [])
        for key in self._allow_keys:
            template, arg = computer_tools.describe_allowance_parts(key)
            self._allow_list.addItem(tr(template).format(arg))
        self._allow_remove_btn = self._small_btn(tr("Remove selected")); self._reset_appr_btn = self._small_btn(tr("Reset approvals"))
        self._allow_remove_btn.clicked.connect(self._remove_allowance)
        self._reset_appr_btn.clicked.connect(self._clear_allowances)
        form.addRow(tr("Allowed without asking:"), self._allow_list)
        form.addRow("", self._hbox(self._allow_remove_btn, self._reset_appr_btn))

        self._sent_btn = self._small_btn(tr("What NOVA sent today") + "…"); self._activity_btn = self._small_btn(tr("View activity log"))
        form.addRow(tr("Transparency:"), self._hbox(self._sent_btn, self._activity_btn))
        self._crash_chk = self._check(form, "Crash reports:", tr("Save a crash report when NOVA fails (stays on this Mac unless you send it)"), c.get("crash_reports", False))

    def _remove_allowance(self):
        i = self._allow_list.currentRow()
        if i >= 0:
            self._allow_list.takeItem(i); del self._allow_keys[i]

    def _clear_allowances(self):
        self._allow_list.clear(); self._allow_keys = []

    # ── Data ──────────────────────────────────────────────────────
    def _tab_data(self, form):
        self._data_export_btn = self._small_btn(tr("Export my data") + "…"); self._data_folder_btn = self._small_btn(tr("Open data folder"))
        self._data_logs_btn = self._small_btn(tr("Open logs")); self._diag_btn = self._small_btn(tr("Copy diagnostics"))
        self._setup_btn = self._small_btn(tr("Run setup again")); self._update_btn = self._small_btn(tr("Check for updates"))
        self._data_wipe_btn = self._small_btn(tr("Delete all my data") + "…")
        form.addRow(tr("Your data:"), self._hbox(self._data_export_btn, self._data_folder_btn))
        form.addRow(tr("Support:"), self._hbox(self._data_logs_btn, self._diag_btn))
        form.addRow(tr("Setup:"), self._hbox(self._setup_btn, self._update_btn))
        self._update_cb = QComboBox()
        for label, value in (("Tell me when there is a new version", "notify"), ("Install new versions by themselves", "install"),
                             ("Do not check", "off")):
            self._update_cb.addItem(tr(label), value)
        self._select(self._update_cb, self._config.get("auto_update", "notify"))
        self._row(form, "Updates:", self._update_cb)
        if self._config.get("update_feed", ""):
            hint = tr("NOVA checks your own update address once a day.")
        elif paths.IS_FROZEN:
            hint = tr("NOVA checks its releases on GitHub once a day and verifies every download before installing it.")
        else:
            hint = tr("This NOVA runs from source: update it with git pull. Check for updates still shows if there is a new release.")
        form.addRow("", self._hint(hint))

        self._sync_folder = self._config.get("sync_folder", "")
        self._sync_btn = self._small_btn(""); self._sync_btn.clicked.connect(self._sync_clicked)
        self._sync_status = self._hint("")
        form.addRow(tr("Other computers:"), self._hbox(self._sync_btn))
        form.addRow("", self._sync_status)
        self._show_sync(self._config.get("sync_status", ""))
        form.addRow(tr("Danger zone:"), self._hbox(self._data_wipe_btn))
        form.addRow("", self._hint(tr("Everything NOVA stores lives in one folder in your Library. Export makes a zip of it "
                                       "(without the API key); Delete removes it and the saved keys.")))

    # ── syncing memories with your other computers (sync.py) ─────
    def _show_sync(self, status: str = ""):
        self._sync_btn.setText(tr("Stop syncing") if self._sync_folder else tr("Set up sync") + "…")
        self._sync_status.setText(status or (
            tr("Syncing through {}.").format(self._sync_folder) if self._sync_folder else
            tr("Keep the same memories on your other computers - a Mac or a Windows PC: choose a folder they all see "
               "(OneDrive, Dropbox, Google Drive, iCloud Drive) and a passphrase.")))

    def _sync_clicked(self):
        if self._sync_folder:
            self._sync_folder = ""; self._show_sync(tr("Syncing stops when you press Save.")); return
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        import sync, keystore
        start = next((p for p in (os.path.expanduser("~/Library/CloudStorage"), os.path.expanduser("~/OneDrive"),
                                  os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs"))
                      if os.path.isdir(p)), os.path.expanduser("~"))
        folder = QFileDialog.getExistingDirectory(self, tr("Choose a folder your other computers see too"), start)
        if not folder: return
        phrase, ok = QInputDialog.getText(self, tr("Sync passphrase"),
                                          tr("At least 8 characters. Use the same passphrase on your other computers: "
                                             "NOVA encrypts what it puts in the folder with it."), QLineEdit.EchoMode.Password)
        if not ok: return
        try:
            others = sync.check_passphrase(folder, phrase)
        except sync.SyncError as e:
            self._show_sync("✗ " + tr(str(e))); return
        if not keystore._save_api_key(phrase, "sync"):
            self._show_sync("✗ " + tr("The passphrase could not be stored safely on this computer.")); return
        self._sync_folder = folder
        self._show_sync(tr("The passphrase fits ✓ - syncing starts when you press Save.") if others else
                        tr("This is the first computer in that folder: set up the others with the same folder and "
                           "passphrase. Syncing starts when you press Save."))

    # ── result ────────────────────────────────────────────────────
    def get_values(self):
        pid = self._provider_cb.currentData() or providers.DEFAULT_PROVIDER
        defaults = providers.info(pid)["models"]
        by_provider = {k: dict(v) for k, v in (self._config.get("models_by_provider", {}) or {}).items()}
        stored = by_provider.get(pid, {})
        pinned = {}
        for slot, cb in self._slot_cbs.items():
            text = cb.currentText().strip()
            if text == self._slot_initial.get(slot, ""):                 # untouched: keep the pin that was stored, if any
                if stored.get(slot): pinned[slot] = stored[slot]         # (a model NOVA swapped in by itself is not pinned)
            elif text and text != defaults.get(slot, ("",))[0]:
                pinned[slot] = text
        if pinned: by_provider[pid] = pinned
        else: by_provider.pop(pid, None)
        return {
            "provider":   pid,
            "base_url":   self._url_edit.text().strip() if self._url_edit.isEnabled() else "",
            "models_by_provider": by_provider,
            "model_key":  self._model_cb.currentData() or "smart",
            "theme":      self._theme_cb.currentData(),
            "font_size":  self._font_sb.value(),
            "tts":        self._tts_chk.isChecked(),
            "tts_voice":  self._voice_cb.currentData(),
            "tts_auto":   self._tts_auto_chk.isChecked(),
            "tts_engine": self._tts_engine_cb.currentData(),
            "stt_engine": self._stt_engine_cb.currentData(),
            "save_history": self._save_hist_chk.isChecked(), "retention_days": self._retention_sb.value(),
            "encrypt_data": self._encrypt_chk.isChecked(),
            "confirm_uploads": self._confirm_up_chk.isChecked(), "confirm_memory": self._confirm_mem_chk.isChecked(),
            "always_allow": list(self._allow_keys),
            "crash_reports": self._crash_chk.isChecked(),
            "external_autosend": self._external_chk.isChecked(),
            "smart_memory": self._smart_mem_chk.isChecked(),
            "auto_update": self._update_cb.currentData(),
            "sync_folder": self._sync_folder,
            "search_engine": self._search_cb.currentData(),
            "voice_auto_stop": self._autostop_chk.isChecked(),
            "voice_barge_in": self._barge_chk.isChecked(),
            "ui_lang":    self._ui_lang_cb.currentData(),
            "reasoning":  self._reason_cb.currentData(),
            "suggest_followups": self._followup_chk.isChecked(),
            "stt_lang":   self._stt_cb.currentData(),
            "wake_word":  self._wake_chk.isChecked(),
            "wake_thresh":self._wake_sb.value(),
            "voice_auto_send": self._voice_autosend_chk.isChecked(),
            "accent_color": self._accent_color,
            "home_city":  self._city_edit.text().strip(),
            "selection_actions": self._selection_chk.isChecked(),
            "selection_paste": self._paste_chk.isChecked(),
            "autostart":  self._auto_chk.isChecked(),
            "start_hidden": self._hidden_chk.isChecked(),
        }

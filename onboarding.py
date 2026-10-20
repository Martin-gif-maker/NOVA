# onboarding.py — first-run setup wizard: consent → API key → permissions → done.
#
# Nothing is requested from the user (and nothing leaves the machine) before this wizard has
# explained it. The wizard only *collects* choices; main.py applies and stores them.
import threading
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                             QCheckBox, QLineEdit, QWidget, QFrame, QComboBox)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
import platform_utils as plat
import themes
import providers
from i18n import tr, language, local, BG

PRIVACY_POINTS = (
    "<b>What stays on your Mac:</b> your chat history, memories, notes and settings "
    "(in your user folder, readable only by you). You can export or delete all of it in Settings.<br><br>"
    "<b>What is sent to other services:</b><br>"
    "• Your messages, and the text of any file or screenshot you ask NOVA to analyse → "
    "<b>the AI provider you choose on the next page</b> (with your own API key). Pick <b>Ollama</b> there "
    "and the AI runs on this Mac instead.<br>"
    "• Optional: spoken audio for voice input → that provider's speech-to-text. With the offline voice "
    "model (Settings → Voice) speech is recognised on this Mac and the wake word never uploads audio.<br>"
    "• Optional: reply text for read-aloud → Microsoft's online voices (edge-tts). Choose the system voice "
    "in Settings → Voice and nothing is sent.<br>"
    "• Weather → Open-Meteo (the city you ask about), news → Google News, web search → several search engines in turn "
    "(DuckDuckGo, Yahoo, Wikipedia …) or Brave; your IP address is visible to them.<br>"
    "• When you ask about your calendar, mail, a web page, selected text or your documents, the part that answers "
    "the question is sent to the AI provider like any other message. Documents are indexed on this Mac; only the "
    "passages that match a question leave it.<br>"
    "• Settings → Privacy → <b>What NOVA sent today</b> lists every request: where it went and how big it was. "
    "You can also encrypt everything NOVA stores on this Mac there.<br><br>"
    "NOVA can also run commands on your computer when you ask. It always asks for approval first "
    "for anything risky (shell commands, deleting files, typing, shutting down)."
)

_SETTINGS_URLS = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "screen":        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "microphone":    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
}


def validate_key(provider: str, key: str, base_url: str = ""):
    """(ok, message) for these credentials. Kept as a module function so tests can replace it."""
    return providers.validate(provider, key, base_url)


class OnboardingDialog(QDialog):
    key_checked = Signal(bool, str)

    def __init__(self, theme: dict, existing_key: bool = False, parent=None, provider: str = "groq",
                 base_url: str = "", saved_keys=None):
        super().__init__(parent)
        self.t = theme
        self.api_key = ""                     # filled when the user enters + validates a new key
        self.provider = provider if provider in providers.PROVIDERS else providers.DEFAULT_PROVIDER
        self.base_url = base_url
        self.keyless = False
        self._saved = set(saved_keys or ()) | ({self.provider} if existing_key else set())   # providers with a stored key
        self._has_key = self.provider in self._saved
        self._key_ok = self._has_key
        self.setWindowTitle(tr("Welcome to NOVA"))
        self.setModal(True)
        self.setMinimumSize(460, 440); self.resize(560, 600)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        t = theme
        self.setStyleSheet(
            f"QDialog{{background:{t['frame_bg']};}}"
            f"QLabel{{color:{t['ai_fg']};}}"
            f"QCheckBox{{color:{t['ai_fg']};spacing:8px;}}"
            f"QLineEdit{{background:{t['ai_bg']};color:{t['ai_fg']};border:1px solid {t['ai_br']};"
            f"border-radius:6px;padding:6px 9px;}}"
            f"QPushButton{{background:{t['send_bg']};color:#ffffff;border:none;border-radius:6px;padding:7px 18px;}}"
            f"QPushButton:hover{{background:{t['send_hv']};}}"
            f"QPushButton:disabled{{background:{t['ai_br']};color:{t['sys_fg']};}}" + themes.controls_css(t))

        root = QVBoxLayout(self); root.setContentsMargins(26, 22, 26, 18); root.setSpacing(12)
        self._stack = QStackedWidget(); root.addWidget(self._stack, 1)
        self._pages = [self._page_welcome(), self._page_key(), self._page_permissions(), self._page_done()]
        for p in self._pages: self._stack.addWidget(self._scrolling(p))

        nav = QHBoxLayout()
        self._dots = QLabel(""); self._dots.setStyleSheet(f"color:{t['sys_fg']};")
        self._back = QPushButton(tr("Back")); self._next = QPushButton(tr("Continue"))
        self._skip = QPushButton(tr("Skip for now"))
        for b in (self._back, self._skip): b.setStyleSheet(
            f"QPushButton{{background:transparent;color:{t['sys_fg']};border:1px solid {t['ai_br']};"
            f"border-radius:8px;padding:8px 16px;}}QPushButton:hover{{color:{t['ai_fg']};}}")
        self._back.clicked.connect(lambda: self._go(-1)); self._next.clicked.connect(lambda: self._go(1))
        self._skip.clicked.connect(self._skip_key)
        nav.addWidget(self._dots); nav.addStretch(); nav.addWidget(self._back); nav.addWidget(self._skip); nav.addWidget(self._next)
        root.addLayout(nav)

        self.key_checked.connect(self._on_key_checked)
        self._poll = QTimer(self); self._poll.timeout.connect(self._refresh_permissions); self._poll.start(1000)
        self._show_page(0)

    # ── helpers ───────────────────────────────────────────────
    @staticmethod
    def _scrolling(page):
        """A page that scrolls when the window is too short for it, instead of cutting off its last lines."""
        from PySide6.QtWidgets import QScrollArea, QFrame
        area = QScrollArea(); area.setWidget(page); area.setWidgetResizable(True); area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
        return area

    def _title(self, text):
        l = QLabel(text); l.setFont(QFont(plat.UI_FONT, 19, QFont.Weight.DemiBold))
        l.setStyleSheet(f"color:{self.t['ai_fg']};"); return l

    def _body(self, html):
        l = QLabel(html); l.setWordWrap(True); l.setTextFormat(Qt.TextFormat.RichText)
        l.setOpenExternalLinks(True); l.setAlignment(Qt.AlignmentFlag.AlignTop); return l

    # ── pages ─────────────────────────────────────────────────
    def _page_welcome(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)
        v.addWidget(self._title(tr("Welcome to NOVA")))
        v.addWidget(self._body(tr("Your personal AI assistant for your desktop. Before we start, here is exactly how your data is handled:")))
        v.addWidget(self._body(local(BG["PRIVACY"] if language() == "bg" else PRIVACY_POINTS)))
        self.consent_chk = QCheckBox(tr("I understand and agree")); self.consent_chk.toggled.connect(self._update_nav)
        v.addWidget(self.consent_chk)
        v.addStretch()
        return w

    def _page_key(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)
        v.addWidget(self._title(tr("Connect your AI")))
        self.provider_cb = QComboBox()
        for pid, p in providers.PROVIDERS.items(): self.provider_cb.addItem(tr(p["label"]), pid)
        self.provider_cb.setCurrentIndex(max(0, self.provider_cb.findData(self.provider)))
        self.provider_cb.setAccessibleName(tr("AI provider"))
        self.provider_cb.currentIndexChanged.connect(self._on_provider_changed)
        v.addWidget(self.provider_cb)
        self.key_help = self._body(""); v.addWidget(self.key_help)
        self.url_edit = QLineEdit(); self.url_edit.setAccessibleName(tr("Server address"))
        self.url_edit.textChanged.connect(self._on_key_edited); v.addWidget(self.url_edit)
        self.key_edit = QLineEdit(); self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setAccessibleName(tr("API key"))
        self.key_edit.textChanged.connect(self._on_key_edited)
        row = QHBoxLayout(); row.addWidget(self.key_edit, 1)
        self.test_btn = QPushButton(tr("Test key")); self.test_btn.clicked.connect(self._test_key); row.addWidget(self.test_btn)
        v.addLayout(row)
        self.key_status = QLabel(""); self.key_status.setWordWrap(True); v.addWidget(self.key_status)
        v.addStretch()
        self._on_provider_changed()
        return w

    def _on_provider_changed(self, *_):
        """Show what the chosen provider needs: a key, a server address, or nothing."""
        self.provider = self.provider_cb.currentData() or providers.DEFAULT_PROVIDER
        p = providers.info(self.provider); name = providers.label(self.provider)
        self._has_key = self.provider in self._saved
        self._key_ok = self._has_key
        self.api_key = ""; self.keyless = False
        if p.get("local"):
            text = tr("{} runs AI models on this Mac - nothing you type leaves your computer, and it works offline. "
                      "Install it from {}, download a model (for example {}), then press Test.").format(
                f"<b>{name}</b>", f"<a href='{p['key_url']}'>ollama.com</a>", "<code>ollama pull llama3.1</code>")
        elif p.get("needs_url"):
            text = tr("Any server that speaks the OpenAI chat API (LM Studio, a company gateway…). Enter its address; the key is optional.")
        else:
            text = tr("NOVA will use {} to think. Create an API key at {} and paste it below. It is stored in your {}, never in a plain file.").format(
                f"<b>{name}</b>", f"<a href='{p['key_url']}'>{p['key_url'].split('//')[-1].rstrip('/')}</a>", plat.KEYSTORE_NAME)
        self.key_help.setText(text)
        needs_url = bool(p.get("local") or p.get("needs_url"))
        self.url_edit.setVisible(needs_url)
        self.url_edit.blockSignals(True)
        self.url_edit.setText(self.base_url if needs_url and self.base_url else p.get("base_url", ""))
        self.url_edit.setPlaceholderText("http://localhost:11434/v1" if p.get("local") else "https://your-server/v1")
        self.url_edit.blockSignals(False)
        self.key_edit.setVisible(not p.get("local"))
        self.key_edit.blockSignals(True); self.key_edit.clear(); self.key_edit.blockSignals(False)
        self.key_edit.setPlaceholderText((p.get("key_hint") or tr("API key (optional)")) + (tr("  (a key is already saved)") if self._has_key else ""))
        self.test_btn.setText(tr("Test key") if p["needs_key"] else tr("Test"))
        self.key_status.setText(tr("Key already saved ✓  (paste a new one to replace it)") if self._has_key else "")
        if hasattr(self, "_next"): self._update_nav()

    def _page_permissions(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)
        v.addWidget(self._title(tr("Permissions")))
        if not plat.IS_MAC:
            v.addWidget(self._body("No extra permissions are needed on this system.")); v.addStretch(); return w
        v.addWidget(self._body(tr("Everything here is optional - NOVA works without it, and macOS only "
                                  "asks when a feature needs it. Grant what you want to use:")))
        self._perm_rows = {}
        for key, name, why in (
            ("accessibility", "Accessibility", "global hotkey, typing into other apps, lock screen"),
            ("screen",        "Screen Recording", "“look at my screen” and screenshots"),
            ("microphone",    "Microphone", "voice input and the wake word")):
            f = QFrame(); f.setStyleSheet(f"QFrame{{border:1px solid {self.t['ai_br']};border-radius:10px;}}")
            h = QHBoxLayout(f); h.setContentsMargins(12, 8, 12, 8)
            col = QVBoxLayout()
            a = QLabel(f"<b>{tr(name)}</b>"); a.setStyleSheet("border:none;")
            b = QLabel(tr(why)); b.setWordWrap(True); b.setStyleSheet(f"border:none;color:{self.t['sys_fg']};")
            col.addWidget(a); col.addWidget(b); h.addLayout(col, 1)
            st = QLabel(""); st.setStyleSheet("border:none;"); h.addWidget(st)
            btn = QPushButton(tr("Allow…")); btn.clicked.connect(lambda _=False, k=key: self._request_permission(k)); h.addWidget(btn)
            self._perm_rows[key] = (st, btn); v.addWidget(f)
        self.wake_chk = QCheckBox(tr("Listen for “Hey NOVA”"))
        self.tts_chk  = QCheckBox(tr("Read replies aloud automatically"))
        for chk, hint in ((self.wake_chk, tr("On this Mac with the offline voice model, otherwise through the AI provider.")),
                          (self.tts_chk, tr("With Microsoft's online voices; Settings → Voice can use the Mac's own voice instead."))):
            note = self._body(hint); note.setStyleSheet(f"color:{self.t['sys_fg']};margin-left:24px;")
            v.addWidget(chk); v.addWidget(note)
        v.addStretch()
        self._refresh_permissions()
        return w

    def _page_done(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)
        v.addWidget(self._title(tr("You're all set")))
        lines = [tr("Show or hide NOVA anywhere with {}").format(f"<b>{plat.HOTKEY_LABEL}</b>"),
                 tr("Type a question, or press the microphone button to speak"),
                 tr("Start a message with {} for a quick calculation (e.g. {})").format("<b>=</b>", "<i>= 15% of 200</i>"),
                 tr("New chat: {} · Settings: the menu at the top right").format(f"<b>{plat.shortcut_label('N')}</b>"),
                 tr("NOVA asks before it runs commands, deletes files or types for you.")]
        v.addWidget(self._body("<br>".join("• " + line for line in lines) + "<br><br>" +
                               tr("You can re-run this setup, export your data or delete everything from Settings at any time.")))
        v.addStretch()
        return w

    # ── navigation ────────────────────────────────────────────
    def _show_page(self, i):
        self._stack.setCurrentIndex(i)
        last = i == len(self._pages) - 1
        self._back.setVisible(i > 0)
        self._skip.setVisible(i == 1 and not self._key_ok)
        self._next.setText(tr("Start using NOVA") if last else tr("Continue"))
        self._dots.setText("●" * (i + 1) + "○" * (len(self._pages) - i - 1))
        self._update_nav()

    def _go(self, d):
        i = self._stack.currentIndex() + d
        if i >= len(self._pages): self.accept(); return
        if i < 0: return
        self._show_page(i)

    def _update_nav(self):
        i = self._stack.currentIndex()
        ok = True
        if i == 0: ok = self.consent_chk.isChecked()
        elif i == 1: ok = self._key_ok
        self._next.setEnabled(ok)
        self._skip.setVisible(i == 1 and not self._key_ok)

    def _skip_key(self):
        self._show_page(2)

    # ── key validation (network call off the UI thread) ───────
    def _on_key_edited(self, _text=""):
        edited = bool(self.key_edit.text().strip()) or (self.url_edit.isVisible() and self.url_edit.text().strip() != (self.base_url or providers.info(self.provider).get("base_url", "")))
        self._key_ok = bool(self._has_key and not edited)
        self.key_status.setText("" if edited else
                                (tr("Key already saved ✓  (paste a new one to replace it)") if self._has_key else ""))
        self._update_nav()

    def _test_key(self):
        key = self.key_edit.text().strip(); prov = self.provider
        url = self.url_edit.text().strip() if self.url_edit.isVisible() else ""
        if providers.info(prov)["needs_key"] and not key and prov != "anthropic":
            self.key_status.setText(tr("Paste your key first")); return
        self.test_btn.setEnabled(False); self.key_status.setText(tr("Checking…"))
        def _bg():
            ok, msg = validate_key(prov, key, url)
            self.key_checked.emit(ok, msg)
        threading.Thread(target=_bg, daemon=True).start()

    def _on_key_checked(self, ok, msg):
        self.test_btn.setEnabled(True)
        self.key_status.setText(("✓ " if ok else "✗ ") + msg)
        self._key_ok = ok
        if ok:
            self.api_key = self.key_edit.text().strip()
            self.base_url = self.url_edit.text().strip() if self.url_edit.isVisible() else ""
            self.keyless = not self.api_key                     # works without a stored key (local server / CLI sign-in)
        self._update_nav()

    # ── permissions ───────────────────────────────────────────
    def _request_permission(self, key):
        if key == "accessibility": plat.accessibility_trusted(prompt=True)
        elif key == "screen":      plat.screen_capture_allowed(request=True)
        elif key == "microphone":
            if plat.microphone_status() == "undetermined":
                plat.request_microphone(); return            # the system prompt appears; no need to open Settings
        plat.open_path(_SETTINGS_URLS[key])

    def _refresh_permissions(self):
        if not plat.IS_MAC or not hasattr(self, "_perm_rows") or self._stack.currentIndex() != 2: return
        for key, (lbl, btn) in self._perm_rows.items():
            if key == "accessibility": ok = plat.accessibility_trusted()
            elif key == "screen":      ok = plat.screen_capture_allowed()
            else:
                st = plat.microphone_status()
                ok = None if st is None else (st == "granted")
            if ok is None: lbl.setText("")
            else:
                lbl.setText("✓ allowed" if ok else "not allowed"); btn.setVisible(not ok)

    # ── result ────────────────────────────────────────────────
    def choices(self) -> dict:
        return {
            "consent":   self.consent_chk.isChecked(),
            "wake_word": bool(getattr(self, "wake_chk", None) and self.wake_chk.isChecked()),
            "tts_auto":  bool(getattr(self, "tts_chk", None) and self.tts_chk.isChecked()),
            "api_key":   self.api_key,
            "provider":  self.provider,
            "base_url":  self.base_url,
            "keyless":   self.keyless or not providers.info(self.provider)["needs_key"],
        }

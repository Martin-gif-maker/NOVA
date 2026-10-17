# widgets.py — chat widgets: message bubbles, the scrolling chat area and the input box.
import re, json, math, time, datetime
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel, QScrollArea, QFrame, QSizePolicy
from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtGui import QFont, QTextDocument
from PySide6.QtGui import Qt as _QtGui
import platform_utils as plat
from i18n import tr
import uistate
import tts
import icons
import actions
from themes import THEMES
from mdrender import _strip_think, _md_to_html, _MD_OK

class _WrapLabel(QLabel):
    """A word-wrapped label that always gets the height its text needs at its current width.

    Qt sizes a wrapped label inside nested or aligned layouts for the height of its *preferred* width.
    When the bubble is narrower than that (a long reply in a normal-sized window) the text needs more
    lines than Qt allowed for, and the end of the message was cut off. Pinning the minimum height to
    heightForWidth(actual width) makes every layout above it give the label enough room."""
    _sized = False
    _fitting = False
    exact = False            # True: the label is exactly as tall as its text (no slack to centre the text in)
    hug = False              # True: as wide as its text on one line, up to what the layout allows (a chat bubble).
                             # Qt's own guess for a wrapped label is narrower, so "remind me at 5 to call Ivan"
                             # wrapped onto two lines in a bubble with room for one.
    _hug_cache = (None, 0)

    def sizeHint(self) -> QSize:
        s = super().sizeHint()
        if not (self.hug and self.wordWrap()): return s
        key = (self.text(), self.font().key(), self.textFormat())
        if self._hug_cache[0] != key:
            doc = QTextDocument(); doc.setDefaultFont(self.font()); doc.setDocumentMargin(0)
            rich = self.textFormat() == Qt.TextFormat.RichText or (
                self.textFormat() == Qt.TextFormat.AutoText and _QtGui.mightBeRichText(self.text()))
            doc.setHtml(self.text()) if rich else doc.setPlainText(self.text())
            self._hug_cache = (key, int(math.ceil(doc.idealWidth())) + 2 * self.margin() + 2)
        w = self._hug_cache[1]
        return QSize(w, max(s.height(), self.heightForWidth(w)))

    def needed_height(self, width: int = None) -> int:
        """The height the text really needs at `width` (QLabel.heightForWidth never answers less than the
        current minimum height, so that is lifted while measuring)."""
        w = self.width() if width is None else width
        floor = self.minimumHeight()
        if floor: self.setMinimumHeight(0)
        try:
            return max(0, self.heightForWidth(w))
        finally:
            if floor: self.setMinimumHeight(floor)

    def _fit(self):
        if self._fitting or not self._sized or self.width() <= 0 or not self.wordWrap(): return
        self._fitting = True
        try:
            h = self.needed_height()
            if self.exact:
                if h != self.minimumHeight() or h != self.maximumHeight(): self.setFixedHeight(h)
            elif h != self.minimumHeight(): self.setMinimumHeight(h)     # grows AND shrinks with the text / width
        finally:
            self._fitting = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sized = True
        self._fit()

    def setText(self, text):
        super().setText(text)
        self._fit()

    def setFont(self, font):
        super().setFont(font)
        self._fit()


WrapLabel = _WrapLabel          # also used by the Settings window for its wrapped hints


def _icon_btn(name: str, tip: str, size: int = 22) -> QPushButton:
    """A small borderless button that shows one of NOVA's line icons (coloured by apply_theme)."""
    b = QPushButton(); b.setFixedSize(size, size); b._icon_name = name
    b.setToolTip(tip); b.setAccessibleName(tip); b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def _paint_icon_btn(b: QPushButton, t: dict, color: str = None, hover_bg: str = None):
    b.setIcon(icons.icon(b._icon_name, color or t["sys_fg"])); b.setIconSize(QSize(15, 15))
    b.setStyleSheet(f"QPushButton{{background:transparent;border:none;border-radius:5px;}}"
                    f"QPushButton:hover{{background:{hover_bg or t['user_bg']};}}")


_LEAD = re.compile(r"^[^\w(\[«“\"'/=+\-]+", re.UNICODE)


def tidy_notice(text: str) -> str:
    """A notice without the emoji many of them start with ("📋  Copied" -> "Copied")."""
    return "\n".join(_LEAD.sub("", line) if i == 0 else line for i, line in enumerate(str(text).split("\n"))) or str(text)


class MessageBubble(QFrame):
    """One message. Yours: a soft rounded bubble on the right. NOVA's: plain text under a small "NOVA" label,
    with what it did (see ToolActivity) and a row of quiet tools. Notices: a small centred line."""
    edit_requested = Signal(object)   # user bubble double-clicked (emits the bubble)
    grew           = Signal()      # streamed text changed the bubble's size

    def __init__(self, text: str, role: str = "user", theme: dict = None, max_width: int = None):
        super().__init__()
        t = theme or THEMES["soft"]
        self._role = role; self._full_text = text; self._theme = t
        self._max_width = max_width
        self._last_render = 0.0
        self._flush_timer = QTimer(self); self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(70)                    # ≈14 repaints/s however fast tokens arrive
        self._flush_timer.timeout.connect(self._flush)
        self.setObjectName("msg")

        outer = QVBoxLayout(self); self._outer = outer
        outer.setSpacing(4)

        self._problem = role == "system" and text.lstrip()[:1] in ("❌", "✗")       # shown in the colour for things that failed
        self._label = _WrapLabel(tidy_notice(text) if role == "system" else text)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self._label.setOpenExternalLinks(True)
        self._label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._label.setFont(plat.ui_font(uistate.FONT_SIZE))
        self._act_btns = []; self._who = None; self._actions = None

        if role == "assistant":
            outer.setContentsMargins(2, 2, 2, 8)
            self._who = QLabel("NOVA"); self._who.setFont(plat.ui_font(8, QFont.Weight.DemiBold))
            outer.addWidget(self._who)
            outer.addWidget(self._label)
            tools = QHBoxLayout(); tools.setContentsMargins(0, 2, 0, 0); tools.setSpacing(4); self._tools = tools
            for name, tip, action in (
                    ("copy", tr("Copy response"), lambda: QApplication.clipboard().setText(_strip_think(self._full_text))),
                    ("speaker", tr("Read aloud"), lambda: tts.speak(self._full_text))):
                btn = _icon_btn(name, tip); btn.clicked.connect(action); tools.addWidget(btn); self._act_btns.append(btn)
            # shown only when the message has a code block
            self._code_copy_btn = _icon_btn("code", tr("Copy code block"))
            self._code_copy_btn.clicked.connect(self._copy_code)
            self._code_copy_btn.setVisible(False)
            tools.addWidget(self._code_copy_btn); tools.addStretch()
            outer.addLayout(tools)
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            self.setMaximumWidth(max_width or 360)
        elif role == "user":
            outer.setContentsMargins(12, 7, 12, 7)
            self._label.hug = True
            outer.addWidget(self._label)
            self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)
            self.setMaximumWidth(max_width or 300)
        else:
            outer.setContentsMargins(8, 2, 8, 2)
            outer.addWidget(self._label)
            self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._label.setFont(plat.ui_font(8))
        self.apply_theme(t)

    def _copy_code(self):
        full = _strip_think(self._full_text)
        blocks = re.findall(r'```[\w+-]*[ \t]*\n?(.*?)```', full, re.DOTALL)
        QApplication.clipboard().setText(blocks[0].strip() if blocks else full)

    def set_actions(self, widget):
        """Show what NOVA did for this reply, between the "NOVA" label and the text."""
        if self._role != "assistant": return
        if self._actions is not None:
            self._outer.removeWidget(self._actions); self._actions.deleteLater()
        self._actions = widget
        self._outer.insertWidget(1, widget)

    def add_tool_button(self, name: str, tip: str, action) -> QPushButton:
        """One more quiet button in the row under a reply (e.g. "regenerate")."""
        btn = _icon_btn(name, tip); btn.clicked.connect(action)
        self._tools.insertWidget(self._tools.count() - 1, btn); self._act_btns.append(btn)
        _paint_icon_btn(btn, self._theme)
        return btn

    def apply_theme(self, t: dict):
        """(Re)style the message - also used when the theme changes while the chat is on screen."""
        self._theme = t
        for btn in self._act_btns: _paint_icon_btn(btn, t)
        if hasattr(self, "_code_copy_btn"): _paint_icon_btn(self._code_copy_btn, t)
        if self._role == "user":
            self.setStyleSheet(f"QFrame#msg{{background-color:{t['user_bg']};border-radius:15px;}}")
            self._label.setStyleSheet(f"color:{t['user_fg']};background:transparent;")
        elif self._role == "assistant":
            self.setStyleSheet("QFrame#msg{background:transparent;border:none;}")
            self._who.setStyleSheet(f"color:{t['sys_fg']};background:transparent;letter-spacing:0.3px;")
            self._label.setStyleSheet(f"color:{t['ai_fg']};background:transparent;")
            if self._label.textFormat() == Qt.TextFormat.RichText and self._full_text.strip():
                self._label.setText(_md_to_html(_strip_think(self._full_text), t))      # code colours depend on the theme
            if self._actions is not None: self._actions.apply_theme(t)
        else:
            self.setStyleSheet("QFrame#msg{background:transparent;}")
            self._label.setStyleSheet(f"color:{t.get('bad', '#C0392B') if self._problem else t['sys_fg']};background:transparent;")

    def append_text(self, chunk: str):
        """Collect streamed text; the (expensive) relayout happens at most every 70 ms."""
        self._full_text += chunk
        if self._role != "assistant":
            self._label.setText(self._full_text); return
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush(self):
        started = time.perf_counter()
        shown = _strip_think(self._full_text)
        fences = shown.count('```')
        if _MD_OK or (fences >= 2 and fences % 2 == 0):
            self._label.setTextFormat(Qt.TextFormat.RichText)
            self._label.setText(_md_to_html(shown, self._theme))
        else:
            self._label.setTextFormat(Qt.TextFormat.PlainText)
            self._label.setText(shown)
        self.grew.emit()
        # Laying out a long reply takes longer and longer; repaint it less often then, so the window stays
        # responsive while the text streams in (drawing may use about a quarter of the time, never most of it).
        self._last_render = time.perf_counter() - started
        self._flush_timer.setInterval(int(min(1500, max(70, self._last_render * 4000))))

    def render_markdown(self):
        self._flush_timer.stop()
        if self._role == "assistant" and self._full_text.strip():
            self._label.setTextFormat(Qt.TextFormat.RichText)
            self._label.setText(_md_to_html(self._full_text, self._theme))
            if hasattr(self, "_code_copy_btn"):
                has_code = "```" in self._full_text
                self._code_copy_btn.setVisible(has_code)

    def mouseDoubleClickEvent(self, e):
        if self._role == "user":
            self.edit_requested.emit(self)
        super().mouseDoubleClickEvent(e)


class DayStamp(QLabel):
    """The small centred time between groups of messages ("Today, 22:41")."""
    def __init__(self, when: datetime.datetime, theme: dict):
        super().__init__(self.wording(when))
        self.when = when
        self.setAlignment(Qt.AlignmentFlag.AlignCenter); self.setFont(plat.ui_font(8))
        self.setContentsMargins(0, 8, 0, 6)
        self.apply_theme(theme)

    @staticmethod
    def wording(when: datetime.datetime, now: datetime.datetime = None) -> str:
        now = now or datetime.datetime.now()
        clock = when.strftime("%H:%M")
        days = (now.date() - when.date()).days
        if days == 0: return f"{tr('Today')}, {clock}"
        if days == 1: return f"{tr('Yesterday')}, {clock}"
        return f"{when.day} {when.strftime('%b')}, {clock}"

    def apply_theme(self, t: dict):
        self.setStyleSheet(f"color:{t['sys_fg']};background:transparent;")


# ──────────────────────────────────────────────────────────────────
#  What NOVA did
# ──────────────────────────────────────────────────────────────────
class ToolActivity(QFrame):
    """What NOVA did for a reply, one neat row per action: an icon, what was done, to what, and whether it
    worked ("📍 Opened Maps  Paris, France  ✓"). Click a row to see the exact tool call and its result."""
    def __init__(self, entries: list, theme: dict):
        super().__init__()
        self._entries = [e for e in entries if e[0] not in actions.HIDDEN or not e[2]]      # [(name, args, ok, result)]
        self._theme = theme
        v = QVBoxLayout(self); v.setContentsMargins(0, 2, 0, 4); v.setSpacing(5)
        self.rows = []; self._detail_labels = []
        for name, args, ok, result in self._entries:
            icon_name, title, detail = actions.describe(name, self._parsed(args))
            row = QPushButton(); row.setCursor(Qt.CursorShape.PointingHandCursor); row.setFixedHeight(32)
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            h = QHBoxLayout(row); h.setContentsMargins(9, 0, 9, 0); h.setSpacing(8)
            ic = QLabel(); ic.setFixedSize(16, 16)
            ttl = QLabel(title); ttl.setFont(plat.ui_font(9, QFont.Weight.Medium))
            det = _ElideLabel(detail); det.setFont(plat.ui_font(9))
            st = QLabel(); st.setFixedSize(16, 16)
            for w in (ic, ttl, det, st): w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            h.addWidget(ic); h.addWidget(ttl); h.addWidget(det, 1); h.addWidget(st)
            row.setAccessibleName(f"{title} {detail}. " + (tr("Done") if ok else tr("Failed")))
            row.setToolTip(tr("Show what NOVA did"))
            more = _WrapLabel(); more.setWordWrap(True); more.setFont(plat.ui_font(8)); more.setVisible(False)
            more.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            more.setTextFormat(Qt.TextFormat.RichText)
            row.clicked.connect(lambda _=False, m=more: m.setVisible(not m.isVisible()))
            v.addWidget(row); v.addWidget(more)
            self.rows.append({"button": row, "icon": ic, "icon_name": icon_name, "title": ttl, "detail": det, "status": st,
                              "more": more, "ok": ok, "name": name, "args": args, "result": result})
        self.apply_theme(theme)

    @staticmethod
    def _parsed(args):
        """The tool's arguments as a dict (the worker hands them over as JSON text)."""
        if isinstance(args, dict): return args
        try:
            v = json.loads(args)
            return v if isinstance(v, dict) else {}
        except (TypeError, ValueError):
            return {}

    def summary(self) -> str:
        """In words: "2 actions · 1 failed"."""
        n = len(self._entries); failed = sum(1 for e in self._entries if not e[2])
        text = tr("{} action").format(n) if n == 1 else tr("{} actions").format(n)
        return text + (" · " + tr("{} failed").format(failed) if failed else "")

    def apply_theme(self, t: dict):
        self._theme = t
        self.setStyleSheet("ToolActivity{background:transparent;border:none;}")
        esc = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for r in self.rows:
            r["button"].setStyleSheet(f"QPushButton{{background:{t['ai_bg']};border:1px solid {t['ai_br']};border-radius:8px;text-align:left;}}"
                                      f"QPushButton:hover{{border-color:{t['sys_fg']};}}")
            r["icon"].setPixmap(icons.pixmap(r["icon_name"], t["ai_fg"]))
            r["title"].setStyleSheet(f"color:{t['ai_fg']};background:transparent;border:none;")
            r["detail"].setStyleSheet(f"color:{t['sys_fg']};background:transparent;border:none;")
            r["status"].setPixmap(icons.pixmap("check" if r["ok"] else "cross", t.get("ok", "#2E7D4F") if r["ok"] else t.get("bad", "#C0392B"), stroke=1.8))
            shown = self._parsed(r["args"])
            args_text = ", ".join(f"{k}={str(v)[:120]}" for k, v in shown.items()) if shown else str(r["args"] or "")
            result = str(r["result"] or "")
            r["more"].setText(f'<b>{esc(r["name"])}</b>({esc(args_text)})<br>→ {esc(result[:300])}{"…" if len(result) > 300 else ""}')
            r["more"].setStyleSheet(f"color:{t['sys_fg']};background:transparent;padding:0 10px 4px 10px;")


class _ElideLabel(QLabel):
    """One line of text that ends in "…" when there is not enough room (instead of pushing the layout wider)."""
    def __init__(self, text: str = ""):
        super().__init__(); self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(10)

    def full_text(self) -> str: return self._full

    def paintEvent(self, e):
        from PySide6.QtGui import QPainter
        p = QPainter(self); p.setFont(self.font()); p.setPen(self.palette().color(self.foregroundRole()))
        text = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, self.width())
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text); p.end()

    def setStyleSheet(self, css: str):
        super().setStyleSheet(css)
        m = re.search(r"color:\s*(#[0-9a-fA-F]{6})", css)
        if m:
            from PySide6.QtGui import QColor
            pal = self.palette(); pal.setColor(self.foregroundRole(), QColor(m.group(1))); self.setPalette(pal)


# ──────────────────────────────────────────────────────────────────
#  Chat Area
# ──────────────────────────────────────────────────────────────────
class _ChatColumn(QWidget):
    """The widget inside the chat's scroll area.

    Qt's minimum height for a column of word-wrapped messages is the height at the narrowest possible width
    (every message wrapped at its tallest), and the scroll area never makes its widget shorter than that. Each
    message reserved 20-40 px it did not use, so an empty gap opened under the last message and grew with every
    message. The height for the real width (the layout's heightForWidth) is what the scroll area should use."""
    def minimumSizeHint(self) -> QSize:
        s = super().minimumSizeHint()
        lay = self.layout()
        if lay is not None and lay.hasHeightForWidth():
            return QSize(s.width(), 0)
        return s


class ChatArea(QScrollArea):
    edit_requested = Signal(object)
    STAMP_GAP = 600           # seconds of silence after which the next message gets a time above it

    def __init__(self):
        super().__init__()
        self._auto_scroll = True
        self._last_stamp = None
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("""
            QScrollArea{border:none;background:transparent;}
            QScrollBar:vertical{width:8px;background:transparent;margin:3px 1px;}
            QScrollBar::handle:vertical{background:rgba(128,128,128,0.32);border-radius:3px;min-height:28px;}
            QScrollBar::handle:vertical:hover{background:rgba(128,128,128,0.5);}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
        """)
        self._container = _ChatColumn()
        self._container.setStyleSheet("background:transparent;")
        self._layout = QVBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setSpacing(8)
        self._layout.setContentsMargins(16, 6, 16, 12)
        self.setWidget(self._container)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def _on_scroll(self, v):
        sb = self.verticalScrollBar()
        self._auto_scroll = v >= sb.maximum() - 40

    _column = 0

    def set_column(self, width: int):
        """Keep the messages in a centred column at most `width` wide (0 = use the whole window) - in full
        screen a line of text as wide as the display is hard to read."""
        self._column = int(width); self._fit_column(); self.restretch_bubbles()

    def _fit_column(self):
        side = 16
        if self._column: side = max(16, (self.viewport().width() - self._column) // 2)
        m = self._layout.contentsMargins()
        if m.left() != side: self._layout.setContentsMargins(side, 6, side, 12)

    def _bubble_max_width(self, role: str = "assistant") -> int:
        """How wide a message may be at the current window size: NOVA's text uses the whole column, your own
        bubble at most four fifths of it."""
        m = self._layout.contentsMargins()
        avail = self.viewport().width() - m.left() - m.right()
        if role == "user": return max(180, min(720, int(avail * 0.82)))
        return max(220, min(860, avail))

    def restretch_bubbles(self):
        """Re-apply the current width cap to every bubble already on screen (called on resize)."""
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, MessageBubble):
                widget.setMaximumWidth(self._bubble_max_width(widget._role))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_column()
        self.restretch_bubbles()

    def add_widget(self, widget) -> object:
        """Add a raw QWidget to the chat and return it."""
        self._layout.addWidget(widget)
        QTimer.singleShot(50, self._scroll_bottom)
        return widget

    def _stamp_if_due(self, theme: dict):
        now = datetime.datetime.now()
        if self._last_stamp is None or (now - self._last_stamp).total_seconds() > self.STAMP_GAP or now.date() != self._last_stamp.date():
            self._layout.addWidget(DayStamp(now, theme or THEMES["soft"]))
        self._last_stamp = now

    def add_message(self, text, role="user", theme=None, markdown=False) -> MessageBubble:
        if role in ("user", "assistant"): self._stamp_if_due(theme)
        b = MessageBubble(text, role, theme, max_width=self._bubble_max_width(role))
        if markdown: b.render_markdown()
        if role == "user":
            # Render markdown in user messages too (bold, inline code, etc.)
            if any(c in text for c in ("**", "*", "`", "##")):
                b._label.setTextFormat(Qt.TextFormat.RichText)
                b._label.setText(_md_to_html(text, theme))
            b.edit_requested.connect(self.edit_requested)
            self._layout.addWidget(b)
            self._layout.setAlignment(b, Qt.AlignmentFlag.AlignRight)
        else:
            self._layout.addWidget(b)
            b.grew.connect(self._scroll_bottom)            # follow the stream while auto-scroll is on
        self._trim_old()
        QTimer.singleShot(30, self._scroll_bottom)
        return b

    MAX_WIDGETS = 300          # older messages stay in the saved history; only the on-screen list is capped

    def _trim_old(self):
        while self._layout.count() > self.MAX_WIDGETS:
            item = self._layout.takeAt(0)
            if item and item.widget(): item.widget().deleteLater()

    def widgets_from(self, start) -> list:
        """`start` and every widget below it."""
        ws = [self._layout.itemAt(i).widget() for i in range(self._layout.count()) if self._layout.itemAt(i).widget()]
        return ws[ws.index(start):] if start in ws else []

    def remove_widget(self, w):
        try:
            w.hide(); self._layout.removeWidget(w); w.deleteLater()
        except RuntimeError:
            pass                       # widget was already deleted (e.g. chat cleared)

    def restyle(self, theme: dict):
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i); wdg = item.widget() if item else None
            if hasattr(wdg, "apply_theme"): wdg.apply_theme(theme)

    def refresh_fonts(self):
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            wdg = item.widget() if item else None
            if isinstance(wdg, MessageBubble) and wdg._role != "system":
                wdg._label.setFont(plat.ui_font(uistate.FONT_SIZE))

    def clear(self):
        self._last_stamp = None
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def _scroll_bottom(self):
        if self._auto_scroll:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def scroll_to_bottom_force(self):
        self._auto_scroll = True
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())




class NovaInput(QTextEdit):
    """Input box: Enter sends, Shift+Enter inserts a newline. It grows with the text, up to a few lines."""
    send_requested = Signal()
    MIN_H, MAX_H = 22, 132

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setTabChangesFocus(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.document().setDocumentMargin(0)
        self.setFixedHeight(self.MIN_H)
        self.document().contentsChanged.connect(self._auto_resize)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and \
                not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.send_requested.emit()
        else:
            super().keyPressEvent(e)

    def _auto_resize(self):
        line = self.fontMetrics().lineSpacing()
        doc_h = int(self.document().size().height()) + 2
        new_h = max(self.MIN_H, line + 2, min(self.MAX_H, doc_h))
        if self.height() != new_h: self.setFixedHeight(new_h)

    def setFont(self, font):
        super().setFont(font); self._auto_resize()

    def resizeEvent(self, e):
        super().resizeEvent(e); self._auto_resize()

    def text(self):         return self.toPlainText()
    def setText(self, t):   self.setPlainText(t)

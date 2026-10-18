# win_build.py — building the window: its layout and buttons, the ＋ and ⋯ menus, the menu bar, the tray icon,
# and the sizes that change between the compact and the full-screen layout.
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
#
# The look ("Crafted"): a quiet Mac window. Three window buttons on the left, the name in the middle, messages
# as plain text on a warm surface, one card at the bottom to write in. Colours come from themes.py, icons from
# icons.py; nothing here uses emoji as an icon.
import re
import logging
from PySide6.QtWidgets import (QApplication, QVBoxLayout, QHBoxLayout, QPushButton, QWidget,
    QLabel, QFrame, QSystemTrayIcon, QMenu, QMenuBar)
from PySide6.QtCore import Qt, QPoint, QRect, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor, QAction, QKeySequence, QPalette
import platform_utils as plat
import paths
import uistate
from uistate import MODE_FULL
import tts
import icons
from i18n import tr
from models import MODELS
from widgets import ChatArea, NovaInput
from settings_dialog import _FlowRow

log = logging.getLogger("nova")
try:
    from games import open_games_menu as _open_games
except Exception:
    _open_games = None


def _plain(text: str) -> str:
    """A menu text without the emoji some translated texts still start with ("📰  Daily news" -> "Daily news")."""
    return re.sub(r"^[^\w(]+", "", str(text), flags=re.UNICODE).strip() or str(text).strip()


class _SubLabel(QLabel):
    """The small second line under the window's name (the song that is playing)."""


class TrafficLights(QWidget):
    """The three round window buttons of a Mac window: red hides NOVA to the menu bar, yellow shrinks it to a
    bubble, green switches full screen. They are real buttons, so the keyboard and VoiceOver can use them."""
    COLORS = ("#FF5F57", "#FEBC2E", "#28C840")

    def __init__(self, on_close, on_minimize, on_zoom):
        super().__init__()
        h = QHBoxLayout(self); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8)
        self.buttons = []
        for tip, fn in ((tr("Hide"), on_close), (tr("Minimize"), on_minimize), (tr("Fullscreen"), on_zoom)):
            b = QPushButton(); b.setFixedSize(12, 12); b.setToolTip(tip); b.setAccessibleName(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, f=fn: f()); h.addWidget(b); self.buttons.append(b)
        self.close, self.minimize, self.zoom = self.buttons
        self.setFixedSize(52, 12)

    def apply(self, t: dict):
        ring = "rgba(0,0,0,0.18)" if not t.get("dark") else "rgba(0,0,0,0.45)"
        for b, c in zip(self.buttons, self.COLORS):
            b.setStyleSheet(f"QPushButton{{background:{c};border:0.5px solid {ring};border-radius:6px;color:transparent;font-size:1px;}}"
                            f"QPushButton:pressed{{background:{QColor(c).darker(125).name()};}}")


class BuildMixin:
    # ── Shared pieces of the look ────────────────────────────────
    RADIUS = 11                    # the window's corners

    def _menu_css(self) -> str:
        t = self._theme
        return (f"QMenu{{background:{t['ai_bg']};border:1px solid {t['ai_br']};border-radius:9px;color:{t['ai_fg']};"
                f"font-size:13px;padding:5px;}}"
                f"QMenu::item{{padding:6px 16px 6px 10px;border-radius:5px;}}"
                f"QMenu::item:selected{{background:{t['accent']};color:#ffffff;}}"
                f"QMenu::item:disabled{{color:{t['sys_fg']};}}"
                f"QMenu::icon{{padding-left:8px;}}"
                f"QMenu::separator{{height:1px;background:{t['ai_br']};margin:5px 8px;}}")

    def _menu(self) -> QMenu:
        m = QMenu(self); m.setStyleSheet(self._menu_css())
        return m

    def _menu_add(self, menu: QMenu, icon: str, text: str, fn):
        """One menu line: a line icon and the text (old emoji at the start of a translated text are dropped)."""
        a = menu.addAction(icons.icon(icon, self._theme["ai_fg"]), _plain(text))
        a.triggered.connect(lambda _=False, f=fn: f())
        return a

    def _paint_icon(self, btn, color: str = None, size: int = 16):
        btn.setIcon(icons.icon(btn._icon_name, color or self._theme["sys_fg"], size)); btn.setIconSize(QSize(size, size))

    # ── UI Scale (normal ↔ fullscreen) ───────────────────────────
    def _apply_ui_scale(self, fullscreen: bool):
        """Sizes and colours that depend on the layout: everything a little larger in full screen."""
        t = self._theme
        base = self.config.get("font_size", 10)
        if fullscreen: msg_fs, tb_h, tb_sz, ib_sz, send_sz, inp_fs, name_fs, small_fs, chip_fs = base + 2, 48, 30, 30, 30, base + 2, 11, 9, 10
        else:          msg_fs, tb_h, tb_sz, ib_sz, send_sz, inp_fs, name_fs, small_fs, chip_fs = base, 40, 26, 26, 26, base, 10, 8, 9
        uistate.FONT_SIZE = msg_fs
        r = self.RADIUS if not fullscreen else 0

        # the window, the title bar and the area around the input box
        self._frame.setStyleSheet(f"QFrame#mainFrame{{background-color:{t['frame_bg']};border:1px solid {t['frame_br']};border-radius:{r}px;}}")
        self._title_bar.setFixedHeight(tb_h)
        self._title_bar.setStyleSheet(f"QFrame#titleBar{{background-color:{t['bar_bg']};border-top-left-radius:{r}px;"
                                      f"border-top-right-radius:{r}px;border-bottom:1px solid {t['bar_br']};}}")
        self._quick_panel.setStyleSheet(f"QFrame#quickPanel{{background-color:{t['bar_bg']};border-bottom:1px solid {t['bar_br']};}}")
        self._input_frame.setStyleSheet("QFrame#inputFrame{background:transparent;border:none;}")
        self._input_card.setStyleSheet(f"QFrame#inputCard{{background-color:{t['ai_bg']};border:1px solid {t['ai_br']};border-radius:10px;}}")

        # title bar: name, the line under it, the small readouts (full screen only)
        self._name_lbl.setFont(plat.ui_font(name_fs, QFont.Weight.DemiBold))
        self._name_lbl.setStyleSheet(f"color:{t['ai_fg']};background:transparent;")
        self._spotify_lbl.setFont(plat.ui_font(max(7, small_fs - 1)))
        self._spotify_lbl.setStyleSheet(f"color:{t['sys_fg']};background:transparent;")
        for lbl in (self._stats_lbl, self._ctx_lbl):
            lbl.setFont(plat.ui_font(small_fs)); lbl.setStyleSheet(f"color:{t['sys_fg']};background:transparent;padding:0 4px;")
            lbl.setVisible(fullscreen)
        for btn in self._title_bar_btns:
            btn.setFixedSize(tb_sz, tb_sz); self._paint_icon(btn, t["sys_fg"], 16 if not fullscreen else 18)
            btn.setStyleSheet(f"QPushButton{{background:transparent;border:none;border-radius:6px;}}"
                              f"QPushButton:hover{{background:{t['user_bg']};}}QPushButton:pressed{{background:{t['ai_br']};}}")
        self._lights.apply(t)

        # the input card
        self.input_field.setFont(plat.ui_font(inp_fs))
        self.input_field.setStyleSheet(f"QTextEdit{{background:transparent;color:{t['ai_fg']};border:none;padding:0;"
                                       f"selection-background-color:{t['accent']};selection-color:#ffffff;}}"
                                       f"QTextEdit:disabled{{color:{t['sys_fg']};}}")
        pal = self.input_field.palette(); pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t["sys_fg"])); self.input_field.setPalette(pal)
        for btn in self._input_bar_btns:
            btn.setFixedSize(ib_sz, ib_sz); self._paint_icon(btn, t["sys_fg"], 16 if not fullscreen else 18)
            btn.setStyleSheet(f"QPushButton{{background:transparent;border:none;border-radius:6px;}}"
                              f"QPushButton:hover{{background:{t['user_bg']};}}QPushButton:pressed{{background:{t['ai_br']};}}")
        self._VOICE_NORMAL = self.voice_btn.styleSheet()
        self._cycle_resp_length_style()
        self._model_lbl.setFont(plat.ui_font(chip_fs))
        self._model_lbl.setStyleSheet(f"QPushButton{{background:transparent;color:{t['sys_fg']};border:1px solid {t['ai_br']};"
                                      f"border-radius:5px;padding:2px 7px;}}QPushButton:hover{{color:{t['ai_fg']};border-color:{t['sys_fg']};}}")
        self.send_btn.setFixedSize(send_sz, send_sz)
        if not self._busy: self._restore_send_look()
        self._scroll_btn.setIcon(icons.icon("down", t["ai_fg"])); self._scroll_btn.setIconSize(QSize(15, 15))
        self._scroll_btn.setStyleSheet(f"QPushButton{{background:{t['ai_bg']};border:1px solid {t['ai_br']};border-radius:14px;}}"
                                       f"QPushButton:hover{{border-color:{t['sys_fg']};}}")

        # quick commands
        for btn in self._quick_btns:
            btn.setFont(plat.ui_font(chip_fs))
            btn.setStyleSheet(f"QPushButton{{background:{t['ai_bg']};color:{t['ai_fg']};border:1px solid {t['ai_br']};"
                              f"border-radius:6px;padding:4px 10px;}}"
                              f"QPushButton:hover{{border-color:{t['sys_fg']};}}QPushButton:pressed{{background:{t['user_bg']};}}")
        self.chat_area.refresh_fonts()
        self.chat_area.set_column(820 if fullscreen else 0)
        self._center_input(fullscreen)

    def _center_input(self, fullscreen: bool):
        """In full screen the input box is as wide as the column of messages, not as wide as the display."""
        side = max(12, (self.width() - 820) // 2) if fullscreen else 12
        self._input_frame.layout().setContentsMargins(side, 4, side, 12 if not fullscreen else 20)

    # ── The "…" menu in the title bar ────────────────────────────
    def _show_overflow_menu(self):
        menu = self._menu()
        self._menu_add(menu, "edit", tr("⊕  New chat"), self._new_chat)
        self._menu_add(menu, "history", tr("📂  Sessions"), self._show_sessions_menu)
        self._menu_add(menu, "export", tr("💾  Export chat"), self._export_chat)
        menu.addSeparator()
        self._menu_add(menu, "palette", tr("🎨  Theme: {}").format(self._theme['label']), self._toggle_theme)
        self._menu_add(menu, "bolt", tr("⚡  Model: {}").format(MODELS[self._model_key][1]), self._switch_model)
        self._menu_add(menu, "pin", tr("Keep on top") if not self._pinned else tr("Do not keep on top"), self._toggle_pin)
        menu.addSeparator()
        self._menu_add(menu, "sliders", tr("⚙  Settings"), self._show_settings)
        self._menu_add(menu, "key", tr("🔑  Change API key"), lambda: self._change_api_key())
        self._menu_add(menu, "plug", tr("🔌  Plugins"), self._show_plugins_dialog)
        self._menu_add(menu, "keyboard", tr("Keyboard shortcuts"), self._show_help)
        menu.exec(self._overflow_btn.mapToGlobal(self._overflow_btn.rect().bottomLeft() + QPoint(0, 4)))

    # ── Quick cmds ───────────────────────────────────────────────
    def _toggle_quick_cmds(self):
        self._quick_visible=not self._quick_visible
        self._quick_panel.setVisible(self._quick_visible)

    # ── UI Build ─────────────────────────────────────────────────
    def _build_ui(self):
        t=self._theme
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)

        x = self.config.get("win_x", 40)
        y = self.config.get("win_y", 80)
        w = min(self.config.get("win_w", 370), 500)   # cap at 500px wide
        h = min(self.config.get("win_h", 540), 800)   # cap at 800px tall
        w = max(w, 280)
        h = max(h, 300)
        # a saved position can be off-screen after a monitor change - pull it back, and keep all of it on screen
        if not any(sc.availableGeometry().contains(QPoint(x + 60, y + 10)) for sc in QApplication.screens()):
            sc = QApplication.primaryScreen().availableGeometry()
            x, y = sc.x() + 40, sc.y() + 80
        from win_modes import on_screen
        self.setGeometry(on_screen(QRect(x, y, w, h)))
        self.setMinimumSize(280, 46)

        self._frame=QFrame(self); self._frame.setObjectName("mainFrame")
        _outer=QVBoxLayout(self); _outer.setContentsMargins(0,0,0,0); _outer.setSpacing(0); _outer.addWidget(self._frame)
        main_layout=QVBoxLayout(self._frame); main_layout.setContentsMargins(1,1,1,1); main_layout.setSpacing(0)

        # ── Title bar: the three window buttons, the name in the middle, two quiet buttons on the right ──
        self._title_bar=QFrame(); self._title_bar.setFixedHeight(40); self._title_bar.setObjectName("titleBar")
        tl=QHBoxLayout(self._title_bar); tl.setContentsMargins(12,0,8,0); tl.setSpacing(4)

        self._lights = TrafficLights(self._close_to_tray, self._toggle_minimize, self._toggle_maximize)
        self._max_btn = self._lights.zoom
        left = QWidget(); ll = QHBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        ll.addWidget(self._lights); ll.addStretch()

        self._name_lbl=QLabel("NOVA"); self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spotify_lbl=_SubLabel(""); self._spotify_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter); self._spotify_lbl.setVisible(False)
        mid = QWidget(); ml = QVBoxLayout(mid); ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)
        ml.addStretch(); ml.addWidget(self._name_lbl); ml.addWidget(self._spotify_lbl); ml.addStretch()
        mid.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)          # dragging the name moves the window

        self._stats_lbl=QLabel(""); self._ctx_lbl=QLabel("")
        self._ctx_lbl.setToolTip(tr("Messages in current context"))
        new_btn=self._tbtn("edit",tr("New chat") + f" ({plat.shortcut_label('N')})"); new_btn.clicked.connect(self._new_chat)
        self._overflow_btn=self._tbtn("menu",tr("More options")); self._overflow_btn.clicked.connect(self._show_overflow_menu)
        self._title_bar_btns=[new_btn,self._overflow_btn]
        right = QWidget(); rl = QHBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(2)
        rl.addStretch(); rl.addWidget(self._ctx_lbl); rl.addWidget(self._stats_lbl); rl.addWidget(new_btn); rl.addWidget(self._overflow_btn)
        self._tb_left, self._tb_right = left, right
        tl.addWidget(left, 1); tl.addWidget(mid, 0); tl.addWidget(right, 1)          # equal sides keep the name centred

        self._title_bar.mousePressEvent=self._tb_press
        self._title_bar.mouseMoveEvent=self._tb_move
        self._title_bar.mouseReleaseEvent=self._tb_release
        self._title_bar.mouseDoubleClickEvent=lambda _e: self._toggle_maximize()

        # ── Quick commands: a row of chips that wraps when the window is narrow ──
        self._quick_panel=QFrame(); self._quick_panel.setObjectName("quickPanel"); self._quick_panel.hide()
        qv=QVBoxLayout(self._quick_panel); qv.setContentsMargins(12,8,12,8)
        self._quick_btns=[]
        for label,fn in [
            (tr("Weather"), lambda: self._quick_cmd(tr("get the current weather") + (f" - {self.config['home_city']}" if self.config.get("home_city") else ""))),
            (tr("Battery"), lambda: self._quick_cmd(tr("what is my battery level"))),
            ("CPU / RAM", lambda: self._quick_cmd(tr("show CPU and RAM stats"))),
            (tr("Network"), lambda: self._quick_cmd(tr("show my network and WiFi info"))),
            (tr("Clipboard"), lambda: self._quick_cmd(tr("what is in my clipboard right now"))),
            (tr("Processes"), lambda: self._quick_cmd(tr("list top 10 running processes by memory"))),
            (tr("Trash"), self._quick_empty_trash),
            (tr("Volume up"), lambda: self._quick_cmd(tr("increase volume by 10"))),
            (tr("Volume down"), lambda: self._quick_cmd(tr("decrease volume by 10"))),
            (tr("Memory"), lambda: self._quick_cmd(tr("read everything you know about me"))),
            (tr("News"), lambda: self._quick_cmd(tr("give me the latest tech news"))),
            (tr("Lock"), lambda: self._quick_cmd(tr("lock the computer"))),
        ]:
            qb=QPushButton(label); qb.setCursor(Qt.CursorShape.PointingHandCursor)
            qb.clicked.connect(fn); self._quick_btns.append(qb)
        qv.addWidget(_FlowRow(*self._quick_btns))

        # ── Chat area ─────────────────────────────────────────────
        self.chat_area=ChatArea()
        self.chat_area.edit_requested.connect(self._edit_message)

        # Scroll-to-bottom button
        self._scroll_btn=QPushButton(self); self._scroll_btn.setFixedSize(28,28)
        self._scroll_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scroll_btn.clicked.connect(self.chat_area.scroll_to_bottom_force); self._scroll_btn.hide()
        self._place_scroll_btn()
        self._scroll_check=QTimer(); self._scroll_check.timeout.connect(
            lambda: self._scroll_btn.setVisible(not self.chat_area._auto_scroll)); self._scroll_check.start(500)

        # ── Input: one card - the text on top, a row of quiet tools under it ──
        self._input_frame=QFrame(); self._input_frame.setObjectName("inputFrame")
        fl=QVBoxLayout(self._input_frame); fl.setContentsMargins(12,4,12,12); fl.setSpacing(0)
        self._input_card=QFrame(); self._input_card.setObjectName("inputCard")
        cv=QVBoxLayout(self._input_card); cv.setContentsMargins(11,9,8,7); cv.setSpacing(6)

        self.input_field=NovaInput(); self.input_field.setPlaceholderText(tr("Message NOVA"))
        self.input_field.setToolTip(tr("Enter sends · Shift+Enter starts a new line"))
        self.input_field.send_requested.connect(self._send)

        row=QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(4)
        self._plus_btn=self._ibtn("plus",tr("Actions")); self._plus_btn.clicked.connect(self._show_plus_menu)
        self.voice_btn=self._ibtn("mic",tr("Voice input - click to start/stop, or hold to talk"))
        self.voice_btn.pressed.connect(self._voice_pressed); self.voice_btn.released.connect(self._voice_released)
        self._len_btn=self._ibtn("lines",tr("Response length: Normal — click to cycle Short / Normal / Detailed"))
        self._len_btn.clicked.connect(self._cycle_resp_length)
        self._input_bar_btns=[self._plus_btn,self.voice_btn,self._len_btn]
        # which model answers, and in which mode - click to change either
        self._model_lbl=QPushButton(MODELS[self._model_key][1]); self._model_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._model_lbl.setToolTip(tr("Mode and model")); self._model_lbl.setAccessibleName(tr("Mode and model"))
        self._model_lbl.clicked.connect(self._show_model_menu)

        self.send_btn=QPushButton(); self.send_btn.setFixedSize(26,26)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self._send)
        self.send_btn.setAccessibleName(tr("Send message"))
        self._len_btn.setAccessibleName(tr("Response length"))
        self.input_field.setAccessibleName(tr("Message NOVA"))
        self._scroll_btn.setAccessibleName(tr("Scroll to latest message"))

        row.addWidget(self._plus_btn); row.addWidget(self.voice_btn); row.addWidget(self._len_btn); row.addSpacing(4)
        row.addWidget(self._model_lbl); row.addStretch(); row.addWidget(self.send_btn)
        cv.addWidget(self.input_field); cv.addLayout(row)
        fl.addWidget(self._input_card)

        main_layout.addWidget(self._title_bar); main_layout.addWidget(self._quick_panel)
        main_layout.addWidget(self.chat_area,stretch=1); main_layout.addWidget(self._input_frame)

        # ── Bubble ───────────────────────────────────────────────
        self._bubble=QFrame(self); self._bubble.setFixedSize(36,36); self._bubble.setGeometry(0,0,36,36)
        self._bubble.setStyleSheet(f"QFrame{{background-color:{t['frame_bg']};border-radius:18px;border:2px solid {t['accent']};}}")
        blbl=QLabel("N",self._bubble); blbl.setGeometry(0,0,36,36); blbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        blbl.setFont(plat.ui_font(11,QFont.Weight.DemiBold)); blbl.setStyleSheet(f"color:{t['accent_fg']};background:transparent;border:none;")
        self._bubble_lbl=blbl
        self._bubble.hide()

        self._bubble_press_pos=QPoint(0,0); self._bubble_click_count=0
        self._bubble_click_timer=QTimer(); self._bubble_click_timer.setSingleShot(True)
        self._bubble_click_timer.timeout.connect(lambda: setattr(self,"_bubble_click_count",0))
        self._bubble.mousePressEvent=self._bubble_press
        self._bubble.mouseMoveEvent=self._bubble_move
        self._bubble.mouseReleaseEvent=self._bubble_release

        self._pulse_state=0; self._pulse_timer=QTimer(); self._pulse_timer.timeout.connect(self._pulse_bubble)

        # the corner you drag to resize (invisible, like on every Mac window)
        self._resize_grip=QLabel("",self); self._resize_grip.setFixedSize(16,16)
        self._resize_grip.setStyleSheet("background:transparent;")
        self._resize_grip.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self._resize_grip.mousePressEvent=self._grip_press
        self._resize_grip.mouseMoveEvent=self._grip_move
        self._resize_grip.mouseReleaseEvent=self._grip_release
        self._grip_drag=None

        self._apply_ui_scale(False)
        self.show(); self._reposition_grip()

    def _place_scroll_btn(self):
        top = self._input_frame.y() if hasattr(self, "_input_frame") and self._input_frame.y() > 0 else self.height() - 96
        self._scroll_btn.move((self.width() - 28) // 2, top - 34); self._scroll_btn.raise_()

    def _tbtn(self,icon,tip=""):
        b=QPushButton(); b.setFixedSize(26,26); b._icon_name=icon; b.setCursor(Qt.CursorShape.PointingHandCursor)
        if tip: b.setToolTip(tip)
        b.setAccessibleName(tip or icon)
        return b

    def _ibtn(self,icon,tip=""):
        b=QPushButton(); b.setFixedSize(26,26); b._icon_name=icon; b.setCursor(Qt.CursorShape.PointingHandCursor)
        if tip: b.setToolTip(tip)
        b.setAccessibleName(tip or icon)
        return b

    def _restore_send_look(self):
        """The send button at rest: the accent colour with a white arrow."""
        t = self._theme
        self.send_btn.setText(""); self.send_btn.setIcon(icons.icon("send", "#ffffff", 14, 2.0)); self.send_btn.setIconSize(QSize(14, 14))
        self.send_btn.setStyleSheet(f"QPushButton{{background:{t['send_bg']};border:none;border-radius:7px;}}"
                                    f"QPushButton:hover{{background:{t['send_hv']};}}"
                                    f"QPushButton:disabled{{background:{t['ai_br']};}}")

    def _show_model_menu(self):
        """The chip in the input box: pick how NOVA behaves (mode) and which model answers."""
        menu = self._menu()
        self._add_mode_items(menu)
        menu.addSeparator()
        self._menu_add(menu, "bolt", tr("⚡  Model: {}").format(MODELS[self._model_key][1]), self._switch_model)
        menu.exec(self._model_lbl.mapToGlobal(self._model_lbl.rect().topLeft() - QPoint(0, menu.sizeHint().height() + 4)))

    # ── Plus menu ────────────────────────────────────────────────
    def _show_plus_menu(self):
        menu = self._menu()
        self._menu_add(menu, "file", tr("📄  Analyze file"), self._analyze_file)
        self._menu_add(menu, "image", tr("📷  Analyze screen"), self._take_screenshot_vision)
        self._menu_add(menu, "crop", tr("✂️  Analyze part of the screen"), self._take_region_vision)
        self._menu_add(menu, "clipboard", tr("📋  Paste clipboard"), self._paste_clipboard)
        menu.addSeparator()
        self._menu_add(menu, "book", tr("📚  Documents"), self._show_documents)
        self._menu_add(menu, "clock", tr("⏰  Scheduled tasks"), self._show_schedule)
        self._menu_add(menu, "note", tr("📝  View notes"), self._show_notes_dialog)
        self._menu_add(menu, "plug", tr("🔌  Tool servers (MCP)"), lambda: self._show_mcp_dialog())
        self._add_mode_menu(menu)
        menu.addSeparator()
        self._menu_add(menu, "headphones", tr("🎧  End voice conversation") if self._conversation else tr("🎧  Voice conversation"), self._toggle_conversation)
        self._menu_add(menu, "stop", tr("⏹  Stop TTS"), tts.stop)
        menu.addSeparator()
        self._menu_add(menu, "news", tr("📰  Daily news"), self._fetch_daily_news)
        self._menu_add(menu, "app", tr("⊘  Quick commands"), self._toggle_quick_cmds)
        self._menu_add(menu, "game", tr("🎮  Games"), lambda: _open_games(self, self._theme) if _open_games else None)
        menu.exec(self._plus_btn.mapToGlobal(self._plus_btn.rect().topLeft() - QPoint(0, menu.sizeHint().height() + 6)))

    def _build_menubar(self):
        """Standard macOS menu bar (File / Edit / View / Window / Help)."""
        mb = QMenuBar()                      # parent-less => the global menu bar on macOS
        def add(menu, text, fn, shortcut=None, role=None):
            a = QAction(text, self)
            if shortcut: a.setShortcut(QKeySequence(shortcut))
            if role is not None: a.setMenuRole(role)
            a.triggered.connect(lambda _=False, f=fn: f()); menu.addAction(a); return a
        m = mb.addMenu(tr("File"))
        add(m, tr("New chat"), self._new_chat, QKeySequence.StandardKey.New)
        add(m, tr("Sessions") + "…", self._show_sessions_menu, "Ctrl+Shift+O")
        add(m, tr("Export chat") + "…", self._export_chat)
        add(m, tr("Settings") + "…", self._show_settings, QKeySequence.StandardKey.Preferences, QAction.MenuRole.PreferencesRole)
        m = mb.addMenu(tr("Edit"))
        for label, name, key in (("Undo", "undo", QKeySequence.StandardKey.Undo), ("Redo", "redo", QKeySequence.StandardKey.Redo),
                                 ("Cut", "cut", QKeySequence.StandardKey.Cut), ("Copy", "copy", QKeySequence.StandardKey.Copy),
                                 ("Paste", "paste", QKeySequence.StandardKey.Paste), ("Select All", "selectAll", QKeySequence.StandardKey.SelectAll)):
            add(m, label, lambda n=name: self._focus_call(n), key)
        m = mb.addMenu(tr("View"))
        add(m, tr("Bigger text"), lambda: self._bump_font(+1), "Ctrl+=")
        add(m, tr("Smaller text"), lambda: self._bump_font(-1), "Ctrl+-")
        add(m, tr("Fullscreen"), self._toggle_maximize)
        add(m, tr("Bubble mode"), self._toggle_minimize)
        m = mb.addMenu(tr("Window"))
        add(m, tr("Show / Hide"), self._toggle_visibility)
        m = mb.addMenu(tr("Help"))
        add(m, tr("What's new"), self._show_whats_new)
        add(m, tr("Keyboard shortcuts"), self._show_help)
        add(m, tr("Open logs"), lambda: self._reveal(paths.LOG_DIR))
        add(m, tr("Usage and cost") + "…", self._show_usage)
        add(m, tr("Copy diagnostics"), self._copy_diagnostics)
        add(m, tr("Check for updates"), self._check_updates)
        self._menubar = mb

    # ── Tray ─────────────────────────────────────────────────────
    def _setup_tray(self):
        self._tray=QSystemTrayIcon(self)
        _icon = self._make_icon()
        self._tray.setIcon(self._make_tray_icon() if plat.IS_MAC else _icon)
        self.setWindowIcon(_icon)
        self._tray.setToolTip(f"NOVA  |  {plat.HOTKEY_LABEL}")
        menu=QMenu()
        menu.addAction(tr("Show / Hide")).triggered.connect(self._toggle_visibility)
        menu.addSeparator()
        menu.addAction(tr("⊕  New chat") + f" ({plat.shortcut_label('N')})").triggered.connect(self._new_chat)
        menu.addAction(tr("💾  Export chat")).triggered.connect(self._export_chat)
        menu.addAction(tr("🔑  Change API key")).triggered.connect(lambda: self._change_api_key())
        menu.addAction(tr("⚙  Settings")).triggered.connect(self._show_settings)
        menu.addSeparator()
        menu.addAction(tr("Quit")).triggered.connect(self._quit_app)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._tray_clicked)
        self._tray.show()

    def _make_tray_icon(self):
        """Monochrome 'template' icon: macOS tints it for light/dark menu bars."""
        px = QPixmap(44, 44); px.fill(QColor(0, 0, 0, 0))
        p = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor("black")); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(3, 3, 38, 38); p.setFont(plat.ui_font(11, QFont.Weight.Bold))
        p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "N"); p.end()
        icon = QIcon(px); icon.setIsMask(True)
        return icon

    def _make_icon(self):
        px=QPixmap(32,32); px.fill(QColor(0,0,0,0))
        p=QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(self._theme["accent"])); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(1,1,30,30); p.setPen(QColor("white"))
        p.setFont(plat.ui_font(10,QFont.Weight.Bold))
        p.drawText(px.rect(),Qt.AlignmentFlag.AlignCenter,"N"); p.end()
        return QIcon(px)

    def _tray_clicked(self,r):
        if r in (QSystemTrayIcon.ActivationReason.Trigger,
                 QSystemTrayIcon.ActivationReason.DoubleClick):
            self._toggle_visibility()

    def _focus_call(self, name: str):
        w = QApplication.focusWidget()
        if isinstance(w, QLabel) and name == "copy" and w.selectedText():
            QApplication.clipboard().setText(w.selectedText()); return
        fn = getattr(w, name, None)
        if callable(fn): fn()

    def _bump_font(self, step: int):
        self.config["font_size"] = max(8, min(22, self.config.get("font_size", 10) + step))
        self._apply_ui_scale(self._mode == MODE_FULL); self.chat_area.refresh_fonts(); self._save_config()

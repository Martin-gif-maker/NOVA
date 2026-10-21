# main.py — NOVA: the window class and the program's entry point.
#
# The window (AssistantWindow) is assembled from mixins, one per area, so no single file has to hold it all:
#   win_build     layout, buttons, menus, menu bar, tray         win_account   provider, models, API key, Settings
#   win_modes     bubble / normal / full-screen                  win_chat      sending, streaming, replies
#   win_voice     microphone, wake word, voice conversation      win_approvals asking before risky actions
#   win_data      chats, sessions, memories, privacy, updates    win_docs      documents and dropped files
#   win_selection text selected in other apps, `--ask`           win_schedule  scheduled tasks
#   win_persona   modes and saved prompts                        win_mcp       tool servers
#   win_extras    stats, Spotify, morning briefing, help
# This file keeps what ties them together: start-up, theme, hotkeys, quitting - and run_app().

import sys
if len(sys.argv) > 2 and sys.argv[1] == "--plugin-host":      # packaged app re-launched as a sandboxed plugin process
    import plugin_host
    sys.exit(plugin_host.main(sys.argv[2:]))
if len(sys.argv) > 1 and sys.argv[1] == "--eventkit-helper":  # packaged app re-launched to talk to Calendar / Reminders
    import eventkit_helper
    sys.exit(eventkit_helper.main())
if "--ask" in sys.argv and "--wait" in sys.argv:              # `NOVA --ask "…" --wait`: print the running NOVA's answer and leave
    import ipc
    sys.exit(ipc.cli(sys.argv))
import os
import gc
import tempfile
import threading
import logging

os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, Signal, QTimer, QObject, QLockFile, QEvent
from PySide6.QtGui import QGuiApplication

import platform_utils as plat
import paths
import uistate
from uistate import MODE_NORMAL, MODE_FULL
from win_modes import WindowModesMixin
from win_voice import VoiceMixin
from win_approvals import ApprovalsMixin
from win_data import DataMixin
from win_chat import ChatMixin
from win_docs import DocsMixin
from win_selection import SelectionMixin
from win_schedule import ScheduleMixin
from win_persona import PersonaMixin
from win_mcp import McpMixin
from win_extras import ExtrasMixin
from win_build import BuildMixin
from win_account import AccountMixin
import tts
import storage
import crash
import ipc
import i18n
from i18n import tr, set_language
from models import MODELS, MODEL_ORDER
from themes import THEMES, THEME_ORDER, readable_on, surfaces
from prompts import _build_prompt
from workers import WakeWordListener

log = logging.getLogger("nova")
try:
    from games import open_games_menu as _open_games
except Exception:
    _open_games = None

# ──────────────────────────────────────────────────────────────────
#  Thread-safe bridge
# ──────────────────────────────────────────────────────────────────
class _Bridge(QObject):
    toggle_window = Signal()
    confirm_request = Signal(str, object)   # (description, holder) - asked from worker threads
    reminder_fired = Signal(str)
    prepare_typing = Signal(object)
    selection_hotkey = Signal()             # "act on the selected text" was pressed in some app
    tts_state = Signal(bool)                # read-aloud started / finished (comes from its own thread)
    tts_playing = Signal(object, float)     # the sound is about to start: (loudness curve of the audio or None, when)
    mcp_changed = Signal(object)            # an MCP tool server connected / failed (comes from its own thread)
    memory_saved = Signal()                 # the AI saved a memory (from the worker thread)


# ──────────────────────────────────────────────────────────────────
#  Main Window
# ──────────────────────────────────────────────────────────────────
class AssistantWindow(WindowModesMixin, VoiceMixin, ApprovalsMixin, DataMixin, DocsMixin, SelectionMixin, ScheduleMixin,
                      PersonaMixin, McpMixin, ChatMixin, ExtrasMixin, BuildMixin, AccountMixin, QWidget):
    _briefing_ready  = Signal(str)
    _news_ready      = Signal(str)
    _spotify_ready   = Signal(str)
    _followup_ready  = Signal(list)
    _title_ready     = Signal(str)
    _sys_msg_ready   = Signal(str)
    _doc_ready       = Signal(object)     # a dropped file / folder was read (see win_docs)
    _region_ready    = Signal(str)        # the user finished (or cancelled) selecting part of the screen
    _update_installed = Signal(str, bool) # (version, restart now?) a new NOVA was put in place
    _models_ready    = Signal(object)
    _update_found    = Signal(object)
    _usage_ready     = Signal(int, int)
    _sync_done       = Signal(object, str)    # (result, error) of a sync with the other computers (win_data)

    def __init__(self):
        super().__init__()
        self._drag_pos         = None
        self._mode             = MODE_NORMAL
        self._pinned           = True
        self._thinking_bubble  = None
        self._streaming_bubble = None
        self._worker           = None
        self._ai_retry_pending = False
        self._session_title    = ""
        self._regen_widget     = None
        self._followup_widget  = None
        self._resp_length      = "normal"   # short | normal | detailed
        self._voice_recorder   = None
        self._vision_worker    = None
        self._wake_listener    = None
        self._conversation     = False          # hands-free voice conversation is on
        self._conv_misses      = 0
        self._barge_in         = None           # listens for you talking over NOVA
        self._echo_gain        = None           # how loud NOVA's own voice reaches the microphone (learned while it speaks)
        self._tagging          = False          # a "keywords for memories" request is running
        self._is_recording     = False
        self._clipboard_hist   = []
        self._last_user_msg    = ""
        self._anim             = None
        # Python's cyclic GC may run on ANY thread; collecting a Qt widget from a worker thread
        # crashes PyQt. So collect only from the GUI thread, on a timer.
        gc.disable()
        self._gc_timer = QTimer(self); self._gc_timer.timeout.connect(gc.collect); self._gc_timer.start(3000)
        self._think_timer      = QTimer(self)
        self._think_timer.timeout.connect(self._animate_thinking)
        self._think_dots       = 0
        self._busy             = False          # an AI request is in flight
        self._voice_press_t    = 0.0
        self._tokens_in = self._tokens_out = 0
        self._voice_press_stopped = False
        self._quitting         = False
        self._app_quitting     = False          # QApplication.quit() has been requested
        self._wiped            = False          # user deleted all data - never write files again
        self._zombies          = []             # cancelled threads that are still finishing
        self._last_ai_bubble   = None
        self._last_other_app   = ""             # the app that was in front before NOVA (target for typed text)
        self._tool_log         = []             # (name, args, ok, result) of the request in flight
        self._tool_groups      = set()          # on-demand tool groups in use right now (calendar, files, an MCP server …)
        self._group_turn       = {}             # group -> the request in which it was last used (see win_chat._next_turn)
        self._turn_no          = 0
        self._last_tool_widget = None
        self._confirm_lock     = threading.Lock()
        self._stats_worker     = None
        self._available_models = set()         # model ids the provider currently offers
        self._encryption_failed = False
        self._quick_visible    = False
        self._saved_normal_geo = None   # geometry before fullscreen
        self._running_spotify  = False
        self._bridge           = _Bridge()
        self._bridge.toggle_window.connect(self._toggle_visibility)
        self._bridge.selection_hotkey.connect(self._on_selection_hotkey)
        self._bridge.tts_state.connect(self._on_tts_state)
        self._bridge.tts_playing.connect(self._on_tts_playing)
        self._bridge.mcp_changed.connect(self._on_mcp_changed)
        self._bridge.memory_saved.connect(self._queue_memory_tags)
        self._briefing_ready.connect(self._show_morning_msg)
        self._news_ready.connect(self._show_news)
        self._spotify_ready.connect(self._update_spotify_lbl)
        self._followup_ready.connect(self._show_followup_chips)
        self._title_ready.connect(self._set_session_title)
        self._models_ready.connect(self._on_models)
        self._sync_done.connect(self._on_sync_done)
        self._update_found.connect(self._offer_update)
        self._sys_msg_ready.connect(lambda m: self.chat_area.add_message(m, "system", self._theme))
        self._doc_ready.connect(self._on_doc_ready)
        self._region_ready.connect(self._on_region_ready)
        self._update_installed.connect(self._on_update_installed)
        self._bridge.confirm_request.connect(self._on_confirm_request)
        self._bridge.reminder_fired.connect(self._on_reminder)
        self._bridge.prepare_typing.connect(self._on_prepare_typing)

        self.config     = self._load_config()
        set_language(self.config.get("ui_lang", "auto"))
        i18n.install_qt_translations()                   # Qt's own buttons and menus in the same language
        if storage.configure(self.config.get("encrypt_data", False)) != self.config.get("encrypt_data", False):
            self._encryption_failed = True          # told to the user once the chat area exists
        crash.install(lambda: bool(self.config.get("crash_reports", False))); crash.enable_fault_log()
        paths.apply_retention(self.config)
        self._activate_models()
        uistate.FONT_SIZE    = self.config.get("font_size", 10)
        tts.ENABLED = self.config.get("tts", True)
        tts.VOICE   = self.config.get("tts_voice", tts.VOICE)
        tts.ENGINE  = self.config.get("tts_engine", "online")
        self._model_key = self.config.get("model_key","smart")
        WakeWordListener.THRESH = self.config.get("wake_thresh", 700)
        self._theme_key = self.config.get("theme","nova")
        if self._theme_key not in THEMES and self._theme_key != "auto": self._theme_key="nova"
        self._theme     = self._resolve_theme()

        self.messages = [{"role":"system","content":_build_prompt()}]
        self.client   = None

        self._build_ui()
        self._apply_persona()
        self._setup_tray()
        self._setup_hotkey()
        self._init_client()
        self._load_history()
        self._startup_notices()
        self._maybe_whats_new()
        self._install_hooks()
        try: QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_theme)
        except Exception as e: log.debug("this Qt does not report light / dark changes: %s", e)
        self._build_menubar()
        self._later(0, self._enable_shadow)
        self._later(1200, self._review_plugins)
        self._start_stats()
        self._start_scheduler()
        self._start_mcp()
        self._start_spotify_monitor()
        self._later(2000, self._maybe_morning_briefing)
        self._later(6000, self._tag_memories)                 # older memories without keywords get them once
        self._later(30000, self._auto_update_check)
        self._later(9000, self._refresh_documents)            # documents that changed while NOVA was closed
        self._later(8000, self._start_sync)                   # memories from your other computers

    def _later(self, ms: int, job):
        """Run a start-up job after `ms` - unless NOVA has been shut down by then (quitting within the first half
        minute must not start an update check or a document refresh)."""
        QTimer.singleShot(ms, lambda: None if self._quitting else job())

    # ── Autostart ────────────────────────────────────────────────
    def _setup_autostart(self):
        return plat.set_autostart(True, os.path.abspath(__file__), self.config.get("start_hidden", True))

    def _remove_autostart(self):
        return plat.set_autostart(False, os.path.abspath(__file__))

    # ── Theme resolution (custom accent never mutates THEMES) ────
    @staticmethod
    def _system_is_dark() -> bool:
        try:
            return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except Exception:
            return False

    def _resolve_theme(self):
        if self._theme_key == "auto":
            th = dict(THEMES["nova" if self._system_is_dark() else "soft"]); th["label"] = "Auto"
        else:
            th = dict(THEMES[self._theme_key])
        ac = self.config.get("accent_color", "")
        if ac:
            th["accent"] = ac; th["send_bg"] = ac
            th["accent_fg"] = readable_on(ac, surfaces(th))
        return th


    # ── Hotkey ───────────────────────────────────────────────────
    def _setup_hotkey(self):
        self._setup_selection_hotkey()
        ok = plat.start_global_hotkey(self._bridge.toggle_window.emit)
        if plat.IS_MAC and (not ok or not plat.accessibility_trusted()):
            QTimer.singleShot(1500, lambda: self.chat_area.add_message(
                tr("⚠️  The global hotkey ({}) and typing need Accessibility permission. "
                   "Allow it in System Settings → Privacy & Security → Accessibility "
                   "(for the app that launches NOVA), then restart NOVA.").format(plat.HOTKEY_LABEL), "system", self._theme))
            if not self.config.get("ax_prompted"):
                self.config["ax_prompted"] = True
                plat.accessibility_trusted(prompt=True)


    # ── Theme ────────────────────────────────────────────────────
    def _on_system_theme(self, *_):
        if self._theme_key == "auto":
            self._theme = self._resolve_theme(); self._apply_theme()


    def _toggle_theme(self):
        order=THEME_ORDER+["auto"]
        idx=order.index(self._theme_key) if self._theme_key in order else -1
        self._theme_key=order[(idx+1)%len(order)]
        self._theme=self._resolve_theme(); self._apply_theme(); self._save_config()
        self.chat_area.add_message(tr("🎨  Theme: {}").format(self._theme['label']),"system",self._theme)

    def _apply_theme(self):
        """Repaint everything in the current theme (colours and sizes live in win_build._apply_ui_scale)."""
        t=self._theme
        self._bubble.setStyleSheet(f"QFrame{{background-color:{t['frame_bg']};border-radius:18px;border:2px solid {t['accent']};}}")
        self._bubble_lbl.setStyleSheet(f"color:{t['accent_fg']};background:transparent;border:none;")
        self.chat_area.restyle(t)
        self._apply_ui_scale(self._mode == MODE_FULL)

    # ── Model ────────────────────────────────────────────────────
    def _switch_model(self):
        idx=MODEL_ORDER.index(self._model_key)
        self._model_key=MODEL_ORDER[(idx+1)%len(MODEL_ORDER)]
        mid,lbl=MODELS[self._model_key]
        self._refresh_model_label(); self._save_config()
        self.chat_area.add_message(tr("⚡  Model: {} ({})").format(lbl, mid),"system",self._theme)


    # ── Shutdown ─────────────────────────────────────────────────
    def closeEvent(self, e):
        """Only a quit closes the window (⌘Q, Dock → Quit, our own Quit); the × button just hides it to the tray.

        Never call QApplication.quit() from here directly: on macOS a quit runs through NSApplication's
        terminate:, which closes the windows and lands here. Quitting again from inside that made AppKit call
        exit() on the spot - NOVA never got back to its own clean exit and the packaged app crashed
        ("NOVA quit unexpectedly"). If this close did not come from a quit, ask for one from the event loop."""
        self._shutdown()
        e.accept()
        if not self._app_quitting:
            self._app_quitting = True
            QTimer.singleShot(0, QApplication.quit)

    def _close_to_tray(self): self._save_config(); self._save_history(); self.hide()

    def _shutdown(self):
        """Stop every thread cleanly and save state (safe to call more than once)."""
        if self._quitting: return
        self._quitting = True
        self._running_spotify = False
        plat.remove_global_hotkey(self._selection_callback())
        for name in ("_gc_timer", "_front_timer", "_think_timer", "_sched_timer"):   # nothing periodic may outlive the window
            t = getattr(self, name, None)
            if t is not None: t.stop()
        self._conversation = False; self._stop_barge_in()
        self._stop_mcp()
        self._external_finish(error="NOVA was closed before it answered.")
        srv = getattr(self, "_ipc_server", None)
        if srv is not None:
            srv.close(); self._ipc_server = None                 # also removes the socket file
        if self._is_recording: self._stop_voice_internal()
        tts.stop()
        if self._wake_listener: self._wake_listener.stop()
        self._abandon_worker()
        if self._stats_worker: self._stats_worker.requestInterruption()
        self._save_config(); self._save_history()
        if hasattr(self,"_tray"): self._tray.hide()
        for th in [self._wake_listener, self._stats_worker, self._voice_recorder, self._vision_worker] + list(self._zombies):
            self._stop_thread(th, 2500)

    def _quit_app(self):
        self._shutdown()
        self._app_quitting = True                 # closeEvent must not ask for a second quit (see there)
        QApplication.quit()


    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.input_field.clear(); self.input_field.setFocus()
            return
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:    # ⌘ on macOS
            step = 1 if e.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal) else -1 if e.key() == Qt.Key.Key_Minus else 0
            if e.key() == Qt.Key.Key_N:
                self._new_chat()
            elif step:
                self._bump_font(step)
        super().keyPressEvent(e)


# ──────────────────────────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────────────────────────
def _setup_logging():
    from logging.handlers import RotatingFileHandler
    os.makedirs(paths.LOG_DIR, exist_ok=True)
    h = RotatingFileHandler(paths.LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO); root.addHandler(h)
    crash.install(lambda: False)                    # log every uncaught error; the window turns reports on if you opted in


class _UrlOpener(QObject):
    """macOS hands a clicked nova://ask?text=… link to the app as a 'file open' event."""
    def __init__(self, window):
        super().__init__(); self._window = window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FileOpen:
            text = ipc.text_from_url(event.url().toString())
            if text:
                self._window._external_ask(text); return True
        return False


_exit_guard = None          # keeps the C callback alive


def _install_exit_guard(window) -> None:
    """Safety net: if something ends the process with C exit() while NOVA is running (AppKit can, during a
    forced terminate), save and leave *before* the C++ static destructors run - PySide can crash in them,
    which macOS reports as "NOVA quit unexpectedly". Every normal path leaves through exit_now() instead."""
    global _exit_guard
    try:
        import ctypes

        def _leave():
            try:
                log.warning("the process is being ended by exit() - leaving through the exit guard")
                window._shutdown()
                logging.shutdown()
            finally:
                os._exit(0)
        _exit_guard = ctypes.CFUNCTYPE(None)(_leave)
        ctypes.CDLL(None).atexit(_exit_guard)
    except Exception as e:
        log.info("exit guard not installed: %s", e)


def run_app(argv) -> int:
    """Start NOVA and block until it quits. Returns the exit code."""
    _setup_logging()
    log.info("NOVA %s starting (frozen=%s)", paths.__version__, paths.IS_FROZEN)
    plat.brand_process("NOVA")                       # menu bar / Dock say "NOVA", not "Python", when run from source
    app = QApplication(argv)
    app.setApplicationName("NOVA"); app.setApplicationDisplayName("NOVA")
    app.setQuitOnLastWindowClosed(False)
    # one NOVA at a time (two copies would fight over the hotkey and the microphone)
    lock = QLockFile(os.path.join(tempfile.gettempdir(), "nova_assistant.lock"))
    lock.setStaleLockTime(0)
    ask = ipc.arg_value(argv, "--ask")               # `NOVA --ask "text"`: how a Shortcut or script hands NOVA a request
    if not lock.tryLock(200):
        if ask:
            sent = ipc.send({"ask": ask})
            print("Passed to the running NOVA." if sent else "NOVA is running but did not take the request."); return 0 if sent else 1
        print("NOVA is already running."); return 0
    window = AssistantWindow()
    app.setWindowIcon(window.windowIcon())           # Dock icon
    app.aboutToQuit.connect(window._shutdown)
    window._ipc_server = ipc.start(window._external_message)
    opener = _UrlOpener(window); app.installEventFilter(opener); window._url_opener = opener      # nova://ask?text=…
    if ask: QTimer.singleShot(900, lambda: window._external_ask(ask))
    if "--hidden" in argv and not ask:               # started at login: stay in the menu bar; the hotkey / tray icon opens it
        window.hide()
    window._refresh_login_item()
    if os.environ.get("NOVA_REPORT_VISIBLE"):        # used by the automated tests
        QTimer.singleShot(600, lambda: log.info("window visible at start: %s", window.isVisible()))
    _install_exit_guard(window)
    quit_after = os.environ.get("NOVA_QUIT_AFTER_MS")        # used by the automated start/quit smoke test
    if quit_after: QTimer.singleShot(int(quit_after), window._quit_app)
    code = app.exec()
    window._shutdown()
    lock.unlock()
    log.info("NOVA quit (code %s)", code)
    return code


def exit_now(code: int):
    """Leave without Python's end-of-process garbage collection.

    By this point everything is saved and every thread is stopped. PySide can crash (segfault) when
    Python destroys leftover signal connections after the QApplication is gone, which macOS would
    report as "NOVA quit unexpectedly" - so skip that phase."""
    logging.shutdown()
    try: sys.stdout.flush(); sys.stderr.flush()
    except Exception: pass                  # leaving anyway: nothing useful can be done about a failed flush
    os._exit(code)


if __name__ == "__main__":
    if "--selftest" in sys.argv:                 # used by CI / packaging: imports worked, paths resolve
        import selftest
        sys.exit(selftest.run())
    try:
        exit_code = run_app(sys.argv)
    except BaseException as e:                    # report, then leave the same safe way as a normal quit
        if isinstance(e, SystemExit):
            exit_code = e.code if isinstance(e.code, int) else 1
        else:
            log.error("Startup crash", exc_info=True)
            import traceback; traceback.print_exc()
            exit_code = 1
    exit_now(exit_code)

# win_extras.py — ambient extras: system stats, Spotify label, morning briefing, news, help and plugin lists.
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
import os
import time
import threading
import datetime
import logging
from PySide6.QtWidgets import (QVBoxLayout, QLabel, QDialog, QTextEdit, QDialogButtonBox)
from PySide6.QtCore import Qt, QTimer
import tools as computer_tools
import platform_utils as plat
import paths
import ledger
from i18n import tr
from schemas import TOOLS_SCHEMA, _PLUGIN_SCHEMAS
from workers import StatsWorker

log = logging.getLogger("nova")


class ExtrasMixin:
    # ── Spotify monitor ──────────────────────────────────────────
    def _start_spotify_monitor(self):
        self._running_spotify=True
        def _bg():
            while self._running_spotify:
                if not self.isVisible():
                    time.sleep(10); continue
                try:
                    title=plat.spotify_now_playing()
                    track = title if (title and title.lower()!="spotify" and " - " in title) else ""
                    self._spotify_ready.emit(track)
                except Exception: self._spotify_ready.emit("")
                time.sleep(10)
        threading.Thread(target=_bg,daemon=True).start()

    def _update_spotify_lbl(self,track:str):
        if track:
            short=track[:35]+"…" if len(track)>35 else track
            self._spotify_lbl.setText(f"♪ {short}")
            self._spotify_lbl.setVisible(True)
        else:
            self._spotify_lbl.setVisible(False)

    # ── Morning briefing ─────────────────────────────────────────
    def _maybe_morning_briefing(self):
        if self.config.get("consent") and 7 <= datetime.datetime.now().hour <= 11:
            home_city = self.config.get("home_city", "")
            def _bg():
                import requests, xml.etree.ElementTree as ET
                weather = ""
                if home_city:                                      # weather needs a place; no silent IP-based guessing
                    w = computer_tools.get_weather(home_city)
                    if not isinstance(w, computer_tools.ToolFailure): weather = str(w)
                news = []
                try:
                    ledger.record("news.google.com", "news headlines")
                    r = requests.get(
                        "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
                        timeout=8, headers={"User-Agent":"Mozilla/5.0"})
                    r.raise_for_status()
                    for item in ET.fromstring(r.content).findall(".//item")[:5]:
                        title = (item.find("title").text or "").strip()
                        if " - " in title: title = title.rsplit(" - ",1)[0].strip()
                        news.append(title)
                except Exception as e: log.info("morning headlines could not be fetched: %s", e)
                self._briefing_ready.emit(weather + "|||" + "\n".join(news))
            threading.Thread(target=_bg, daemon=True).start()

    def _show_morning_msg(self, payload: str):
        parts   = payload.split("|||", 1)
        weather = parts[0].strip()
        news    = parts[1].strip() if len(parts) > 1 else ""
        lines   = [tr("Good morning! ☀️")]
        if weather: lines.append(tr("Weather") + f": {weather}")
        if news:
            lines.append("\n" + tr("Top news:"))
            for i, h in enumerate(news.splitlines(), 1):
                lines.append(f"  {i}. {h}")
        lines.append("\n" + tr("Ready — what shall we start with?"))
        self.chat_area.add_message("\n".join(lines), "assistant", self._theme)

    # ── Daily news ───────────────────────────────────────────────
    def _fetch_daily_news(self):
        self.chat_area.add_message(tr("📰  Loading news..."), "system",self._theme)
        def _bg():
            try:
                import requests,xml.etree.ElementTree as ET
                ls="en-US&gl=US&ceid=US:en"
                ledger.record("news.google.com", "news headlines")
                r=requests.get(f"https://news.google.com/rss?hl={ls}",
                    timeout=10,headers={"User-Agent":"Mozilla/5.0"})
                r.raise_for_status()
                root=ET.fromstring(r.content); items=root.findall(".//item")[:12]
                today=datetime.datetime.now().strftime("%d.%m.%Y")
                lines=[f"**📰 Top news — {today}**\n"]
                for i,item in enumerate(items,1):
                    title=(item.find("title").text or "").strip()
                    if " - " in title: title=title.rsplit(" - ",1)[0].strip()
                    lines.append(f"{i}. {title}")
                self._news_ready.emit("\n".join(lines))
            except Exception as e: self._news_ready.emit(f"❌ Error: {e}")
        threading.Thread(target=_bg,daemon=True).start()

    def _show_news(self,text:str):
        self.chat_area.add_message(text,"assistant",self._theme,markdown=True)
        QTimer.singleShot(60, self.chat_area.scroll_to_bottom_force)

    def _start_stats(self):
        self._stats_worker=StatsWorker()
        self._stats_worker.paused = not self.isVisible()
        self._stats_worker.updated.connect(lambda txt: self._stats_lbl.setText(txt))
        self._stats_worker.start()

    def _quick_empty_trash(self):
        if not self._ask_user("Permanently empty the Trash"):
            return
        def _bg():
            self._sys_msg_ready.emit("🗑️  " + computer_tools.empty_recycle_bin())
        threading.Thread(target=_bg, daemon=True).start()

    def _show_plugins_dialog(self):
        t = self._theme
        d = QDialog(self); d.setWindowTitle(tr("NOVA — Active Plugins & Tools"))
        d.setMinimumWidth(380); d.setMinimumHeight(260)
        d.setStyleSheet(f"background:{t['frame_bg']};color:{t['ai_fg']};")
        v = QVBoxLayout(d); v.setContentsMargins(16,14,16,14)
        te = QTextEdit(); te.setReadOnly(True)
        te.setStyleSheet(f"background:{t['ai_bg']};color:{t['ai_fg']};"
                         f"border:1px solid {t['ai_br']};border-radius:8px;padding:8px;")
        # Built-in tools count
        builtin = [s["function"]["name"] for s in TOOLS_SCHEMA if s.get("function")]
        plugin_tools = [s["function"]["name"] for s in _PLUGIN_SCHEMAS if s.get("function")]
        lines = [f"Built-in tools ({len(builtin)}):"]
        for name in sorted(builtin):
            lines.append(f"  • {name}")
        if plugin_tools:
            lines.append(f"\nPlugin tools ({len(plugin_tools)}):") 
            for name in sorted(plugin_tools):
                info = computer_tools.PLUGIN_INFO.get(name, {})
                how = ("sandboxed — " + (", ".join(info["permissions"]) or "no permissions")) if info.get("sandboxed") \
                    else "NOT sandboxed (no MANIFEST)"
                lines.append(f"  • {name}   [{info.get('file', '?')}: {how}]")
            # List plugin files
            plugins_dir = paths.PLUGINS_DIR
            if os.path.isdir(plugins_dir):
                pfiles = [f for f in os.listdir(plugins_dir) if f.endswith(".py")]
                lines.append(f"\nPlugin files: {', '.join(pfiles)}")
        else:
            lines.append("\nNo plugins loaded.")
            lines.append(f"Drop .py files into: {paths.PLUGINS_DIR}")
        te.setPlainText("\n".join(lines))
        v.addWidget(te)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.setStyleSheet(f"QPushButton{{background:{t['send_bg']};color:#fff;border:none;"
                         f"border-radius:8px;padding:4px 16px;}}QPushButton:hover{{background:{t['send_hv']}}}")
        bb.rejected.connect(d.reject); v.addWidget(bb)
        d.exec()

    def _show_help(self):
        t = self._theme
        d = QDialog(self); d.setWindowTitle(tr("NOVA — Keyboard Shortcuts"))
        d.setMinimumWidth(360)
        d.setStyleSheet(f"background:{t['frame_bg']};color:{t['ai_fg']};")
        v = QVBoxLayout(d); v.setSpacing(10); v.setContentsMargins(20,16,20,16)
        shortcuts = [
            (plat.HOTKEY_LABEL,            "Show / hide NOVA from anywhere"),
            (plat.SELECTION_HOTKEY_LABEL,  "Explain, translate or rewrite the text selected in any app"),
            (f"{plat.MOD_NAME} + N",       "New chat"),
            (f"{plat.MOD_NAME} + + / −",   "Increase / decrease font size"),
            ("Enter",          "Send message"),
            ("Shift + Enter",  "New line"),
            ("= …",            "Quick calculator  (e.g. = 15% of 200, = 2^10)"),
            ("＋",              "Open action menu (news, clipboard, file, screen…)"),
            (tr("Microphone"), "Voice input — click again to stop"),
            (tr("Length"),     "Cycle response length: Short / Normal / Detailed"),
            ("≡",              "The menu: new chat, sessions, theme, model, settings"),
            (tr("Regenerate"), "Regenerate last AI response"),
            (tr("Double-click"), "Edit a sent message (removes it and the replies after it)"),
            (f"{plat.MOD_NAME} + Q",       "Quit NOVA"),
            (tr("Drag the title bar"), "Move window"),
            (tr("Drag a corner"),      "Resize window"),
        ]
        for key, desc in shortcuts:
            row = QLabel(f"<b style='color:{t['accent_fg']}'>{key}</b>&nbsp;&nbsp;{tr(desc)}")
            row.setTextFormat(Qt.TextFormat.RichText)
            row.setFont(plat.ui_font(9))
            v.addWidget(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.setStyleSheet(f"QPushButton{{background:{t['send_bg']};color:#fff;border:none;"
                         f"border-radius:8px;padding:4px 16px;}}QPushButton:hover{{background:{t['send_hv']}}}")
        bb.rejected.connect(d.reject); v.addWidget(bb)
        d.exec()

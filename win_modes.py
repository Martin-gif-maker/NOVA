# win_modes.py — window geometry: bubble / normal / fullscreen, dragging, resizing, show/hide.
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
import logging
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QRect, QEasingCurve, QAbstractAnimation
from PySide6.QtGui import QGuiApplication
import platform_utils as plat
from uistate import MODE_BUBBLE, MODE_NORMAL, MODE_FULL
from i18n import tr

log = logging.getLogger("nova")


def on_screen(rect: QRect) -> QRect:
    """`rect` moved (and if need be shrunk) so that all of it is on the screen it starts on."""
    screens = QApplication.screens()
    home = next((sc for sc in screens if sc.availableGeometry().contains(rect.topLeft())), QApplication.primaryScreen())
    area = home.availableGeometry()
    w, h = min(rect.width(), area.width()), min(rect.height(), area.height())
    x = min(max(rect.x(), area.x()), area.x() + area.width() - w)
    y = min(max(rect.y(), area.y()), area.y() + area.height() - h)
    return QRect(x, y, w, h)

class WindowModesMixin:
    # ── THREE-MODE window management ─────────────────────────────
    def _run_geometry_anim(self, start_rect, end_rect, duration, easing, on_finished):
        """Resize/move the window, animated on Windows; instant on macOS.

        macOS's Cocoa windowing animates a frameless/translucent top-level
        window's geometry unreliably — the window (and the QScrollArea
        viewport inside it) can be left at a stale in-between size. Setting
        the final geometry directly avoids that class of bug entirely.
        """
        if plat.IS_MAC:
            self._anim = None
            self.setGeometry(end_rect)
            QTimer.singleShot(0, on_finished)
            return
        anim = QPropertyAnimation(self, b"geometry"); anim.setDuration(duration)
        anim.setStartValue(start_rect); anim.setEndValue(end_rect)
        anim.setEasingCurve(easing)
        anim.finished.connect(on_finished)
        self._anim = anim; anim.start()

    def _set_mode(self, target_mode: str):
        if self._anim and self._anim.state()==QAbstractAnimation.State.Running: return

        current = self._mode

        if target_mode == MODE_BUBBLE:
            if current == MODE_FULL: self._restore_from_full(then_bubble=True); return
            # normal → bubble
            self.config["win_h"]=self.height(); self.config["win_w"]=self.width()
            self.setMinimumSize(0,0)
            _start=QRect(self.x(),self.y(),self.width(),self.height())
            _end=QRect(self.x(),self.y(),36,36)
            def _done_bubble():
                self._mode=MODE_BUBBLE; self._frame.hide(); self._resize_grip.hide()
                self.setFixedSize(36,36); self._bubble.setGeometry(0,0,36,36)
                self._bubble.show(); self._pulse_timer.start(600)
                self._max_btn.setText("□")
                _last = next((m["content"][:280] for m in reversed(self.messages)
                              if m.get("role") == "assistant"), tr("NOVA — click to expand"))
                self._bubble.setToolTip(_last)
            self._run_geometry_anim(_start, _end, 220, QEasingCurve.Type.InCubic, _done_bubble)

        elif target_mode == MODE_NORMAL:
            if current == MODE_BUBBLE:
                # bubble → normal
                w=self.config.get("win_w",370); h=self.config.get("win_h",540)
                self._bubble.hide(); self._pulse_timer.stop()
                self.setMinimumSize(0,0); self.setMaximumSize(16777215,16777215)
                self._frame.show(); self._resize_grip.show()
                _start=QRect(self.x(),self.y(),36,36)
                _end=on_screen(QRect(self.x(),self.y(),w,h))      # a bubble parked in a corner opens fully on screen
                def _done_normal():
                    self._mode=MODE_NORMAL; self.setMinimumSize(280,46); self._reposition_grip()
                    self._max_btn.setText("□")
                self._run_geometry_anim(_start, _end, 280, QEasingCurve.Type.OutCubic, _done_normal)
            elif current == MODE_FULL:
                self._restore_from_full()

        elif target_mode == MODE_FULL:
            # normal → fullscreen
            self._saved_normal_geo=self.geometry()
            screen=(self.screen() or QApplication.primaryScreen()).availableGeometry()
            self.setMinimumSize(0,0); self.setMaximumSize(16777215,16777215)
            _start=self.geometry()
            _end=QRect(screen.x(),screen.y(),screen.width(),screen.height())
            def _done_full():
                self._mode=MODE_FULL; self._max_btn.setText("❐"); self._reposition_grip()
                self._apply_ui_scale(True)
            self._run_geometry_anim(_start, _end, 250, QEasingCurve.Type.OutCubic, _done_full)

    def _restore_from_full(self, then_bubble=False):
        geo=self._saved_normal_geo or QRect(40,80,370,540)
        self.setMinimumSize(0,0); self.setMaximumSize(16777215,16777215)
        def _done():
            self._mode=MODE_NORMAL; self.setMinimumSize(280,46)
            self._max_btn.setText("□"); self._reposition_grip()
            self._apply_ui_scale(False)
            if then_bubble: QTimer.singleShot(50, lambda: self._set_mode(MODE_BUBBLE))
        self._run_geometry_anim(self.geometry(), geo, 250, QEasingCurve.Type.OutCubic, _done)

    def _toggle_minimize(self):
        if self._mode==MODE_BUBBLE: self._set_mode(MODE_NORMAL)
        else: self._set_mode(MODE_BUBBLE)

    def _toggle_maximize(self):
        if self._mode==MODE_FULL: self._set_mode(MODE_NORMAL)
        else: self._set_mode(MODE_FULL)

    def _pulse_bubble(self):
        t=self._theme
        colors=[t["accent"],t["send_hv"],t["send_bg"],t["frame_br"]]
        c=colors[self._pulse_state%len(colors)]
        self._bubble.setStyleSheet(f"QFrame{{background-color:{t['frame_bg']};border-radius:18px;border:2px solid {c};}}")
        self._pulse_state+=1

    # ── Drag (title bar) ─────────────────────────────────────────
    def _tb_press(self,e):
        if e.button()==Qt.MouseButton.LeftButton:
            self._drag_pos=e.globalPosition().toPoint()-self.frameGeometry().topLeft()

    def _tb_move(self,e):
        if self._drag_pos and e.buttons()==Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint()-self._drag_pos)

    def _tb_release(self,_e): self._drag_pos=None; self._save_config()

    # ── Bubble press/move/release ────────────────────────────────
    def _bubble_press(self,e):
        if e.button()==Qt.MouseButton.LeftButton:
            self._bubble_press_pos=e.position().toPoint()
            self._drag_pos=e.globalPosition().toPoint()-self.frameGeometry().topLeft()

    def _bubble_move(self,e):
        if self._drag_pos and e.buttons()==Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint()-self._drag_pos)

    def _bubble_release(self,e):
        if e.button()!=Qt.MouseButton.LeftButton: return
        if (e.position().toPoint()-self._bubble_press_pos).manhattanLength()>=8:
            self._bubble_click_count=0; self._bubble_click_timer.stop(); return
        self._bubble_click_count+=1
        if self._bubble_click_count>=2:
            self._bubble_click_count=0; self._bubble_click_timer.stop(); self._set_mode(MODE_NORMAL)
        else: self._bubble_click_timer.start(350)

    # ── Resize grip ───────────────────────────────────────────────
    def _reposition_grip(self): self._resize_grip.move(self.width()-16,self.height()-16)

    def _grip_press(self,e):
        if e.button()==Qt.MouseButton.LeftButton: self._grip_drag=e.globalPosition().toPoint()

    def _grip_move(self,e):
        if self._grip_drag:
            d=e.globalPosition().toPoint()-self._grip_drag
            self.resize(max(280,self.width()+d.x()),max(200,self.height()+d.y()))
            self._grip_drag=e.globalPosition().toPoint(); self._reposition_grip()

    def _grip_release(self,_e): self._grip_drag=None; self._save_config()

    def wheelEvent(self,e):
        if e.modifiers()&Qt.KeyboardModifier.ControlModifier:
            self.setWindowOpacity(max(0.3,min(1.0,self.windowOpacity()+e.angleDelta().y()/120*0.05)))
        else: super().wheelEvent(e)

    def _toggle_pin(self):
        self._pinned=not self._pinned
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,self._pinned)
        self.show(); self.setGeometry(geo)

    def _toggle_visibility(self):
        if self.isVisible(): self.hide()
        else: self._bring_to_front()

    def _bring_to_front(self):
        self.show(); self.raise_(); self.activateWindow(); plat.activate_app()

    def showEvent(self, e):
        super().showEvent(e)
        if self._stats_worker: self._stats_worker.paused = False

    def hideEvent(self, e):
        super().hideEvent(e)
        if self._stats_worker: self._stats_worker.paused = True

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reposition_grip()
        if hasattr(self, "_scroll_btn"): self._place_scroll_btn()
        if hasattr(self, "_input_frame") and self._mode == MODE_FULL: self._center_input(True)

    def _enable_shadow(self):
        if QGuiApplication.platformName() == "cocoa":
            plat.enable_window_shadow(int(self.winId()))

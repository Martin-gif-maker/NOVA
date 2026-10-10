# win_voice.py — voice input, push-to-talk and the wake word.
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
import time
import logging
from PySide6.QtCore import QTimer
import tts
import echo
from i18n import tr
from workers import VoiceRecorder, WakeWordListener, BargeInMonitor
import speech

log = logging.getLogger("nova")


class VoiceMixin:
    _VOICE_NORMAL = ("QPushButton{background:transparent;color:#888888;border:none;border-radius:12px;}"
                     "QPushButton:hover{background:rgba(128,128,128,0.15);color:#444444;}")
    _VOICE_REC    = ("QPushButton{background:#CC2222;color:#ffffff;border:1px solid #991111;border-radius:12px;}"
                     "QPushButton:hover{background:#AA1111;}")

    # ── Wake word ────────────────────────────────────────────────
    def _start_wake_listener(self):
        if (self._wake_listener or not self.client or not self.config.get("wake_word", False)
                or not self.config.get("consent")): return
        try:
            import sounddevice as _sd
            _sd.query_devices()  # verify audio is available
        except Exception:
            return
        l = WakeWordListener(self.client, self.config.get("stt_engine", "auto"), self.config.get("stt_lang", ""))
        l.wake_detected.connect(self._on_wake_word)
        l.error_occurred.connect(self._on_wake_error)
        self._wake_listener = l
        l.start()

    def _stop_wake_listener(self):
        l = self._wake_listener; self._wake_listener = None
        if l:
            l.stop(); self._retire_thread(l)

    def _apply_wake_setting(self):
        if self.config.get("wake_word", False): self._start_wake_listener()
        else: self._stop_wake_listener()

    def _on_wake_error(self, msg: str):
        log.warning("wake word stopped: %s", msg)
        self._wake_listener = None
        self.chat_area.add_message(f"⚠️  {msg}", "system", self._theme)

    def _on_wake_word(self,command:str):
        self._bring_to_front()
        if command:
            self.chat_area.add_message(tr("🎙  Heard: «{}»").format(command),"system",self._theme)
            if self._busy:
                self.input_field.setText(command)
                self.chat_area.add_message(tr("NOVA is still answering - your command is in the input box."), "system",self._theme)
            else:
                self.input_field.setText(command); QTimer.singleShot(200,self._send)
        else:
            self.chat_area.add_message(tr("🎙  NOVA is listening..."), "system",self._theme)
            self.input_field.setFocus()

    # ── Voice ────────────────────────────────────────────────────
    def _voice_pressed(self):
        self._voice_press_t = time.monotonic()
        if self._conversation:                                    # tapping the mic ends a hands-free conversation
            self._voice_press_stopped = True
            if tts.active() > 0: tts.stop()
            self._end_conversation(); return
        if self._is_recording:
            self._voice_press_stopped = True; self._stop_voice_internal()
        else:
            self._voice_press_stopped = False; self._start_voice()

    def _voice_released(self):
        """Holding the button for more than half a second = push-to-talk: letting go stops recording."""
        if not self._voice_press_stopped and self._is_recording and time.monotonic() - self._voice_press_t > 0.5:
            self._stop_voice_internal()

    def _toggle_voice(self):
        if self._is_recording: self._stop_voice_internal()
        else: self._start_voice()

    def _start_voice(self):
        if not self.client: return
        if self._voice_recorder is not None and self._voice_recorder.isRunning():
            self.chat_area.add_message(tr("Still transcribing the last recording…"), "system",self._theme); return
        if self._wake_listener: self._wake_listener.pause()
        self._is_recording=True; self._voice_pulse_state=0
        self._voice_pulse_timer=QTimer(self); self._voice_pulse_timer.timeout.connect(self._pulse_voice_btn)
        self._voice_pulse_timer.start(500)
        self._pulse_voice_btn()
        talking = self._conversation
        if not talking: self.chat_area.add_message(tr("🎤  Recording... tap mic to stop."), "system",self._theme)
        self._voice_recorder=VoiceRecorder(self.client, self.config.get("stt_lang",""),
                                           True if talking else self.config.get("voice_auto_stop", True),
                                           self.config.get("stt_engine", "auto"), idle_secs=self.CONVERSATION_IDLE_SECS if talking else 0)
        self._voice_recorder.text_ready.connect(self._on_voice_done)
        self._voice_recorder.silence.connect(self._on_voice_silence)
        self._voice_recorder.error.connect(self._on_voice_error); self._voice_recorder.start()

    def _pulse_voice_btn(self):
        """While recording the microphone button is red and gently pulses between two shades."""
        import icons
        c=["#D92D20","#F04438"][self._voice_pulse_state%2]
        self.voice_btn.setIcon(icons.icon("mic", "#ffffff"))
        self.voice_btn.setStyleSheet(f"QPushButton{{background:{c};border:none;border-radius:6px;}}")
        self._voice_pulse_state+=1

    def _voice_finished_ui(self):
        if hasattr(self,"_voice_pulse_timer"): self._voice_pulse_timer.stop()
        self._is_recording=False; self.voice_btn.setStyleSheet(self._VOICE_NORMAL)
        self._paint_icon(self.voice_btn, self._theme["sys_fg"])
        if self._wake_listener and tts.active() == 0: self._wake_listener.resume()

    def _stop_voice_internal(self):
        if self._voice_recorder: self._voice_recorder.stop()
        self._voice_finished_ui()

    def _on_voice_done(self,text):
        self._voice_finished_ui()
        if self._conversation:
            self._conv_misses = 0
            if self._is_end_phrase(text):
                self._end_conversation(); return
            self.input_field.setText(text); self._send()          # hands-free: straight to NOVA
            return
        self.input_field.setText(text); self.input_field.setFocus()
        if self.config.get("voice_auto_send", False):
            QTimer.singleShot(300, self._send)
        else:
            self.chat_area.add_message(tr("🎤  Recognized: {}").format(text),"system",self._theme)

    def _on_voice_error(self,err):
        self._voice_finished_ui()
        if self._conversation:
            self._conv_misses += 1
            if self._conv_misses >= 2:                            # twice in a row nothing usable: stop instead of looping
                self.chat_area.add_message(f"❌  {err}","system",self._theme); self._end_conversation(); return
            QTimer.singleShot(300, self._conversation_listen); return
        self.chat_area.add_message(f"❌  {err}","system",self._theme)

    def _on_voice_silence(self):
        """Nobody spoke for a while."""
        self._voice_finished_ui()
        if self._conversation: self._end_conversation(tr("🎧  Voice conversation ended (it was quiet)."))

    def _tts_state(self, speaking: bool):
        """Called from the read-aloud thread: hand over to the window's own thread."""
        self._bridge.tts_state.emit(bool(speaking))

    def _on_tts_state(self, speaking: bool):
        l = self._wake_listener
        if l:
            if speaking: l.pause()
            elif not self._is_recording and not self._conversation: l.resume()
        if not self._conversation: return
        if not speaking:                                          # (listening for you talking over it starts with the sound)
            self._stop_barge_in()
            QTimer.singleShot(250, self._conversation_listen)     # NOVA finished talking: your turn

    def _tts_playing(self, path):
        """Called from the read-aloud thread just before the sound starts. In a voice conversation the audio's
        loudness curve is worked out here, so that NOVA's own voice from the speakers is not taken for yours."""
        reference = None
        if path and self._conversation and self.config.get("voice_barge_in", True):
            try: reference = echo.reference_envelope(path)
            except Exception as e: log.info("no playback reference: %s", e)
        self._bridge.tts_playing.emit(reference, time.monotonic())

    def _on_tts_playing(self, reference, started: float):
        if self._conversation and tts.active() > 0:
            if self._barge_in is not None: self._stop_barge_in()
            self._start_barge_in(reference, started)

    # ── Hands-free conversation ──────────────────────────────────
    CONVERSATION_IDLE_SECS = 12
    END_PHRASES = ("stop listening", "stop conversation", "end conversation", "goodbye", "good bye", "bye", "bye bye",
                   "that's all", "thats all", "thank you that's all", "стоп", "край", "довиждане", "чао", "спри да слушаш")

    def _is_end_phrase(self, text: str) -> bool:
        said = "".join(ch for ch in (text or "").lower() if ch.isalnum() or ch in " '").strip()
        return said in self.END_PHRASES or said.replace("'", "") in self.END_PHRASES

    def _toggle_conversation(self):
        if self._conversation: self._end_conversation()
        else: self._start_conversation()

    def _start_conversation(self):
        if not self.client: return
        if not speech.pick_engine(self.client, self.config.get("stt_engine", "auto"), self.config.get("stt_lang", "")):
            self.chat_area.add_message("❌  " + tr("Voice input is not available: this AI provider has no speech-to-text and the "
                                                   "offline voice model is not installed (Settings → Voice)."), "system", self._theme)
            return
        self._conversation = True; self._conv_misses = 0
        self.chat_area.add_message(tr("🎧  Voice conversation is on — just talk. Say “stop listening” or tap the mic to end. "
                                      "You can talk over NOVA to interrupt it."), "system", self._theme)
        if self._wake_listener: self._wake_listener.pause()
        self._conversation_listen()

    def _end_conversation(self, message: str = None):
        if not self._conversation: return
        self._conversation = False
        self._stop_barge_in()
        if self._is_recording: self._stop_voice_internal()
        self.chat_area.add_message(message or tr("🎧  Voice conversation ended."), "system", self._theme)
        if self._wake_listener and tts.active() == 0: self._wake_listener.resume()

    def _conversation_listen(self):
        """Your turn: start listening - unless NOVA is still working, speaking, or the conversation is over."""
        if not self._conversation or self._quitting or self._is_recording or self._busy or tts.active() > 0: return
        if self._voice_recorder is not None and self._voice_recorder.isRunning():
            QTimer.singleShot(300, self._conversation_listen); return
        self._start_voice()

    def _start_barge_in(self, reference=None, started: float = None):
        if self._barge_in is not None or not self.config.get("voice_barge_in", True): return
        m = BargeInMonitor(reference, started, getattr(self, "_echo_gain", None)); m.interrupted.connect(self._on_barge_in)
        self._barge_in = m; m.start()

    def _stop_barge_in(self):
        m, self._barge_in = self._barge_in, None
        if m is not None:
            m.stop(); self._retire_thread(m)
            gain = m.learned_gain()
            if gain is not None: self._echo_gain = gain           # how loud NOVA's voice reaches the microphone here

    def _on_barge_in(self):
        if self._conversation and tts.active() > 0:
            tts.stop()                                            # → "not speaking" → listening starts

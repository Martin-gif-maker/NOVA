"""Hands-free voice conversation: the turn-taking between listening, answering and speaking (no real audio)."""
import pytest
pytest.importorskip("PySide6")
from gui_support import FakeCompletions, _wait_idle
import tts, win_voice, speech


class FakeRecorder:
    """Stands in for the microphone thread; the test decides what was 'heard'."""
    made = []
    def __init__(self, client, language="", auto_stop=True, engine="auto", idle_secs=0):
        self.auto_stop, self.idle_secs = auto_stop, idle_secs
        self.text_ready = _Sig(); self.error = _Sig(); self.silence = _Sig(); self.running = False
        FakeRecorder.made.append(self)
    def start(self): self.running = True
    def stop(self): self.running = False
    def isRunning(self): return self.running
    def hear(self, text): self.running = False; self.text_ready.emit(text)
    def quiet(self): self.running = False; self.silence.emit()
    def fail(self, msg): self.running = False; self.error.emit(msg)


class _Sig:
    def __init__(self): self.slots = []
    def connect(self, fn): self.slots.append(fn)
    def emit(self, *a):
        for fn in list(self.slots): fn(*a)


@pytest.fixture
def talk(win, monkeypatch):
    FakeRecorder.made = []
    monkeypatch.setattr(win_voice, "VoiceRecorder", FakeRecorder)
    monkeypatch.setattr(speech, "pick_engine", lambda *a, **k: "cloud")
    spoken = []; state = {"active": 0}
    monkeypatch.setattr(tts, "speak", lambda text: (spoken.append(text), state.update(active=1), win._on_tts_state(True),
                                                    win._on_tts_playing(None, 0.0))[0])
    monkeypatch.setattr(tts, "stop", lambda: state.update(active=0))
    monkeypatch.setattr(tts, "active", lambda: state["active"])
    monkeypatch.setattr(tts, "ENABLED", True)
    started = []
    monkeypatch.setattr(win, "_start_barge_in", lambda *a: started.append("on"))
    monkeypatch.setattr(win, "_stop_barge_in", lambda: started.append("off"))
    def finish_speaking():
        state["active"] = 0; win._on_tts_state(False); win._pump(400)
    return type("T", (), {"spoken": spoken, "barge": started, "finish_speaking": staticmethod(finish_speaking), "state": state})


def test_a_whole_exchange_listen_answer_speak_listen(win, talk):
    FakeCompletions.script = [["It is ", "sunny."]]
    win._start_conversation()
    assert win._conversation and len(FakeRecorder.made) == 1 and win._is_recording
    rec = FakeRecorder.made[0]
    assert rec.auto_stop is True and rec.idle_secs == win.CONVERSATION_IDLE_SECS      # it stops by itself; you never press anything
    rec.hear("what is the weather"); _wait_idle(win)
    assert [m["content"] for m in win.messages[1:]] == ["what is the weather", "It is sunny."]
    assert talk.spoken == ["It is sunny."]                                             # read aloud even though auto-read is off
    assert len(FakeRecorder.made) == 1 and talk.barge == ["on"]                        # not listening for a turn while NOVA talks
    talk.finish_speaking()
    assert len(FakeRecorder.made) == 2 and win._is_recording and talk.barge == ["on", "off"]   # your turn again


def test_saying_stop_or_tapping_the_mic_ends_it(win, talk):
    win._start_conversation()
    FakeRecorder.made[-1].hear("Stop listening.")
    assert not win._conversation and len(win.messages) == 1                            # the words were not sent to the AI
    win._start_conversation(); assert win._conversation
    win._voice_pressed()
    assert not win._conversation and not win._is_recording
    for phrase in ("goodbye", "That's all", "стоп", "Довиждане!"):
        assert win._is_end_phrase(phrase), phrase
    assert not win._is_end_phrase("please stop the music") and not win._is_end_phrase("bye bye birdie is a film")


def test_silence_ends_it_and_two_unclear_turns_end_it(win, talk):
    win._start_conversation()
    FakeRecorder.made[-1].quiet()
    assert not win._conversation
    win._start_conversation()
    FakeRecorder.made[-1].fail("Nothing was recognised.")
    win._pump(450)
    assert win._conversation and len(FakeRecorder.made) == 3                           # one unclear turn: listen again
    FakeRecorder.made[-1].fail("Nothing was recognised.")
    assert not win._conversation                                                        # twice: stop instead of looping


def test_talking_over_nova_stops_the_speech(win, talk):
    win._conversation = True; talk.state["active"] = 1
    win._on_barge_in()
    assert talk.state["active"] == 0
    win._conversation = False; talk.state["active"] = 1
    win._on_barge_in(); assert talk.state["active"] == 1                               # outside a conversation: never interrupts


def test_without_read_aloud_it_still_takes_turns(win, talk, monkeypatch):
    monkeypatch.setattr(tts, "ENABLED", False)
    FakeCompletions.script = [["ok"]]
    win._start_conversation(); FakeRecorder.made[-1].hear("hello"); _wait_idle(win); win._pump(600)
    assert talk.spoken == [] and len(FakeRecorder.made) == 2 and win._is_recording


def test_a_failed_request_ends_the_conversation(win, talk):
    win._start_conversation(); FakeRecorder.made[-1].running = False; win._is_recording = False
    win._on_error("401 invalid api key", "auth")
    assert not win._conversation


def test_no_speech_to_text_means_no_conversation(win, talk, monkeypatch):
    monkeypatch.setattr(speech, "pick_engine", lambda *a, **k: "")
    win._start_conversation()
    assert not win._conversation and FakeRecorder.made == []


def test_the_monitor_starts_with_the_sound_and_knows_what_is_played(win, monkeypatch, tmp_path):
    """Speech state alone starts nothing (the voice is still being prepared); the monitor starts when the sound does."""
    import numpy as np
    made = []
    class FakeMonitor:
        def __init__(self, reference=None, started=None, seed_gain=None):
            self.reference, self.started, self.seed_gain = reference, started, seed_gain
            self.interrupted = _Sig(); self.stopped = False; made.append(self)
        def start(self): pass
        def stop(self): self.stopped = True
        def learned_gain(self): return 0.7
    monkeypatch.setattr(win_voice, "BargeInMonitor", FakeMonitor)
    monkeypatch.setattr(win, "_retire_thread", lambda t: None)
    monkeypatch.setattr(tts, "active", lambda: 1)
    monkeypatch.setattr(win_voice.echo, "reference_envelope", lambda path: np.ones(10, dtype=np.float32) if path.endswith(".mp3") else None)
    win._conversation = True
    win._on_tts_state(True)
    assert made == []                                                       # preparing the voice: not listening yet
    win._tts_playing("/tmp/reply.mp3"); win._pump(50)                      # what the speech thread calls
    assert len(made) == 1 and len(made[0].reference) == 10 and made[0].started > 0 and made[0].seed_gain is None
    win._on_tts_state(False)
    assert made[0].stopped and win._echo_gain == 0.7                        # what it learned is kept…
    win._tts_playing(None); win._pump(50)                                   # (a voice with no file: the simple loudness check)
    assert len(made) == 2 and made[1].reference is None and made[1].seed_gain == 0.7     # …for the next reply
    win._stop_barge_in()
    win.config["voice_barge_in"] = False
    win._tts_playing("/tmp/reply.mp3"); win._pump(50)
    assert len(made) == 2                                                   # switched off in Settings: no monitor at all
    win._conversation = False; win.config["voice_barge_in"] = True
    win._tts_playing("/tmp/reply.mp3"); win._pump(50)
    assert len(made) == 2                                                   # reading aloud outside a conversation: never

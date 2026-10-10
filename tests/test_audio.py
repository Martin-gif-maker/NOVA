"""Wake word + voice recording against a scripted fake microphone (no real audio, no network)."""
import sys, time, types
import numpy as np
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
import workers


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _chunk(amp, n=512):
    return (np.random.RandomState(1).randn(n) * amp).astype(np.int16).reshape(-1, 1)


class FakeStream:
    """Plays a scripted list of amplitudes, then raises to mimic the mic going away."""
    script = []
    def __init__(self, *a, **k): self.i = 0
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n):
        if self.i >= len(FakeStream.script):
            time.sleep(0.02); return _chunk(5), False                       # endless quiet room
        amp = FakeStream.script[self.i]; self.i += 1; time.sleep(0.001)
        return _chunk(amp), False


class FakeClient:
    def __init__(self, text): self.text = text; self.calls = 0
    class _A:
        pass
    @property
    def audio(self):
        outer = self
        return types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=lambda **kw: (setattr(outer, "calls", outer.calls + 1), outer.text)[1]))


@pytest.fixture
def mic(monkeypatch):
    sd = types.SimpleNamespace(InputStream=FakeStream, query_devices=lambda: [])
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    return sd


def test_voice_recorder_stops_itself_after_you_finish_talking(app, mic):
    FakeStream.script = [5] * 14 + [3000] * 40 + [5] * 80          # calibrate, speak, silence
    client = FakeClient("hello nova")
    got, errs = [], []
    r = workers.VoiceRecorder(client, "en", auto_stop=True)
    r.text_ready.connect(got.append); r.error.connect(errs.append)
    t = time.time(); r.run()                                        # run synchronously
    assert got == ["hello nova"] and not errs and time.time() - t < 5 and client.calls == 1


def test_voice_recorder_reports_silence_instead_of_hanging(app, mic):
    FakeStream.script = [5] * 40
    r = workers.VoiceRecorder(FakeClient(""), "", auto_stop=False)
    r.MAX_SECS = 1                                                   # keep the test fast
    errs = []; r.error.connect(errs.append); r.run()
    assert errs and "recognised" in errs[0].lower()


def test_voice_recorder_surfaces_microphone_errors(app, monkeypatch):
    class Boom:
        def __init__(self, *a, **k): raise OSError("Permission denied")
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(InputStream=Boom))
    errs = []; r = workers.VoiceRecorder(FakeClient("x")); r.error.connect(errs.append); r.run()
    assert errs and "Microphone" in errs[0] and "System Settings" in errs[0]


def test_wake_word_triggers_only_on_the_whole_word(app, mic):
    workers.WakeWordListener.THRESH = 700
    for heard, expect in (("Hey Nova, open notes please", "open notes please"), ("what an innovation", None), ("supernova explosion", None)):
        FakeStream.script = [5] * 5 + [3000] * 25 + [5] * 60
        l = workers.WakeWordListener(FakeClient(heard)); l.COOL = 0
        out = []; l.wake_detected.connect(out.append)
        import threading
        th = threading.Thread(target=l.run, daemon=True); th.start()
        end = time.time() + 6
        while time.time() < end and not out and l.client.calls == 0: app.processEvents(); time.sleep(0.05)
        for _ in range(10): app.processEvents(); time.sleep(0.03)          # let a queued signal be delivered
        l.stop(); th.join(3)
        assert l.client.calls >= 1
        assert (out[0] if out else None) == expect, heard


def test_wake_word_gives_up_with_a_clear_message_when_mic_is_unavailable(app, monkeypatch):
    class Boom:
        def __init__(self, *a, **k): raise OSError("no mic")
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(InputStream=Boom))
    monkeypatch.setattr(workers.time, "sleep", lambda s: None)
    l = workers.WakeWordListener(FakeClient("")); errs = []; l.error_occurred.connect(errs.append); l.run()
    assert errs and "Microphone" in errs[0] or "microphone" in errs[0]


def test_wake_word_is_paused_while_nova_speaks(app, mic):
    FakeStream.script = [3000] * 40
    l = workers.WakeWordListener(FakeClient("nova hi")); l.pause()
    import threading
    th = threading.Thread(target=l.run, daemon=True); th.start(); time.sleep(0.8)
    assert l.client.calls == 0                                       # paused: never listens or uploads
    l.stop(); th.join(3)


# ── hands-free conversation ────────────────────────────────────────
def test_recorder_gives_up_quietly_when_nobody_speaks(app, mic):
    FakeStream.script = [5] * 400                                   # only room noise
    client = FakeClient("should not be asked")
    got, errs, quiet = [], [], []
    r = workers.VoiceRecorder(client, "en", auto_stop=True, idle_secs=2)       # 2 s = ~62 chunks
    r.text_ready.connect(got.append); r.error.connect(errs.append); r.silence.connect(lambda: quiet.append(1))
    r.run()
    assert quiet == [1] and not got and not errs and client.calls == 0         # nothing is sent to speech-to-text


def test_recorder_idle_limit_does_not_cut_off_someone_who_is_talking(app, mic):
    FakeStream.script = [5] * 14 + [3000] * 120 + [5] * 80          # speaks for longer than the idle limit
    client = FakeClient("a long sentence")
    got, quiet = [], []
    r = workers.VoiceRecorder(client, "en", auto_stop=True, idle_secs=2)
    r.text_ready.connect(got.append); r.silence.connect(lambda: quiet.append(1)); r.run()
    assert got == ["a long sentence"] and not quiet


def test_barge_in_fires_only_for_something_louder_than_novas_own_voice(app, mic):
    fired = []
    FakeStream.script = [1500] * 20 + [1600] * 60                   # NOVA talking through the speakers the whole time
    m = workers.BargeInMonitor(); m.interrupted.connect(lambda: fired.append(1))
    import threading
    t = threading.Thread(target=m.run); t.start(); time.sleep(0.5); m.stop(); t.join(3)
    assert fired == []                                              # its own voice does not interrupt it
    FakeStream.script = [1500] * 20 + [1500] * 10 + [9000] * 12 + [1500] * 50   # …then you speak over it
    m = workers.BargeInMonitor(); m.interrupted.connect(lambda: fired.append(1)); m.run()
    assert fired == [1]
    FakeStream.script = [1500] * 20 + [9000] * 3 + [1500] * 60      # a cough / a door: too short
    m = workers.BargeInMonitor(); m.interrupted.connect(lambda: fired.append(2))
    t = threading.Thread(target=m.run); t.start(); time.sleep(0.5); m.stop(); t.join(3)
    assert fired == [1]


def test_barge_in_with_a_reference_knows_novas_voice_from_yours(app, mic):
    """The monitor is told what NOVA is playing: the same loudness coming back does nothing, you on top of it does."""
    import threading
    rng = np.random.RandomState(3)
    words = np.repeat(rng.uniform(1500, 4500, 40), 6) * np.tile([1, 1, 1, 1, 1, 0.02], 40)      # 240 chunks: words with gaps
    reference = words.astype(np.float32)
    heard = [0.0] * 6 + list(reference * 0.6)                        # the speakers reach the microphone 6 chunks later, at 60 %
    fired = []
    FakeStream.script = [max(5, a) for a in heard]
    m = workers.BargeInMonitor(reference, time.monotonic()); m.interrupted.connect(lambda: fired.append("echo only"))
    t = threading.Thread(target=m.run); t.start(); time.sleep(1.2); m.stop(); t.join(3)
    assert fired == [] and m.learned_gain() == pytest.approx(0.6, rel=0.5)
    FakeStream.script = [max(5, a) for a in heard[:120]] + [14000] * 12 + [max(5, a) for a in heard[132:]]     # you, 4 s in
    m = workers.BargeInMonitor(reference, time.monotonic(), m.learned_gain()); m.interrupted.connect(lambda: fired.append("you"))
    m.run()
    assert fired == ["you"]
    assert workers.BargeInMonitor().learned_gain() is None           # without a reference there is nothing to learn

"""Speech recognition on this Mac with Whisper (speech.py): which engine is used, silence and the phrases Whisper
imagines in it, the download - and, with the real model, Bulgarian and English sentences spoken by the Mac's own
voices into files (nothing is played, no microphone).

Real-model part: NOVA_WHISPER_MODEL=<path to ggml-large-v3-turbo-q5_0.bin> pytest tests/test_whisper_local.py
"""
import hashlib, os, subprocess, sys, types
import numpy as np
import pytest
import speech

LOUD = (np.sin(np.linspace(0, 400 * np.pi, 16000)) * 9000).astype("<i2")      # one second of "speech"
QUIET = (np.random.default_rng(0).standard_normal(16000) * 60).astype("<i2")    # one second of a quiet room


def _pcm(*parts) -> bytes:
    return np.concatenate(parts).astype("<i2").tobytes()


@pytest.fixture
def fake_whisper(monkeypatch, tmp_path):
    """A stand-in for pywhispercpp that answers what the test says."""
    said = {"text": "Какво е времето?"}
    calls = []
    class Model:
        def __init__(self, path, **kw): calls.append(path)
        def transcribe(self, audio, language="auto"):
            calls.append(language); return [types.SimpleNamespace(text=" " + said["text"])]
    module = types.ModuleType("pywhispercpp.model"); module.Model = Model
    monkeypatch.setitem(sys.modules, "pywhispercpp", types.ModuleType("pywhispercpp"))
    monkeypatch.setitem(sys.modules, "pywhispercpp.model", module)
    model = tmp_path / speech.WHISPER_FILE; model.write_bytes(b"x")
    monkeypatch.setenv("NOVA_WHISPER_MODEL", str(model))
    monkeypatch.setattr(speech, "whisper_installed", lambda: True)
    return types.SimpleNamespace(said=said, calls=calls)


def test_whisper_on_this_mac_is_preferred_once_it_is_installed(fake_whisper, monkeypatch):
    cloud = types.SimpleNamespace(audio=object())
    monkeypatch.setattr(speech, "cloud_available", lambda c: c is cloud)
    monkeypatch.setattr(speech, "local_ready", lambda: False)
    assert speech.pick_engine(cloud) == "local" and speech.pick_engine(cloud, "cloud") == "cloud"
    monkeypatch.delenv("NOVA_WHISPER_MODEL")
    assert speech.pick_engine(cloud) == "cloud" and speech.pick_engine(None) == ""


def test_speech_is_transcribed_in_the_chosen_language(fake_whisper, tmp_path):
    f = tmp_path / "rec.wav"
    speech.write_wav(str(f), speech.RATE, np.frombuffer(_pcm(QUIET, LOUD, QUIET), "<i2"))
    assert speech.transcribe(None, str(f), "bg", "local") == "Какво е времето?"
    assert fake_whisper.calls[-1] == "bg"
    speech.transcribe(None, str(f), "", "local")
    assert fake_whisper.calls[-1] == "auto"                                   # no language set: Whisper detects it


def test_silence_is_never_sent_as_words(fake_whisper):
    fake_whisper.said["text"] = "Абонирайте се!"
    assert speech.transcribe_whisper(_pcm(QUIET, QUIET)) == ""                 # nothing loud enough: the model is not even asked
    assert fake_whisper.calls == []
    short = (LOUD[:6000]).astype("<i2")
    assert speech.transcribe_whisper(_pcm(QUIET, short, QUIET)) == ""          # a cough + Whisper's favourite phantom
    assert speech.transcribe_whisper(_pcm(LOUD, LOUD, QUIET)) == "Абонирайте се!"   # really said, at length: kept


def test_the_model_download_is_checked(monkeypatch, tmp_path):
    data = b"model" * 1000
    monkeypatch.setattr(speech, "WHISPER_SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setenv("NOVA_WHISPER_MODEL", str(tmp_path / "m.bin"))
    import requests
    class R:
        headers = {"content-length": str(len(data))}
        def __init__(self, d): self.d = d
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_content(self, n): yield self.d
    monkeypatch.setattr(requests, "get", lambda url, **k: R(data))
    steps = []
    assert speech.download_whisper(steps.append) == str(tmp_path / "m.bin") and steps == [1.0]
    monkeypatch.setattr(requests, "get", lambda url, **k: R(b"tampered"))
    os.remove(tmp_path / "m.bin")
    with pytest.raises(speech.SpeechError, match="checksum"): speech.download_whisper()
    assert list(tmp_path.iterdir()) == []


# ── the real model ──
real = pytest.mark.skipif(not (os.environ.get("NOVA_WHISPER_MODEL", "").endswith(".bin") and sys.platform == "darwin"),
                          reason="needs the Whisper model: NOVA_WHISPER_MODEL=<ggml file>")


def _say(tmp_path, voice, text) -> str:
    f = tmp_path / f"{abs(hash(text))}.wav"
    subprocess.run(["say", "-v", voice, "-o", str(f), "--file-format=WAVE", "--data-format=LEI16@16000", text],
                   check=True, capture_output=True)                               # writes a file; nothing is played
    return str(f)


@real
@pytest.mark.parametrize("voice,lang,text", [
    ("Daria", "bg", "Какво е времето в София утре?"),
    ("Daria", "bg", "Добави среща с Иван в петък."),
    ("Daria", "", "Колко батерия ми остава?"),                                  # language detected by itself
    ("Samantha", "en", "Open Paris on the map and tell me the weather."),
])
def test_the_real_model_understands_bulgarian_and_english(tmp_path, voice, lang, text):
    pytest.importorskip("pywhispercpp")
    got = speech.transcribe(None, _say(tmp_path, voice, text), lang, "local")
    words = lambda s: set(w.strip(".,?!").lower() for w in s.split())
    assert len(words(got) & words(text)) >= len(words(text)) - 1, got           # at most one word different


@real
def test_the_real_model_hears_nothing_in_a_quiet_room(tmp_path):
    pytest.importorskip("pywhispercpp")
    f = tmp_path / "quiet.wav"
    speech.write_wav(str(f), speech.RATE, np.frombuffer(_pcm(QUIET, QUIET, QUIET), "<i2"))
    assert speech.transcribe(None, str(f), "bg", "local") == ""


def test_settings_downloads_and_removes_the_model(app, monkeypatch):
    import settings_dialog, themes
    from gui_support import _pump
    state = {"ready": False}
    monkeypatch.setattr(speech, "whisper_installed", lambda: True)
    monkeypatch.setattr(speech, "whisper_ready", lambda: state["ready"])
    def fake_download(progress=None, cancelled=None):
        progress(0.5); state["ready"] = True
    monkeypatch.setattr(speech, "download_whisper", fake_download)
    monkeypatch.setattr(speech, "remove_whisper", lambda: state.update(ready=False))
    d = settings_dialog.SettingsDialog({}, themes.THEMES["soft"])
    assert d._whisper_btn.text() == "Download (574 MB)" and "Bulgarian" in d._whisper_status.text()
    d._whisper_btn.click()
    for _ in range(40):
        _pump(app, 25)
        if d._whisper_job is None: break
    assert d._whisper_btn.text() == "Remove" and "Installed" in d._whisper_status.text()
    d._whisper_btn.click(); assert d._whisper_btn.text().startswith("Download")

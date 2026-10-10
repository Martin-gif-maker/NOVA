"""Speech recognition plumbing (speech.py): which engine is used, the offline model's download checks, and the
file formats. No microphone, no network and no real model: the recogniser and the download are stand-ins."""
import hashlib, io, json, sys, types, wave, zipfile
import numpy as np
import pytest
import speech, paths, ledger


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(paths, "OUTBOUND_FILE", str(tmp_path / "outbound.log"))
    monkeypatch.setattr(speech, "_model", None)
    return tmp_path


def cloud_client(text="hello from the cloud", seen=None):
    def create(file=None, model=None, response_format=None, **kw):
        if seen is not None: seen.append({"bytes": len(file[1]), "model": model, **kw})
        return text
    return types.SimpleNamespace(host="api.example", audio=types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=create)))


def install_model(home):
    (home / "models" / speech.MODEL_NAME / "am").mkdir(parents=True)


def fake_vosk(monkeypatch, words=("turn", "the", "lights", "on")):
    """A recogniser that 'hears' one word per chunk of audio."""
    class Rec:
        def __init__(self, model, rate, grammar=None): self.n = 0; self.grammar = grammar
        def AcceptWaveform(self, chunk): self.n += 1; return self.n == 2      # one finished phrase, the rest comes at the end
        def Result(self): return json.dumps({"text": " ".join(words[:2])})
        def FinalResult(self): return json.dumps({"text": " ".join(words[2:])})
    mod = types.SimpleNamespace(SetLogLevel=lambda n: None, Model=lambda path: ("model", path), KaldiRecognizer=Rec)
    monkeypatch.setitem(sys.modules, "vosk", mod)
    monkeypatch.setattr(speech, "vosk_installed", lambda: True)
    return mod


def test_recordings_are_saved_as_proper_wav_files(tmp_path):
    samples = (np.sin(np.arange(1600) / 5) * 9000).astype(np.int16).reshape(-1, 1)        # the shape the microphone delivers
    path = str(tmp_path / "take.wav")
    speech.write_wav(path, 16000, samples)
    with wave.open(path, "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 1600)
        assert np.array_equal(np.frombuffer(w.readframes(1600), dtype="<i2"), samples.reshape(-1))


def test_which_engine_is_used(home, monkeypatch):
    monkeypatch.setattr(speech.model_registry, "stt_model", lambda: "whisper-test")
    cloud, nothing = cloud_client(), types.SimpleNamespace(audio=None)
    assert speech.cloud_available(cloud) and not speech.cloud_available(nothing) and not speech.cloud_available(None)
    monkeypatch.setattr(speech, "vosk_installed", lambda: True)
    assert speech.local_ready() is False                                           # the package alone is not enough
    assert speech.pick_engine(cloud) == "cloud" and speech.pick_engine(nothing) == "" and speech.pick_engine(cloud, "local") == ""
    install_model(home)
    assert speech.local_ready() is True
    assert speech.pick_engine(cloud) == "cloud"                                    # auto: the provider's, any language
    assert speech.pick_engine(nothing) == "local" and speech.pick_engine(cloud, "local") == "local"
    assert speech.pick_engine(nothing, "cloud") == ""
    monkeypatch.setattr(speech.model_registry, "stt_model", lambda: "")            # a provider without speech-to-text
    assert not speech.cloud_available(cloud) and speech.pick_engine(cloud) == "local"


def test_cloud_transcription_sends_the_recording_and_notes_it(home, monkeypatch, tmp_path):
    monkeypatch.setattr(speech.model_registry, "stt_model", lambda: "whisper-test")
    f = tmp_path / "a.wav"; f.write_bytes(b"RIFF" + b"\0" * 996)
    seen = []
    assert speech.transcribe(cloud_client("  Какво е времето?  ", seen), str(f), language="bg") == "Какво е времето?"
    assert seen == [{"bytes": 1000, "model": "whisper-test", "language": "bg"}]
    sent = ledger.entries()[-1]
    assert (sent["dest"], sent["what"], sent["bytes"], sent["detail"]) == ("api.example", "speech-to-text", 1000, "a voice recording")
    with pytest.raises(speech.SpeechError, match="no speech-to-text"): speech.transcribe_cloud(types.SimpleNamespace(audio=None), str(f))


def test_offline_transcription_and_its_requirements(home, monkeypatch, tmp_path):
    good = str(tmp_path / "good.wav"); speech.write_wav(good, 16000, np.zeros(16000 * 2, dtype=np.int16))
    nothing = types.SimpleNamespace(audio=None)
    with pytest.raises(speech.SpeechError, match="not installed. Download it"): speech.transcribe(nothing, good, engine="local")
    with pytest.raises(speech.SpeechError, match="Voice input is not available"): speech.transcribe(nothing, good)
    fake_vosk(monkeypatch); install_model(home)
    assert speech.transcribe(nothing, good) == "turn the lights on"                # nothing leaves the Mac
    assert ledger.entries() == []
    grammar = speech.recognizer('["nova", "[unk]"]')
    assert grammar.grammar == '["nova", "[unk]"]'                                  # the wake word listens for one word only
    wrong = str(tmp_path / "cd-quality.wav")
    with wave.open(wrong, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100); w.writeframes(b"\0" * 400)
    with pytest.raises(speech.SpeechError, match="16 kHz mono"): speech.transcribe_local(wrong)
    speech.remove_model()
    assert not speech.local_ready()
    with pytest.raises(speech.SpeechError, match="not installed"): speech.recognizer()


def test_wake_word_is_a_whole_word():
    assert speech.heard_wake_word("hey nova what time is it") and speech.heard_wake_word("nova")
    assert not speech.heard_wake_word("innovation is great") and not speech.heard_wake_word("") and not speech.heard_wake_word(None)


def _archive(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items(): z.writestr(name, data)
    return buf.getvalue()


def _serve(monkeypatch, blob: bytes):
    class R:
        headers = {"content-length": str(len(blob))}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_content(self, n): return (blob[i:i + n] for i in range(0, len(blob), n))
    import requests
    monkeypatch.setattr(requests, "get", lambda url, stream=True, timeout=30: R())


def test_the_voice_model_is_checked_before_it_is_unpacked(home, monkeypatch):
    good = _archive({speech.MODEL_NAME + "/am/final.mdl": b"model", speech.MODEL_NAME + "/README": b"hi"})
    _serve(monkeypatch, good)
    with pytest.raises(speech.SpeechError, match="checksum mismatch"): speech.download_model()      # not the file NOVA expects
    assert not (home / "models" / speech.MODEL_NAME).exists() and list((home / "models").iterdir()) == []
    monkeypatch.setattr(speech, "MODEL_SHA256", hashlib.sha256(good).hexdigest())
    progress = []
    assert speech.download_model(progress.append) == str(home / "models" / speech.MODEL_NAME)
    assert (home / "models" / speech.MODEL_NAME / "am" / "final.mdl").read_bytes() == b"model" and progress[-1] == 1.0
    assert [p.name for p in (home / "models").iterdir()] == [speech.MODEL_NAME]                     # the download itself is gone
    assert ledger.entries()[-1]["what"] == "voice model download"
    bad = _archive({"../../escape.txt": b"gotcha"})                                                # an archive that tries to write elsewhere
    _serve(monkeypatch, bad); monkeypatch.setattr(speech, "MODEL_SHA256", hashlib.sha256(bad).hexdigest())
    with pytest.raises(speech.SpeechError, match="Unsafe path"): speech.download_model()
    assert not (home.parent / "escape.txt").exists() and not (home / "escape.txt").exists()

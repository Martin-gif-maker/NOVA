# speech.py — speech-to-text, in the cloud or entirely on this Mac.
#
#   cloud  the active AI provider's transcription endpoint (Groq / OpenAI Whisper): best quality, many languages
#   local  Vosk with a small English model stored in NOVA's data folder: private, works offline, English only
#
# The on-device model also powers the wake word: a recogniser restricted to the words "nova" / "hey nova"
# listens continuously without any audio leaving the computer.
import os, json, wave, zipfile, hashlib, logging, threading
import paths
import ledger
import models as model_registry

log = logging.getLogger("nova")

MODEL_NAME   = "vosk-model-small-en-us-0.15"
MODEL_URL    = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
MODEL_SHA256 = "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498"
MODEL_MB     = 41
WAKE_GRAMMAR = '["nova", "hey nova", "[unk]"]'
RATE         = 16000

_model = None
_model_lock = threading.Lock()


class SpeechError(Exception):
    pass


# ── on-device model ────────────────────────────────────────────────
def write_wav(path: str, rate: int, audio) -> None:
    """Save recorded sound (16-bit mono samples, a numpy array) as a .wav file."""
    import numpy as np
    pcm = np.ascontiguousarray(np.asarray(audio).reshape(-1), dtype="<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(rate)); w.writeframes(pcm.tobytes())


def models_dir() -> str:
    return os.path.join(paths.DATA_DIR, "models")


def model_path() -> str:
    return os.path.join(models_dir(), MODEL_NAME)


def vosk_installed() -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec("vosk") is not None
    except Exception:
        return False


def local_ready() -> bool:
    return vosk_installed() and os.path.isdir(os.path.join(model_path(), "am"))


def download_model(progress=None) -> str:
    """Fetch the offline voice model (~41 MB), verify its checksum, unpack it. Returns the model folder."""
    import requests
    os.makedirs(models_dir(), mode=0o700, exist_ok=True)
    zpath = os.path.join(models_dir(), MODEL_NAME + ".zip.part")
    h = hashlib.sha256(); done = 0
    ledger.record(MODEL_URL, "voice model download")
    with requests.get(MODEL_URL, stream=True, timeout=30) as r:
        r.raise_for_status(); total = int(r.headers.get("content-length", 0))
        with open(zpath, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk); h.update(chunk); done += len(chunk)
                if progress and total: progress(done / total)
    if h.hexdigest() != MODEL_SHA256:
        os.remove(zpath)
        raise SpeechError("The downloaded voice model is corrupt or was tampered with (checksum mismatch).")
    root = os.path.realpath(models_dir())
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():                                  # never write outside the models folder
            if not os.path.realpath(os.path.join(root, name)).startswith(root + os.sep):
                os.remove(zpath); raise SpeechError("Unsafe path inside the voice model archive.")
        z.extractall(root)
    os.remove(zpath)
    return model_path()


def remove_model() -> None:
    global _model
    import shutil
    with _model_lock: _model = None
    shutil.rmtree(model_path(), ignore_errors=True)


def _load():
    global _model
    with _model_lock:
        if _model is None:
            if not local_ready():
                raise SpeechError("The offline voice model is not installed (Settings → Voice → Download).")
            import vosk
            vosk.SetLogLevel(-1)
            _model = vosk.Model(model_path())
        return _model


def recognizer(grammar: str = None):
    """A streaming recogniser. With `grammar` it only knows those words (used for the wake word)."""
    import vosk
    m = _load()
    return vosk.KaldiRecognizer(m, RATE, grammar) if grammar else vosk.KaldiRecognizer(m, RATE)


def transcribe_pcm(pcm: bytes) -> str:
    """16 kHz mono 16-bit audio -> text, entirely on this Mac."""
    rec = recognizer(); parts = []
    for i in range(0, len(pcm), 8000):
        if rec.AcceptWaveform(pcm[i:i + 8000]):
            parts.append(json.loads(rec.Result()).get("text", ""))
    parts.append(json.loads(rec.FinalResult()).get("text", ""))
    return " ".join(p for p in parts if p).strip()


def transcribe_local(wav_path: str) -> str:
    with wave.open(wav_path, "rb") as wf:
        if wf.getframerate() != RATE or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise SpeechError("Local speech recognition needs 16 kHz mono 16-bit audio.")
        return transcribe_pcm(wf.readframes(wf.getnframes()))


def heard_wake_word(text: str) -> bool:
    return "nova" in (text or "").split()


# ── cloud ──────────────────────────────────────────────────────────
def cloud_available(client) -> bool:
    return bool(client is not None and getattr(client, "audio", None) is not None and model_registry.stt_model())


def transcribe_cloud(client, wav_path: str, language: str = "") -> str:
    if not cloud_available(client):
        raise SpeechError("This AI provider has no speech-to-text.")
    with open(wav_path, "rb") as f:
        kw = {"language": language} if language else {}
        audio = f.read()
        ledger.record(getattr(client, "host", "AI provider"), "speech-to-text", len(audio), "a voice recording")
        r = client.audio.transcriptions.create(file=("audio.wav", audio), model=model_registry.stt_model(),
                                               response_format="text", **kw)
    return str(getattr(r, "text", r)).strip()


# ── choosing ───────────────────────────────────────────────────────
def pick_engine(client, engine: str = "auto", language: str = "") -> str:
    """'local' | 'cloud' | '' (nothing usable).  auto = cloud when the provider has it (better quality, any
    language), otherwise the on-device model."""
    if engine == "local":
        return "local" if local_ready() else ""
    if engine == "cloud":
        return "cloud" if cloud_available(client) else ""
    if cloud_available(client): return "cloud"
    return "local" if local_ready() else ""


def transcribe(client, wav_path: str, language: str = "", engine: str = "auto") -> str:
    which = pick_engine(client, engine, language)
    if which == "cloud": return transcribe_cloud(client, wav_path, language)
    if which == "local": return transcribe_local(wav_path)
    if engine == "local":
        raise SpeechError("The offline voice model is not installed. Download it in Settings → Voice.")
    raise SpeechError("Voice input is not available: this AI provider has no speech-to-text and the offline "
                      "voice model is not installed (Settings → Voice → Download offline voice model).")

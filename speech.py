# speech.py — speech-to-text, in the cloud or entirely on this Mac.
#
#   cloud    the active AI provider's transcription endpoint (Groq / OpenAI Whisper): many languages
#   whisper  whisper.cpp with OpenAI's large-v3-turbo model on this Mac (574 MB, downloaded on request): Bulgarian,
#            English and 97 more languages, as well as the cloud does it (it is the same model), nothing leaves the Mac
#   vosk     a small English model (41 MB): English only - and the wake word
#
# The on-device model also powers the wake word: a recogniser restricted to the words "nova" / "hey nova"
# listens continuously without any audio leaving the computer.
import os, re, json, wave, zipfile, hashlib, logging, threading
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


def recognizer(grammar: str | None = None):
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


# ── on-device Whisper: any language ────────────────────────────────
WHISPER_FILE   = "ggml-large-v3-turbo-q5_0.bin"
WHISPER_URL    = ("https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/"
                  + WHISPER_FILE)
WHISPER_SHA256 = "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2"
WHISPER_BYTES  = 574041195
WHISPER_MB     = 574
_whisper_lock  = threading.Lock()
# What Whisper "hears" in silence (it learned them from subtitles). Dropped when they are all there is and there
# was hardly any speech - a real "thank you" said to NOVA still gets through.
_PHANTOMS = {"thank you", "thanks for watching", "thank you for watching", "thank you very much", "you", "bye",
             "абонирайте се", "благодаря за гледането", "благодаря", "субтитри", "продължава",
             "продолжение следует", "спасибо за просмотр", "untertitel im auftrag des zdf", "sous-titrage"}


def whisper_path() -> str:
    return os.environ.get("NOVA_WHISPER_MODEL") or os.path.join(models_dir(), WHISPER_FILE)


def whisper_installed() -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec("pywhispercpp") is not None
    except Exception:
        return False


def whisper_ready() -> bool:
    try:
        size = os.path.getsize(whisper_path())
    except OSError:
        return False
    return whisper_installed() and (size == WHISPER_BYTES or "NOVA_WHISPER_MODEL" in os.environ)


def download_whisper(progress=None, cancelled=None) -> str:
    """Fetch the model (574 MB), check its SHA-256, put it in place. progress(fraction). Returns the file."""
    import downloads
    report = (lambda done, total: progress(done / (total or WHISPER_BYTES))) if progress else None
    try:
        return downloads.fetch(WHISPER_URL, whisper_path(), WHISPER_SHA256, "voice model download", report, cancelled)
    except downloads.DownloadError as e:
        raise SpeechError(str(e))


def remove_whisper() -> None:
    try: os.remove(whisper_path())
    except OSError: pass


def speech_seconds(samples) -> float:
    """How long the recording is louder than its own background, in seconds (30 ms steps)."""
    import numpy as np
    n = 480
    k = len(samples) // n
    if k == 0: return 0.0
    rms = np.sqrt((samples[:k * n].reshape(k, n) ** 2).mean(1))
    floor = float(np.percentile(rms, 10))
    return float((rms > max(0.012, floor * 4)).sum()) * n / RATE


def transcribe_whisper(pcm: bytes, language: str = "") -> str:
    """16 kHz mono 16-bit audio -> text with the on-device Whisper model. The model is loaded for this recording
    (0.2 s) and let go afterwards, so its memory (~0.8 GB) is only in use while it works."""
    import numpy as np
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    voiced = speech_seconds(audio)
    if voiced < 0.25: return ""                                   # silence or a cough: nothing to send
    from pywhispercpp.model import Model
    with _whisper_lock:
        m = Model(whisper_path(), n_threads=max(1, min(8, (os.cpu_count() or 4) - 1)), print_progress=False,
                  print_realtime=False, redirect_whispercpp_logs_to=None)
        try:
            text = " ".join(s.text.strip() for s in m.transcribe(audio, language=language or "auto")).strip()
        finally:
            del m
    plain = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    if not plain or (plain in _PHANTOMS and voiced < 0.8): return ""
    return text


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
    """'local' | 'cloud' | '' (nothing usable).  auto = Whisper on this Mac when it is installed (the same model as
    the cloud, and private), otherwise the provider's speech-to-text, otherwise the small English model."""
    if engine == "local":
        return "local" if whisper_ready() or local_ready() else ""
    if engine == "cloud":
        return "cloud" if cloud_available(client) else ""
    if whisper_ready(): return "local"
    if cloud_available(client): return "cloud"
    return "local" if local_ready() else ""


def transcribe(client, wav_path: str, language: str = "", engine: str = "auto") -> str:
    which = pick_engine(client, engine, language)
    if which == "cloud": return transcribe_cloud(client, wav_path, language)
    if which == "local" and whisper_ready():
        with wave.open(wav_path, "rb") as wf:
            if wf.getframerate() != RATE or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                raise SpeechError("Local speech recognition needs 16 kHz mono 16-bit audio.")
            return transcribe_whisper(wf.readframes(wf.getnframes()), language)
    if which == "local": return transcribe_local(wav_path)
    if engine == "local":
        raise SpeechError("The offline voice model is not installed. Download it in Settings → Voice.")
    raise SpeechError("Voice input is not available: this AI provider has no speech-to-text and the offline "
                      "voice model is not installed (Settings → Voice → Download offline voice model).")

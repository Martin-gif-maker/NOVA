# tts.py — read-aloud (edge-tts neural voices; offline: the Mac's own voice, `say`).
import os, re, tempfile, threading
import platform_utils as plat
from mdrender import _strip_think
import logging

log = logging.getLogger("nova")

ENABLED = True
VOICE   = "en-US-AriaNeural"   # edge-tts neural voice (change in Settings)
ENGINE  = "online"             # "online" = Microsoft neural voices (text is sent to Microsoft's speech service)
                               # "system" = the Mac's built-in voice: offline, nothing leaves the computer

_gen      = 0            # bumped by every stop/speak - older jobs see it and stay silent
_active   = 0            # speech jobs currently synthesising / playing
_lock     = threading.Lock()
STATE_CB  = None         # callback(bool) - lets the window pause the wake-word mic
PLAY_CB   = None         # callback(path or None) - called on the speech thread just before the sound starts; the
                         # window uses the file to tell NOVA's own voice from yours in a voice conversation

def _notify_state():
    cb = STATE_CB
    if cb:
        try: cb(_active > 0)
        except Exception as e: log.info("speech state listener failed: %s", e)

def _playing(path):
    cb = PLAY_CB
    if cb:
        try: cb(path)
        except Exception as e: log.info("playback listener failed: %s", e)

def stop():
    """Stop any currently playing / pending TTS immediately."""
    global _gen
    with _lock: _gen += 1
    plat.stop_audio()

def _clean(text: str) -> str:
    text = re.sub(r"```.*?```", " (code block) ", _strip_think(text), flags=re.DOTALL)
    text = re.sub(r"[*`#<>]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 600:
        cut = text[:600]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = cut[:end + 1] if end > 200 else cut
    return text

def speak(text: str):
    global _active
    if not ENABLED: return
    stop()
    clean = _clean(text)
    if not clean: return
    with _lock:
        my_gen = _gen; _active += 1
    _notify_state()

    def _bg():
        global _active
        fname = None
        try:
            synthesized = False
            if ENGINE != "system":
                try:
                    import asyncio, edge_tts, ledger
                    fd, fname = tempfile.mkstemp(suffix=".mp3"); os.close(fd)
                    ledger.record("speech.platform.bing.com", "read aloud", len(clean.encode("utf-8")), "the text being spoken")
                    asyncio.run(edge_tts.Communicate(clean, VOICE).save(fname))
                    synthesized = True
                except Exception:
                    synthesized = False
            if not synthesized:                  # the Mac's own voice, written to a file first
                if fname:
                    try: os.unlink(fname)
                    except OSError: pass
                fd, fname = tempfile.mkstemp(suffix=".aiff"); os.close(fd)
                synthesized = plat.synth_native(clean, fname)
            if my_gen != _gen: return            # stopped or superseded while synthesising
            _playing(fname if synthesized else None)
            if my_gen != _gen: return
            if synthesized:
                try: plat.play_audio_file(fname)
                except Exception: plat.speak_native(clean)    # playback failed -> offline voice
            else:
                plat.speak_native(clean)
        finally:
            if fname:
                try: os.unlink(fname)
                except OSError: pass
            with _lock: _active = max(0, _active - 1)
            _notify_state()
    threading.Thread(target=_bg, daemon=True).start()


def active() -> int:
    """Number of speech jobs currently synthesising/playing."""
    return _active

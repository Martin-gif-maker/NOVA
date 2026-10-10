# echo.py — telling your voice apart from NOVA's own voice coming back through the loudspeakers.
#
# While NOVA reads a reply aloud in a voice conversation, the microphone hears that reply too. NOVA knows exactly
# what it is playing, so instead of one fixed loudness bar it compares, 30 times a second, what the microphone
# hears with what the loudspeakers should be producing at that moment:
#   • it learns how loud its own voice arrives at the microphone (the "gain") and with what delay,
#   • and only something clearly louder than that expected echo, for about a quarter of a second, counts as you.
# In the pauses between NOVA's words the expected echo is close to nothing, so there even a normal voice gets in.
#
# Only loudness is compared (no audio is stored or sent anywhere). It is a level comparison, not full echo
# cancellation: with loud speakers right next to the microphone you may have to speak up or use a pause.
import os, logging, subprocess, tempfile

log = logging.getLogger("nova")

RATE  = 16000
CHUNK = 512                       # 32 ms: the microphone is read in pieces of this size
CHUNK_SECS = CHUNK / RATE


def envelope(samples, chunk: int = CHUNK):
    """Loudness (RMS) of each `chunk` samples of 16-bit audio."""
    import numpy as np
    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    n = len(x) // chunk
    if n == 0: return np.zeros(0, dtype=np.float32)
    return np.sqrt(np.mean(x[:n * chunk].reshape(n, chunk) ** 2, axis=1))


def reference_envelope(path: str):
    """The loudness curve of an audio file NOVA is about to play (mp3 / aiff / wav), or None if it cannot be read.
    Uses afconvert, which ships with macOS."""
    import wave
    import numpy as np
    fd, tmp = tempfile.mkstemp(suffix=".wav"); os.close(fd)
    try:
        r = subprocess.run(["/usr/bin/afconvert", "-f", "WAVE", "-d", f"LEI16@{RATE}", "-c", "1", path, tmp],
                           capture_output=True, timeout=20)
        if r.returncode != 0: return None
        with wave.open(tmp, "rb") as w:
            if w.getframerate() != RATE or w.getsampwidth() != 2: return None
            data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        env = envelope(data)
        return env if len(env) else None
    except (OSError, subprocess.SubprocessError, wave.Error, EOFError, ValueError) as e:
        log.info("no playback reference: %s", e); return None
    finally:
        try: os.unlink(tmp)
        except OSError: pass


def _sliding_max(a, back: int, ahead: int = 0):
    """out[i] = max(a[i-back .. i+ahead]) (indexes outside the array count as silence)."""
    import numpy as np
    n = len(a); width = back + ahead + 1
    padded = np.concatenate([np.zeros(back, dtype=np.float32), a, np.zeros(ahead, dtype=np.float32)])
    return np.lib.stride_tricks.sliding_window_view(padded, width).max(axis=1)[:n] if n else a


class EchoGate:
    """Feed it the microphone's loudness chunk by chunk; `feed` returns True once you are talking over NOVA."""
    MAX_DELAY  = 2.5        # seconds between "playback was started" and the microphone hearing it, at most
    TAIL       = 8          # chunks of room echo after a sound (≈ 0.25 s)
    JITTER     = 2          # chunks of slack around the measured delay
    MARGIN     = 2.2        # you must be this many times louder than the expected echo
    FLOOR      = 900.0      # …and at least this loud (a quiet room is ≈ 50, close speech ≈ 2000+)
    HOLD       = 8          # for this many chunks (≈ 0.25 s): a cough or a door is not an interruption
    DRIFT      = 1.3        # what is at most this much louder than expected still counts as NOVA's own voice
    MIN_LEARN  = 12         # chunks of NOVA's voice heard before anything can interrupt (≈ 0.4 s)
    HISTORY    = 160        # chunks remembered for learning (≈ 5 s)
    MIN_CORR   = 0.55       # how clearly the delay must show before it is trusted

    def __init__(self, reference, offset: int = 0, seed_gain: float = None):
        import numpy as np
        self._np = np
        self.ref = np.asarray(reference, dtype=np.float32)
        self.D = int(round(self.MAX_DELAY / CHUNK_SECS))
        self.i = int(offset)                                   # where in the reference "now" is (playback clock)
        self.delay = None                                      # chunks, once measured
        self.gain = float(seed_gain) if seed_gain else 0.0
        self._seed = self.gain
        peak = float(np.percentile(self.ref, 95)) if len(self.ref) else 0.0
        self._active = max(60.0, 0.08 * peak)                  # the reference counts as "NOVA is speaking" above this
        self._wide = _sliding_max(self.ref, self.D)            # delay unknown: the loudest thing in the last 2.5 s
        self._tight = None
        self._mic = []; self._idx = []                         # recent microphone loudness and its reference position
        self._first = None                                     # where NOVA's voice starts in the reference
        self._ratios = 0; self._loud = 0; self._since_fit = 0

    # what the loudspeakers contribute at reference position i (before the gain is applied)
    def _expected(self, i: int) -> float:
        table = self._tight if self._tight is not None else self._wide
        if i < 0: return 0.0
        if i >= len(table):                                    # just after the end: the tail of the last sounds
            back = self.D if self._tight is None else (self.delay + self.TAIL + self.JITTER)
            return float(self.ref[max(0, i - back):].max()) if i - back < len(self.ref) and len(self.ref) else 0.0
        return float(table[i])

    def _fit_delay(self):
        """Find the delay at which the microphone's loudness follows the reference best."""
        np = self._np
        if len(self._mic) < 30: return
        m = np.asarray(self._mic, dtype=np.float32); idx = np.asarray(self._idx)
        if m.std() < 1e-3: return
        best, best_d = 0.0, None
        ref = np.concatenate([np.zeros(self.D + 1, dtype=np.float32), self.ref, np.zeros(len(m) + self.D + 1, dtype=np.float32)])
        for d in range(0, self.D + 1):
            r = ref[idx - d + self.D + 1]
            if r.std() < 1e-3: continue
            c = float(np.corrcoef(m, r)[0, 1])
            if c > best: best, best_d = c, d
        if best_d is not None and best >= self.MIN_CORR and best_d != self.delay:
            self.delay = best_d
            # echo of position i is what was played at i-delay, plus the room's tail and a little slack either way
            shifted = np.concatenate([np.zeros(best_d, dtype=np.float32), self.ref])
            self._tight = _sliding_max(shifted, self.TAIL + self.JITTER, self.JITTER)

    def _fit_gain(self):
        np = self._np
        # Before the delay is known, the first MAX_DELAY after NOVA starts may simply be the sound still on its
        # way: those chunks say nothing about how loud the echo is.
        first = 0 if self._tight is not None else (self._first if self._first is not None else 10 ** 9) + self.D
        ratios = [m / e for m, e in ((m, self._expected(i)) for m, i in zip(self._mic, self._idx) if i >= first)
                  if e >= self._active]
        self._ratios = len(ratios)
        if len(ratios) >= self.MIN_LEARN:
            learned = float(np.percentile(ratios, 92))
            self.gain = max(learned, 0.5 * self._seed) if self._seed else learned

    def learned(self) -> bool:
        """Has NOVA's own voice been heard for long enough to know how loud it arrives?"""
        return self._ratios >= self.MIN_LEARN

    def threshold(self) -> float:
        return max(self.FLOOR, self.MARGIN * self.gain * self._expected(self.i))

    def feed(self, mic_rms: float) -> bool:
        i = self.i; self.i += 1
        expected = self._expected(i)
        if self._first is None and expected >= self._active: self._first = i
        over = mic_rms > max(self.FLOOR, self.MARGIN * self.gain * expected)
        ready = self._ratios >= self.MIN_LEARN                 # NOVA's own voice has been heard (or found to be inaudible)
        # Once NOVA's own level is known, learn only from chunks that fit it: your voice must not teach the gate
        # that the echo is louder than it is (a slow drift, such as the volume being nudged, still gets through).
        fits = mic_rms <= max(self.FLOOR * 0.5, self.DRIFT * self.gain * expected)
        if not ready or fits:
            self._mic.append(float(mic_rms)); self._idx.append(i)
            if len(self._mic) > self.HISTORY: del self._mic[0], self._idx[0]
        self._since_fit += 1
        if self._since_fit >= 4:
            self._since_fit = 0
            self._fit_delay(); self._fit_gain()
        if not ready:
            self._loud = 0; return False
        self._loud = self._loud + 1 if over else max(0.0, self._loud - 0.5)        # the gaps between your words do not reset it
        return self._loud >= self.HOLD

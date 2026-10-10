"""Telling your voice from NOVA's own voice in the loudspeakers (echo.py).

No microphone and no sound: rooms are simulated - NOVA's speech is delayed, scaled, smeared by the room and
mixed with noise, sometimes with a person talking over it - and the gate is fed what a microphone would hear."""
import sys, wave
import numpy as np
import pytest
import echo

mac_only = pytest.mark.skipif(sys.platform != "darwin", reason="uses afconvert / say")


def speech(rng, secs, level=3000.0):
    """Speech-like sound: words of noise with short gaps and longer pauses between sentences."""
    n = int(secs * echo.RATE); x = np.zeros(n, dtype=np.float32); pos = 0; words = 0
    while pos < n:
        w = int(rng.uniform(0.12, 0.45) * echo.RATE)
        seg = rng.standard_normal(min(w, n - pos)).astype(np.float32) * level * rng.uniform(0.5, 1.3)
        ramp = np.minimum(1.0, np.minimum(np.arange(len(seg)), len(seg) - np.arange(len(seg))) / 400.0)
        x[pos:pos + len(seg)] = seg * ramp
        pos += w; words += 1
        pos += int((rng.uniform(0.03, 0.14) if words % rng.integers(4, 9) else rng.uniform(0.3, 0.6)) * echo.RATE)
    return x


def room(played, rng, gain, delay, reverb=0.12, noise=40.0):
    """What the microphone gets from the loudspeakers."""
    taps = int(reverb * echo.RATE)
    ir = np.zeros(taps + 1, dtype=np.float32); ir[0] = 1.0
    k = rng.integers(1, taps, 40); ir[k] += rng.standard_normal(40).astype(np.float32) * 0.25 * np.exp(-k / (taps / 3))
    d = int(delay * echo.RATE)
    out = np.zeros(len(played) + d, dtype=np.float32)
    out[d:] = np.convolve(played, ir)[:len(played)] * gain
    return out + rng.standard_normal(len(out)).astype(np.float32) * noise


def fires_at(mic, reference, offset=0, seed_gain=None):
    """Seconds (on the playback clock) at which the gate reports an interruption, or None."""
    gate = echo.EchoGate(reference, offset=offset, seed_gain=seed_gain)
    for k, level in enumerate(echo.envelope(mic[offset * echo.CHUNK:])):
        if gate.feed(float(level)): return (k + offset) * echo.CHUNK_SECS, gate
    return None, gate


def scene(seed, gain, delay, **kw):
    rng = np.random.default_rng(seed)
    nova = speech(rng, 10.0)
    return nova, echo.envelope(nova), room(nova, rng, gain, delay, **kw)


def add_voice(mic, seed, at, secs, level):
    you = speech(np.random.default_rng(seed), secs, level)
    out = mic.copy(); start = int(at * echo.RATE)
    out[start:start + len(you)] += you[:len(out) - start]
    return out


@pytest.mark.parametrize("gain,delay", [(0.15, 0.1), (0.5, 0.35), (1.2, 0.2), (1.2, 0.9), (0.5, 1.4), (1.2, 2.1), (2.5, 0.5)])
def test_novas_own_voice_in_the_speakers_never_interrupts_it(gain, delay):
    for seed in range(4):
        nova, reference, mic = scene(seed, gain, delay, reverb=0.05 + 0.08 * seed, noise=20 + 30 * seed)
        at, gate = fires_at(mic, reference, offset=seed * 3)
        assert at is None, f"interrupted itself at {at:.2f}s (seed {seed})"
        assert gate.learned() and gate.gain == pytest.approx(gain, rel=0.6)            # it worked out how loud the echo is…
        assert gate.delay is not None and abs(gate.delay * echo.CHUNK_SECS - delay) < 0.13     # …and how late it arrives


@pytest.mark.parametrize("gain,delay", [(0.15, 0.1), (0.5, 0.35), (1.2, 0.2), (1.2, 0.9)])
def test_talking_over_it_clearly_is_noticed_quickly(gain, delay):
    for seed in range(4):
        nova, reference, mic = scene(seed, gain, delay)
        loudest_echo = float(np.percentile(echo.envelope(mic), 95))
        at, _ = fires_at(add_voice(mic, 100 + seed, 5.0, 3.0, max(2500.0, 3.5 * loudest_echo)), reference)
        assert at is not None and 5.0 <= at <= 6.5, f"fired at {at} (seed {seed})"


def test_with_headphones_a_normal_voice_is_enough():
    for seed in range(4):
        nova, reference, mic = scene(seed, 0.0, 0.3)                         # nothing of NOVA reaches the microphone
        assert fires_at(mic, reference)[0] is None
        at, _ = fires_at(add_voice(mic, 200 + seed, 4.0, 3.0, 1800.0), reference)
        assert at is not None and 4.0 <= at <= 5.0


def test_a_cough_or_a_door_is_not_an_interruption():
    nova, reference, mic = scene(1, 0.5, 0.3)
    bang = mic.copy(); start = int(5.0 * echo.RATE)
    bang[start:start + 3 * echo.CHUNK] += np.random.default_rng(9).standard_normal(3 * echo.CHUNK).astype(np.float32) * 20000
    assert fires_at(bang, reference)[0] is None


def test_nothing_can_interrupt_before_novas_voice_has_been_measured():
    nova, reference, mic = scene(2, 1.2, 0.8)
    early = add_voice(mic, 300, 0.0, 0.7, 9000.0)                            # a loud noise in the very first moments
    at, gate = fires_at(early, reference)
    assert at is None and gate.gain == pytest.approx(1.2, rel=0.6)           # …and it did not spoil the measurement either


def test_your_voice_does_not_teach_it_that_the_echo_is_louder():
    nova, reference, mic = scene(3, 0.3, 0.4)
    quiet_talk = add_voice(mic, 400, 3.0, 6.0, 900.0)                        # murmuring along, never loud enough to interrupt
    gate = echo.EchoGate(reference)
    for level in echo.envelope(quiet_talk): gate.feed(float(level))
    assert gate.gain == pytest.approx(0.3, rel=0.6)


def test_a_small_loudspeaker_that_distorts_is_still_recognised():
    for seed in range(4):
        rng = np.random.default_rng(seed)
        nova = speech(rng, 10.0); played = np.tanh(nova / 5000.0) * 5000.0   # what leaves the speaker is not what was sent
        assert fires_at(room(played, rng, 1.2, 0.3), echo.envelope(nova))[0] is None


def test_the_level_learned_in_one_reply_carries_over_and_fades():
    nova, reference, mic = scene(5, 0.8, 0.3)
    _, first = fires_at(mic, reference)
    assert fires_at(mic, reference, seed_gain=first.gain)[0] is None
    gate = echo.EchoGate(reference, seed_gain=4.0)                           # the speakers were much louder last time
    for level in echo.envelope(mic): gate.feed(float(level))
    assert 1.9 <= gate.gain <= 2.1                                           # at most halved per reply: it lets go gradually


def test_envelope_and_edge_cases():
    assert list(echo.envelope(np.full(1024, 100, dtype=np.int16))) == [100.0, 100.0] and len(echo.envelope([1, 2, 3])) == 0
    gate = echo.EchoGate(np.zeros(0, dtype=np.float32))                      # an empty reference: plain loudness
    assert not any(gate.feed(50.0) for _ in range(100)) and gate.threshold() == echo.EchoGate.FLOOR
    silent = echo.EchoGate(np.zeros(300, dtype=np.float32))
    assert not any(silent.feed(40.0) for _ in range(400))                    # runs past the end of the reference without trouble
    late = echo.EchoGate(np.full(50, 3000, dtype=np.float32), offset=-3)
    assert late.feed(10.0) is False


@mac_only
def test_the_loudness_curve_of_a_real_audio_file(tmp_path):
    tone = (np.sin(np.arange(echo.RATE) * 2 * np.pi * 440 / echo.RATE) * 8000).astype(np.int16)
    sound = np.concatenate([tone, np.zeros(echo.RATE // 2, dtype=np.int16), tone // 4])
    path = tmp_path / "speech.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)          # not NOVA's format: afconvert has to resample
        stereo = np.repeat(np.interp(np.arange(0, len(sound), echo.RATE / 44100), np.arange(len(sound)), sound).astype(np.int16), 2)
        w.writeframes(stereo.tobytes())
    curve = echo.reference_envelope(str(path))
    assert abs(len(curve) * echo.CHUNK_SECS - 2.5) < 0.1
    assert curve[5] == pytest.approx(8000 / np.sqrt(2), rel=0.05) and curve[40] < 20 and curve[60] == pytest.approx(2000 / np.sqrt(2), rel=0.05)
    (tmp_path / "junk.mp3").write_bytes(b"not audio at all")
    assert echo.reference_envelope(str(tmp_path / "junk.mp3")) is None and echo.reference_envelope(str(tmp_path / "missing.mp3")) is None


@mac_only
def test_the_macs_own_voice_can_be_written_to_a_file_and_measured(tmp_path):
    import platform_utils as plat
    path = str(tmp_path / "voice.aiff")
    assert plat.synth_native("- Hello. This sentence is written to a file, not spoken.", path) is True      # silent: a file only
    curve = echo.reference_envelope(path)
    assert curve is not None and len(curve) * echo.CHUNK_SECS > 1.5 and curve.max() > 1000 and (curve < 60).any()

import time
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
import onboarding
import providers
import main, win_account
import win_voice
import paths
import themes


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _pump(app, ms=200):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents(); time.sleep(0.01)


def test_wizard_requires_consent_then_valid_key(app, monkeypatch):
    monkeypatch.setattr(onboarding, "validate_key", lambda p, k, u="": (k == "gsk_good", "msg"))
    d = onboarding.OnboardingDialog(themes.THEMES["soft"])
    assert not d._next.isEnabled()                       # cannot continue without consent
    d.consent_chk.setChecked(True); assert d._next.isEnabled()
    d._go(1)                                             # key page
    assert not d._next.isEnabled()
    d.key_edit.setText("gsk_bad"); d._test_key(); _pump(app)
    assert not d._next.isEnabled()
    d.key_edit.setText("gsk_good"); d._test_key(); _pump(app)
    assert d._next.isEnabled() and d.api_key == "gsk_good"
    d._go(1); d._go(1)                                   # permissions, done
    d.wake_chk.setChecked(True)
    ch = d.choices()
    assert ch["consent"] and ch["wake_word"] and not ch["tts_auto"] and ch["api_key"] == "gsk_good"


def test_existing_key_can_continue_without_retyping(app):
    d = onboarding.OnboardingDialog(themes.THEMES["nova"], existing_key=True)
    d.consent_chk.setChecked(True); d._go(1)
    assert d._next.isEnabled()
    assert d.choices()["api_key"] == ""                  # nothing new to store


def test_wake_word_needs_consent(app, monkeypatch, tmp_path):
    import types
    monkeypatch.setattr(win_account, "_get_api_key", lambda *a, **k: "k")
    monkeypatch.setattr(providers, "make_client", lambda *a, **k: types.SimpleNamespace())
    monkeypatch.setattr(main.AssistantWindow, "_run_onboarding", lambda self, k="": k)
    monkeypatch.setattr(main.AssistantWindow, "_maybe_morning_briefing", lambda self: None)
    monkeypatch.setattr(main.AssistantWindow, "_start_spotify_monitor", lambda self: None)
    monkeypatch.setattr(paths, "CONFIG_FILE", str(tmp_path / "c.json"))
    monkeypatch.setattr(main.plat, "start_global_hotkey", lambda cb: True)
    started = []
    monkeypatch.setattr(win_voice, "WakeWordListener", lambda c, *a: started.append(1) or types.SimpleNamespace(
        wake_detected=types.SimpleNamespace(connect=lambda f: None),
        error_occurred=types.SimpleNamespace(connect=lambda f: None), start=lambda: None, stop=lambda: None,
        isFinished=lambda: True, isRunning=lambda: False))
    import sys
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(query_devices=lambda: []))
    w = main.AssistantWindow()
    w.config["wake_word"] = True; w.config["consent"] = False
    w._start_wake_listener(); assert not started          # no consent -> never starts
    w.config["consent"] = True
    w._start_wake_listener(); assert started
    w._shutdown()

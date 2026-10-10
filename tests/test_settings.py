import pytest
import settings
from settings import Settings


def test_defaults_are_complete_and_independent():
    a, b = Settings(), Settings()
    assert set(settings.SCHEMA) <= set(a) and a["font_size"] == 10 and a["wake_word"] is False
    a["always_allow"].append("x")
    assert b["always_allow"] == []                                  # mutable defaults are never shared


def test_bad_values_are_repaired_not_fatal():
    s = Settings({"font_size": "huge", "theme": "neon", "retention_days": -5, "wake_thresh": 99999, "tts": "yes",
                  "always_allow": "oops", "win_w": 5, "reasoning": "extreme", "font_size_extra": 3})
    assert s["font_size"] == 10 and s["theme"] == "auto" and s["retention_days"] == 0 and s["wake_thresh"] == 2000
    assert s["tts"] is True and s["always_allow"] == [] and s["win_w"] == 280 and s["reasoning"] == "low"
    assert s["font_size_extra"] == 3                                 # unknown keys from the file are kept, not destroyed


def test_typo_in_code_is_caught():
    s = Settings()
    with pytest.raises(KeyError, match="did you mean 'font_size'"):
        s.get("font_sise")
    with pytest.raises(KeyError):
        s["wake_wrod"] = True
    with pytest.raises(ValueError):
        s["font_size"] = "big"
    s["font_size"] = 99; assert s["font_size"] == 22                 # clamped to the allowed range


def test_non_strict_mode_warns_instead_of_raising(monkeypatch, caplog):
    monkeypatch.setattr(Settings, "STRICT", False)
    s = Settings()
    assert s.get("font_sise", 7) == 7
    s["font_size"] = "big"; assert s["font_size"] == 10              # invalid write ignored
    assert "did you mean" in caplog.text


def test_save_never_contains_a_key_and_roundtrips():
    s = Settings({"groq_api_key": "gsk_secret", "theme": "soft"})
    out = s.to_json()
    assert "groq_api_key" not in out and Settings(out)["theme"] == "soft"

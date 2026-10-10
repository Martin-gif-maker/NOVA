# diagnostics.py — a support report the user can paste into a bug report (no secrets, no chat content).
import re, sys, platform
import paths
import platform_utils as plat

_SECRET = re.compile(r"(gsk_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._-]{12,})")
_SAFE_KEYS = ("theme", "model_key", "reasoning", "font_size", "tts", "tts_auto", "wake_word", "voice_auto_send",
              "stt_lang", "suggest_followups", "onboarded", "consent", "schema", "ui_lang")


def _tail(path: str, n: int) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f: lines = f.readlines()[-n:]
        return _SECRET.sub("<redacted>", "".join(lines))
    except OSError:
        return "(no log yet)"


def build_diagnostics(config: dict, log_lines: int = 60) -> str:
    cfg = {k: config.get(k) for k in _SAFE_KEYS if k in config}
    perms = {}
    if plat.IS_MAC:
        perms = {"accessibility": plat.accessibility_trusted(), "screen_recording": plat.screen_capture_allowed(),
                 "microphone": plat.microphone_status()}
    return "\n".join([
        f"NOVA {paths.__version__} (schema {paths.SCHEMA_VERSION}, frozen={paths.IS_FROZEN})",
        f"OS: {platform.platform()}  machine={platform.machine()}",
        f"Python: {sys.version.split()[0]}",
        f"Always-allow entries: {len(config.get('always_allow', []))}",
        f"Settings: {cfg}", f"Permissions: {perms}", "", f"--- last {log_lines} log lines ---",
        _tail(paths.LOG_FILE, log_lines)])

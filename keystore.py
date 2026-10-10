# keystore.py — where API keys live: the OS keychain first, a private 0600 file as fallback.
# One entry per AI provider ("groq_api_key", "anthropic_api_key", …).
import os
import paths
import logging

log = logging.getLogger("nova")

_KR_SERVICE = "NOVA_AI_Assistant"
try:
    import keyring as _keyring
    _KEYRING_OK = True
except ImportError:
    _keyring = None
    _KEYRING_OK = False

_KEY_FILE = paths.KEY_FILE


def _user(provider: str) -> str:
    return f"{provider or 'groq'}_api_key"


def _file(provider: str) -> str:
    return _KEY_FILE if (provider or "groq") == "groq" else f"{_KEY_FILE}_{provider}"


def _get_api_key(provider: str = "groq") -> str:
    """Read the provider's API key from the keychain, then from the private fallback file."""
    if _KEYRING_OK:
        try:
            v = _keyring.get_password(_KR_SERVICE, _user(provider))
            if v: return v
        except Exception as e: log.info("the Keychain could not be read: %s", e)
    try:
        with open(_file(provider), "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _save_api_key(key: str, provider: str = "groq") -> str:
    """Store the key. Returns 'keyring', 'file' (private fallback) or '' on failure."""
    if _KEYRING_OK:
        try:
            _keyring.set_password(_KR_SERVICE, _user(provider), key)
            return "keyring"
        except Exception as e: log.info("the key could not be stored in the Keychain: %s", e)
    try:
        fd = os.open(_file(provider), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(key)
        return "file"
    except OSError:
        return ""


def delete_api_key(provider: str = "groq") -> None:
    if _KEYRING_OK:
        try: _keyring.delete_password(_KR_SERVICE, _user(provider))
        except Exception as e: log.debug("no Keychain entry to delete: %s", e)
    try: os.remove(_file(provider))
    except OSError: pass


# ── other secrets (Keychain only - never written to a file) ────────
def get_secret(name: str) -> str:
    if not _KEYRING_OK: return ""
    try: return _keyring.get_password(_KR_SERVICE, name) or ""
    except Exception: return ""


def set_secret(name: str, value: str) -> bool:
    """Store a secret in the Keychain. False if the Keychain is not available (nothing is stored anywhere else)."""
    if not _KEYRING_OK: return False
    try:
        _keyring.set_password(_KR_SERVICE, name, value)
        return _keyring.get_password(_KR_SERVICE, name) == value
    except Exception:
        return False


def delete_secret(name: str) -> None:
    if not _KEYRING_OK: return
    try: _keyring.delete_password(_KR_SERVICE, name)
    except Exception as e: log.debug("no Keychain entry to delete: %s", e)

# providers.py — the AI services NOVA can talk to, behind one interface.
#
# Every client returned by make_client() looks the same to the rest of the app:
#     client.chat.completions.create(model=…, messages=…, tools=…, stream=…, max_tokens=…, reasoning_effort=…)
#     client.audio.transcriptions.create(…)        (only if the provider offers speech-to-text)
#     client.models.list()                          -> iterable of objects with .id
#     client.begin_request()                        -> called once per user request (optional hook)
# Messages / tools / streamed chunks use the OpenAI chat-completions shape; each adapter translates.
import re, time, logging, threading
import ledger

log = logging.getLogger("nova")

# slot -> (model id, short label shown in the UI).  "smart" is the default, "fast" the rate-limit fallback.
PROVIDERS = {
    "groq": {
        "label": "Groq (free tier, fast)", "kind": "groq", "needs_key": True, "key_hint": "gsk_…",
        "key_url": "https://console.groq.com/keys",
        "models": {"smart": ("openai/gpt-oss-120b", "120B"), "fast": ("openai/gpt-oss-20b", "20B"),
                   "mix": ("qwen/qwen3.8-27b", "QWEN")},
        "preferred": {"smart": ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "qwen/qwen3.8-27b"],
                      "fast": ["openai/gpt-oss-20b", "llama-3.1-8b-instant", "qwen/qwen3.8-27b"],
                      "mix": ["qwen/qwen3.8-27b", "qwen/qwen3-32b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b"]},
        "vision": ["meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct",
                   "qwen/qwen3.8-27b"],
        "stt": "whisper-large-v3-turbo",
    },
    "anthropic": {
        "label": "Anthropic (Claude)", "kind": "anthropic", "needs_key": True, "key_hint": "sk-ant-…",
        "key_url": "https://platform.claude.com/",
        # Opus is the default; the cheaper tiers fill the app's "fast" and "mix" slots.
        "models": {"smart": ("claude-opus-5-5", "OPUS"), "fast": ("claude-haiku-4-5", "HAIKU"),
                   "mix": ("claude-sonnet-5-5", "SONNET")},
        "preferred": {"smart": ["claude-opus-5-5", "claude-sonnet-5-5"], "fast": ["claude-haiku-4-5", "claude-sonnet-5-5"],
                      "mix": ["claude-sonnet-5-5", "claude-opus-5-5"]},
        "vision": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5"],     # every current Claude model reads images
        "stt": None,                                                                 # no speech-to-text endpoint
    },
    "openai": {
        "label": "OpenAI", "kind": "openai", "needs_key": True, "key_hint": "sk-…",
        "key_url": "https://platform.openai.com/api-keys",
        # ids change often: these are only starting points - the live model list decides (see models.reconcile)
        "models": {"smart": ("gpt-4o", "SMART"), "fast": ("gpt-4o-mini", "FAST"), "mix": ("gpt-4o", "MIX")},
        "preferred": {"smart": ["gpt-5", "gpt-4.1", "gpt-4o"], "fast": ["gpt-5-mini", "gpt-4.1-mini", "gpt-4o-mini"],
                      "mix": ["gpt-4.1", "gpt-4o", "gpt-5"]},
        "vision": [], "stt": "whisper-1",                                            # vision: uses the chat model
    },
    "ollama": {
        "label": "Ollama (runs on this Mac, private, offline)", "kind": "openai", "needs_key": False, "key_hint": "",
        "key_url": "https://ollama.com/download", "base_url": "http://localhost:11434/v1", "local": True,
        "models": {"smart": ("llama3.1", "LOCAL"), "fast": ("llama3.1", "LOCAL"), "mix": ("llama3.1", "LOCAL")},
        "preferred": {"smart": ["qwen2.5", "llama3.3", "llama3.1", "mistral"], "fast": ["llama3.2", "llama3.1", "qwen2.5"],
                      "mix": ["llama3.1", "qwen2.5", "mistral"]},
        "vision": ["llama3.2-vision", "llava"], "stt": None,
    },
    "custom": {
        "label": "Custom (any OpenAI-compatible server)", "kind": "openai", "needs_key": False, "key_hint": "",
        "key_url": "", "needs_url": True,
        "models": {"smart": ("", "SMART"), "fast": ("", "FAST"), "mix": ("", "MIX")},
        "preferred": {"smart": [], "fast": [], "mix": []}, "vision": [], "stt": None,
    },
}
DEFAULT_PROVIDER = "groq"


def info(provider_id: str) -> dict:
    return PROVIDERS.get(provider_id) or PROVIDERS[DEFAULT_PROVIDER]


def label(provider_id: str) -> str:
    return info(provider_id)["label"].split(" (")[0]


def base_url_for(provider_id: str, configured: str = "") -> str:
    return (configured or "").strip() or info(provider_id).get("base_url", "") or ""


# ── Errors, the same for every provider ────────────────────────────
class ProviderError(Exception):
    """A provider failure reduced to what the app needs to decide what to do next."""
    def __init__(self, kind: str, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.kind, self.retry_after = kind, retry_after


# ── the provider's per-minute allowance ────────────────────────────
# Free tiers count tokens per minute and per model (Groq: 8,000). The provider says how much is left with every
# answer; NOVA remembers it, so it can use the other model or wait exactly as long as needed *before* sending a
# request that would be refused - instead of failing first and guessing afterwards.
_ALLOWANCE: dict[str, tuple] = {}   # model id -> (tokens left, tokens per minute, when that was true)
_allow_lock = threading.Lock()


def _seconds(text) -> float:
    """'7.66s' / '1m3.5s' / '690ms' -> seconds."""
    m = re.fullmatch(r"\s*(?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?(?:([\d.]+)ms)?\s*", str(text or ""))
    if not m or not any(m.groups()): return 0.0
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3) or 0) + float(m.group(4) or 0) / 1000


def note_allowance(model: str, headers) -> None:
    """Remember what the provider's answer said about the tokens left this minute."""
    try:
        left = int(float(headers.get("x-ratelimit-remaining-tokens"))); limit = int(float(headers.get("x-ratelimit-limit-tokens")))
    except (TypeError, ValueError, AttributeError):
        return
    if limit > 0:
        with _allow_lock: _ALLOWANCE[model] = (left, limit, time.monotonic())


def spend(model: str, tokens: int) -> None:
    """Count tokens NOVA has just used (the provider's own number arrives with the next answer)."""
    with _allow_lock:
        if model in _ALLOWANCE:
            left, limit, at = _ALLOWANCE[model]
            _ALLOWANCE[model] = (left - max(0, int(tokens)), limit, at)


def allowance(model: str):
    """Tokens that can be sent to `model` right now, or None if the provider has not said (then nothing is assumed).
    The allowance refills steadily: a sixtieth of the per-minute limit every second."""
    with _allow_lock: known = _ALLOWANCE.get(model)
    if not known: return None
    left, limit, at = known
    return int(min(limit, left + (time.monotonic() - at) * limit / 60.0))


def wait_for(model: str, need: int) -> float:
    """Seconds until `need` tokens are available for `model` (0 = now, or unknown)."""
    with _allow_lock: known = _ALLOWANCE.get(model)
    if not known: return 0.0
    left, limit, at = known
    need = min(int(need), limit)                       # more than a whole minute's worth can never be "waited for"
    have = min(limit, left + (time.monotonic() - at) * limit / 60.0)
    return max(0.0, (need - have) * 60.0 / limit)


def _retry_after_from_text(text: str):
    m = re.search(r"try again in\s+(?:(\d+)m)?([\d.]+)s", text or "")
    return (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else None


def _sdk_modules():
    import sys
    return [sys.modules[n] for n in ("anthropic", "openai", "groq") if n in sys.modules]


def classify_error(exc: Exception):
    """(kind, retry_after_seconds).  kind ∈ rate_limit | auth | not_found | bad_request | connection |
    server | tool_json | other.   Typed SDK exceptions are checked first (most specific first); plain
    exceptions fall back to reading the message."""
    if isinstance(exc, ProviderError):
        return exc.kind, exc.retry_after
    text = str(exc)
    for sdk in _sdk_modules():
        def _is(name, sdk=sdk):
            cls = getattr(sdk, name, None)
            return cls is not None and isinstance(exc, cls)
        if _is("RateLimitError"):
            ra = None
            try: ra = float(exc.response.headers.get("retry-after"))     # type: ignore[attr-defined]  # the SDK's error has one
            except Exception: ra = _retry_after_from_text(text)
            return "rate_limit", ra
        if _is("AuthenticationError") or _is("PermissionDeniedError"): return "auth", None
        if _is("NotFoundError"): return "not_found", None
        if _is("BadRequestError"): return "bad_request", None
        if _is("APIConnectionError"): return "connection", None       # includes timeouts
        if _is("APIStatusError"):
            code = getattr(exc, "status_code", 0) or 0
            return ("server" if code >= 500 else "other"), None
    low = text.lower()
    if "rate_limit" in low or "429" in low: return "rate_limit", _retry_after_from_text(text)
    if "401" in low or "invalid api key" in low or "authentication" in low or "api_key" in low: return "auth", None
    if "overload" in low or "503" in low or "529" in low or "500" in low: return "server", None
    if "connection" in low or "timed out" in low or "timeout" in low or "network" in low: return "connection", None
    return "other", None


FRIENDLY = {
    "rate_limit": "Rate limit — wait a moment and try again.",
    "auth": "API key error — use 'Change API key' in the menu.",
    "connection": "Network error — check your connection.",
    "server": "The AI service is having trouble — try again in a moment.",
    "not_found": "That model is not available on this account — pick another in Settings.",
}


# ── Outbound ledger ────────────────────────────────────────────────
def note_chat(host: str, kw: dict) -> None:
    """Record one chat request in the 'what NOVA sent' ledger: destination, size, shape - never the text."""
    msgs = kw.get("messages") or []
    images = sum(1 for m in msgs if isinstance(m.get("content"), list)
                 for part in m["content"] if isinstance(part, dict) and part.get("type") == "image_url")
    detail = f"model {kw.get('model', '?')}, {len(msgs)} messages"
    if kw.get("tools"): detail += f", {len(kw['tools'])} tool definitions"
    if images: detail += f", {images} image(s)"
    ledger.record(host, "image analysis" if images else "chat",
                  ledger.size_of(msgs) + ledger.size_of(kw.get("tools") or []), detail)


# ── Usage ──────────────────────────────────────────────────────────
def _usage_of(obj):
    u = getattr(getattr(obj, "x_groq", None), "usage", None) or getattr(obj, "usage", None)
    if not u: return 0, 0
    return int(getattr(u, "prompt_tokens", 0) or 0), int(getattr(u, "completion_tokens", 0) or 0)


def metered(client, kw: dict, result):
    """Pass a provider's answer through unchanged while noting the tokens it reports (see usage.py)."""
    import usage
    provider_id, model = getattr(client, "provider_id", "?"), kw.get("model", "?")
    if not kw.get("stream"):
        tin, tout = _usage_of(result)
        usage.record(provider_id, model, tin, tout)
        return result

    def chunks():
        tin = tout = 0
        try:
            for chunk in result:
                a, b = _usage_of(chunk); tin += a; tout += b
                yield chunk
        finally:
            usage.record(provider_id, model, tin, tout)
    return chunks()


# ── Clients ────────────────────────────────────────────────────────
class _GroqAdapter:
    """Groq's own SDK, with the one Groq-specific request quirk applied."""
    host = "api.groq.com"

    def __init__(self, api_key: str):
        from groq import Groq
        self._c = Groq(api_key=api_key, timeout=60.0, max_retries=0)     # the worker does its own, smarter retries
        self.chat = _NS(completions=_NS(create=self._create))
        self.audio = self._c.audio
        self.models = self._c.models

    def _create(self, **kw):
        effort = kw.pop("reasoning_effort", None)
        if effort and "gpt-oss" in kw.get("model", ""):                 # only these models take the parameter
            kw["reasoning_effort"] = effort
        note_chat(self.host, kw)
        stream = self._c.chat.completions.create(**kw)
        note_allowance(kw.get("model", ""), getattr(getattr(stream, "response", None), "headers", None))
        return metered(self, kw, stream)

    def begin_request(self): pass


class _NS:
    def __init__(self, **kw): self.__dict__.update(kw)


def make_client(provider_id: str, api_key: str = "", base_url: str = ""):
    """Build the client for a provider. Raises ProviderError('auth') when a required key is missing."""
    client = _make_client(provider_id, api_key, base_url)
    client.provider_id = provider_id if provider_id in PROVIDERS else DEFAULT_PROVIDER      # for the usage view
    return client


def _make_client(provider_id: str, api_key: str = "", base_url: str = ""):
    p = info(provider_id)
    if p["needs_key"] and not api_key and p["kind"] != "anthropic":       # Anthropic can also use an `ant auth login` profile
        raise ProviderError("auth", f"{label(provider_id)} needs an API key.")
    if p["kind"] == "groq":
        return _GroqAdapter(api_key)
    if p["kind"] == "anthropic":
        from provider_anthropic import AnthropicClient
        return AnthropicClient(api_key or None)
    from provider_openai import OpenAICompatClient
    url = base_url_for(provider_id, base_url)
    if p.get("needs_url") and not url:
        raise ProviderError("bad_request", "Enter the server address (base URL) for the custom provider.")
    return OpenAICompatClient(api_key or "not-needed", url or None, local=bool(p.get("local")))


def list_model_ids(client) -> set:
    ledger.record(getattr(client, "host", "AI provider"), "model list")
    page = client.models.list()
    return {m.id for m in getattr(page, "data", page)}


def validate(provider_id: str, api_key: str = "", base_url: str = ""):
    """(ok, message) — tries the cheap 'list models' call with these credentials."""
    name = label(provider_id)
    try:
        ids = list_model_ids(make_client(provider_id, api_key, base_url))
        if info(provider_id).get("local") and not ids:
            return False, "Ollama is running but has no models yet. Run e.g. `ollama pull llama3.1` first."
        return True, f"{name} works ✓" + (f" ({len(ids)} models)" if ids else "")
    except Exception as e:
        kind, _ = classify_error(e)
        if kind == "auth": return False, f"{name} rejected this key. Check it and try again."
        if kind == "connection":
            if info(provider_id).get("local"):
                return False, "Could not reach Ollama. Install it from ollama.com and make sure it is running."
            return False, f"Could not reach {name} - check your internet connection" + (" and the server address." if base_url else ".")
        return False, f"Could not verify: {str(e)[:140]}"

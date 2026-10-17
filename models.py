# models.py — the models NOVA is currently using (for the active provider), kept in one place so they can
# be refreshed at runtime when a provider retires or renames a model.
import providers

MODEL_ORDER = ["smart", "fast", "mix"]
MODELS: dict[str, tuple] = {}            # slot -> (model id, short label); filled by activate()
VISION_MODELS: list[str] = []            # tried in order; unavailable ones are skipped
PREFERRED: dict[str, list[str]] = {}     # slot -> ids to fall back to when the configured one is gone
_state: dict[str, str | None] = {"provider": providers.DEFAULT_PROVIDER, "stt": None}

_NOT_CHAT = ("embed", "whisper", "tts", "guard", "moderation", "dall", "image", "audio", "realtime", "transcribe",
             "orpheus", "safeguard", "rerank")


def activate(provider_id: str, overrides: dict | None = None) -> None:
    """Switch every model slot to the given provider's defaults (+ the user's pinned ids)."""
    p = providers.info(provider_id)
    _state["provider"] = provider_id if provider_id in providers.PROVIDERS else providers.DEFAULT_PROVIDER
    _state["stt"] = p.get("stt")
    MODELS.clear(); MODELS.update({k: tuple(v) for k, v in p["models"].items()})
    PREFERRED.clear(); PREFERRED.update({k: list(v) for k, v in p.get("preferred", {}).items()})
    VISION_MODELS[:] = list(p.get("vision") or [])
    apply_overrides(overrides)


def provider() -> str:
    return _state["provider"] or providers.DEFAULT_PROVIDER


def fast_model_id() -> str:
    return MODELS["fast"][0]


def stt_model():
    """Speech-to-text model of the active provider, or None if it has none."""
    return _state["stt"]


def vision_models() -> list:
    """Models to try for images: the provider's vision list, else the current chat models."""
    return list(VISION_MODELS) or [MODELS["smart"][0], MODELS["mix"][0]]


def apply_overrides(overrides: dict | None) -> None:
    """config["models_by_provider"][provider] = {"smart": "model-id", ...} lets users pin their own models."""
    for key, mid in (overrides or {}).items():
        if key in MODELS and isinstance(mid, str) and mid.strip():
            MODELS[key] = (mid.strip(), MODELS[key][1])


def fetch_available(client) -> set:
    return providers.list_model_ids(client)


def chat_models(available) -> list:
    return sorted(m for m in available if not any(x in m.lower() for x in _NOT_CHAT))


def reconcile(available: set) -> list:
    """Replace configured models that no longer exist. Returns human-readable change notes."""
    notes: list[str] = []
    if not available:
        return notes
    for key, (mid, label) in list(MODELS.items()):
        if mid in available:
            continue
        taken = {v[0] for k, v in MODELS.items() if k != key}            # avoid two slots ending up with the same model
        cands = [c for c in PREFERRED.get(key, []) if c in available]
        if not cands:                                                     # e.g. Ollama: whatever is installed
            cands = [m for c in PREFERRED.get(key, []) for m in sorted(available) if m.startswith(c)] or chat_models(available)
        pick = next((c for c in cands if c not in taken), cands[0] if cands else None)
        if pick:
            MODELS[key] = (pick, label)
            notes.append(f"{label}: {mid or 'no model set'} is not available - using {pick}")
    live = [v for v in VISION_MODELS if v in available]
    if live and live != VISION_MODELS:
        VISION_MODELS[:] = live                       # in place: the vision worker holds a reference to this list
    return notes


activate(providers.DEFAULT_PROVIDER)

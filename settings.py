# settings.py — every setting NOVA understands, declared once: type, default, allowed values.
#
# `Settings` is a dict (so existing code keeps working) that
#   • always contains every declared key (defaults are filled in on load),
#   • repairs values of the wrong type / out of range instead of crashing later,
#   • catches typos: touching an undeclared key logs a warning with a "did you mean…" hint,
#     and raises immediately when NOVA_STRICT_CONFIG=1 (the test-suite sets this).
import os, copy, difflib, logging

log = logging.getLogger("nova")


class Field:
    def __init__(self, typ, default, choices=None, lo=None, hi=None, doc=""):
        self.typ, self.default, self.choices, self.lo, self.hi, self.doc = typ, default, choices, lo, hi, doc

    def clean(self, value):
        """Return (value, ok). Not ok => the caller should fall back to the default."""
        t = self.typ
        if t is bool:
            if isinstance(value, bool): return value, True
            if isinstance(value, (int, float)) and value in (0, 1): return bool(value), True
            return None, False
        if t is int:
            if isinstance(value, bool) or not isinstance(value, (int, float)): return None, False
            value = int(value)
            if self.lo is not None: value = max(self.lo, value)
            if self.hi is not None: value = min(self.hi, value)
            return value, True
        if t is str:
            if not isinstance(value, str): return None, False
            if self.choices and value not in self.choices: return None, False
            return value, True
        if t in (list, dict):
            return (value, True) if isinstance(value, t) else (None, False)
        return value, True


F = Field
SCHEMA = {
    # bookkeeping
    "schema":            F(int, 0, doc="settings-file format version (see paths.upgrade_config)"),
    "onboarded":         F(bool, False, doc="the first-run wizard was completed"),
    "seen_version":      F(str, "", doc="the NOVA version whose 'what's new' note was already shown"),
    "consent":           F(bool, False, doc="the user agreed to the data-handling summary"),
    "ax_prompted":       F(bool, False, doc="the Accessibility system prompt was already shown once"),
    # window
    "win_x": F(int, 40), "win_y": F(int, 80), "win_w": F(int, 370, lo=280, hi=4000), "win_h": F(int, 540, lo=200, hi=4000),
    "theme":             F(str, "auto", choices=("auto", "nova", "matrix", "ember", "soft")),
    "accent_color":      F(str, "", doc="custom accent as #rrggbb, empty = theme default"),
    "font_size":         F(int, 10, lo=8, hi=22),
    "ui_lang":           F(str, "auto", choices=("auto", "en", "bg")),
    "external_autosend": F(bool, False, doc="send requests that arrive from Shortcuts / `--ask` / nova:// links without waiting for Enter"),
    "selection_actions": F(bool, True, doc="⌃⇧Space acts on the text selected in any app (explain, translate, rewrite …)"),
    "selection_custom":  F(dict, {}, doc='your own ⌃⇧Space actions: {"Shorter": {"prompt": "Make this shorter:", "replace": true}}'),
    "selection_paste":   F(bool, False, doc="paste a rewrite / translation straight over the selection instead of only copying it"),
    # AI
    "provider":          F(str, "groq", choices=("groq", "anthropic", "openai", "ollama", "custom"), doc="which AI service answers"),
    "base_url":          F(str, "", doc="server address for the Ollama / custom provider, empty = default"),
    "keyless":           F(bool, False, doc="the provider works without a stored key (local server, or a signed-in CLI profile)"),
    "model_key":         F(str, "smart", choices=("smart", "fast", "mix")),
    "models":            F(dict, {}, doc='(Groq, legacy) pin model ids per slot, e.g. {"smart": "provider/model"}'),
    "models_by_provider": F(dict, {}, doc='pin model ids per provider: {"openai": {"smart": "…", "fast": "…"}}'),
    "reasoning":         F(str, "low", choices=("low", "medium", "high")),
    "suggest_followups": F(bool, False),
    "mode":              F(str, "default", doc="how NOVA behaves: default, coder, translator, tutor, writer, or one of custom_modes"),
    "custom_modes":      F(dict, {}, doc='your own modes: {"Lawyer": "instructions…"}'),
    "saved_prompts":     F(dict, {"tldr": "Summarize the following in three short bullet points:",
                                  "eli5": "Explain this in very simple words, as if to a child:",
                                  "fix": "Find and fix the problems in this code. Show the corrected code, then explain each fix in one line:"},
                           doc="reusable prompts: type /name in the message box"),
    "prices":            F(dict, {}, doc='your prices in USD per million tokens, for the cost estimate: {"model-id": [input, output]}'),
    "search_engine":     F(str, "ddg", choices=("ddg", "brave"), doc="ddg = DuckDuckGo (no key, unofficial); brave = Brave Search API (needs a key)"),
    # voice
    "tts":               F(bool, True), "tts_auto": F(bool, False),
    "tts_voice":         F(str, "en-US-AriaNeural"),
    "stt_lang":          F(str, "", doc="language hint for speech-to-text, empty = auto-detect"),
    "stt_engine":        F(str, "auto", choices=("auto", "cloud", "local"), doc="where speech is transcribed; local = on this Mac (English)"),
    "tts_engine":        F(str, "online", choices=("online", "system"), doc="online neural voices, or the built-in system voice (offline)"),
    "voice_auto_send":   F(bool, False), "voice_auto_stop": F(bool, True),
    "wake_word":         F(bool, False), "wake_thresh": F(int, 700, lo=200, hi=2000),
    "voice_barge_in":    F(bool, True, doc="in a voice conversation, talking over NOVA stops it and lets you speak"),
    # privacy & safety
    "save_history":      F(bool, True), "retention_days": F(int, 90, lo=0, hi=3650), "activity_days": F(int, 30, lo=0, hi=3650),
    "confirm_uploads":   F(bool, True), "confirm_memory": F(bool, False),
    "smart_memory":      F(bool, True, doc="ask the AI once per saved memory for search keywords, so memories are found by meaning"),
    "always_allow":      F(list, [], doc="approval keys the user chose 'always allow' for"),
    "plugins_allowed":   F(dict, {}), "plugins_denied": F(dict, {}),
    "mcp_servers":       F(dict, {}, doc='connected MCP tool servers: {"name": {"command": "npx", "args": [...], "env": {...}} | {"url": "https://…", "headers": {...}}}'),
    "encrypt_data":      F(bool, False, doc="chats, memories, notes and logs are stored encrypted (key in the Keychain)"),
    "crash_reports":     F(bool, False, doc="save a crash report (no chat content) when NOVA fails"),
    "crash_report_url":  F(str, "", doc="https address crash reports may be sent to - only ever after asking"),
    # misc
    "autostart":         F(bool, False),
    "start_hidden":      F(bool, True, doc="when started at login, stay in the menu bar instead of opening the window"),
    "shortcuts":         F(dict, {"work": ["chrome", "code", "spotify"]}, doc="word -> list of apps to open"),
    "home_city":         F(str, "", doc="used by the Weather quick command, empty = auto-detect"),
    "update_feed":       F(str, "", doc="https URL of the update feed JSON"),
    "auto_update":       F(str, "notify", choices=("off", "notify", "install"), doc="daily update check: off, tell me, or install by itself"),
    "update_checked":    F(str, "", doc="the day of the last automatic update check"),
}
LEGACY_KEYS = {"groq_api_key", "lang"}        # still tolerated in old files; removed by paths.upgrade_config


class Settings(dict):
    STRICT = False                             # set from the environment at import; tests turn it on

    def __init__(self, raw=None):
        super().__init__()
        self._warned = set()
        raw = dict(raw or {})
        for key, field in SCHEMA.items():
            if key in raw:
                value, ok = field.clean(raw.pop(key))
                if not ok:
                    log.warning("setting %r had an invalid value - using the default %r", key, field.default)
                    value = copy.deepcopy(field.default)
            else:
                value = copy.deepcopy(field.default)
            dict.__setitem__(self, key, value)
        for key, value in raw.items():         # keys we don't know: keep them (never destroy user data) but say so
            if key not in LEGACY_KEYS:
                log.warning("unknown setting %r in config.json%s", key, self._hint(key))
            dict.__setitem__(self, key, value)

    # ── typo detection ────────────────────────────────────────────
    @staticmethod
    def _hint(key):
        close = difflib.get_close_matches(key, SCHEMA.keys(), n=1)
        return f" - did you mean {close[0]!r}?" if close else ""

    def _check(self, key):
        if key in SCHEMA or key in LEGACY_KEYS or dict.__contains__(self, key):
            return
        msg = f"undeclared setting {key!r}{self._hint(key)} (declare it in settings.SCHEMA)"
        if Settings.STRICT:
            raise KeyError(msg)
        if key not in self._warned:
            self._warned.add(key); log.warning(msg)

    def __getitem__(self, key): self._check(key); return dict.__getitem__(self, key)
    def get(self, key, default=None): self._check(key); return dict.get(self, key, default)
    def setdefault(self, key, default=None): self._check(key); return dict.setdefault(self, key, default)
    def pop(self, key, *default): self._check(key); return dict.pop(self, key, *default)

    def __setitem__(self, key, value):
        self._check(key)
        field = SCHEMA.get(key)
        if field is not None:
            cleaned, ok = field.clean(value)
            if not ok:
                msg = f"invalid value {value!r} for setting {key!r}"
                if Settings.STRICT: raise ValueError(msg)
                log.warning("%s - keeping %r", msg, dict.get(self, key)); return
            value = cleaned
        dict.__setitem__(self, key, value)

    def update(self, *args, **kw):
        for k, v in dict(*args, **kw).items():
            self[k] = v

    def to_json(self) -> dict:
        """Plain dict for saving (never includes legacy secrets)."""
        return {k: v for k, v in self.items() if k != "groq_api_key"}


Settings.STRICT = os.environ.get("NOVA_STRICT_CONFIG") == "1"

# provider_openai.py — OpenAI and every server that speaks its chat-completions protocol
# (Ollama on this Mac, LM Studio, OpenRouter, a company gateway …).
#
# These servers agree on the basics but differ in small request details, and which model accepts
# what changes over time. Instead of hard-coding a table that goes stale, this client *learns*: when
# a server rejects a parameter it says so in the 400, we drop/rename that one parameter, retry once,
# and remember the answer for that model.
import logging
import ledger
from providers import _LazySDK

log = logging.getLogger("nova")


class _NS:
    def __init__(self, **kw): self.__dict__.update(kw)


class OpenAICompatClient(_LazySDK):
    def __init__(self, api_key: str, base_url: str | None = None, local: bool = False, http_client=None):
        self._args = (api_key, base_url, http_client)
        self.local = local
        self.host = ledger.host_of(base_url) if base_url else "api.openai.com"
        self.chat = _NS(completions=_NS(create=self._create))
        self.audio = _NS(transcriptions=_NS(create=self._transcribe))
        self._quirks: dict[str, set] = {}   # model id -> set of things this model/server does not accept

    def _make_sdk_client(self):
        import openai
        api_key, base_url, http_client = self._args
        kw = {"http_client": http_client} if http_client is not None else {}      # tests inject a simulated server
        # local models can take a while to load into memory on the first request
        return openai.OpenAI(api_key=api_key, base_url=base_url, timeout=300.0 if self.local else 60.0, max_retries=0, **kw)

    @property
    def _sdk(self):
        import openai
        return openai

    @property
    def models(self): return self._c.models

    def begin_request(self): pass

    # ── chat ──────────────────────────────────────────────────────
    def _shape(self, kw: dict) -> dict:
        kw = dict(kw)
        q = self._quirks.setdefault(kw.get("model", ""), set())
        kw.pop("reasoning_effort", None)                           # optional everywhere, rejected by many servers: not sent
        if "max_completion_tokens" in q and "max_tokens" in kw:
            kw["max_completion_tokens"] = kw.pop("max_tokens")
        if "no_temperature" in q: kw.pop("temperature", None)
        if "no_tools" in q: kw.pop("tools", None); kw.pop("tool_choice", None)
        if kw.get("stream") and "no_stream_options" not in q:
            kw["stream_options"] = {"include_usage": True}        # token counts on the final chunk
        return kw

    def _learn(self, model: str, message: str) -> bool:
        """Read a 400 and note what to change. True if there is something new to try."""
        q = self._quirks.setdefault(model, set()); low = message.lower(); before = set(q)
        if "max_completion_tokens" in low: q.add("max_completion_tokens")
        if "temperature" in low: q.add("no_temperature")
        if "stream_options" in low: q.add("no_stream_options")
        if "tool" in low and ("not support" in low or "unsupported" in low or "does not support" in low): q.add("no_tools")
        return q != before

    def _create(self, **kw):
        model = kw.get("model", "")
        import providers
        providers.note_chat(self.host, kw)
        for _ in range(4):                                          # each pass can fix one rejected parameter
            try:
                return providers.metered(self, kw, self._c.chat.completions.create(**self._shape(kw)))
            except self._sdk.BadRequestError as e:
                if not self._learn(model, str(e)):
                    raise
                log.info("%s: adapting request for %s (%s)", "local server" if self.local else "provider", model,
                         ", ".join(sorted(self._quirks[model])))
        return providers.metered(self, kw, self._c.chat.completions.create(**self._shape(kw)))

    def supports_tools(self, model: str) -> bool:
        return "no_tools" not in self._quirks.get(model, set())

    # ── speech-to-text (OpenAI has it; most local servers don't) ──
    def _transcribe(self, **kw):
        return self._c.audio.transcriptions.create(**kw)

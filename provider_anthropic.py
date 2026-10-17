# provider_anthropic.py — Claude, through the official Anthropic SDK (Messages API).
#
# NOVA's worker speaks the OpenAI chat-completions shape; this adapter translates both ways:
#   request   system/user/assistant/tool messages + function tools  ->  system blocks, content blocks, tool definitions
#   response  Claude's event stream                                 ->  OpenAI-style chunks (delta.content / delta.tool_calls)
#
# Things that are specific to current Claude models and handled here on purpose:
#   • Thinking is always on for the newest models and its depth is set with `output_config.effort`
#     (NOVA's "Thinking: Fast / Balanced / Deep" setting). Sampling parameters are not sent.
#   • Thinking blocks must go back *unchanged* while a tool call is waiting for its result, so the raw
#     assistant turn is kept for the duration of one request's tool loop and replayed verbatim.
#     Older turns are sent without thinking blocks (NOVA rebuilds its prompt and trims history between
#     requests, which would invalidate them), and `prefix_mismatch_behavior: "drop_block"` makes any
#     leftover mismatch degrade gracefully instead of failing the request.
#   • Safety classifiers can decline a request (`stop_reason: "refusal"`). Server-side fallbacks are
#     switched on so a false positive is retried on another model instead of becoming an error.
#   • Tool inputs stream as they are generated (`eager_input_streaming`); NOVA validates every tool
#     call against its schema before running it and never runs a truncated or refused turn's tools.
#   • Prompt caching: the stable part of the system prompt (plus the tool list in front of it) gets a
#     cache breakpoint; the growing conversation uses automatic caching.
import json, logging
from providers import ProviderError, _LazySDK


def _anthropic():
    import anthropic                                   # 0.35 s: imported on first use, not at start-up
    return anthropic

log = logging.getLogger("nova")

BETA_FALLBACK = "server-side-fallback-2026-07-01"          # `fallbacks: "default"`
BETA_BINDING  = "thinking-binding-controls-2026-08-01"     # `thinking.block_binding`
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
STREAM_MAX_TOKENS  = 64000        # thinking counts toward max_tokens, so leave real room
UTILITY_MAX_TOKENS = 16000        # short helper calls (summaries, suggestions)
VOLATILE_MARK = "\n\nCURRENT DATE & TIME:"                 # everything from here on changes per request
EFFORTS = ("low", "medium", "high")
_FINISH = {"end_turn": "stop", "stop_sequence": "stop", "pause_turn": "stop", "tool_use": "tool_calls",
           "max_tokens": "length", "refusal": "content_filter"}


class _NS:
    def __init__(self, **kw): self.__dict__.update(kw)


def _chunk(content=None, tool_calls=None, finish_reason=None, usage=None):
    c = _NS(choices=[_NS(delta=_NS(content=content, tool_calls=tool_calls), finish_reason=finish_reason)])
    if usage is not None: c.usage = usage
    return c


def _tc(index, id_, name, args):
    return _NS(index=index, id=id_, function=_NS(name=name, arguments=args))


def _btype(block):
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)


def _bget(block, key):
    return block.get(key) if isinstance(block, dict) else getattr(block, key, None)


class AnthropicClient(_LazySDK):
    def __init__(self, api_key: str | None = None, http_client=None):
        # No key given -> the SDK resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile.
        # max_retries=0: NOVA's worker decides what to do on a rate limit (switch to the fast model at once).
        self._kw: dict = {"max_retries": 0}
        if api_key: self._kw["api_key"] = api_key
        if http_client is not None: self._kw["http_client"] = http_client    # tests inject a simulated server
        self.chat = _NS(completions=_NS(create=self._create))
        self.audio = None                                   # Claude has no speech-to-text endpoint
        self.models = _NS(list=self._list_models)
        self._raw_turns = {}        # first tool_use id -> the assistant turn's content blocks, exactly as received
        self._caps = {}             # model id -> capabilities
        self._betas_ok = True       # switched off if this organisation rejects a beta header

    # ── hooks used by the worker ──────────────────────────────────
    def _make_sdk_client(self):
        return _anthropic().Anthropic(**self._kw)

    @property
    def _client(self): return self._c

    def begin_request(self):
        """A new user request starts: thinking blocks from the previous tool loop are no longer replayed."""
        self._raw_turns.clear()

    def _list_models(self):
        return _NS(data=[_NS(id=m.id) for m in self._client.models.list()])      # iterating the page auto-paginates

    # ── model capabilities (asked once per model) ─────────────────
    def capabilities(self, model: str) -> _NS:
        if model in self._caps: return self._caps[model]
        legacy = "haiku" in model                           # safe guess if the lookup fails
        caps = _NS(adaptive=not legacy, effort=set() if legacy else set(EFFORTS), max_out=STREAM_MAX_TOKENS, vision=True)
        try:
            m = self._client.models.retrieve(model)
            c = m.capabilities                              # untyped nested dict: bracket access, ["supported"] at the leaf
            caps.adaptive = bool(c["thinking"]["types"]["adaptive"]["supported"])
            caps.effort = {lvl for lvl in EFFORTS if c["effort"]["supported"] and c["effort"][lvl]["supported"]}
            caps.vision = bool(c["image_input"]["supported"])
            caps.max_out = int(m.max_tokens)
        except Exception as e:
            log.info("could not read capabilities of %s (%s) - using defaults", model, type(e).__name__)
        self._caps[model] = caps
        return caps

    # ── request building ──────────────────────────────────────────
    @staticmethod
    def _tool(t: dict) -> dict:
        f = t.get("function", t)
        return {"name": f["name"], "description": f.get("description", ""),
                "input_schema": f.get("parameters") or {"type": "object", "properties": {}},
                "eager_input_streaming": True}

    @staticmethod
    def _user_blocks(content) -> list:
        if isinstance(content, str):
            return [{"type": "text", "text": content}] if content.strip() else []
        blocks = []
        for part in content or []:
            if part.get("type") == "text" and part.get("text", "").strip():
                blocks.append({"type": "text", "text": part["text"]})
            elif part.get("type") == "image_url":
                url = part["image_url"]["url"]
                if url.startswith("data:"):
                    head, data = url.split(",", 1)
                    blocks.append({"type": "image", "source": {"type": "base64",
                                                                "media_type": head[5:].split(";")[0] or "image/jpeg", "data": data}})
                else:
                    blocks.append({"type": "image", "source": {"type": "url", "url": url}})
        return blocks

    @staticmethod
    def _tool_result(m: dict) -> dict:
        """NOVA stores tool results as {"ok": …, "result"/"error": …}; Claude gets the text plus `is_error`."""
        text = m.get("content", "") or ""
        block = {"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""), "content": text}
        try:
            d = json.loads(text)
            if isinstance(d, dict) and "ok" in d:
                if d["ok"]:
                    block["content"] = str(d.get("result", ""))
                else:
                    block["content"] = str(d.get("error", "")); block["is_error"] = True
        except ValueError:
            pass
        if not block["content"]: block["content"] = "(no output)"
        return block

    def _convert(self, messages: list):
        """OpenAI-style history -> (system blocks, Anthropic messages)."""
        i = 0; system_texts = []
        while i < len(messages) and messages[i].get("role") == "system":
            if isinstance(messages[i].get("content"), str): system_texts.append(messages[i]["content"])
            i += 1
        system = []
        if system_texts:
            head = system_texts[0]
            stable, sep, volatile = head.partition(VOLATILE_MARK)
            system.append({"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}})   # tools + stable prompt cached
            tail = "\n\n".join(([(sep + volatile).strip()] if sep else []) + system_texts[1:])
            if tail.strip(): system.append({"type": "text", "text": tail})

        out = []
        def add(role, blocks):
            if not blocks: return
            if out and out[-1]["role"] == role and role == "user":
                out[-1]["content"].extend(blocks)             # tool results of one round belong in ONE user message
            else:
                out.append({"role": role, "content": list(blocks)})

        for m in messages[i:]:
            role = m.get("role")
            if role == "user":
                add("user", self._user_blocks(m.get("content")))
            elif role == "system":                             # a note in the middle of the chat: keep it as plain context
                if isinstance(m.get("content"), str) and m["content"].strip():
                    add("user", [{"type": "text", "text": "[Note] " + m["content"]}])
            elif role == "tool":
                add("user", [self._tool_result(m)])
            elif role == "assistant":
                tcs = m.get("tool_calls") or []
                raw = self._raw_turns.get(tcs[0]["id"]) if tcs else None
                if raw is not None:
                    blocks = list(raw)                         # verbatim, thinking blocks included
                else:
                    blocks = []
                    if isinstance(m.get("content"), str) and m["content"].strip():
                        blocks.append({"type": "text", "text": m["content"]})
                    for tc in tcs:
                        try: args = json.loads(tc["function"].get("arguments") or "{}")
                        except ValueError: args = {}
                        blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                                       "input": args if isinstance(args, dict) else {}})
                if blocks: out.append({"role": "assistant", "content": blocks})
        return system, self._repair(out)

    @staticmethod
    def _repair(msgs: list) -> list:
        """Guarantee what the API requires: starts with a user turn, every tool_use is answered in the next
        user message, and no tool_result is left without its tool_use."""
        fixed = []
        for idx, m in enumerate(msgs):
            blocks = m["content"]
            if m["role"] == "assistant":
                nxt = msgs[idx + 1]["content"] if idx + 1 < len(msgs) and msgs[idx + 1]["role"] == "user" else []
                answered = {_bget(b, "tool_use_id") for b in nxt if _btype(b) == "tool_result"}
                blocks = [b for b in blocks if _btype(b) != "tool_use" or _bget(b, "id") in answered]
            else:
                prev = fixed[-1]["content"] if fixed and fixed[-1]["role"] == "assistant" else []
                asked = {_bget(b, "id") for b in prev if _btype(b) == "tool_use"}
                blocks = [b for b in blocks if _btype(b) != "tool_result" or _bget(b, "tool_use_id") in asked]
            if blocks: fixed.append({"role": m["role"], "content": blocks})
        while fixed and fixed[0]["role"] != "user": fixed.pop(0)
        return fixed

    def _request(self, kw: dict, utility: bool):
        model = kw["model"]; caps = self.capabilities(model)
        system, messages = self._convert(kw["messages"])
        req = {"model": model, "messages": messages,
               "max_tokens": min(UTILITY_MAX_TOKENS if utility else STREAM_MAX_TOKENS, caps.max_out),
               "cache_control": {"type": "ephemeral"}}       # automatic caching for the growing conversation
        if system: req["system"] = system
        if kw.get("tools"): req["tools"] = [self._tool(t) for t in kw["tools"]]      # tool_choice stays "auto" (the default)
        effort = kw.get("reasoning_effort")
        if effort in caps.effort: req["output_config"] = {"effort": effort}
        betas = []
        if caps.adaptive:
            req["thinking"] = {"type": "adaptive"}
            if self._betas_ok:
                req["thinking"]["block_binding"] = {"prefix_mismatch_behavior": "drop_block"}
                betas.append(BETA_BINDING)
        if model in FALLBACK_MODELS and self._betas_ok:
            req["fallbacks"] = "default"; betas.append(BETA_FALLBACK)
        return req, betas

    def _open(self, req: dict, betas: list):
        if betas:
            return self._client.beta.messages.stream(betas=betas, **req)
        return self._client.messages.stream(**req)

    def _beta_rejected(self, exc: Exception, betas: list) -> bool:
        """An organisation without access to a beta gets a 400 naming the header or the field."""
        low = str(exc).lower()
        if betas and ("anthropic-beta" in low or "block_binding" in low or "fallbacks" in low):
            self._betas_ok = False
            log.warning("Anthropic rejected a beta option (%s) - continuing without fallbacks / block binding", str(exc)[:160])
            return True
        return False

    # ── the one entry point ───────────────────────────────────────
    host = "api.anthropic.com"

    def _create(self, **kw):
        import providers
        providers.note_chat(self.host, kw)
        if kw.get("stream"):
            return providers.metered(self, kw, self._stream(kw))
        return providers.metered(self, kw, self._complete(kw))

    def _complete(self, kw: dict):
        for attempt in (1, 2):
            req, betas = self._request(kw, utility=True)
            try:
                with self._open(req, betas) as stream:        # streaming under the hood: no HTTP timeout on long answers
                    final = stream.get_final_message()
                break
            except _anthropic().BadRequestError as e:
                if attempt == 1 and self._beta_rejected(e, betas): continue
                raise
        refused = final.stop_reason == "refusal"
        text = "" if refused else "".join(b.text for b in final.content if b.type == "text")
        return _NS(choices=[_NS(message=_NS(content=text), finish_reason=_FINISH.get(final.stop_reason, "stop"))],
                   usage=self._usage(final))

    @staticmethod
    def _usage(final) -> _NS:
        u = final.usage
        prompt = (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0)
        return _NS(prompt_tokens=prompt, completion_tokens=u.output_tokens or 0,
                   cached_tokens=getattr(u, "cache_read_input_tokens", 0) or 0)

    @staticmethod
    def _echoable(content: list) -> list:
        """The blocks to send back next round. After a server-side fallback, only text survives from before
        the switch (the declined model's thinking / tool_use must not be echoed)."""
        last = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
        if last < 0: return list(content)
        return [b for b in content[:last] if b.type == "text"] + [b for b in content[last + 1:] if b.type != "fallback"]

    def _stream(self, kw: dict):
        for attempt in (1, 2):
            req, betas = self._request(kw, utility=False)
            started = False
            try:
                with self._open(req, betas) as stream:
                    tool_at = {}; n = 0                         # content-block index -> tool-call number
                    for event in stream:
                        started = True
                        if event.type == "content_block_start" and event.content_block.type == "tool_use":
                            tool_at[event.index] = n
                            yield _chunk(tool_calls=[_tc(n, event.content_block.id, event.content_block.name, "")]); n += 1
                        elif event.type == "content_block_delta":
                            d = event.delta
                            if d.type == "text_delta" and d.text:
                                yield _chunk(content=d.text)
                            elif d.type == "input_json_delta" and event.index in tool_at and d.partial_json:
                                yield _chunk(tool_calls=[_tc(tool_at[event.index], None, None, d.partial_json)])
                    final = stream.get_final_message()
            except _anthropic().BadRequestError as e:
                if attempt == 1 and not started and self._beta_rejected(e, betas): continue
                raise
            except ValueError as e:
                # the SDK could not parse a tool input at all: there is no tool_use block to answer, so the
                # worker re-issues this round (bounded by its retry count)
                raise ProviderError("tool_json", f"The model produced an unreadable tool call ({e}).")
            break

        blocks = self._echoable(final.content)
        tool_ids = [b.id for b in blocks if b.type == "tool_use"]
        if tool_ids and final.stop_reason == "tool_use":
            if len(self._raw_turns) > 64: self._raw_turns.clear()
            self._raw_turns[tool_ids[0]] = blocks              # replayed verbatim while its results are pending
        if final.model and final.model != req["model"]:
            log.info("request to %s was served by %s (safety fallback)", req["model"], final.model)
        dropped = [t for t in (getattr(final, "input_transformations", None) or []) if _bget(t, "type") == "thinking_dropped"]
        if dropped:
            log.info("%d thinking block(s) were dropped by the API (%s)", len(dropped), _bget(dropped[0], "reason"))
        last = _chunk(finish_reason=_FINISH.get(final.stop_reason, "stop"), usage=self._usage(final))
        if final.stop_reason == "refusal":
            last.refusal_category = getattr(final.stop_details, "category", None) if final.stop_details else None
        yield last

"""The provider adapters, exercised through the real SDKs against a simulated HTTP server."""
import json
import pytest
import providers, models

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")
from provider_anthropic import AnthropicClient, BETA_BINDING, BETA_FALLBACK

CAPS = {"image_input": {"supported": True}, "structured_outputs": {"supported": True},
        "thinking": {"supported": True, "types": {"enabled": {"supported": False}, "adaptive": {"supported": True}}},
        "effort": {"supported": True, "low": {"supported": True}, "medium": {"supported": True}, "high": {"supported": True},
                   "xhigh": {"supported": True}, "max": {"supported": True}}}
HAIKU_CAPS = {"image_input": {"supported": True}, "structured_outputs": {"supported": True},
              "thinking": {"supported": True, "types": {"enabled": {"supported": True}, "adaptive": {"supported": False}}},
              "effort": {"supported": False, "low": {"supported": False}, "medium": {"supported": False}, "high": {"supported": False},
                         "xhigh": {"supported": False}, "max": {"supported": False}}}


def sse(*events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def message_events(model, blocks, stop_reason="end_turn", usage_in=120, usage_out=30):
    """A full SSE transcript for one assistant message made of `blocks`."""
    ev = [{"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
                                                "content": [], "stop_reason": None, "stop_sequence": None,
                                                "usage": {"input_tokens": usage_in, "output_tokens": 1}}}]
    for i, b in enumerate(blocks):
        if b["type"] == "text":
            ev.append({"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
            for piece in b["chunks"]:
                ev.append({"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": piece}})
        elif b["type"] == "thinking":
            ev.append({"type": "content_block_start", "index": i, "content_block": {"type": "thinking", "thinking": "", "signature": ""}})
            ev.append({"type": "content_block_delta", "index": i, "delta": {"type": "signature_delta", "signature": b["signature"]}})
        elif b["type"] == "tool_use":
            ev.append({"type": "content_block_start", "index": i,
                       "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}})
            for piece in b["json_chunks"]:
                ev.append({"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": piece}})
        ev.append({"type": "content_block_stop", "index": i})
    ev.append({"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None}, "usage": {"output_tokens": usage_out}})
    ev.append({"type": "message_stop"})
    return sse(*ev)


class Server:
    """Records every request and answers from a queue of canned responses."""
    def __init__(self): self.requests = []; self.queue = []; self.caps = {}
    def handler(self, request):
        path = request.url.path
        if path.startswith("/v1/models/"):
            mid = path.rsplit("/", 1)[-1]
            return httpx2.Response(200, json={"id": mid, "type": "model", "display_name": mid, "created_at": "2026-01-01T00:00:00Z",
                                              "max_input_tokens": 1000000, "max_tokens": 128000 if "haiku" not in mid else 64000,
                                              "capabilities": self.caps.get(mid, CAPS)})
        if path == "/v1/models":
            return httpx2.Response(200, json={"data": [{"id": "claude-opus-5-5", "type": "model", "display_name": "x", "created_at": "2026-01-01T00:00:00Z"},
                                                       {"id": "claude-haiku-4-5", "type": "model", "display_name": "y", "created_at": "2026-01-01T00:00:00Z"}],
                                              "has_more": False, "first_id": "claude-opus-5-5", "last_id": "claude-haiku-4-5"})
        body = json.loads(request.content); self.requests.append((dict(request.headers), body))
        resp = self.queue.pop(0)
        if isinstance(resp, tuple):                                   # (status, json) error
            return httpx2.Response(resp[0], json=resp[1], headers={"retry-after": "7"} if resp[0] == 429 else {})
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=resp)


@pytest.fixture
def claude():
    server = Server()
    client = AnthropicClient("sk-ant-test", http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(server.handler)))
    return client, server


TOOLS = [{"type": "function", "function": {"name": "get_weather", "description": "Weather",
                                           "parameters": {"type": "object", "properties": {"location": {"type": "string"}}, "required": []}}}]
SYSTEM = "You are NOVA.\n\nCURRENT DATE & TIME: Wednesday 10:00\n\nLONG-TERM MEMORY:\n• likes tea"


def collect(stream):
    text, calls, finish, usage, last = "", {}, None, None, None
    for ch in stream:
        last = ch; c = ch.choices[0]
        if c.delta.content: text += c.delta.content
        for tc in c.delta.tool_calls or []:
            d = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
            if tc.id: d["id"] = tc.id
            if tc.function.name: d["name"] += tc.function.name
            if tc.function.arguments: d["args"] += tc.function.arguments
        if c.finish_reason: finish = c.finish_reason
        if getattr(ch, "usage", None): usage = ch.usage
    return text, calls, finish, usage, last


def test_request_shape_for_the_default_claude_model(claude):
    client, server = claude
    server.queue.append(message_events("claude-opus-5-5", [{"type": "text", "chunks": ["Hel", "lo"]}]))
    text, calls, finish, usage, _ = collect(client.chat.completions.create(
        model="claude-opus-5-5", stream=True, max_tokens=900, temperature=0.7, reasoning_effort="low", tools=TOOLS, tool_choice="auto",
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": "hi"}]))
    assert text == "Hello" and not calls and finish == "stop" and usage.prompt_tokens == 120 and usage.completion_tokens == 30
    headers, body = server.requests[0]
    assert body["model"] == "claude-opus-5-5" and body["stream"] is True
    assert body["max_tokens"] == 64000                               # room for thinking, not NOVA's small text budget
    assert "temperature" not in body and "tool_choice" not in body   # sampling params / forced tools are rejected by this model
    assert body["thinking"] == {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
    assert body["output_config"] == {"effort": "low"}
    assert body["fallbacks"] == "default"
    assert BETA_BINDING in headers["anthropic-beta"] and BETA_FALLBACK in headers["anthropic-beta"]
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["system"][0] == {"type": "text", "text": "You are NOVA.", "cache_control": {"type": "ephemeral"}}   # stable part cached
    assert "CURRENT DATE & TIME" in body["system"][1]["text"] and "cache_control" not in body["system"][1]
    assert body["tools"] == [{"name": "get_weather", "description": "Weather", "eager_input_streaming": True,
                              "input_schema": TOOLS[0]["function"]["parameters"]}]
    assert body["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def test_tool_loop_replays_thinking_blocks_unchanged_and_marks_errors(claude):
    client, server = claude
    server.queue.append(message_events("claude-opus-5-5", [
        {"type": "thinking", "signature": "SIG-ABC"},
        {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "json_chunks": ['{"loca', 'tion": "Sofia"}']},
        {"type": "tool_use", "id": "toolu_2", "name": "get_weather", "json_chunks": ['{"location": "Mars"}']}], stop_reason="tool_use"))
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "weather?"}]
    text, calls, finish, _, _ = collect(client.chat.completions.create(model="claude-opus-5-5", stream=True, messages=msgs, tools=TOOLS))
    assert finish == "tool_calls" and calls[0] == {"id": "toolu_1", "name": "get_weather", "args": '{"location": "Sofia"}'}
    assert calls[1]["id"] == "toolu_2" and json.loads(calls[1]["args"]) == {"location": "Mars"}
    # what NOVA's worker appends, then the next round:
    msgs.append({"role": "assistant", "content": "", "tool_calls": [
        {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["args"]}} for c in calls.values()]})
    msgs.append({"role": "tool", "tool_call_id": "toolu_1", "content": json.dumps({"ok": True, "result": "Sofia: +12°C"})})
    msgs.append({"role": "tool", "tool_call_id": "toolu_2", "content": json.dumps({"ok": False, "error": "Unknown place"})})
    server.queue.append(message_events("claude-opus-5-5", [{"type": "text", "chunks": ["12°C in Sofia."]}]))
    text, _, finish, _, _ = collect(client.chat.completions.create(model="claude-opus-5-5", stream=True, messages=msgs, tools=TOOLS))
    assert text == "12°C in Sofia." and finish == "stop"
    sent = server.requests[1][1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    a = sent[1]["content"]
    assert a[0]["type"] == "thinking" and a[0]["signature"] == "SIG-ABC"          # replayed verbatim while results were pending
    assert [b["type"] for b in a] == ["thinking", "tool_use", "tool_use"] and a[1]["input"] == {"location": "Sofia"}
    results = sent[2]["content"]                                                   # both results in ONE user message
    assert results[0] == {"type": "tool_result", "tool_use_id": "toolu_1", "content": "Sofia: +12°C"}
    assert results[1] == {"type": "tool_result", "tool_use_id": "toolu_2", "content": "Unknown place", "is_error": True}


def test_a_new_request_does_not_replay_old_thinking(claude):
    client, server = claude
    server.queue.append(message_events("claude-opus-5-5", [
        {"type": "thinking", "signature": "OLD"}, {"type": "tool_use", "id": "toolu_9", "name": "get_weather", "json_chunks": ["{}"]}], stop_reason="tool_use"))
    collect(client.chat.completions.create(model="claude-opus-5-5", stream=True, messages=[{"role": "user", "content": "a"}], tools=TOOLS))
    client.begin_request()                                                          # the user sent a new message
    history = [{"role": "user", "content": "a"},
               {"role": "assistant", "content": "", "tool_calls": [{"id": "toolu_9", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "toolu_9", "content": json.dumps({"ok": True, "result": "sunny"})},
               {"role": "assistant", "content": "Sunny."}, {"role": "user", "content": "thanks"}]
    server.queue.append(message_events("claude-opus-5-5", [{"type": "text", "chunks": ["ok"]}]))
    collect(client.chat.completions.create(model="claude-opus-5-5", stream=True, messages=history, tools=TOOLS))
    blocks = [b["type"] for m in server.requests[1][1]["messages"] for b in m["content"]]
    assert "thinking" not in blocks and blocks == ["text", "tool_use", "tool_result", "text", "text"]


def test_history_is_repaired_into_a_valid_conversation(claude):
    client, _ = claude
    _, msgs = client._convert([
        {"role": "assistant", "content": "leftover from a trimmed history"},
        {"role": "tool", "tool_call_id": "orphan", "content": "x"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "get_weather", "arguments": "not json"}}]},
        {"role": "user", "content": "never mind"}])
    assert msgs[0]["role"] == "user"                                   # must start with the user
    flat = [(m["role"], b["type"]) for m in msgs for b in m["content"]]
    assert ("assistant", "tool_use") not in flat and ("user", "tool_result") not in flat      # unanswered call / orphan result removed


def test_smaller_model_gets_no_effort_and_no_adaptive_thinking(claude):
    client, server = claude
    server.caps["claude-haiku-4-5"] = HAIKU_CAPS
    server.queue.append(message_events("claude-haiku-4-5", [{"type": "text", "chunks": ["hi"]}]))
    collect(client.chat.completions.create(model="claude-haiku-4-5", stream=True, reasoning_effort="high",
                                           messages=[{"role": "user", "content": "hi"}]))
    headers, body = server.requests[0]
    assert "thinking" not in body and "output_config" not in body and "fallbacks" not in body
    assert "anthropic-beta" not in headers and body["max_tokens"] == 64000


def test_refusal_and_truncation_are_reported_not_hidden(claude):
    client, server = claude
    server.queue.append(message_events("claude-opus-5-5", [], stop_reason="refusal"))
    *_, finish, _, last = collect(client.chat.completions.create(model="claude-opus-5-5", stream=True, messages=[{"role": "user", "content": "x"}]))
    assert finish == "content_filter"
    server.queue.append(message_events("claude-opus-5-5", [{"type": "tool_use", "id": "t", "name": "get_weather", "json_chunks": ['{"loc']}], stop_reason="max_tokens"))
    *_, finish, _, _ = collect(client.chat.completions.create(model="claude-opus-5-5", stream=True, messages=[{"role": "user", "content": "x"}], tools=TOOLS))
    assert finish == "length"                                          # the worker refuses to run a cut-off tool call


def test_beta_rejection_degrades_to_a_plain_request(claude):
    client, server = claude
    server.queue.append((400, {"type": "error", "error": {"type": "invalid_request_error",
                                                           "message": "Unexpected value(s) `x` for the `anthropic-beta` header."}}))
    server.queue.append(message_events("claude-opus-5-5", [{"type": "text", "chunks": ["fine"]}]))
    text, *_ = collect(client.chat.completions.create(model="claude-opus-5-5", stream=True, messages=[{"role": "user", "content": "x"}]))
    assert text == "fine"
    headers, body = server.requests[1]
    assert "anthropic-beta" not in headers and "fallbacks" not in body and body["thinking"] == {"type": "adaptive"}


def test_errors_are_classified_from_typed_exceptions(claude):
    client, server = claude
    server.queue.append((429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}))
    with pytest.raises(Exception) as e:
        collect(client.chat.completions.create(model="claude-opus-5-5", stream=True, messages=[{"role": "user", "content": "x"}]))
    assert providers.classify_error(e.value) == ("rate_limit", 7.0)
    server.queue.append((401, {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}))
    with pytest.raises(Exception) as e:
        collect(client.chat.completions.create(model="claude-opus-5-5", stream=True, messages=[{"role": "user", "content": "x"}]))
    assert providers.classify_error(e.value)[0] == "auth"
    assert providers.classify_error(Exception("Error code: 429 - rate_limit_exceeded. Please try again in 1m3.5s")) == ("rate_limit", 63.5)
    assert providers.classify_error(providers.ProviderError("tool_json", "x"))[0] == "tool_json"


def test_images_and_helper_calls(claude):
    client, server = claude
    server.queue.append(message_events("claude-opus-5-5", [{"type": "text", "chunks": ["a red square"]}]))
    r = client.chat.completions.create(model="claude-opus-5-5", max_tokens=300, messages=[{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}, {"type": "text", "text": "what is this?"}]}])
    assert r.choices[0].message.content == "a red square"
    body = server.requests[0][1]
    assert body["messages"][0]["content"][0] == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}
    assert body["max_tokens"] == 16000 and "tools" not in body
    assert providers.list_model_ids(client) == {"claude-opus-5-5", "claude-haiku-4-5"}


def test_provider_registry_and_model_slots():
    try:
        models.activate("anthropic")
        assert models.MODELS["smart"][0] == "claude-opus-5-5" and models.fast_model_id() == "claude-haiku-4-5"
        assert models.stt_model() is None and "claude-opus-5-5" in models.vision_models()
        models.activate("ollama")
        notes = models.reconcile({"qwen2.5:14b", "nomic-embed-text"})
        assert models.MODELS["smart"][0] == "qwen2.5:14b" and notes               # picks an installed chat model, not the embedder
        models.activate("openai", {"smart": "my-model"})
        assert models.MODELS["smart"][0] == "my-model" and models.stt_model() == "whisper-1"
    finally:
        models.activate("groq")
    with pytest.raises(providers.ProviderError):
        providers.make_client("groq", "")                                          # a required key is missing
    with pytest.raises(providers.ProviderError):
        providers.make_client("custom", "", "")                                    # custom needs a server address


# ── OpenAI-compatible servers (OpenAI, Ollama, LM Studio, gateways) ──
openai = pytest.importorskip("openai")
from provider_openai import OpenAICompatClient


def _oa_http():
    import importlib
    return importlib.import_module("httpx2" if "httpx2" in openai._base_client.__dict__ else "httpx")


def _oa_sse(chunks):
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _oa_chunk(content=None, tool_calls=None, finish=None, usage=None):
    c = {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "m",
         "choices": [{"index": 0, "delta": {k: v for k, v in (("content", content), ("tool_calls", tool_calls)) if v is not None},
                      "finish_reason": finish}]}
    if usage: c["usage"] = usage; c["choices"] = []
    return c


class OAServer:
    def __init__(self): self.requests = []; self.queue = []
    def handler(self, request):
        http = _oa_http()
        if request.url.path.endswith("/models"):
            return http.Response(200, json={"object": "list", "data": [{"id": "llama3.1:8b", "object": "model", "created": 1, "owned_by": "x"}]})
        self.requests.append(json.loads(request.content))
        r = self.queue.pop(0)
        if isinstance(r, tuple): return http.Response(r[0], json=r[1])
        return http.Response(200, headers={"content-type": "text/event-stream"}, content=r)


@pytest.fixture
def compat():
    server = OAServer(); http = _oa_http()
    client = OpenAICompatClient("k", "http://localhost:11434/v1", local=True,
                                http_client=openai.DefaultHttpxClient(transport=http.MockTransport(server.handler)))
    return client, server


def test_openai_compatible_stream_and_usage(compat):
    client, server = compat
    server.queue.append(_oa_sse([_oa_chunk(content="Hel"), _oa_chunk(content="lo"),
                                 _oa_chunk(tool_calls=[{"index": 0, "id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": "{\"location\""}}]),
                                 _oa_chunk(tool_calls=[{"index": 0, "function": {"arguments": ": \"Sofia\"}"}}]),
                                 _oa_chunk(finish="tool_calls"), _oa_chunk(usage={"prompt_tokens": 50, "completion_tokens": 9, "total_tokens": 59})]))
    text, calls, finish, usage, _ = collect_oa(client.chat.completions.create(
        model="llama3.1:8b", stream=True, max_tokens=900, temperature=0.7, reasoning_effort="low", tools=TOOLS, tool_choice="auto",
        messages=[{"role": "user", "content": "hi"}]))
    assert text == "Hello" and calls[0] == {"id": "call_1", "name": "get_weather", "args": '{"location": "Sofia"}'} and finish == "tool_calls"
    assert usage.prompt_tokens == 50
    body = server.requests[0]
    assert "reasoning_effort" not in body and body["stream_options"] == {"include_usage": True} and body["max_tokens"] == 900
    assert providers.list_model_ids(client) == {"llama3.1:8b"}


def collect_oa(stream):
    text, calls, finish, usage = "", {}, None, None
    for ch in stream:
        if getattr(ch, "usage", None): usage = ch.usage
        if not ch.choices: continue
        c = ch.choices[0]
        if c.delta.content: text += c.delta.content
        for tc in c.delta.tool_calls or []:
            d = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
            if tc.id: d["id"] = tc.id
            if tc.function and tc.function.name: d["name"] += tc.function.name
            if tc.function and tc.function.arguments: d["args"] += tc.function.arguments
        if c.finish_reason: finish = c.finish_reason
    return text, calls, finish, usage, None


def test_openai_compatible_learns_from_rejections(compat):
    client, server = compat
    err = lambda m: (400, {"error": {"message": m, "type": "invalid_request_error"}})
    server.queue += [err("Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."),
                     err("Unsupported value: 'temperature' does not support 0.7 with this model."),
                     err("registry.ollama.ai/library/gemma does not support tools"),
                     _oa_sse([_oa_chunk(content="ok"), _oa_chunk(finish="stop")])]
    text, *_ = collect_oa(client.chat.completions.create(model="m", stream=True, max_tokens=900, temperature=0.7, tools=TOOLS,
                                                        tool_choice="auto", messages=[{"role": "user", "content": "hi"}]))
    assert text == "ok"
    last = server.requests[-1]
    assert last["max_completion_tokens"] == 900 and "max_tokens" not in last and "temperature" not in last and "tools" not in last
    assert not client.supports_tools("m")
    server.queue.append(_oa_sse([_oa_chunk(content="again"), _oa_chunk(finish="stop")]))           # remembered: no more failed attempts
    collect_oa(client.chat.completions.create(model="m", stream=True, max_tokens=900, temperature=0.7, tools=TOOLS, messages=[{"role": "user", "content": "x"}]))
    assert len(server.requests) == 5 and "tools" not in server.requests[-1]


def test_openai_compatible_real_errors_still_surface(compat):
    client, server = compat
    server.queue.append((400, {"error": {"message": "context length exceeded", "type": "invalid_request_error"}}))
    with pytest.raises(Exception) as e:
        collect_oa(client.chat.completions.create(model="m", stream=True, messages=[{"role": "user", "content": "x"}]))
    assert providers.classify_error(e.value)[0] == "bad_request" and len(server.requests) == 1

# chatutil.py — message-list helpers shared by the workers and the window.
import os, json

from mdrender import _strip_think

def _safe_tail(msgs: list, n: int) -> list:
    """Last n messages, never starting on an orphaned `tool` result (the API rejects those)."""
    tail = msgs[-n:] if n > 0 else []
    while tail and tail[0].get("role") == "tool":
        tail = tail[1:]
    return tail


def compress_messages(client, model_id: str, messages: list) -> list:
    """Summarise old turns once the history gets long. Safe to call from a worker thread."""
    if len(messages) < 42: return messages
    tail = _safe_tail(messages[1:], 15)
    old  = messages[1:len(messages) - len(tail)]
    texts = [f"{m['role']}: {m['content'][:200]}" for m in old
             if m.get("role") in ("user", "assistant", "system")
             and isinstance(m.get("content"), str) and m["content"].strip()]
    if not texts: return messages
    try:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user",
                       "content": "Summarize this conversation in 3-4 sentences, keeping names, "
                                  "facts and open tasks:\n" + "\n".join(texts[-40:])}],
            max_tokens=300)
        summary = resp.choices[0].message.content or ""
        if not summary.strip(): return messages
        return [messages[0], {"role": "system", "content": f"[Older conversation summary: {_strip_think(summary)}]"}] + tail
    except Exception:
        # Couldn't summarise (rate limit, network...): still keep the context bounded instead of growing forever.
        return [messages[0]] + _safe_tail(messages[1:], 30)


_LENGTH_HINTS = (" (Answer briefly in 1-2 sentences.)", " (Give a thorough, detailed explanation.)")

def _strip_hints(messages: list) -> list:
    """Remove the temporary response-length hint from stored user messages."""
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            for h in _LENGTH_HINTS:
                if m["content"].endswith(h): m["content"] = m["content"][:-len(h)]
    return messages


def _plain_messages(msgs: list) -> list:
    """Only the user/assistant text turns (no tool plumbing, no empty replies, no length hints)."""
    out = [dict(m) for m in msgs
           if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
           and m["content"].strip()]
    return _strip_hints(out)


def _write_private_json(path: str, obj, **kw):
    """Atomic JSON write, readable only by the current user (plain text: used for the settings file)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, **kw)
    try: os.chmod(tmp, 0o600)
    except OSError: pass
    os.replace(tmp, path)


def _write_data_json(path: str, obj) -> None:
    """Chats and other personal data: atomic, private, and encrypted when that setting is on."""
    import storage
    storage.write_json(path, obj)

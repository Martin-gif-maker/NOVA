# usage.py — how much NOVA used each AI model: requests and tokens, kept on this Mac, and what that roughly costs.
#
# Every answer from a provider reports how many tokens went in and came out; NOVA adds them up per day and
# model. Cost is an ESTIMATE from prices per million tokens that you can edit (Settings → AI → Usage and cost) -
# the provider's own bill is what counts. Models running on this Mac (Ollama) cost nothing.
import json, time, logging, threading
import paths
import storage

log = logging.getLogger("nova")
_lock = threading.Lock()

# USD per million tokens (input, output). Only prices that were checked against the provider's published list
# are built in; add the others yourself.
DEFAULT_PRICES = {
    "claude-opus-5-5":   [4.0, 20.0],
    "claude-sonnet-5-5": [2.0, 10.0],
}
FREE_PROVIDERS = ("ollama",)


def record(provider: str, model: str, tokens_in: int, tokens_out: int) -> None:
    """Note one answered request."""
    try:
        tokens_in, tokens_out = int(tokens_in or 0), int(tokens_out or 0)
        if tokens_in <= 0 and tokens_out <= 0: return
        line = json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "provider": str(provider or "?"), "model": str(model or "?"),
                           "in": tokens_in, "out": tokens_out}, ensure_ascii=False)
        with _lock:
            storage.append_line(paths.USAGE_FILE, line)
    except Exception as e:                        # bookkeeping must never break a reply
        log.debug("usage: %s", e)


def entries(days: int = 1) -> list:
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - (max(1, days) - 1) * 86400))
    out = []
    for l in storage.read_lines(paths.USAGE_FILE):
        try: e = json.loads(l)
        except ValueError: continue
        if isinstance(e, dict) and str(e.get("t", ""))[:10] >= cutoff: out.append(e)
    return out


def price_for(model: str, provider: str, prices: dict):
    """(input, output) USD per million tokens, or None when no price is known."""
    if provider in FREE_PROVIDERS: return (0.0, 0.0)
    table = {**DEFAULT_PRICES, **(prices or {})}
    p = table.get(model)
    if p is None:                                 # dated ids such as claude-opus-5-5-20260801 use the base model's price
        p = next((v for k, v in table.items() if model.startswith(k + "-")), None)
    try:
        return (float(p[0]), float(p[1])) if p is not None else None
    except (TypeError, ValueError, IndexError):
        return None


def cost(tokens_in: int, tokens_out: int, price) -> float:
    return (tokens_in * price[0] + tokens_out * price[1]) / 1_000_000


def summary(items: list, prices: dict = None) -> dict:
    """{'rows': [{provider, model, requests, in, out, cost|None}], 'requests', 'in', 'out', 'cost', 'unpriced': [models]}"""
    agg = {}
    for e in items:
        k = (e.get("provider", "?"), e.get("model", "?"))
        a = agg.setdefault(k, [0, 0, 0])
        a[0] += 1; a[1] += int(e.get("in", 0) or 0); a[2] += int(e.get("out", 0) or 0)
    rows, total, unpriced = [], 0.0, []
    for (provider, model), (n, tin, tout) in agg.items():
        price = price_for(model, provider, prices)
        c = cost(tin, tout, price) if price is not None else None
        if c is None: unpriced.append(model)
        else: total += c
        rows.append({"provider": provider, "model": model, "requests": n, "in": tin, "out": tout, "cost": c})
    rows.sort(key=lambda r: (-(r["in"] + r["out"]), r["model"]))
    return {"rows": rows, "requests": sum(r["requests"] for r in rows), "in": sum(r["in"] for r in rows),
            "out": sum(r["out"] for r in rows), "cost": total, "unpriced": sorted(set(unpriced))}


def money(amount) -> str:
    if amount is None: return "—"
    if amount == 0: return "$0"
    return f"${amount:.4f}" if amount < 0.01 else f"${amount:.2f}"


def count(n: int) -> str:
    return f"{n:,}".replace(",", " ")

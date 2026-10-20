"""Measure NOVA's tool use.

    .venv/bin/python -m evals routing                      no AI needed: are the right tools sent with each request?
    .venv/bin/python -m evals live                         the real model (the provider's key from the Keychain)
    .venv/bin/python -m evals live --model fast --lang bg  the fast model, Bulgarian requests only
    .venv/bin/python -m evals live --only en-maps,en-lock  just these cases
    .venv/bin/python -m evals live --provider custom --base-url http://127.0.0.1:8080/v1 --model <id>
                                                           any OpenAI-compatible server (Ollama, LM Studio, mlx-lm …)
    .venv/bin/python -m evals live --budget 100000         stop once 100k tokens are used (a free tier's daily allowance
                                                           is about two full runs' worth) …
    .venv/bin/python -m evals live --resume evals/results/<file>.json
                                                           … and run the rest later, added to the same results

NOVA's real data is never touched: everything runs with an empty temporary data folder, and the tools are
stand-ins (nothing happens on the Mac). Live results are saved in evals/results/.
"""
import argparse, datetime, json, os, sys, tempfile

os.environ.setdefault("NOVA_DATA_DIR", tempfile.mkdtemp(prefix="nova_eval_"))     # before any NOVA module loads
os.environ["NOVA_NO_MIGRATE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from evals import harness  # noqa: E402


def _pick(cases, args):
    if args.lang: cases = [c for c in cases if harness.lang(c) == args.lang]
    if args.only: cases = [c for c in cases if c["id"] in set(args.only.split(","))]
    return cases[:args.limit] if args.limit else cases


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals", description=__doc__.split("\n")[0])
    ap.add_argument("what", choices=("routing", "live"))
    ap.add_argument("--provider", default="groq")
    ap.add_argument("--model", default="smart", help="a slot (smart, fast, mix) or a model id")
    ap.add_argument("--lang", choices=("en", "bg"))
    ap.add_argument("--only", help="comma-separated case ids")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--base-url", default="", help="server address for the custom / ollama providers")
    ap.add_argument("--name", default="", help="the model's name in the report (instead of its id or path)")
    ap.add_argument("--budget", type=int, default=0, help="stop before the next request once this many tokens are used")
    ap.add_argument("--resume", default="", help="an earlier results .json: run only the requests it lacks, add them to it")
    args = ap.parse_args(argv)

    cases = harness.load_cases()
    bad = harness.problems(cases)
    if bad:
        print("The cases have mistakes:\n  " + "\n  ".join(bad)); return 2
    cases = _pick(cases, args)

    if args.what == "routing":
        rows = harness.routing(cases)
        s = harness.routing_summary(rows)
        print(harness.markdown(routing_sum=s, title=f"Tool routing, {len(cases)} requests"))
        for m in s["misses"]: print("  not sent:", m)
        return 0

    from PySide6.QtCore import QCoreApplication
    _app = QCoreApplication.instance() or QCoreApplication([])        # the worker's signals need one
    assert _app is not None
    import models, providers, keystore
    models.activate(args.provider)
    model_id = models.MODELS[args.model][0] if args.model in models.MODELS else args.model
    if args.model not in models.MODELS:                    # one named model for every slot: no switching mid-run
        models.apply_overrides({slot: model_id for slot in models.MODELS})
    key = os.environ.get("NOVA_EVAL_KEY") or keystore._get_api_key(args.provider)
    try:
        client = providers.make_client(args.provider, key, args.base_url)
    except providers.ProviderError as e:
        print(f"No working {args.provider} key: {e}"); return 2

    shown = args.name or model_id
    earlier: list = []
    if args.resume:
        with open(args.resume, encoding="utf-8") as f: old = json.load(f)
        if (old.get("provider"), old.get("model")) != (args.provider, shown):
            print(f"{args.resume} measured {old.get('provider')} · {old.get('model')}, not {args.provider} · {shown}.")
            return 2
        earlier = old["results"]
        have = {r["id"] for r in earlier}
        cases = [c for c in cases if c["id"] not in have]
        print(f"{len(earlier)} requests done already, {len(cases)} to go.")

    def report(i, n, r):
        mark = "ok  " if r["ok"] else "MISS"
        print(f"{i:3}/{n} {mark} {r['id']:<28} {r['secs']:5.1f}s {r['tok_in'] + r['tok_out']:6} tok  " +
              (r["error"] or " ".join(t for t, _ in r["calls"]) or "(no tool)"), flush=True)

    new, stopped = harness.run_all(harness.interleave(cases), client, model_id, args.budget, report)
    for r in new: r["model"] = shown
    if stopped == "the key was refused" and not new:
        print("The key was refused - stopping."); return 2
    results = earlier + new
    left = len(cases) - len(new)

    s = harness.live_summary(results)
    import re
    if args.resume:
        name = os.path.splitext(os.path.basename(args.resume))[0]
    else:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
        name = f"{stamp}-{args.provider}-" + re.sub(r"[^\w.]+", "-", shown.split("/")[-1]).strip("-").lower()
    out = os.path.join(harness.HERE, "results"); os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, name + ".json"), "w", encoding="utf-8") as f:
        json.dump({"provider": args.provider, "model": shown, "summary": s, "left": left, "results": results},
                  f, ensure_ascii=False, indent=1)
    title = f"{args.provider} · {shown} · {len(results)} requests · {name[:10]}"
    if left: title += f" ({left} not run yet)"
    with open(os.path.join(out, name + ".md"), "w", encoding="utf-8") as f:
        f.write(harness.markdown(live_sum=s, title=title))
    print("\n" + harness.markdown(live_sum=s, title=title))
    for line in s["failures"]: print("  ", line)
    print(f"Saved: evals/results/{name}.json")
    if stopped:
        print(f"Stopped with {left} requests left: {stopped}.\nThe rest, later: python -m evals live "
              f"--provider {args.provider} --model {model_id} --resume evals/results/{name}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

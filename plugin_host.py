# plugin_host.py — runs ONE plugin in its own process. NOVA starts it inside the macOS sandbox
# (see sandbox.py), so the plugin only gets what its MANIFEST asked for and you approved.
#
#   plugin_host.py <plugin.py> describe            -> the plugin's tools as JSON
#   plugin_host.py <plugin.py> call <tool-name>    -> runs the tool with JSON arguments read from stdin
# The answer is the last line of stdout, prefixed with MARK; anything the plugin prints goes to stderr.
import sys, json

MARK = "@@NOVA-PLUGIN-RESULT@@"


def _load(path: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location("nova_plugin", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list) -> int:
    real_out = sys.stdout
    sys.stdout = sys.stderr                           # a plugin's own print() must not corrupt the answer
    try:
        path, mode = argv[0], argv[1]
        tools = getattr(_load(path), "TOOLS", [])
        if mode == "describe":
            answer = {"ok": True, "tools": [{"name": str(t["name"]), "description": str(t.get("description", "")),
                                             "params": t.get("params", {}), "required": list(t.get("required", []))}
                                            for t in tools]}
        elif mode == "call":
            fn = next((t["function"] for t in tools if t["name"] == argv[2]), None)
            if fn is None:
                answer = {"ok": False, "error": f"the plugin has no tool named {argv[2]!r}"}
            else:
                args = json.loads(sys.stdin.read() or "{}")
                answer = {"ok": True, "result": str(fn(**args))}
        else:
            answer = {"ok": False, "error": f"unknown mode {mode!r}"}
    except BaseException as e:                        # a plugin failing must still produce an answer
        answer = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        sys.stdout = real_out
    real_out.write("\n" + MARK + json.dumps(answer, ensure_ascii=False, default=str) + "\n")
    real_out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

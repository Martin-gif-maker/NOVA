"""A tiny hand-written MCP server (stdio) that misbehaves on request - for the edge cases a polite server never shows.
Modes (argv[1]): normal | noisy | pages | asks | dies | slow"""
import sys, json, time

mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
TOOLS = [{"name": f"tool{i}", "description": f"Tool number {i}", "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}}}
         for i in range(5)]


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()


if mode == "noisy":
    print("Starting up… (a log line on stdout, which the protocol forbids but servers do)"); sys.stdout.flush()

for line in sys.stdin:
    try: msg = json.loads(line)
    except ValueError: continue
    method, rid = msg.get("method"), msg.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                                                       "serverInfo": {"name": "fake", "version": "0.1"}}})
    elif method == "notifications/initialized":
        if mode == "asks":                                   # the server asks the client things; a client must answer or refuse
            send({"jsonrpc": "2.0", "id": "srv-1", "method": "ping"})
            send({"jsonrpc": "2.0", "id": "srv-2", "method": "sampling/createMessage", "params": {"messages": []}})
    elif method == "tools/list":
        if mode == "pages":
            cursor = (msg.get("params") or {}).get("cursor")
            start = int(cursor) if cursor else 0
            page = TOOLS[start:start + 2]
            result = {"tools": page}
            if start + 2 < len(TOOLS): result["nextCursor"] = str(start + 2)
            send({"jsonrpc": "2.0", "id": rid, "result": result})
        else:
            send({"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info", "data": "listing"}})
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS[:2] + [{"name": "", "description": "nameless"}, "junk"]}})
    elif method == "tools/call":
        params = msg.get("params") or {}
        if mode == "dies": sys.exit(3)
        if mode == "slow": time.sleep(5)
        if mode == "noisy": print("working…"); sys.stdout.flush()
        send({"jsonrpc": "2.0", "id": rid, "result": {"content": [
            {"type": "text", "text": f"{params.get('name')} got {json.dumps(params.get('arguments'), sort_keys=True)}"},
            {"type": "image", "data": "AAAA", "mimeType": "image/png"},
            {"type": "resource", "resource": {"uri": "file:///x", "text": "embedded text"}}]}})
    elif rid is not None and method:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Method not found: {method}"}})
    elif rid is not None and mode == "asks":                 # answers to OUR requests arrive here
        with open(sys.argv[2], "a") as f: f.write(json.dumps(msg) + "\n")

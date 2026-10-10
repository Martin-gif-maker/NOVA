# mcp_client.py — connects NOVA to MCP servers (Model Context Protocol): ready-made tool servers for
# GitHub, Notion, databases, file systems … that many AI apps share.
#
# A server is either a program NOVA starts and talks to over its stdin/stdout ("stdio"), or a web
# address ("streamable HTTP"). Both speak JSON-RPC 2.0. NOVA does the handshake (`initialize`), asks for
# the tools (`tools/list`) and calls them (`tools/call`). Nothing else of the protocol is used: no
# sampling, no resources, no prompts - a server cannot make NOVA call the AI or read files on its own.
#
# Servers are programs the user chose to install; NOVA still treats what they return as untrusted text
# and asks before each kind of tool is used for the first time (see tools.py).
import os, re, json, shutil, logging, threading, subprocess
import paths

log = logging.getLogger("nova")

PROTOCOL_VERSION = "2025-06-18"           # what NOVA offers; a server may answer with any version it prefers
CONNECT_TIMEOUT = 30
CALL_TIMEOUT = 120
MAX_RESULT_CHARS = 12000
_NAME = re.compile(r"[^a-zA-Z0-9_-]+")


class MCPError(Exception):
    pass


def safe_name(text: str) -> str:
    return _NAME.sub("_", str(text or "")).strip("_") or "x"


def tool_id(server: str, tool: str) -> str:
    """The name the AI sees for a server's tool (letters, digits, _ and - only; at most 64 characters)."""
    return ("mcp__" + safe_name(server)[:24] + "__" + safe_name(tool))[:64]


def gui_env(extra: dict = None) -> dict:
    """Environment for a server program: an app started from the Dock has a bare PATH, so add the usual places."""
    env = dict(os.environ)
    home = os.path.expanduser("~")
    more = ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", os.path.join(home, ".local", "bin"),
            os.path.join(home, ".cargo", "bin"), os.path.join(home, ".bun", "bin"), os.path.join(home, ".deno", "bin")]
    have = env.get("PATH", "/usr/bin:/bin").split(":")
    env["PATH"] = ":".join(have + [p for p in more if p not in have])
    for k in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE"):       # NOVA's own (packaged) Python must not leak into theirs
        env.pop(k, None)
    env.update({str(k): str(v) for k, v in (extra or {}).items()})
    return env


# ── transports ─────────────────────────────────────────────────────
class _Pending:
    def __init__(self): self.event = threading.Event(); self.message = None


class StdioTransport:
    """Starts the server program and exchanges one JSON message per line."""
    def __init__(self, command: str, args=None, env: dict = None, cwd: str = None):
        self.command, self.args, self.env, self.cwd = command, list(args or []), env or {}, cwd
        self.proc = None; self._next = 0; self._pending = {}; self._lock = threading.Lock(); self._wlock = threading.Lock()
        self.stderr_tail = []; self.closed = False

    def start(self) -> None:
        env = gui_env(self.env)
        exe = self.command if os.path.isabs(self.command) else shutil.which(self.command, path=env["PATH"])
        if not exe:
            hint = {"npx": "Install Node.js (nodejs.org) first.", "node": "Install Node.js (nodejs.org) first.",
                    "uvx": "Install uv (docs.astral.sh/uv) first.", "uv": "Install uv (docs.astral.sh/uv) first.",
                    "docker": "Install Docker Desktop first."}.get(os.path.basename(self.command), "")
            raise MCPError(f"The program “{self.command}” was not found on this Mac. {hint}".strip())
        try:
            self.proc = subprocess.Popen([exe, *self.args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         env=env, cwd=self.cwd or os.path.expanduser("~"), text=True, encoding="utf-8",
                                         errors="replace", bufsize=1, start_new_session=True)
        except OSError as e:
            raise MCPError(f"Could not start “{self.command}”: {e}")
        threading.Thread(target=self._read_loop, daemon=True, name="mcp-read").start()
        threading.Thread(target=self._stderr_loop, daemon=True, name="mcp-err").start()

    def _stderr_loop(self):
        try:
            for line in self.proc.stderr:
                self.stderr_tail = (self.stderr_tail + [line.rstrip()])[-8:]
        except Exception as e: log.debug("stopped reading a tool server's messages: %s", e)

    def _read_loop(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line: continue
                try: msg = json.loads(line)
                except ValueError: continue                     # a server that prints logs on stdout: ignore the noise
                if isinstance(msg, dict): self._incoming(msg)
        except Exception as e:
            log.info("mcp read loop ended: %s", e)
        self.closed = True
        with self._lock:
            for p in self._pending.values(): p.event.set()       # wake everyone who is still waiting

    def _incoming(self, msg: dict):
        if "id" in msg and ("result" in msg or "error" in msg):
            with self._lock: p = self._pending.get(msg["id"])
            if p: p.message = msg; p.event.set()
        elif "method" in msg and "id" in msg:                    # the server asks US something
            if msg["method"] == "ping": self._write({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
            else:                                                # sampling, roots, elicitation …: NOVA does not offer these
                self._write({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported by NOVA"}})
        # notifications (progress, log lines, list_changed) need no answer

    def _write(self, msg: dict):
        if self.proc is None or self.proc.poll() is not None: raise MCPError(self._died())
        try:
            with self._wlock:
                self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n"); self.proc.stdin.flush()
        except (OSError, ValueError):
            raise MCPError(self._died())

    def _died(self) -> str:
        tail = " ".join(self.stderr_tail[-3:])[:300]
        return "The server stopped" + (f": {tail}" if tail else ".")

    def request(self, method: str, params: dict = None, timeout: float = CALL_TIMEOUT) -> dict:
        with self._lock:
            self._next += 1; rid = self._next
            p = self._pending[rid] = _Pending()
        try:
            self._write({"jsonrpc": "2.0", "id": rid, "method": method, **({"params": params} if params is not None else {})})
            if not p.event.wait(timeout):
                try: self.notify("notifications/cancelled", {"requestId": rid, "reason": "timeout"})
                except MCPError: pass
                raise MCPError(f"The server did not answer within {int(timeout)} seconds.")
            if p.message is None: raise MCPError(self._died())
            if "error" in p.message:
                err = p.message["error"] or {}
                raise MCPError(str(err.get("message") or err)[:400])
            return p.message.get("result") or {}
        finally:
            with self._lock: self._pending.pop(rid, None)

    def notify(self, method: str, params: dict = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})

    def close(self) -> None:
        self.closed = True
        p = self.proc
        if p is None: return
        try: p.stdin.close()                                     # the polite way: end of input
        except Exception as e: log.debug("tool server: closing its input: %s", e)
        try: p.wait(timeout=1.5)
        except Exception:
            try: p.terminate(); p.wait(timeout=2)
            except Exception:
                try: p.kill()
                except Exception as e: log.debug("tool server: stopping it: %s", e)


class HttpTransport:
    """Streamable HTTP: every request is a POST; the answer is JSON or a short event stream."""
    def __init__(self, url: str, headers: dict = None):
        if not url.lower().startswith(("https://", "http://localhost", "http://127.0.0.1", "http://[::1]")):
            raise MCPError("A remote MCP server must use https:// (plain http is only allowed for this Mac).")
        self.url, self.headers = url, {str(k): str(v) for k, v in (headers or {}).items()}
        self.session_id = None; self.version = None; self._next = 0; self._lock = threading.Lock(); self.closed = False

    def start(self) -> None:
        pass

    def _post(self, body: dict, timeout: float):
        import requests, ledger
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **self.headers}
        if self.session_id: h["Mcp-Session-Id"] = self.session_id
        if self.version: h["MCP-Protocol-Version"] = self.version
        ledger.record(self.url, "MCP server", ledger.size_of(body), str(body.get("method", "")))
        try:
            return requests.post(self.url, json=body, headers=h, timeout=timeout, stream=True)
        except requests.RequestException as e:
            raise MCPError(f"Could not reach the server: {type(e).__name__}")

    def request(self, method: str, params: dict = None, timeout: float = CALL_TIMEOUT) -> dict:
        with self._lock:
            self._next += 1; rid = self._next
        r = self._post({"jsonrpc": "2.0", "id": rid, "method": method, **({"params": params} if params is not None else {})}, timeout)
        try:
            if r.status_code in (401, 403): raise MCPError("The server refused the login (check the token in its settings).")
            if r.status_code >= 400: raise MCPError(f"The server answered with error {r.status_code}.")
            if r.headers.get("Mcp-Session-Id"): self.session_id = r.headers["Mcp-Session-Id"]
            if "text/event-stream" in r.headers.get("Content-Type", ""):
                msg = self._from_stream(r, rid)
            else:
                try: msg = r.json()
                except ValueError: raise MCPError("The server sent something that is not MCP.")
        finally:
            r.close()
        if not isinstance(msg, dict): raise MCPError("The server sent something that is not MCP.")
        if "error" in msg:
            err = msg["error"] or {}
            raise MCPError(str(err.get("message") or err)[:400])
        return msg.get("result") or {}

    @staticmethod
    def _from_stream(r, rid):
        data = []
        for raw in r.iter_lines(decode_unicode=True):
            if raw is None: continue
            if raw.startswith("data:"):
                data.append(raw[5:].lstrip())
            elif raw == "" and data:                             # blank line = end of one event
                try: msg = json.loads("\n".join(data))
                except ValueError: msg = None
                data = []
                if isinstance(msg, dict) and msg.get("id") == rid and ("result" in msg or "error" in msg): return msg
        raise MCPError("The server closed the connection without an answer.")

    def notify(self, method: str, params: dict = None) -> None:
        r = self._post({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}, 30)
        r.close()

    def close(self) -> None:
        self.closed = True
        if not self.session_id: return
        try:
            import requests
            requests.delete(self.url, headers={**self.headers, "Mcp-Session-Id": self.session_id}, timeout=5).close()
        except Exception as e: log.debug("tool server: ending the session: %s", e)


# ── one server ─────────────────────────────────────────────────────
def normalise(spec: dict) -> dict:
    """A server's settings in one shape: {'command', 'args', 'env', 'url', 'headers', 'enabled'}.
    Accepts the layout other apps use ({"command": "npx", "args": [...]}) and {"url": ...}."""
    spec = dict(spec or {})
    url = str(spec.get("url") or spec.get("serverUrl") or "").strip()
    command = str(spec.get("command") or "").strip()
    args = spec.get("args") or []
    if isinstance(args, str): args = args.split()
    if command and not args and " " in command and not os.path.exists(command):       # "npx -y some-server" typed as one line
        import shlex
        parts = shlex.split(command); command, args = parts[0], parts[1:]
    return {"command": command, "args": [str(a) for a in args], "env": dict(spec.get("env") or {}), "url": url,
            "headers": dict(spec.get("headers") or {}), "enabled": bool(spec.get("enabled", True))}


def parse_pasted(text: str) -> dict:
    """Server definitions pasted as JSON: {"mcpServers": {...}}, {"name": {...}} or a single {"command": …}. -> {name: spec}"""
    try: data = json.loads(text)
    except ValueError: raise MCPError("That is not valid JSON.")
    if not isinstance(data, dict): raise MCPError("Expected a JSON object.")
    if isinstance(data.get("mcpServers"), dict): data = data["mcpServers"]
    elif isinstance(data.get("servers"), dict): data = data["servers"]
    if "command" in data or "url" in data: data = {"server": data}
    out = {}
    for name, spec in data.items():
        if isinstance(spec, dict) and (spec.get("command") or spec.get("url")):
            out[safe_name(name)[:24]] = normalise(spec)
    if not out: raise MCPError("No server with a command or a url was found in that JSON.")
    return out


# ── secrets ────────────────────────────────────────────────────────
# A server's environment values and HTTP headers are usually tokens. They are kept in the Keychain; the settings
# file only remembers WHICH values exist: {"env": {"GITHUB_TOKEN": "@keychain"}}.
SECRET = "@keychain"


def split_secrets(servers: dict, known: dict = None) -> tuple:
    """(settings without the secret values, {server: {"env": {...}, "headers": {...}}}).
    A value that is already the placeholder keeps the secret stored earlier (`known`)."""
    known = known or {}
    safe, secrets = {}, {}
    for name, spec in (servers or {}).items():
        if not isinstance(spec, dict): continue
        spec = normalise(spec); out = dict(spec); mine = {}
        for part in ("env", "headers"):
            real = {}
            for key, value in spec[part].items():
                if value == SECRET: value = known.get(name, {}).get(part, {}).get(key)
                if value is not None and str(value) != "": real[key] = str(value)
            out[part] = {key: SECRET for key in real}
            if real: mine[part] = real
        safe[name] = out
        if mine: secrets[name] = mine
    return safe, secrets


def join_secrets(servers: dict, secrets: dict = None) -> dict:
    """The settings as the servers need them: placeholders replaced by the real values (missing ones are left out)."""
    secrets = secrets or {}
    out = {}
    for name, spec in (servers or {}).items():
        if not isinstance(spec, dict): continue
        spec = normalise(spec)
        for part in ("env", "headers"):
            real = {}
            for key, value in spec[part].items():
                if value == SECRET: value = secrets.get(name, {}).get(part, {}).get(key)
                if value is not None: real[key] = value
            spec[part] = real
        out[name] = spec
    return out


class Server:
    def __init__(self, name: str, spec: dict):
        self.name, self.spec = name, normalise(spec)
        self.transport = None; self.tools = []; self.status = "off"; self.error = ""; self.info = {}
        self._lock = threading.Lock()

    @property
    def is_http(self) -> bool:
        return bool(self.spec["url"])

    def connect(self) -> None:
        """Start / reach the server, shake hands and read its tools. Raises MCPError."""
        with self._lock:
            self.close(); self.status = "starting"; self.error = ""
            try:
                if self.is_http: t = HttpTransport(self.spec["url"], self.spec["headers"])
                elif self.spec["command"]: t = StdioTransport(self.spec["command"], self.spec["args"], self.spec["env"])
                else: raise MCPError("This server has neither a command nor a url.")
                t.start(); self.transport = t
                result = t.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                                  "clientInfo": {"name": "NOVA", "version": paths.__version__}}, CONNECT_TIMEOUT)
                self.info = result.get("serverInfo") or {}
                if self.is_http: t.version = str(result.get("protocolVersion") or PROTOCOL_VERSION)
                t.notify("notifications/initialized")
                self.tools = self._list_tools()
                self.status = "ready"
            except MCPError as e:
                self.status = "error"; self.error = str(e); self._drop(); raise
            except Exception as e:
                self.status = "error"; self.error = f"{type(e).__name__}: {e}"; self._drop(); raise MCPError(self.error)

    def _list_tools(self) -> list:
        tools, cursor = [], None
        for _ in range(50):                                      # pages; a sane server has a handful
            result = self.transport.request("tools/list", {"cursor": cursor} if cursor else {}, CONNECT_TIMEOUT)
            for t in result.get("tools") or []:
                if isinstance(t, dict) and t.get("name"):
                    schema = t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {}
                    tools.append({"name": str(t["name"]), "description": str(t.get("description") or t.get("title") or "")[:1000],
                                  "schema": schema if schema.get("type") == "object" else {"type": "object", "properties": {}}})
            cursor = result.get("nextCursor")
            if not cursor: break
        return tools[:200]

    def call(self, tool: str, arguments: dict, timeout: float = CALL_TIMEOUT):
        """Run a tool. Returns (text, is_error)."""
        if self.transport is None or self.status != "ready": raise MCPError(f"The server “{self.name}” is not connected.")
        try:
            result = self.transport.request("tools/call", {"name": tool, "arguments": arguments or {}}, timeout)
        except MCPError:
            if getattr(self.transport, "closed", False): self.status = "error"; self.error = "The server stopped."
            raise
        parts = []
        for item in result.get("content") or []:
            if not isinstance(item, dict): continue
            kind = item.get("type")
            if kind == "text": parts.append(str(item.get("text", "")))
            elif kind == "resource" and isinstance(item.get("resource"), dict) and item["resource"].get("text"):
                parts.append(str(item["resource"]["text"]))
            elif kind == "resource_link": parts.append(f"[link: {item.get('uri', '')}]")
            elif kind: parts.append(f"[{kind} content not shown]")
        if not parts and result.get("structuredContent") is not None:
            parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
        text = "\n".join(p for p in parts if p).strip() or "(the tool returned nothing)"
        if len(text) > MAX_RESULT_CHARS: text = text[:MAX_RESULT_CHARS] + "\n[… shortened]"
        return text, bool(result.get("isError"))

    def _drop(self):
        t, self.transport = self.transport, None
        if t is not None:
            try: t.close()
            except Exception as e: log.debug("tool server: closing the connection: %s", e)

    def close(self) -> None:
        self._drop(); self.tools = []
        if self.status != "error": self.status = "off"


# ── all servers ────────────────────────────────────────────────────
class Manager:
    """The configured servers. `on_change(server)` is called (from a worker thread) whenever one connects or fails."""
    def __init__(self, on_change=None):
        self.servers = {}; self.on_change = on_change; self._lock = threading.Lock()

    def apply(self, config: dict) -> None:
        """Make the running servers match the settings: start new / changed ones, stop removed or disabled ones."""
        wanted = {safe_name(n)[:24]: normalise(s) for n, s in (config or {}).items() if isinstance(s, dict)}
        with self._lock:
            for name in list(self.servers):
                if name not in wanted or not wanted[name]["enabled"] or self.servers[name].spec != wanted[name]:
                    s = self.servers.pop(name); s.close(); self._changed(s)
            for name, spec in wanted.items():
                if spec["enabled"] and name not in self.servers:
                    s = self.servers[name] = Server(name, spec)
                    threading.Thread(target=self._connect, args=(s,), daemon=True, name=f"mcp-{name}").start()

    def _connect(self, server: Server):
        try:
            server.connect()
            log.info("MCP server %s ready: %d tools", server.name, len(server.tools))
        except MCPError as e:
            log.warning("MCP server %s failed: %s", server.name, e)
        self._changed(server)

    def _changed(self, server: Server):
        if self.on_change:
            try: self.on_change(server)
            except Exception as e: log.warning("mcp on_change failed: %s", e)

    def reconnect(self, name: str) -> None:
        s = self.servers.get(name)
        if s: threading.Thread(target=self._connect, args=(s,), daemon=True).start()

    def call(self, server: str, tool: str, arguments: dict):
        s = self.servers.get(server)
        if s is None: raise MCPError(f"The server “{server}” is not connected.")
        return s.call(tool, arguments)

    def stop_all(self) -> None:
        with self._lock:
            for s in self.servers.values(): s.close()
            self.servers = {}

# ipc.py — lets another program hand NOVA a request: `NOVA --ask "text"` or a nova://ask?text=… link
# (that is how an Apple Shortcut calls NOVA). The second copy passes the text to the running NOVA over a
# local socket that only the same user can open, then exits - or, with `--wait`, stays until NOVA has answered
# and prints the answer, so the Shortcut can use it.
import os, json, time, socket, hashlib, logging, tempfile
from urllib.parse import urlparse, parse_qs

log = logging.getLogger("nova")
MAX_TEXT = 8000


def server_name() -> str:
    """Where the running NOVA listens: a socket inside its own (user-only) data folder. One per data folder and
    temp folder, so a test run never talks to your real NOVA. macOS limits socket paths to 104 characters, so a
    very deep data folder falls back to a short name in /tmp."""
    import paths
    tag = hashlib.sha1((tempfile.gettempdir() + "|" + paths.DATA_DIR).encode()).hexdigest()[:10]
    path = os.path.join(paths.DATA_DIR, f".ipc-{tag}")
    if len(path.encode()) > 100:
        path = f"/tmp/nova-{os.getuid() if hasattr(os, 'getuid') else 0}-{tag}.sock"
    return path


def _frame(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"            # one message = one line of JSON


def _connect(timeout: float):
    """A plain connection to the running NOVA (None if there is none). No Qt here, so the short-lived copy that
    only passes a request on never shows up in the Dock."""
    if not hasattr(socket, "AF_UNIX"): return None
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(server_name()); return sock
    except OSError:
        sock.close(); return None


def reachable(timeout: float = 0.5) -> bool:
    sock = _connect(timeout)
    if sock is None: return False
    sock.close(); return True


def send(payload: dict, timeout_ms: int = 1500) -> bool:
    """Give `payload` to the running NOVA. False if none is listening."""
    sock = _connect(timeout_ms / 1000)
    if sock is None: return False
    try:
        sock.sendall(_frame(payload)); return True
    except OSError:
        return False
    finally:
        sock.close()


def request(payload: dict, wait_secs: float = 600, connect_secs: float = 1.5) -> tuple:
    """Hand `payload` to the running NOVA and wait for its answer. Returns (status, text):
    "ok" + the reply · "error" + NOVA's reason · "offline" (no NOVA) · "timeout" · "closed" (NOVA went away)."""
    sock = _connect(connect_secs)
    if sock is None: return "offline", ""
    buf = bytearray(); deadline = time.monotonic() + wait_secs
    try:
        sock.sendall(_frame(dict(payload, wait=True)))
        while b"\n" not in buf:
            left = deadline - time.monotonic()
            if left <= 0: return "timeout", ""
            sock.settimeout(min(left, 1.0))
            try: chunk = sock.recv(65536)
            except socket.timeout: continue
            if not chunk: break
            buf.extend(chunk)
    except OSError:
        return "closed", ""
    finally:
        sock.close()
    try:
        msg = json.loads(bytes(buf).split(b"\n")[0].decode("utf-8"))
        if "reply" in msg: return "ok", str(msg["reply"])
        return "error", str(msg.get("error") or "NOVA gave no answer.")
    except (ValueError, AttributeError, TypeError):
        return "closed", ""


class Reply:
    """The caller that is waiting for an answer (`NOVA --ask … --wait`). Answer it once; later calls do nothing."""
    def __init__(self, conn): self._conn = conn

    def alive(self) -> bool:
        return self._conn is not None

    def _gone(self):
        self._conn = None                                  # the caller hung up (timed out, or was stopped)

    def _finish(self, payload: dict) -> bool:
        conn, self._conn = self._conn, None
        if conn is None: return False
        try:
            conn.write(_frame(payload)); conn.flush(); conn.disconnectFromServer()
            return True
        except RuntimeError:                               # the connection object is already gone
            return False

    def send(self, text: str) -> bool:
        return self._finish({"reply": str(text)})

    def fail(self, why: str) -> bool:
        return self._finish({"error": str(why)})


def start(on_message):
    """Listen for other copies. `on_message(dict, reply)` runs on the GUI thread; `reply` is a Reply when the caller
    waits for an answer, otherwise None. Returns the server (keep a reference)."""
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)        # this user only
    QLocalServer.removeServer(server_name())                                   # a leftover from a crash
    if not server.listen(server_name()):
        log.info("ipc: could not listen (%s)", server.errorString()); return None

    def _connected():
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            state = {"buf": bytearray(), "handled": False, "reply": None}

            def _handle(c=conn, st=state):
                if st["handled"]: return
                st["handled"] = True
                try:
                    msg = json.loads(bytes(st["buf"]).split(b"\n")[0].decode("utf-8"))
                    if not isinstance(msg, dict): raise ValueError("not an object")
                except Exception as e:
                    log.info("ipc: ignored a malformed message (%s)", e); c.abort(); return
                if msg.pop("wait", False): st["reply"] = Reply(c)
                try: on_message(msg, st["reply"])
                except Exception as e:
                    log.warning("ipc: handling a request failed (%s)", e)
                    if st["reply"]: st["reply"].fail("NOVA could not take the request.")

            def _read(c=conn, st=state):
                if st["handled"]: c.readAll(); return
                st["buf"].extend(bytes(c.readAll()))
                if len(st["buf"]) > MAX_TEXT * 8: st["handled"] = True; c.abort(); return
                if b"\n" in st["buf"]: _handle()

            def _done(c=conn, st=state):
                if st["buf"] and not st["handled"]: _handle()                  # a message sent without the line end
                if st["reply"]: st["reply"]._gone()
                c.deleteLater()
            conn.readyRead.connect(_read); conn.disconnected.connect(_done)
            if conn.bytesAvailable(): _read()
    server.newConnection.connect(_connected)
    return server


def text_from_url(url: str):
    """nova://ask?text=hello%20there  ->  'hello there'   (None for anything else)."""
    try:
        u = urlparse(str(url))
    except ValueError:
        return None
    if u.scheme.lower() != "nova": return None
    if (u.netloc or u.path.strip("/")).lower() not in ("ask", ""): return None
    q = parse_qs(u.query)
    text = (q.get("text") or q.get("q") or [""])[0].strip()
    return text[:MAX_TEXT] or None


def arg_value(argv: list, flag: str):
    """The value after `flag` on the command line ('' if the flag is last), or None if it is absent."""
    if flag not in argv: return None
    i = argv.index(flag)
    return " ".join(argv[i + 1:]).strip() if i + 1 < len(argv) else ""


def ask_args(argv: list) -> tuple:
    """(text, wait, seconds) from a command line. `--wait` and `--timeout N` may stand before or after the text:
    NOVA --ask "what is on my calendar" --wait      NOVA --wait --timeout 120 --ask summarize this"""
    args = list(argv); wait = False; secs = 600.0
    while "--wait" in args:
        args.remove("--wait"); wait = True
    if "--timeout" in args:
        i = args.index("--timeout")
        try: secs = max(5.0, min(float(args[i + 1]), 3600.0)); del args[i:i + 2]
        except (IndexError, ValueError): del args[i:i + 1]
    return arg_value(args, "--ask"), wait, secs


def _start_nova() -> bool:
    """Start NOVA on its own (menu bar only) for a caller that found none running."""
    import sys, subprocess
    cmd = [sys.executable] if getattr(sys, "frozen", False) else \
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")]
    try:
        subprocess.Popen(cmd + ["--hidden"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
        return True
    except OSError:
        return False


EXIT_OK, EXIT_NO_NOVA, EXIT_NO_ANSWER, EXIT_TIMEOUT = 0, 1, 2, 3


def cli(argv: list, out=None, err=None, start_secs: float = 40) -> int:
    """`NOVA --ask "text" --wait`: print NOVA's answer and nothing else, so a Shortcut or script can use it.
    Exit code: 0 answered · 1 NOVA could not be reached · 2 NOVA gave no answer (reason on stderr) · 3 timed out."""
    import sys
    out = out or sys.stdout; err = err or sys.stderr
    text, _wait, secs = ask_args(argv)
    if not text:
        print('Usage: NOVA --ask "your request" --wait [--timeout SECONDS]', file=err); return EXIT_NO_ANSWER
    if not reachable():
        if not _start_nova():
            print("NOVA is not running and could not be started.", file=err); return EXIT_NO_NOVA
        deadline = time.monotonic() + start_secs
        while not reachable(0.3):
            if time.monotonic() > deadline:
                print("NOVA did not start in time.", file=err); return EXIT_NO_NOVA
            time.sleep(0.3)
    status, reply = request({"ask": text[:MAX_TEXT]}, secs)
    if status == "ok":
        print(reply, file=out); return EXIT_OK
    if status == "timeout":
        print(f"NOVA did not answer within {int(secs)} seconds.", file=err); return EXIT_TIMEOUT
    if status == "error":
        print(reply, file=err); return EXIT_NO_ANSWER
    print("NOVA is not running." if status == "offline" else "NOVA closed before answering.", file=err)
    return EXIT_NO_NOVA

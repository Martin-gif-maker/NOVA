# sandbox.py — runs plugins inside the macOS sandbox (Seatbelt, via /usr/bin/sandbox-exec).
#
# A plugin that declares a MANIFEST never runs inside NOVA. Each of its tool calls is a short-lived
# separate process that starts with NOTHING allowed and then gets exactly what the manifest asked for
# and the user approved:
#     (always)        run Python, read the plugin's own file, read/write its private data folder
#     "network"       talk to the internet
#     "read_files"    read Documents, Desktop, Downloads, Pictures, Music, Movies
#     "write_files"   create and change files in Documents, Desktop, Downloads
# Never, whatever the manifest says: NOVA's own data (chats, memories, keys), the Keychain, ~/Library,
# hidden files such as ~/.ssh, starting other apps, AppleScript, the clipboard, the screen.
import os, sys, json, subprocess, tempfile
import paths

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
PERMISSIONS = {
    "network":     "Use the internet",
    "read_files":  "Read files in Documents, Desktop, Downloads, Pictures, Music and Movies",
    "write_files": "Create and change files in Documents, Desktop and Downloads",
}
READ_DIRS  = ("Documents", "Desktop", "Downloads", "Pictures", "Music", "Movies")
WRITE_DIRS = ("Documents", "Desktop", "Downloads")
MARK = "@@NOVA-PLUGIN-RESULT@@"
CALL_TIMEOUT = 30


def available() -> bool:
    return sys.platform == "darwin" and os.access(SANDBOX_EXEC, os.X_OK)


def _q(path: str) -> str:
    return '"' + os.path.realpath(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _runtime_roots() -> list:
    """Folders the Python that runs the plugin lives in (interpreter, standard library, NOVA's code)."""
    roots = {sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.dirname(os.path.realpath(sys.executable)), paths.CODE_DIR}
    meipass = getattr(sys, "_MEIPASS", None)             # packaged app: the unpacked bundle
    if meipass: roots.add(meipass)
    if paths.IS_FROZEN:                                  # …/NOVA.app/Contents
        roots.add(os.path.dirname(os.path.dirname(os.path.realpath(sys.executable))))
    return sorted(os.path.realpath(r) for r in roots if r)


def host_command(plugin_path: str, *tail: str) -> list:
    """The command line that runs plugin_host for this plugin (without the sandbox wrapper)."""
    if paths.IS_FROZEN:
        return [sys.executable, "--plugin-host", plugin_path, *tail]
    return [sys.executable, "-I", os.path.join(paths.CODE_DIR, "plugin_host.py"), plugin_path, *tail]


def data_dir(plugin_path: str) -> str:
    """The plugin's private folder: the only place it can always write."""
    name = os.path.splitext(os.path.basename(plugin_path))[0]
    d = os.path.join(paths.PLUGINS_DIR, ".data", name)
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def profile(perms, plugin_path: str, work: str) -> str:
    """The Seatbelt profile for one plugin: deny everything, then allow the minimum plus `perms`."""
    home = os.path.realpath(os.path.expanduser("~"))
    roots = " ".join(f"(subpath {_q(r)})" for r in _runtime_roots())
    rules = [
        "(version 1)", "(deny default)", '(import "bsd.sb")',
        "(allow process-fork)", f"(allow process-exec {roots})",
        "(allow sysctl-read)", "(allow file-read-metadata)",
        '(allow file-read* (subpath "/usr") (subpath "/System") (subpath "/Library") (subpath "/opt") '
        '(subpath "/private/etc") (subpath "/private/var/db/timezone") (literal "/dev/urandom") (literal "/dev/random") '
        '(literal "/dev/null"))',
        f"(allow file-read* {roots})",
    ]
    if "read_files" in perms:
        rules.append("(allow file-read* " + " ".join(f"(subpath {_q(os.path.join(home, d))})" for d in READ_DIRS) + ")")
    if "write_files" in perms:
        dirs = " ".join(f"(subpath {_q(os.path.join(home, d))})" for d in WRITE_DIRS)
        rules.append(f"(allow file-read* {dirs})"); rules.append(f"(allow file-write* {dirs})")
    if "network" in perms:
        rules += ["(allow network*)", "(allow system-socket)",
                  '(allow mach-lookup (global-name "com.apple.mDNSResponder") (global-name "com.apple.dnssd.service") '
                  '(global-name "com.apple.trustd") (global-name "com.apple.trustd.agent") '
                  '(global-name "com.apple.SystemConfiguration.configd") (global-name "com.apple.SystemConfiguration.DNSConfiguration") '
                  '(global-name "com.apple.networkd") (global-name "com.apple.symptomsd"))',
                  '(allow file-read* (subpath "/private/var/run"))']
    # Later rules win: these stay closed whatever was allowed above.
    protected = [paths.DATA_DIR, paths.LOG_DIR, os.path.join(home, "Library")]
    rules.append("(deny file-read* file-write* " + " ".join(f"(subpath {_q(p)})" for p in protected) + ")")
    rules.append(f"(deny file-write* (subpath {_q(paths.CODE_DIR)}))")
    rules.append('(deny file-read* file-write* (regex #"^' + home.replace(".", "\\.") + '/\\.[^/]+"))')   # ~/.ssh, ~/.zshrc …
    # …except what the Python runtime itself needs when it is installed inside one of those places,
    # the plugin's own file, and its private folder.
    rules.append(f"(allow file-read* {roots})")
    rules.append(f"(allow file-read* (literal {_q(plugin_path)}) (subpath {_q(work)}))")
    rules.append(f'(allow file-write* (subpath {_q(work)}) (literal "/dev/null"))')
    return "\n".join(rules) + "\n"


def run(plugin_path: str, perms, tail: list, stdin_text: str = "", timeout: float = CALL_TIMEOUT, work: str = None) -> dict:
    """Run plugin_host for this plugin inside the sandbox. Returns its answer: {"ok": bool, "result"/"error"/"tools"}.
    `work` is the plugin's private folder (default: plugins/.data/<name> in NOVA's data folder)."""
    if not available():
        return {"ok": False, "error": "The macOS sandbox is not available, so sandboxed plugins cannot run here."}
    if work is None: work = data_dir(plugin_path)
    else: os.makedirs(work, mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".sb", delete=False, encoding="utf-8") as f:
        f.write(profile(set(perms or ()), plugin_path, work)); prof = f.name
    try:
        env = {"PATH": "/usr/bin:/bin", "HOME": work, "TMPDIR": work, "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.run([SANDBOX_EXEC, "-f", prof] + host_command(plugin_path, *tail), input=stdin_text,
                              capture_output=True, text=True, timeout=timeout, cwd=work, env=env,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"The plugin did not answer within {int(timeout)} seconds and was stopped."}
    except OSError as e:
        return {"ok": False, "error": f"Could not start the plugin: {e}"}
    finally:
        try: os.unlink(prof)
        except OSError: pass
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(MARK):
            try: return json.loads(line[len(MARK):])
            except ValueError: break
    err = (proc.stderr or "").strip().splitlines()
    return {"ok": False, "error": "The plugin stopped without an answer" + (f": {err[-1][:200]}" if err else ".")}

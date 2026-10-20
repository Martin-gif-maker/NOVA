import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# A home folder of its own: whatever a test gets wrong with "~" (a folder created, a file deleted) happens in a
# throw-away folder, never in the real Desktop or Documents.
os.environ["HOME"] = tempfile.mkdtemp(prefix="nova_home_")
for _d in ("Desktop", "Documents", "Downloads", "Library"): os.makedirs(os.path.join(os.environ["HOME"], _d))
os.environ["NOVA_DATA_DIR"] = tempfile.mkdtemp(prefix="nova_test_")   # never touch real user data
os.environ["NOVA_NO_MIGRATE"] = "1"
os.environ["NOVA_STRICT_CONFIG"] = "1"                              # a mistyped setting name fails the tests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import keyring
from keyring.backend import KeyringBackend


class MemoryKeyring(KeyringBackend):
    """The tests never read or write the real macOS Keychain."""
    priority = 1
    store = {}
    def get_password(self, service, username): return self.store.get((service, username))
    def set_password(self, service, username, password): self.store[(service, username)] = password
    def delete_password(self, service, username): self.store.pop((service, username), None)


keyring.set_keyring(MemoryKeyring())

# ── no test may reach the internet ─────────────────────────────────
# A test that lets a real tool run (weather, a web page …) is slow when the network is, can time out, and leaves a
# worker thread behind that later crashes the run. Every connection except to this computer fails at once and the
# test is marked failed. (NOVA_LIVE_TESTS=1 lifts this for tests/test_live.py, which talks to the real AI on purpose.)
import socket
_NET_TRIES: list = []
_real_connect = socket.socket.connect
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _guarded_connect(self, address):
    if os.environ.get("NOVA_LIVE_TESTS") != "1" and self.family in (socket.AF_INET, socket.AF_INET6):
        host = str(address[0])
        if not (host.startswith("127.") or host in ("::1", "localhost", "0.0.0.0")):
            import traceback
            here = [f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in traceback.extract_stack()[:-1]
                    if f.filename.startswith(_ROOT) and ".venv" not in f.filename and "conftest" not in f.filename]
            _NET_TRIES.append(f"{host} from {' > '.join(here[-4:]) or 'outside NOVA'}")
            raise ConnectionRefusedError(f"a test tried to reach the internet ({host}) - fake the tool or the server instead")
    return _real_connect(self, address)


socket.socket.connect = _guarded_connect

import platform_utils                                         # the tests never read or write the real "launch at login" entry
if sys.platform == "win32":                                   # …on Windows that is a registry value, as is the nova:// link handler
    platform_utils._RUN_KEY = r"Software\NOVA-tests\Run"
    platform_utils._CLASSES_KEY = r"Software\NOVA-tests\Classes"
else:
    platform_utils._LAUNCH_AGENT = os.path.join(os.environ["NOVA_DATA_DIR"], "LaunchAgents", "com.nova.assistant.plist")

pytest_plugins = ["gui_support"]          # the `app` and `win` fixtures


@pytest.fixture(autouse=True)
def _plain_storage():
    """Every test starts with encryption off and an empty key store."""
    import storage, tools
    MemoryKeyring.store.clear(); storage._state.update(on=False, key=None)
    tools.begin_request()                       # no "read untrusted content" state leaks between tests
    yield
    storage._state.update(on=False, key=None)


@pytest.fixture(autouse=True)
def _no_internet():
    _NET_TRIES.clear()
    yield
    assert not _NET_TRIES, f"this test tried to reach the internet: {sorted(set(_NET_TRIES))}"


@pytest.fixture(autouse=True)
def _no_real_keys():
    """No test may press a real key, change which app is in front or quit one of this computer's apps - whatever it
    forgets to fake.
    (Set directly, not through monkeypatch, so a test's own monkeypatch.undo() cannot lift it.)"""
    def refuse(*a, **k): raise AssertionError("a test tried to press real keys")
    saved = platform_utils._press_cmd, platform_utils.activate_pid, platform_utils.activate_app
    platform_utils._press_cmd = refuse; platform_utils.activate_pid = lambda pid: False
    platform_utils.activate_app = lambda: None                 # …and never pull the test process in front of your work
    send_keys = getattr(platform_utils, "_send_keys", None)    # Windows: the one function every key press goes through
    if send_keys is not None: platform_utils._send_keys = refuse
    real_quit = platform_utils.quit_app
    platform_utils.quit_app = lambda name: []                  # "quit Notes" in a test never reaches your Notes
    yield
    platform_utils._press_cmd, platform_utils.activate_pid, platform_utils.activate_app = saved
    if send_keys is not None: platform_utils._send_keys = send_keys
    platform_utils.quit_app = real_quit


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    """Point every module's storage at a fresh temp folder."""
    import tools, tools_files, games
    monkeypatch.setattr(tools, "MEMORY_FILE", str(tmp_path / "mem.json"))
    monkeypatch.setattr(tools, "REMINDERS_FILE", str(tmp_path / "rem.json"))
    monkeypatch.setattr(tools_files, "NOTES_FILE", str(tmp_path / "notes.txt"))
    monkeypatch.setattr(games, "GAMES_FILE", str(tmp_path / "games.json"))
    import paths
    monkeypatch.setattr(paths, "DOCS_FILE", str(tmp_path / "docs.json"))
    monkeypatch.setattr(paths, "SCHEDULE_FILE", str(tmp_path / "schedule.json"))
    monkeypatch.setattr(paths, "USAGE_FILE", str(tmp_path / "usage.log"))
    return tmp_path


# ── failed tests, in short ─────────────────────────────────────────
# On GitHub the reasons are also written to a small file, which packaging/ci_report.py shows on the run page.
_FAILURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test-failures.txt")


def _note_failure(name: str, report) -> None:
    if not os.environ.get("GITHUB_ACTIONS"): return
    crash = getattr(getattr(report, "longrepr", None), "reprcrash", None)
    reason = crash.message if crash is not None else str(getattr(report, "longrepr", ""))[-400:]
    with open(_FAILURES, "a", encoding="utf-8") as f:
        f.write(f"{name}: {' '.join(str(reason).split())[:420]}\n")


def pytest_runtest_logreport(report):
    if report.failed: _note_failure(report.nodeid + ("" if report.when == "call" else f" [{report.when}]"), report)


def pytest_collectreport(report):
    if report.failed: _note_failure(report.nodeid + " [collect]", report)


# ── clean process exit ─────────────────────────────────────────────
# The tests deliberately leave many windows alive in one process. PySide can segfault when Python
# garbage-collects their signal connections during interpreter shutdown, *after* every test has
# passed, which would turn a green run into exit code 139. The app itself avoids the same phase
# (main.exit_now); the test run does too, once pytest and its plugins have finished reporting.
def pytest_sessionfinish(session, exitstatus):
    session.config._nova_exitstatus = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    if "PySide6.QtWidgets" not in sys.modules:
        return
    try:                                                    # `coverage run -m pytest`: save what was measured first
        import coverage
        cov = coverage.Coverage.current()
        if cov is not None: cov.stop(); cov.save()
    except ImportError:
        pass
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(getattr(config, "_nova_exitstatus", 0))

import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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

import platform_utils                                         # the tests never read or write the real "launch at login" file
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
def _no_real_keys():
    """No test may press a real key or change which app is in front on this Mac - whatever it forgets to fake.
    (Set directly, not through monkeypatch, so a test's own monkeypatch.undo() cannot lift it.)"""
    def refuse(*a, **k): raise AssertionError("a test tried to press real keys")
    saved = platform_utils._press_cmd, platform_utils.activate_pid, platform_utils.activate_app
    platform_utils._press_cmd = refuse; platform_utils.activate_pid = lambda pid: False
    platform_utils.activate_app = lambda: None                 # …and never pull the test process in front of your work
    yield
    platform_utils._press_cmd, platform_utils.activate_pid, platform_utils.activate_app = saved


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

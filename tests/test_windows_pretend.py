"""On a Mac nobody runs the Windows branches of NOVA's code. This starts a separate Python that claims to be Windows
(with stand-ins for the Windows libraries), imports the whole app and builds the window - see pretend_windows.py."""
import os, subprocess, sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.mark.skipif(sys.platform == "win32", reason="on Windows the real thing is tested")
def test_the_app_starts_when_python_says_it_is_windows():
    r = subprocess.run([sys.executable, "-u", os.path.join(HERE, "pretend_windows.py")], capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and r.stdout.strip().endswith("OK"), out[-3000:]
    assert "windows wording: Start with Windows | Moved to Recycle Bin" in out
    assert "calendar tools: []" in out and "'calendar'" not in out.split("groups:")[1].splitlines()[0]
    assert "assistant on Windows" in out and "Ctrl+Q" in out and "notify hook set: True" in out
    assert "The shortcut Ctrl+Alt+Space is already used by another program" in out

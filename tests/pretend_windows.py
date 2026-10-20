"""Run by test_windows_pretend.py on a Mac: import NOVA and build its window while Python claims to be on Windows.

It cannot test Windows itself - only that the Windows branches of NOVA's own code (which the Mac never takes) run
without Python errors: the platform layer is chosen, the tool list and the prompt are the Windows ones, the window
is built with its keyboard shortcuts and tray notifications. Prints OK as its last line."""
import os, sys, tempfile, json, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
data = tempfile.mkdtemp(prefix="nova_pretend_win_")
os.environ["NOVA_DATA_DIR"] = data; os.environ["NOVA_NO_MIGRATE"] = "1"
with open(os.path.join(data, "config.json"), "w") as f:
    json.dump({"onboarded": True, "consent": True, "schema": 2, "provider": "ollama", "keyless": True, "ax_prompted": True}, f)
# everything from outside NOVA is imported while the platform is still the real one
import importlib
for _name in ("subprocess", "asyncio", "socket", "ctypes", "shutil", "threading", "logging", "wave", "zipfile", "hashlib",
              "webbrowser", "urllib.parse", "PySide6.QtWidgets", "PySide6.QtGui", "PySide6.QtCore", "PySide6.QtNetwork",
              "PySide6.QtSvg", "keyring", "psutil", "requests", "numpy", "PIL.Image", "pyperclip", "pygments", "markdown_it",
              "cryptography", "groq", "openai", "anthropic", "sounddevice", "vosk", "edge_tts", "pypdf", "pyautogui"):
    try: importlib.import_module(_name)
    except Exception as e: print(f"({_name} is not here: {e})")
import keyring
from keyring.backend import KeyringBackend
class Mem(KeyringBackend):
    priority = 1; store = {}
    def get_password(self, s, u): return self.store.get((s, u))
    def set_password(self, s, u, p): self.store[(s, u)] = p
    def delete_password(self, s, u): self.store.pop((s, u), None)
keyring.set_keyring(Mem())

sys.platform = "win32"                      # from here on NOVA believes it is on Windows
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plat_windows as pw

class FakeLib:
    def __getattr__(self, name): return lambda *a: 0
pw._win = lambda name: FakeLib()            # no Windows libraries here
pw._powershell = lambda *a, **k: (1, "no powershell on a Mac")
pw._RUN_KEY = r"Software\NOVA-tests\Run"
import platform_utils as plat
assert plat is pw, "the Windows layer was not chosen"
import i18n, paths, prompts, schemas, main, ipc, docs
for _name in ("tools", "updater", "whatsnew", "selftest"): importlib.import_module(_name)
print("data dir rule:", paths._data_dir.__name__, "| windows wording:", i18n.tr("Launch at login"), "|", i18n.tr("Moved to Trash"))
print("groups:", sorted(schemas.GROUPS))
print("tools offered:", len(schemas.TOOLS_SCHEMA), "| calendar tools:", [s["function"]["name"] for s in schemas.TOOLS_SCHEMA if "calendar" in s["function"]["name"]])
print("prompt:", [l for l in prompts._build_prompt("hi").splitlines() if "Windows" in l or "more_tools" in l])
print("pipe:", ipc.server_name(), "| docs on windows:", docs.ON_WINDOWS)

from PySide6.QtWidgets import QApplication
app = QApplication([])
plat.start_global_hotkey = lambda cb: False                 # pretend another program owns the shortcut
W = main.AssistantWindow
for name in ("_start_wake_listener", "_maybe_morning_briefing", "_start_spotify_monitor", "_tag_memories", "_refresh_documents", "_auto_update_check"):
    setattr(W, name, lambda self: None)
w = W()
end = time.time() + 2.5
while time.time() < end: app.processEvents(); time.sleep(0.01)
texts = []
def walk(widget):
    from PySide6.QtWidgets import QLabel
    for lbl in widget.findChildren(QLabel):
        t = lbl.text()
        if t and len(t) > 25: texts.append(t)
walk(w)
print("window built:", type(w).__name__, "| shortcuts on the window:", sorted(a.shortcut().toString() for a in w.actions() if not a.shortcut().isEmpty()))
print("notify hook set:", plat.NOTIFY_HOOK is not None, "| tray tooltip:", w._tray.toolTip())
print("hotkey notice:", [t[:110] for t in texts if "already used" in t][:1])
plat.notify("NOVA", "hello from the pretend PC", 1000)
w._shutdown()
print("notify hook after shutdown:", plat.NOTIFY_HOOK)
print("OK", flush=True)
os._exit(0)

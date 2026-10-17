# PyInstaller spec — builds NOVA.app.   Run via packaging/build_mac.sh
import os, re, glob
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs, collect_data_files

block_cipher = None
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', open("paths.py", encoding="utf-8").read()).group(1)   # one place: paths.py
hidden = (collect_submodules("keyring.backends") + collect_submodules("edge_tts") +
          collect_submodules("ddgs") + collect_submodules("pygments.lexers") + collect_submodules("pygments.styles") +
          ["markdown_it", "linkify_it", "mdurl"] + ["AppKit", "Quartz", "ApplicationServices", "AVFoundation", "sounddevice"] +
          # AI providers, on-device speech, encryption, and the modules NOVA imports lazily
          collect_submodules("anthropic") + collect_submodules("openai") + ["groq", "vosk", "cffi", "_cffi_backend",
          "cryptography.hazmat.primitives.ciphers.aead", "provider_anthropic", "provider_openai", "plugin_host",
          "sandbox", "storage", "ledger", "crash", "memory", "speech", "mac_apps", "eventkit_helper", "EventKit", "Vision", "docs", "schedule", "modes", "mcp_client", "ipc",
          "PySide6.QtNetwork"] +
          # every module of NOVA itself, including the ones that are only imported when first needed
          [os.path.splitext(f)[0] for f in glob.glob("*.py") if f not in ("main.py", "create_shortcut.py")])

# vosk loads its native library (libvosk.dyld) from inside the package folder at run time
vosk_bins = collect_dynamic_libs("vosk")
try:
    import vosk as _vosk
    _lib = os.path.join(os.path.dirname(_vosk.__file__), "libvosk.dyld")
    if os.path.exists(_lib) and not any(os.path.basename(b[0]) == "libvosk.dyld" for b in vosk_bins):
        vosk_bins.append((_lib, "vosk"))
except ImportError:
    pass
extra_datas = collect_data_files("certifi")          # CA bundle for https (providers, updates, weather)
extra_datas += collect_data_files("numbers_parser")  # its empty-document template and data tables
hidden += collect_submodules("numbers_parser")
hidden += ["xlrd"]                                     # old .xls files (imported only when one is opened)
hidden += ["PySide6.QtSvg"]                            # the line icons are drawn from SVG
hidden += ["onnxruntime", "tokenizers"]                # search by meaning (embeddings.py, imported when first used)

a = Analysis(["main.py"], pathex=["."], binaries=vosk_bins, datas=[("nova.icns", ".")] + extra_datas,
             hiddenimports=hidden, excludes=["tkinter", "matplotlib", "scipy", "pytest", "PyQt6", "PyQt5", "PySide2",
             # pulled in by `tokenizers` but never used: NOVA downloads the model itself (embeddings.py)
             "huggingface_hub", "hf_xet", "fsspec", "onnxruntime.training", "onnxruntime.tools", "onnxruntime.transformers"], noarchive=False)
# Qt's on-screen keyboard plugin is not used on a Mac, and it is the only thing that pulls in Qt Quick / QML / OpenGL (17 MB).
_UNUSED_QT = ("QtQuick", "QtQml", "QtVirtualKeyboard", "QtOpenGL", "libqtvirtualkeyboardplugin")
# onnxruntime also ships its C library for other programs (32 MB); the Python binding NOVA uses has it all built in.
_UNUSED_LIBS = _UNUSED_QT + ("libonnxruntime.",)
a.binaries = [b for b in a.binaries if not any(u in b[0] for u in _UNUSED_LIBS)]
a.datas = [d for d in a.datas if not any(u in d[0] for u in _UNUSED_QT)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="NOVA", console=False,
          argv_emulation=False, target_arch=None, codesign_identity=os.environ.get("NOVA_SIGN_ID"),
          entitlements_file="packaging/entitlements.plist")
coll = COLLECT(exe, a.binaries, a.datas, name="NOVA")
app = BUNDLE(coll, name="NOVA.app", icon="nova.icns", bundle_identifier="com.nova.assistant",
             version=VERSION,
             info_plist={
                 "CFBundleDisplayName": "NOVA", "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
                 "LSMinimumSystemVersion": "12.0", "NSHighResolutionCapable": True,
                 "CFBundleURLTypes": [{"CFBundleURLName": "com.nova.assistant.ask", "CFBundleURLSchemes": ["nova"]}],   # nova://ask?text=…
                 "NSMicrophoneUsageDescription": "NOVA listens for voice commands and the optional wake word.",
                 "NSAppleEventsUsageDescription": "NOVA controls apps such as Mail, your browser, Spotify and Finder when you ask it to.",
                 "NSCalendarsFullAccessUsageDescription": "NOVA reads and adds calendar events when you ask it to.",
                 "NSCalendarsUsageDescription": "NOVA reads and adds calendar events when you ask it to.",
                 "NSRemindersFullAccessUsageDescription": "NOVA reads and adds reminders when you ask it to.",
                 "NSRemindersUsageDescription": "NOVA reads and adds reminders when you ask it to.",
                 "NSScreenCaptureUsageDescription": "NOVA looks at your screen when you ask it to analyse it.",
                 "NSDesktopFolderUsageDescription": "NOVA saves screenshots and exports to your Desktop when you ask.",
             })

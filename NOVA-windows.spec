# PyInstaller spec — builds the Windows app: dist/NOVA/NOVA.exe (no console window) and, next to it,
# NOVA-cli.exe (the same program with a console, so `NOVA-cli --ask "…" --wait` can print its answer).
# Run via packaging/build_windows.ps1
import os, re, glob
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs, collect_data_files

VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', open("paths.py", encoding="utf-8").read()).group(1)   # one place: paths.py
hidden = (collect_submodules("keyring.backends") + collect_submodules("edge_tts") +
          collect_submodules("ddgs") + collect_submodules("pygments.lexers") + collect_submodules("pygments.styles") +
          ["markdown_it", "linkify_it", "mdurl", "sounddevice", "win32ctypes.core", "pyperclip", "pypdf"] +
          # AI providers, on-device speech, encryption, and the modules NOVA imports lazily
          collect_submodules("anthropic") + collect_submodules("openai") + ["groq", "vosk", "cffi", "_cffi_backend",
          "cryptography.hazmat.primitives.ciphers.aead", "PySide6.QtNetwork", "PySide6.QtSvg", "xlrd"] +
          collect_submodules("numbers_parser") +
          ["onnxruntime", "tokenizers"] +                  # search by meaning (embeddings.py, imported when first used)
          ["pywhispercpp", "pywhispercpp.model", "_pywhispercpp"] +   # speech in any language (speech.py, on first use)
          # every module of NOVA itself, including the ones that are only imported when first needed
          [os.path.splitext(f)[0] for f in glob.glob("*.py") if f not in ("main.py", "create_shortcut.py")])

vosk_bins = collect_dynamic_libs("vosk")             # libvosk.dll and the runtime libraries beside it
extra_datas = collect_data_files("certifi")          # CA bundle for https (providers, updates, weather)
extra_datas += collect_data_files("numbers_parser")  # its empty-document template and data tables

a = Analysis(["main.py"], pathex=["."], binaries=vosk_bins, datas=[("nova.ico", ".")] + extra_datas,
             hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "scipy", "pytest", "PyQt6", "PyQt5", "PySide2",
                       "AppKit", "Quartz", "Foundation", "objc", "EventKit", "Vision", "AVFoundation", "ApplicationServices",
                       # pulled in by `tokenizers` but never used: NOVA downloads the model itself (embeddings.py)
                       "huggingface_hub", "hf_xet", "fsspec", "onnxruntime.training", "onnxruntime.tools",
                       "onnxruntime.transformers"],
             noarchive=False)
# Qt's on-screen keyboard plugin is not used, and it is the only thing that pulls in Qt Quick / QML / OpenGL.
_UNUSED_QT = ("Qt6Quick", "Qt6Qml", "Qt6VirtualKeyboard", "Qt6OpenGL", "qtvirtualkeyboardplugin", "opengl32sw")
a.binaries = [b for b in a.binaries if not any(u.lower() in b[0].lower() for u in _UNUSED_QT)]
a.datas = [d for d in a.datas if not any(u.lower() in d[0].lower() for u in _UNUSED_QT)]
pyz = PYZ(a.pure)

# The details Windows shows under Properties → Details
os.makedirs("build_win", exist_ok=True)
_nums = tuple(int(x) for x in (re.findall(r"\d+", VERSION) + ["0"] * 4)[:4])
with open(os.path.join("build_win", "version_info.txt"), "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={_nums}, prodvers={_nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Martin'),
      StringStruct('FileDescription', 'NOVA'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'NOVA'),
      StringStruct('OriginalFilename', 'NOVA.exe'),
      StringStruct('ProductName', 'NOVA'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""")
_common = dict(exclude_binaries=True, icon="nova.ico", version=os.path.join("build_win", "version_info.txt"))
exe = EXE(pyz, a.scripts, [], name="NOVA", console=False, **_common)
cli = EXE(pyz, a.scripts, [], name="NOVA-cli", console=True, **_common)
coll = COLLECT(exe, cli, a.binaries, a.datas, name="NOVA")

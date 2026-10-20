"""
Run this once (setup_mac.command / setup_windows.bat do) to:
  macOS    1. create the NOVA icon (nova.icns)
           2. create NOVA.app in ~/Applications, so NOVA is in Spotlight and Launchpad and can be dragged to the Dock
  Windows  1. create the NOVA icon (nova.ico)
           2. put a NOVA shortcut in the Start menu
"""
import os, sys, shlex, shutil, plistlib, subprocess

HELPER_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_PY    = os.path.join(HELPER_DIR, "main.py")
ICNS_PATH  = os.path.join(HELPER_DIR, "nova.icns")
ICO_PATH   = os.path.join(HELPER_DIR, "nova.ico")

from PIL import Image, ImageDraw, ImageFont

ACCENT = (83, 74, 183)       # #534AB7 — NOVA's purple
BG     = (245, 245, 247)     # #f5f5f7 soft light

FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
]


def _version() -> str:
    """NOVA's version, read from paths.py (without importing it - that would create the data folder)."""
    import re
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "paths.py"), encoding="utf-8") as f:
            return re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)
    except Exception:
        return "6"


def _load_font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size)               # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def draw_icon(sz):
    """One square RGBA frame of the NOVA icon at `sz` px."""
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # outer glow ring
    ring = int(sz * 0.04)
    draw.ellipse([ring, ring, sz - ring - 1, sz - ring - 1], fill=(*ACCENT, 40))
    # main circle
    pad = int(sz * 0.08)
    draw.ellipse([pad, pad, sz - pad - 1, sz - pad - 1], fill=ACCENT)

    # "N" letter
    font = _load_font(int(sz * 0.46))
    text = "N"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (sz - tw) // 2 - bbox[0]
    ty = (sz - th) // 2 - bbox[1]
    draw.text((tx, ty), text, fill=(255, 255, 255), font=font)
    return img


# ── macOS ────────────────────────────────────────────────────────
def make_mac():
    """Build ~/Applications/NOVA.app as a real AppleScript applet.

    (A bundle whose executable is a plain shell script is rejected by recent macOS versions with
    LaunchServices error -10669, so Spotlight / the Dock could not open it.)"""
    draw_icon(1024).save(ICNS_PATH, format="ICNS")        # Pillow generates all sizes
    print(f"✔  Icon created:  {ICNS_PATH}")

    apps_dir = os.path.expanduser("~/Applications")
    app      = os.path.join(apps_dir, "NOVA.app")
    os.makedirs(apps_dir, exist_ok=True)
    tmp_app  = os.path.join(apps_dir, ".NOVA-build.app")     # osacompile only builds an applet if the name ends in .app
    if os.path.exists(tmp_app):
        shutil.rmtree(tmp_app)

    py, main = shlex.quote(sys.executable), shlex.quote(MAIN_PY)
    script = ("#!/bin/bash\n"
              "export PATH=/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$PATH\n"
              f"cd {shlex.quote(HELPER_DIR)} 2>/dev/null || {{\n"
              "  osascript -e 'display alert \"NOVA\" message \"The NOVA folder moved. Re-run setup_mac.command.\"'; exit 1; }\n"
              f"[ -x {py} ] || {{ osascript -e 'display alert \"NOVA\" message \"Python environment not found. Re-run setup_mac.command.\"'; exit 1; }}\n"
              "mkdir -p \"$HOME/Library/Logs\"\n"
              f"exec {py} {main} >> \"$HOME/Library/Logs/NOVA.log\" 2>&1\n")
    applescript = ('on run\n'
                   '  set launcher to (POSIX path of (path to me)) & "Contents/Resources/launch.sh"\n'
                   '  do shell script "nohup " & quoted form of launcher & " >/dev/null 2>&1 &"\n'
                   'end run\n'
                   'on reopen\n'
                   '  run\n'
                   'end reopen\n')
    src = os.path.join(HELPER_DIR, ".launcher.applescript")
    with open(src, "w") as f: f.write(applescript)
    try:
        subprocess.run(["osacompile", "-o", tmp_app, src], check=True, capture_output=True)
    finally:
        os.remove(src)
    res = os.path.join(tmp_app, "Contents", "Resources")
    launcher = os.path.join(res, "launch.sh")
    with open(launcher, "w") as f: f.write(script)
    os.chmod(launcher, 0o755)
    shutil.copy(ICNS_PATH, os.path.join(res, "applet.icns"))

    plist_path = os.path.join(tmp_app, "Contents", "Info.plist")
    with open(plist_path, "rb") as f: info = plistlib.load(f)
    info.update({
        "CFBundleName": "NOVA", "CFBundleDisplayName": "NOVA", "CFBundleIdentifier": "com.nova.assistant",
        "CFBundleShortVersionString": _version(), "CFBundleVersion": _version(), "LSUIElement": False,
        "NSMicrophoneUsageDescription": "NOVA listens for the wake word and voice commands.",
        "NSAppleEventsUsageDescription": "NOVA controls apps such as Mail, your browser, Spotify and Finder on request.",
        "NSCalendarsFullAccessUsageDescription": "NOVA reads and adds calendar events when you ask it to.",
        "NSCalendarsUsageDescription": "NOVA reads and adds calendar events when you ask it to.",
        "NSRemindersFullAccessUsageDescription": "NOVA reads and adds reminders when you ask it to.",
        "NSRemindersUsageDescription": "NOVA reads and adds reminders when you ask it to.",
    })
    with open(plist_path, "wb") as f: plistlib.dump(info, f)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", tmp_app], capture_output=True)   # re-seal after edits

    if os.path.exists(app):
        shutil.rmtree(app)
    os.rename(tmp_app, app)
    os.utime(app)                                           # nudge Finder to refresh the icon

    print(f"✔  App created:   {app}")
    print("\nOpen it from Spotlight (⌘Space → NOVA), Launchpad, or drag it to your Dock.")
    print("\nmacOS attributes permissions (Accessibility, Microphone, Screen Recording) to the")
    print(f"program that runs NOVA. Grant them to:  {os.path.realpath(sys.executable)}")
    print("Errors are logged to ~/Library/Logs/NOVA.log")


# ── Windows ──────────────────────────────────────────────────────
def make_ico(path: str = ICO_PATH) -> str:
    """The icon as a Windows .ico holding every size the taskbar, Start menu and Explorer ask for."""
    draw_icon(256).save(path, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    return path


def windows_shortcut_command() -> tuple:
    """(program, arguments) the Start menu shortcut runs: the windowless Python of this environment and main.py."""
    exe = sys.executable
    if os.path.basename(exe).lower() == "python.exe":
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(pyw): exe = pyw
    return exe, f'"{MAIN_PY}"'


def make_windows():
    if not os.path.exists(ICO_PATH): make_ico()
    programs = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")
    os.makedirs(programs, exist_ok=True)
    lnk = os.path.join(programs, "NOVA.lnk")
    target, args = windows_shortcut_command()
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:NOVA_LNK); "
              "$s.TargetPath = $env:NOVA_TARGET; $s.Arguments = $env:NOVA_ARGS; $s.WorkingDirectory = $env:NOVA_DIR; "
              "$s.IconLocation = $env:NOVA_ICON; $s.Description = 'NOVA - AI assistant'; $s.Save()")
    env = dict(os.environ, NOVA_LNK=lnk, NOVA_TARGET=target, NOVA_ARGS=args, NOVA_DIR=HELPER_DIR, NOVA_ICON=ICO_PATH)
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env, check=True)
    print(f"Shortcut created:  {lnk}")
    print("Open NOVA from the Start menu (type NOVA), or pin it to the taskbar from there.")


if __name__ == "__main__":
    if "--icon-only" in sys.argv: print(make_ico())          # for the build script
    elif sys.platform == "win32": make_windows()
    else: make_mac()

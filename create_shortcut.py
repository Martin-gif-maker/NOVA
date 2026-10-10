"""
Run this once (setup_mac.command does) to:
  1. create the NOVA icon (nova.icns)
  2. create NOVA.app in ~/Applications, so NOVA is in Spotlight and Launchpad and can be dragged to the Dock
"""
import os, sys, shlex, shutil, plistlib, subprocess

HELPER_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_PY    = os.path.join(HELPER_DIR, "main.py")
ICNS_PATH  = os.path.join(HELPER_DIR, "nova.icns")

from PIL import Image, ImageDraw, ImageFont

ACCENT = (83, 74, 183)       # #534AB7 — NOVA's purple
BG     = (245, 245, 247)     # #f5f5f7 soft light

FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
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


if __name__ == "__main__":
    make_mac()

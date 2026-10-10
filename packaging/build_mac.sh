#!/bin/bash
# Build NOVA.app (+ optional signing, notarization and a .dmg).
#
#   ./packaging/build_mac.sh                      unsigned build (runs on this Mac; others get a Gatekeeper warning)
#   NOVA_SIGN_ID="Developer ID Application: Your Name (TEAMID)" ./packaging/build_mac.sh
#   ... plus NOVA_NOTARY_PROFILE=<keychain profile from `xcrun notarytool store-credentials`> to notarize
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install --quiet -r requirements.lock 2>/dev/null || pip install --quiet -r requirements.txt pyinstaller

DIST="${NOVA_DIST:-dist}"                      # NOVA_DIST=dist_next builds next to an app that is still open
if pgrep -f "$PWD/$DIST/NOVA.app/Contents/MacOS/NOVA" >/dev/null 2>&1; then
  echo "✖ NOVA is running from $DIST/NOVA.app - quit it first (or build elsewhere: NOVA_DIST=dist_next $0)"; exit 1
fi
rm -rf "build_$DIST" "$DIST"
pyinstaller --noconfirm --distpath "$DIST" --workpath "build_$DIST" NOVA.spec
APP="$DIST/NOVA.app"

echo "▶ self-test"                              # with a throw-away data folder: the build never touches your own
NOVA_DATA_DIR="$(mktemp -d)" NOVA_NO_MIGRATE=1 "$APP/Contents/MacOS/NOVA" --selftest

if [ -n "${NOVA_SIGN_ID:-}" ]; then
  echo "▶ signing"
  codesign --force --deep --options runtime --timestamp \
           --entitlements packaging/entitlements.plist --sign "$NOVA_SIGN_ID" "$APP"
  codesign --verify --deep --strict "$APP"
else
  echo "⚠ NOVA_SIGN_ID not set - the app is unsigned (ad-hoc)."
  codesign --force --deep --sign - --entitlements packaging/entitlements.plist "$APP" || true
fi

VERSION=$(sed -n 's/^__version__ *= *"\(.*\)"/\1/p' paths.py)
DMG="$DIST/NOVA-$VERSION.dmg"
echo "▶ dmg"
hdiutil create -volname NOVA -srcfolder "$APP" -ov -format UDZO "$DMG" >/dev/null

if [ -n "${NOVA_SIGN_ID:-}" ] && [ -n "${NOVA_NOTARY_PROFILE:-}" ]; then
  echo "▶ notarizing (takes a few minutes)"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOVA_NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
fi
echo "✔ $APP  and  $DMG"

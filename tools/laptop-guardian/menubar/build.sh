#!/bin/bash
# Builds Guardian.app (the shield in the menu bar) with Apple's Command Line Tools: no Xcode,
# no packages. `guardian.py menu install` runs this and puts the result in ~/Applications.
set -euo pipefail
cd "$(dirname "$0")"
OUT=build
APP="$OUT/Guardian.app"
rm -rf "$OUT"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
# Built for the Mac it is built on. An app marked "macOS 13.0 or later" does not open on
# macOS 12, so an older Mac gets its own version as the floor; a newer one keeps 13.0.
# GUARDIAN_MACOS_MIN overrides it (to try an older floor from a newer Mac).
HOST="$(sw_vers -productVersion)"
MAJOR="${HOST%%.*}"
REST="${HOST#*.}"
MINOR="${REST%%.*}"
if [ "$MAJOR" -ge 13 ]; then MIN=13.0
elif [ "$MAJOR" -ge 11 ]; then MIN="$MAJOR.0"
elif [ "$MAJOR" -eq 10 ] && [ "$MINOR" -ge 15 ]; then MIN=10.15
else
  echo "The menu bar app needs macOS 10.15 or newer; this Mac has $HOST. The helper works without it." >&2
  exit 1
fi
MIN="${GUARDIAN_MACOS_MIN:-$MIN}"
swiftc -O -swift-version 5 -target "$(uname -m)-apple-macos$MIN" main.swift -o "$APP/Contents/MacOS/Guardian"
cp Info.plist "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :LSMinimumSystemVersion $MIN" "$APP/Contents/Info.plist"
ICONSET="$OUT/AppIcon.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  "$APP/Contents/MacOS/Guardian" --icon "$ICONSET/icon_${s}x${s}.png" "$s"
  "$APP/Contents/MacOS/Guardian" --icon "$ICONSET/icon_${s}x${s}@2x.png" "$((s * 2))"
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET"
codesign --force --sign - "$APP" >/dev/null 2>&1
echo "built $APP (for macOS $MIN and newer)"

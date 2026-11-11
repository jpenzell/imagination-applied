#!/bin/bash
# Builds Guardian.app (the shield in the menu bar) with Apple's Command Line Tools: no Xcode,
# no packages. `guardian.py menu install` runs this and puts the result in ~/Applications.
set -euo pipefail
cd "$(dirname "$0")"
OUT=build
APP="$OUT/Guardian.app"
rm -rf "$OUT"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -swift-version 5 -target "$(uname -m)-apple-macos13.0" main.swift -o "$APP/Contents/MacOS/Guardian"
cp Info.plist "$APP/Contents/Info.plist"
ICONSET="$OUT/AppIcon.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  "$APP/Contents/MacOS/Guardian" --icon "$ICONSET/icon_${s}x${s}.png" "$s"
  "$APP/Contents/MacOS/Guardian" --icon "$ICONSET/icon_${s}x${s}@2x.png" "$((s * 2))"
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET"
codesign --force --sign - "$APP" >/dev/null 2>&1
echo "built $APP"

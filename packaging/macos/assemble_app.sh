#!/usr/bin/env bash
# Assemble Rig Relay.app with SwiftUI shell + PyInstaller helper
#
# Prerequisites:
#   - PyInstaller helper already built (packaging/macos/build_pyinstaller.sh)
#   - SwiftUI shell already built (macos/RigRelayShell/.build/release/RigRelayShell)
#
# Output: dist/Rig Relay.app (SwiftUI app with bundled helper)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SWIFT_BUILD="$REPO_ROOT/macos/RigRelayShell/.build/release/RigRelayShell"
HELPER_DIR="$REPO_ROOT/dist/RigRelayHelper"
DIST_DIR="$REPO_ROOT/dist"
APP="$DIST_DIR/Rig Relay.app"

cd "$REPO_ROOT"

echo "=== Assembling Rig Relay.app ==="

# ── 1. Verify inputs ──────────────────────────────────────────────

if [ ! -f "$SWIFT_BUILD" ]; then
    echo "ERROR: SwiftUI shell not built. Run:"
    echo "  cd macos/RigRelayShell && xcrun swift build -c release"
    exit 1
fi

if [ ! -d "$HELPER_DIR" ]; then
    echo "Building PyInstaller helper first..."
    ./packaging/macos/build_pyinstaller.sh
fi

if [ ! -f "$HELPER_DIR/RigRelay" ]; then
    echo "ERROR: Helper not found at $HELPER_DIR/RigRelay"
    exit 1
fi

echo "  SwiftUI shell: $SWIFT_BUILD"
echo "  Helper: $HELPER_DIR"

# ── 2. Create app bundle structure ─────────────────────────────────

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
mkdir -p "$APP/Contents/Resources/RigRelayHelper"

# ── 3. Copy SwiftUI executable ─────────────────────────────────────

cp "$SWIFT_BUILD" "$APP/Contents/MacOS/RigRelayShell"
chmod +x "$APP/Contents/MacOS/RigRelayShell"

# ── 4. Copy PyInstaller helper ─────────────────────────────────────

cp -R "$HELPER_DIR/"* "$APP/Contents/Resources/RigRelayHelper/"
chmod +x "$APP/Contents/Resources/RigRelayHelper/RigRelay"

# ── 5. Copy frontend/docs if not already in helper ─────────────────

if [ ! -d "$APP/Contents/Resources/frontend" ]; then
    cp -R frontend/desktop "$APP/Contents/Resources/frontend/desktop" 2>/dev/null || true
fi
if [ ! -d "$APP/Contents/Resources/docs" ]; then
    cp -R docs/demo "$APP/Contents/Resources/docs/demo" 2>/dev/null || true
fi

# ── 6. Info.plist ──────────────────────────────────────────────────

cat > "$APP/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>en</string>
	<key>CFBundleDisplayName</key>
	<string>Rig Relay</string>
	<key>CFBundleExecutable</key>
	<string>RigRelayShell</string>
	<key>CFBundleIdentifier</key>
	<string>es.juliantorres.rigrelay</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>Rig Relay</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>0.2.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>LSMinimumSystemVersion</key>
	<string>14.0</string>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>NSSupportsAutomaticGraphicsSwitching</key>
	<true/>
	<key>NSHumanReadableCopyright</key>
	<string>Local governed runtime for agent work. No account, API key, network, merge, or push required.</string>
</dict>
</plist>
PLIST

# ── 7. Ad-hoc sign ─────────────────────────────────────────────────

codesign --force --deep --sign - "$APP" 2>/dev/null && \
    echo "  Signed: ad-hoc" || echo "  Signing: skipped"

# ── 8. Zip ─────────────────────────────────────────────────────────

rm -f "$DIST_DIR/Rig Relay.app.zip"
ditto -c -k --keepParent "$APP" "$DIST_DIR/Rig Relay.app.zip"

echo ""
echo "=== Assembly complete ==="
echo "App:  $APP"
echo "Size: $(du -sh "$APP" | cut -f1)"
echo "Zip:  $DIST_DIR/Rig Relay.app.zip ($(du -sh "$DIST_DIR/Rig Relay.app.zip" | cut -f1))"
echo ""
echo "Contents:"
echo "  MacOS/RigRelayShell          — SwiftUI launcher"
echo "  Resources/RigRelayHelper/    — Python/pywebview cockpit"
echo "  Info.plist                   — Bundle metadata"

#!/bin/bash
set -euo pipefail

# ── Rig Relay macOS App Builder (X4) ──────────────────────
# Builds the RigRelayShell SPM executable and bundles it into
# a .app package suitable for codesign / notarization.
#
# Usage: ./build-app.sh [--release|--debug] [--sign IDENTITY]
#
# Output: macos/.build/bundle/RigRelayShell.app/

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../RigRelayShell" && pwd)"
BUILD_DIR="$PROJECT_DIR/.build"
BUNDLE_DIR="$BUILD_DIR/bundle"
APP_DIR="$BUNDLE_DIR/RigRelayShell.app"
CONTENTS="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS/MacOS"
RESOURCES_DIR="$CONTENTS/Resources"
FRAMEWORKS_DIR="$CONTENTS/Frameworks"
PLUGINS_DIR="$CONTENTS/PlugIns"

CONFIG="${1:-debug}"
if [[ "$CONFIG" == "--release" ]]; then
	CONFIG="release"
	BUILD_ARGS="-c release"
elif [[ "$CONFIG" == "--debug" ]]; then
	CONFIG="debug"
	BUILD_ARGS=""
else
	CONFIG="debug"
	BUILD_ARGS=""
fi

IDENTITY="${2:-}"

echo "=== Rig Relay App Builder (X4) ==="
echo "  Configuration: $CONFIG"
[[ -n "$IDENTITY" ]] && echo "  Signing identity: $IDENTITY"

# ── Step 1: Build SPM executable ──────────────────────────
echo ""
echo "[1/5] Building RigRelayShell executable..."
cd "$PROJECT_DIR"
swift build $BUILD_ARGS

EXECUTABLE_PATH=$(swift build $BUILD_ARGS --show-bin-path)/RigRelayShell
if [[ ! -f "$EXECUTABLE_PATH" ]]; then
	echo "ERROR: Build failed — executable not found at $EXECUTABLE_PATH"
	exit 1
fi

BUILD_VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$SCRIPT_DIR/../Resources/Info.plist" 2>/dev/null || echo "1")
SHORT_VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$SCRIPT_DIR/../Resources/Info.plist" 2>/dev/null || echo "0.1.0")

echo "  Executable: $EXECUTABLE_PATH"
echo "  Version: $SHORT_VERSION ($BUILD_VERSION)"

# ── Step 2: Create .app bundle structure ──────────────────
echo ""
echo "[2/5] Creating .app bundle at $APP_DIR..."
rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$FRAMEWORKS_DIR" "$PLUGINS_DIR"

cp "$EXECUTABLE_PATH" "$MACOS_DIR/RigRelayShell"
chmod +x "$MACOS_DIR/RigRelayShell"

# ── Step 3: Copy resources ────────────────────────────────
echo "[3/5] Copying bundle resources..."

cp "$SCRIPT_DIR/../Resources/Info.plist" "$CONTENTS/Info.plist"

if [[ -d "$PROJECT_DIR/Sources/RigRelayShell/Resources/GridlineFrontend" ]]; then
	cp -R "$PROJECT_DIR/Sources/RigRelayShell/Resources/GridlineFrontend" "$RESOURCES_DIR/"
else
	echo "  WARNING: GridlineFrontend resources not found — app will fail to load"
fi

# Add third-party notices and license files
if [[ -f "$SCRIPT_DIR/../../THIRD_PARTY_NOTICES.md" ]]; then
	cp "$SCRIPT_DIR/../../THIRD_PARTY_NOTICES.md" "$RESOURCES_DIR/"
fi
if [[ -f "$SCRIPT_DIR/../../LICENSE" ]]; then
	cp "$SCRIPT_DIR/../../LICENSE" "$RESOURCES_DIR/"
fi

# ── Step 4: Entitlements check ────────────────────────────
echo "[4/5] Validating entitlements..."
ENTITLEMENTS="$SCRIPT_DIR/../Resources/RigRelayShell.entitlements"
if [[ -f "$ENTITLEMENTS" ]]; then
	/usr/libexec/PlistBuddy -c "Print" "$ENTITLEMENTS" >/dev/null 2>&1 &&
		echo "  Entitlements: valid plist" ||
		echo "  WARNING: Entitlements plist validation failed"
else
	echo "  WARNING: No entitlements file found at $ENTITLEMENTS"
fi

# ── Step 5: Signing (if identity provided) ────────────────
echo "[5/5] Code signing..."
if [[ -n "$IDENTITY" ]]; then
	if [[ "$IDENTITY" == "--sign" ]] && [[ -n "${3:-}" ]]; then
		IDENTITY="$3"
	fi

	# Sign with hardened runtime for notarization
	codesign --force --options runtime --timestamp \
		--entitlements "$ENTITLEMENTS" \
		--sign "$IDENTITY" \
		"$APP_DIR" 2>&1 || {
		echo "  WARNING: codesign failed. Check identity '$IDENTITY' is in keychain."
	}
	echo "  Signed with: $IDENTITY"
else
	echo "  Skipped — no signing identity provided"
fi

# ── Summary ───────────────────────────────────────────────
echo ""
echo "=== Build Complete ==="
echo "  App:  $APP_DIR"
echo "  Version: $SHORT_VERSION ($BUILD_VERSION)"
echo "  Config: $CONFIG"
echo ""
echo "  Bundle contents:"
find "$APP_DIR" -type f | sed "s|$APP_DIR|  Contents|" | sort
echo ""
echo "  To sign:  ./build-app.sh --release --sign 'Developer ID Application: ...'"
echo "  To notarize: ./prepare-signing.sh notarize 'Developer ID Application: ...'"

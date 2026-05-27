#!/bin/bash
set -euo pipefail

# ── Rig Relay macOS Unified App Builder (X4.4) ─────────────
# Builds the RigRelayShell SPM SwiftUI app AND the Xcode
# Safari Web Extension .appex, then bundles them into one
# unified .app package suitable for codesign / notarization.
#
# This is the single declared product build route:
#   SPM app (SwiftUI, WebKit, native bridge)
#   + Xcode extension (.appex, Safari handler)
#   = RigRelayShell.app with embedded extension
#
# Usage: ./build-app.sh [--release|--debug] [--sign IDENTITY]
#        ./build-app.sh --skip-extension [--release]  # build without extension
#
# Output: macos/.build/bundle/RigRelayShell.app/

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../RigRelayShell" && pwd)"
BUILD_DIR="$PROJECT_DIR/.build"
BUNDLE_DIR="$BUILD_DIR/bundle"
APP_DIR="$BUNDLE_DIR/RigRelayShell.app"
CONTENTS="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS/MacOS"
RESOURCES_DIR="$CONTENTS/Resources"
FRAMEWORKS_DIR="$CONTENTS/Frameworks"
PLUGINS_DIR="$CONTENTS/PlugIns"

XCODE_PROJECT="$REPO_ROOT/macos/SafariExtension/SafariExtension.xcodeproj/RigRelayShell/RigRelayShell.xcodeproj"
EXTENSION_TARGET="RigRelayShell Extension"
EXTENSION_BUILD_DIR="$BUILD_DIR/xcode-build"

SKIP_EXTENSION=false
IDENTITY=""

# Parse args
while [[ $# -gt 0 ]]; do
	case "$1" in
	--release)
		CONFIG="release"
		shift
		;;
	--debug)
		CONFIG="debug"
		shift
		;;
	--skip-extension)
		SKIP_EXTENSION=true
		shift
		;;
	--sign)
		IDENTITY="${2:-}"
		if [[ -z "$IDENTITY" ]]; then
			echo "ERROR: --sign requires an identity argument"
			exit 1
		fi
		shift 2
		;;
	*)
		# legacy positional: first extra arg treated as config, second as identity
		if [[ "$1" == "--release" || "$1" == "--debug" ]]; then
			CONFIG="${1#--}"
		else
			IDENTITY="$1"
		fi
		shift
		;;
	esac
done

CONFIG="${CONFIG:-debug}"
if [[ "$CONFIG" == "release" ]]; then
	BUILD_ARGS="-c release"
else
	BUILD_ARGS=""
fi

echo "=== Rig Relay Unified App Builder (X4.4) ==="
echo "  Configuration: $CONFIG"
echo "  Skip extension: $SKIP_EXTENSION"
[[ -n "$IDENTITY" ]] && echo "  Signing identity: $IDENTITY"

# ── Step 1: Build SPM executable ──────────────────────────
echo ""
echo "[1/6] Building RigRelayShell SPM executable..."
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

# ── Step 2: Build Xcode Safari extension .appex ────────────
echo ""
APPEX_PATH=""
if [[ "$SKIP_EXTENSION" == true ]]; then
	echo "[2/6] Skipping Safari extension build (--skip-extension)"
else
	echo "[2/6] Building Safari extension .appex..."
	if [[ ! -d "$XCODE_PROJECT" ]]; then
		echo "  WARNING: Xcode project not found at $XCODE_PROJECT"
		echo "  Skipping extension build — app will not embed extension"
	else
		xcodebuild -project "$XCODE_PROJECT" \
			-target "$EXTENSION_TARGET" \
			-configuration "$CONFIG" \
			CONFIGURATION_BUILD_DIR="$EXTENSION_BUILD_DIR" \
			build 2>&1 | tail -5

		APPEX_PATH="$EXTENSION_BUILD_DIR/RigRelayShell Extension.appex"
		if [[ -d "$APPEX_PATH" ]]; then
			echo "  Extension built: $APPEX_PATH"
		else
			echo "  WARNING: Extension build succeeded but .appex not found at expected path"
			echo "  Looking for .appex..."
			APPEX_PATH=$(find "$EXTENSION_BUILD_DIR" -name "*.appex" -type d 2>/dev/null | head -1)
			if [[ -z "$APPEX_PATH" ]]; then
				echo "  ERROR: Could not locate built .appex"
				exit 1
			fi
			echo "  Found at: $APPEX_PATH"
		fi
	fi
fi

# ── Step 3: Create .app bundle structure ──────────────────
echo ""
echo "[3/6] Creating .app bundle at $APP_DIR..."
rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$FRAMEWORKS_DIR" "$PLUGINS_DIR"

cp "$EXECUTABLE_PATH" "$MACOS_DIR/RigRelayShell"
chmod +x "$MACOS_DIR/RigRelayShell"

# ── Step 4: Copy resources ────────────────────────────────
echo "[4/6] Copying bundle resources..."

cp "$SCRIPT_DIR/../Resources/Info.plist" "$CONTENTS/Info.plist"

if [[ -d "$PROJECT_DIR/Sources/RigRelayShell/Resources/GridlineFrontend" ]]; then
	cp -R "$PROJECT_DIR/Sources/RigRelayShell/Resources/GridlineFrontend" "$RESOURCES_DIR/"
else
	echo "  WARNING: GridlineFrontend resources not found — app will fail to load"
fi

if [[ -f "$REPO_ROOT/THIRD_PARTY_NOTICES.md" ]]; then
	cp "$REPO_ROOT/THIRD_PARTY_NOTICES.md" "$RESOURCES_DIR/"
fi
if [[ -f "$REPO_ROOT/LICENSE" ]]; then
	cp "$REPO_ROOT/LICENSE" "$RESOURCES_DIR/"
fi

# ── Step 5: Embed Safari extension ─────────────────────────
echo ""
if [[ -n "$APPEX_PATH" && -d "$APPEX_PATH" ]]; then
	echo "[5/6] Embedding Safari extension..."
	cp -R "$APPEX_PATH" "$PLUGINS_DIR/"
	echo "  Embedded: $PLUGINS_DIR/$(basename "$APPEX_PATH")"

	# Verify the extension handler is present
	if [[ -f "$PLUGINS_DIR/$(basename "$APPEX_PATH")/Contents/MacOS/RigRelayShell Extension" ]]; then
		echo "  Extension handler binary: present"
	else
		echo "  WARNING: Extension handler binary not found at expected path"
	fi
else
	echo "[5/6] No extension to embed — app will run without Safari companion"
	echo "  To embed extension: omit --skip-extension and ensure Xcode is installed"
fi

# ── Step 6: Signing (if identity provided) ────────────────
echo ""
echo "[6/6] Code signing..."
if [[ -n "$IDENTITY" ]]; then
	ENTITLEMENTS="$SCRIPT_DIR/../Resources/RigRelayShell.entitlements"

	# Sign nested code in correct order: deepest first
	if [[ -n "$APPEX_PATH" && -d "$PLUGINS_DIR/$(basename "$APPEX_PATH")" ]]; then
		echo "  Signing extension..."
		codesign --force --options runtime --timestamp \
			--sign "$IDENTITY" \
			"$PLUGINS_DIR/$(basename "$APPEX_PATH")" 2>&1 ||
			echo "  WARNING: Extension codesign failed"
	fi

	# Sign the app
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
echo "  App:        $APP_DIR"
echo "  Version:    $SHORT_VERSION ($BUILD_VERSION)"
echo "  Config:     $CONFIG"
echo "  Extension:  $([[ -n "$APPEX_PATH" && -d "$APPEX_PATH" ]] && echo "embedded" || echo "not embedded")"
echo ""
echo "  Bundle contents:"
find "$APP_DIR" -type f | sed "s|$APP_DIR|  Contents|" | sort
echo ""
echo "  To sign:    ./build-app.sh --release --sign 'Developer ID Application: ...'"
echo "  No extension: ./build-app.sh --skip-extension"
echo "  To notarize: ./prepare-signing.sh notarize 'Developer ID Application: ...'"

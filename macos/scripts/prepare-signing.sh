#!/bin/bash
set -euo pipefail

# ── Rig Relay Signing & Notarization Preparation (X4) ─────
# Prepares and submits RigRelayShell.app for notarization.
# Requires: Apple Developer ID Application certificate in keychain.
#
# Usage:
#   ./prepare-signing.sh validate            # Check signing readiness
#   ./prepare-signing.sh sign IDENTITY       # Sign with hardened runtime
#   ./prepare-signing.sh notarize IDENTITY   # Sign + submit for notarization
#   ./prepare-signing.sh staple              # Staple notarization ticket
#   ./prepare-signing.sh verify             # Verify signature and notarization

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/../RigRelayShell/.build/bundle/RigRelayShell.app"
ENTITLEMENTS="$SCRIPT_DIR/../Resources/RigRelayShell.entitlements"
BUNDLE_ID="com.rigrelay.RigRelayShell"
NOTARY_PROFILE="rig-relay-notary"

CMD="${1:-validate}"
IDENTITY="${2:-}"

die() {
	echo "ERROR: $*" >&2
	exit 1
}
warn() { echo "WARNING: $*" >&2; }

check_app() {
	if [[ ! -d "$APP_DIR" ]]; then
		die "App bundle not found at $APP_DIR. Run build-app.sh first."
	fi
}

check_identity() {
	if [[ -z "$IDENTITY" ]]; then
		die "Signing identity required. Usage: $0 $CMD 'Developer ID Application: ...'"
	fi
	if ! security find-identity -v -p codesigning | grep -q "$IDENTITY"; then
		die "Signing identity '$IDENTITY' not found in keychain."
	fi
}

check_notary_profile() {
	if ! xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" &>/dev/null; then
		warn "Notary profile '$NOTARY_PROFILE' not configured."
		warn "  Set up with: xcrun notarytool store-credentials '$NOTARY_PROFILE' \\"
		warn "    --apple-id 'your@email.com' --team-id 'TEAMID' --password '@keychain:AC_PASSWORD'"
	fi
}

case "$CMD" in
validate)
	echo "=== Signing Readiness Validation ==="

	echo ""
	echo "1. App bundle:"
	if [[ -d "$APP_DIR" ]]; then
		echo "   ✓ Found at $APP_DIR"
	else
		echo "   ✗ Not found — run build-app.sh first"
	fi

	echo ""
	echo "2. Entitlements:"
	if [[ -f "$ENTITLEMENTS" ]]; then
		echo "   ✓ Found at $ENTITLEMENTS"
		echo "   Contents:"
		/usr/libexec/PlistBuddy -c "Print" "$ENTITLEMENTS" 2>/dev/null | sed 's/^/     /'
	else
		echo "   ✗ Not found"
	fi

	echo ""
	echo "3. Signing identities (Developer ID Application):"
	DEVELOPER_IDS=$(security find-identity -v -p codesigning | grep "Developer ID Application" || true)
	if [[ -n "$DEVELOPER_IDS" ]]; then
		echo "   ✓ Available:"
		echo "$DEVELOPER_IDS" | sed 's/^/     /'
	else
		echo "   ✗ No Developer ID Application certificates found"
		echo "     Required for notarized distribution."
	fi

	echo ""
	echo "4. Notarization tooling:"
	if xcrun notarytool help &>/dev/null; then
		echo "   ✓ notarytool available"
	else
		echo "   ✗ notarytool not available (Xcode CLT required)"
	fi

	echo ""
	echo "5. Hardened Runtime check:"
	if [[ -f "$ENTITLEMENTS" ]]; then
		if /usr/libexec/PlistBuddy -c "Print :com.apple.security.app-sandbox" "$ENTITLEMENTS" &>/dev/null; then
			echo "   ✓ App Sandbox enabled"
		else
			echo "   ⚠ App Sandbox not set in entitlements (required for App Store)"
		fi
		HAS_GET_TASK_ALLOW=$(/usr/libexec/PlistBuddy -c "Print :com.apple.security.get-task-allow" "$ENTITLEMENTS" 2>/dev/null || echo "")
		if [[ "$HAS_GET_TASK_ALLOW" == "true" ]]; then
			echo "   ✗ com.apple.security.get-task-allow=true — MUST be false for notarization"
		else
			echo "   ✓ get-task-allow not set (correct for release)"
		fi
	fi

	echo ""
	echo "=== Readiness: $( ([[ -d "$APP_DIR" ]] && [[ -f "$ENTITLEMENTS" ]] && [[ -n "$DEVELOPER_IDS" ]]) && echo "READY (identity available)" || echo "BLOCKED (see above)") ==="
	;;

sign)
	check_identity
	check_app

	echo "=== Signing RigRelayShell.app ==="
	echo "  Identity: $IDENTITY"
	echo "  Entitlements: $ENTITLEMENTS"

	codesign --force --options runtime --timestamp \
		--entitlements "$ENTITLEMENTS" \
		--sign "$IDENTITY" \
		--deep "$APP_DIR"

	echo ""
	echo "=== Signature Verification ==="
	codesign -dvvv "$APP_DIR" 2>&1 || true
	echo ""
	echo "  Signed successfully."
	;;

notarize)
	check_identity
	check_app
	check_notary_profile

	echo "=== Signing and Notarizing ==="

	# 1. Sign
	echo "[1/3] Signing..."
	codesign --force --options runtime --timestamp \
		--entitlements "$ENTITLEMENTS" \
		--sign "$IDENTITY" \
		--deep "$APP_DIR"

	# 2. Create zip for notarization
	echo "[2/3] Creating submission archive..."
	ZIP_PATH="$SCRIPT_DIR/../RigRelayShell/.build/RigRelayShell-notarize.zip"
	rm -f "$ZIP_PATH"
	ditto -c -k --keepParent "$APP_DIR" "$ZIP_PATH"

	# 3. Submit
	echo "[3/3] Submitting to notary service..."
	xcrun notarytool submit "$ZIP_PATH" \
		--keychain-profile "$NOTARY_PROFILE" \
		--wait \
		--output-format json | tee "$SCRIPT_DIR/../RigRelayShell/.build/notarization-result.json"

	echo ""
	echo "  Submission complete. Check status:"
	echo "    xcrun notarytool history --keychain-profile '$NOTARY_PROFILE'"
	echo "  After approval, staple the ticket:"
	echo "    ./prepare-signing.sh staple"
	;;

staple)
	check_app
	echo "=== Stapling notarization ticket ==="
	xcrun stapler staple "$APP_DIR"
	echo "  Stapled."
	xcrun stapler validate "$APP_DIR" 2>&1
	;;

verify)
	check_app
	echo "=== Verification ==="
	echo ""
	echo "Code signature:"
	codesign -dvvv "$APP_DIR" 2>&1 || true
	echo ""
	echo "Notarization:"
	spctl --assess --verbose=4 --type execute "$APP_DIR" 2>&1 || true
	echo ""
	echo "Gatekeeper:"
	spctl --assess -vv --type execute "$APP_DIR" 2>&1 || true
	;;

*)
	echo "Usage: $0 {validate|sign IDENTITY|notarize IDENTITY|staple|verify}"
	exit 1
	;;
esac

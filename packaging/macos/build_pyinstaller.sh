#!/usr/bin/env bash
# Build PyInstaller helper for Rig Relay.app
#
# Output: dist/RigRelayHelper/ (executable + resources)
# This is NOT the final app — it's bundled inside the SwiftUI shell.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== Building PyInstaller helper ==="

uv run python -c "import PyInstaller" 2>/dev/null || uv add --dev pyinstaller

export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
rm -rf build "Rig Relay.spec"

uv run pyinstaller \
    --name="RigRelay" \
    --noconfirm \
    --clean \
    --hidden-import=rig_relay \
    --hidden-import=webview \
    --hidden-import=duckdb \
    --hidden-import=pydantic \
    --hidden-import=platformdirs \
    --add-data="frontend/desktop:frontend/desktop" \
    --add-data="docs/demo:docs/demo" \
    --add-data="docs/schemas:docs/schemas" \
    --add-data="etc:etc" \
    rig_relay/packaged_app.py

echo ""
echo "=== Extracting helper ==="

HELPER_DIR="$REPO_ROOT/dist/RigRelayHelper"
rm -rf "$HELPER_DIR"
mkdir -p "$HELPER_DIR"

# Copy the entire dist/RigRelay directory (includes _internal + executable)
cp -R "dist/RigRelay/"* "$HELPER_DIR/"

# Rename executable from RigRelay to make it clear
if [ -f "$HELPER_DIR/RigRelay" ]; then
    chmod +x "$HELPER_DIR/RigRelay"
fi

# Clean up the PyInstaller .app (we only need the helper dir)
rm -rf "dist/RigRelay.app"

echo ""
echo "=== Helper built ==="
echo "Helper: $HELPER_DIR/RigRelay"
echo "Size:   $(du -sh "$HELPER_DIR" | cut -f1)"

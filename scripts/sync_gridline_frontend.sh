#!/usr/bin/env bash
# sync_gridline_frontend.sh — Deterministic sync from canonical frontend source to native bundle.
# Owner: Lane T0 — NativeHostedGridlineProductionSurface
# Safety: one-way rsync from frontend/desktop/ to the SPM .copy resource target.
#          Never deletes the target root — only overwrites matching files and adds new ones.
#          Excludes .DS_Store and other ephemeral artifacts.
#
# Usage: bash scripts/sync_gridline_frontend.sh [--check-only]
#   --check-only   Dry-run: exit 1 if any file differs; exit 0 if in sync.

set -euo pipefail

CANONICAL="frontend/desktop"
TARGET="macos/RigRelayShell/Sources/RigRelayShell/Resources/GridlineFrontend"

if [ ! -d "$CANONICAL" ]; then
	echo "ERROR: canonical frontend source not found at $CANONICAL" >&2
	exit 1
fi
if [ ! -d "$TARGET" ]; then
	echo "ERROR: target bundle directory not found at $TARGET" >&2
	exit 1
fi

RSYNC_ARGS=(
	--archive
	--delete
	--exclude='.DS_Store'
	--exclude='.gitkeep'
	--exclude='node_modules'
	"$CANONICAL/"
	"$TARGET/"
)

if [ "${1:-}" = "--check-only" ]; then
	if rsync --dry-run --itemize-changes "${RSYNC_ARGS[@]}" | grep -q .; then
		echo "DRIFT DETECTED: bundled frontend differs from canonical source."
		rsync --dry-run --itemize-changes "${RSYNC_ARGS[@]}"
		exit 1
	fi
	echo "OK: bundled frontend matches canonical source."
	exit 0
fi

echo "Syncing $CANONICAL -> $TARGET ..."
rsync "${RSYNC_ARGS[@]}"
echo "Done. Run with --check-only to verify parity."

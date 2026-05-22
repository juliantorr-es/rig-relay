#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

STEWARD="uv run python scripts/rig_opencode_idle_steward.py"
ARGS="--project-root . --worktree default --show-reasoning-stream"

echo "=== OpenCode Idle Runner ==="
echo "Running until no tasks remain or blocked..."
echo

iteration=0
while true; do
    iteration=$((iteration + 1))
    echo "--- Iteration $iteration ---"
    $STEWARD $ARGS || true

    state=$(python3 -c "
import json
p = '.build/rig-relay/derived/opencode_idle_steward_last_run_v1.json'
try:
    with open(p) as f:
        r = json.load(f)
    print(r.get('steward_state',''))
except: print('no_action')
")

    case "$state" in
        no_action)
            echo "✓ No more tasks — queue is empty or all completed."
            break
            ;;
        blocked)
            echo "✗ Blocked — check blocker_reasons in last run artifact."
            break
            ;;
        audit_unblock_plan)
            echo "✗ All tasks blocked — audit written to .build/rig-relay/derived/."
            break
            ;;
        repair_steward_substrate)
            echo "🔧 Repair dispatched — waiting for repair to complete."
            ;;
        *)
            echo "→ State: $state — continuing to next task..."
            ;;
    esac
    echo
done

echo
echo "=== Runner stopped after $iteration iteration(s) ==="

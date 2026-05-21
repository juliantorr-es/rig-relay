#!/usr/bin/env python3
"""Git pre-push hook — triggers maintenance on milestone-tagged pushes.

Checks if the push includes a milestone tag (v*, release*, milestone*).
If yes, runs full GitHub maintenance before the push completes.
If no — normal dev push — skips silently. No deployment delay. Fully local.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HOOK_CONFIG = _REPO_ROOT / ".rig" / "relay" / "push_hook_config.json"

_MILESTONE_TAG_PATTERNS = [
    "v[0-9]*",
    "release-*",
    "milestone-*",
    "rc-*",
    "tag: maintenance",
]


def _detect_milestone_tags() -> list[str]:
    """Check if the current push includes milestone tags. Reads from stdin (git hook protocol)."""
    tags: list[str] = []
    for line in sys.stdin:
        parts = line.strip().split()
        if not parts:
            continue
        ref = parts[2] if len(parts) > 2 else ""
        if ref.startswith("refs/tags/"):
            tag_name = ref.replace("refs/tags/", "")
            if _is_milestone_tag(tag_name):
                tags.append(tag_name)
    return tags


def _is_milestone_tag(tag: str) -> bool:
    import fnmatch

    for pattern in _MILESTONE_TAG_PATTERNS:
        if fnmatch.fnmatch(tag, pattern):
            return True
    return False


def _run_maintenance() -> dict[str, object]:
    """Run the full maintenance workflow. Returns status dict."""
    try:
        result = subprocess.run(
            ["uv", "run", "python", "scripts/rig_github_maintenance.py", "all"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            env={**__import__("os").environ, "RIG_LIVE_AUTH_TESTS": "1"},
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[:500],
            "stderr": result.stderr[:500],
        }
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


def _save_hook_state(tag: str, status: dict[str, object]) -> None:
    _HOOK_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if _HOOK_CONFIG.exists():
        try:
            existing = json.loads(_HOOK_CONFIG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    existing["last_milestone_push"] = {
        "tag": tag,
        "maintenance_result": status,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }
    _HOOK_CONFIG.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    # Quick check: are we pushing tags?
    tags = _detect_milestone_tags()

    if not tags:
        # Normal dev push — no milestone tags. Skip maintenance.
        return 0

    print(f"\n  Milestone tag detected: {tags[0]}")
    print(f"  Running GitHub maintenance before push...")
    print()

    status = _run_maintenance()
    _save_hook_state(tags[0], status)

    if status.get("success"):
        print("  Maintenance complete. Proceeding with push.")
        print()
        return 0
    else:
        print(
            f"  Warning: maintenance encountered issues: {status.get('stderr', 'unknown')[:200]}"
        )
        print("  Proceeding with push (maintenance is advisory, not blocking).")
        print()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

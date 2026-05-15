#!/usr/bin/env python3
"""Generate the IDE capability map documentation from the canonical manifest.

Produces docs/protocols/ide-capability-map.md.

Usage:
    uv run python scripts/rig_relay_generate_ide_capability_map.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "etc" / "rig.ide.capability_manifest.v1.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "protocols" / "ide-capability-map.md"

RISK_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🔴"}
POLICY_LABELS = {
    "allow": "Allow",
    "allow_if_workspace_trusted": "Allow (trusted)",
    "ask_once_per_session": "Ask once/session",
    "always_ask": "Always ask",
    "deny": "Deny",
}
PLANE_LABELS = {"ide": "IDE", "ui": "UI", "core": "Core"}


def _impl_icon(impl: dict) -> str:
    parts = []
    if impl.get("vscode"):
        parts.append("✅ VS Code")
    if impl.get("sidecar"):
        parts.append("✅ Sidecar")
    if impl.get("jetbrains"):
        parts.append("⬜ JetBrains")
    if impl.get("zed"):
        parts.append("⬜ Zed")
    return " • ".join(parts) if parts else "⬜ Not implemented"


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    capabilities = manifest.get("capabilities", {})

    # Group by plane
    by_plane: dict[str, dict[str, dict]] = {}
    for name, info in capabilities.items():
        plane = info.get("plane", "ide")
        by_plane.setdefault(plane, {})[name] = info

    lines: list[str] = []
    lines.append("# IDE Capability Map")
    lines.append("")
    lines.append(
        "Canonical capability registry for Rig Relay IDE bridges. "
        "Generated from `etc/rig.ide.capability_manifest.v1.json`. "
        "Do not edit by hand."
    )
    lines.append("")
    lines.append(f"**Total capabilities:** {len(capabilities)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    plane_order = ["ide", "ui", "core"]
    for plane in plane_order:
        caps = by_plane.get(plane, {})
        if not caps:
            continue

        lines.append(f"## {PLANE_LABELS.get(plane, plane)} Capabilities")
        lines.append("")

        # Table header
        lines.append("| Capability | Risk | Mutates | Policy | Workspace Trust | Implemented |")
        lines.append("|---|---|---|---|---|---|")

        for name in sorted(caps):
            info = caps[name]
            risk = info.get("risk", "unknown")
            mutates = info.get("mutates", False)
            policy = info.get("default_policy", "deny")
            requires_trust = info.get("requires_workspace_trust", False)
            impl = info.get("implemented_in", {})

            risk_str = f"{RISK_EMOJI.get(risk, '⚪')} {risk.capitalize()}"
            mutates_str = "Yes" if mutates is True else ("Possible" if mutates == "possible" else "No")

            policy_str = POLICY_LABELS.get(policy, policy)
            trust_str = "Required" if requires_trust else "—"
            impl_str = _impl_icon(impl)

            lines.append(f"| `{name}` | {risk_str} | {mutates_str} | {policy_str} | {trust_str} | {impl_str} |")

        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Policy Meanings")
    lines.append("")
    lines.append("| Policy | Behavior |")
    lines.append("|---|---|")
    lines.append("| `allow` | No prompt. Capability executes immediately. |")
    lines.append("| `allow_if_workspace_trusted` | No prompt in trusted workspaces. Refused in untrusted. |")
    lines.append("| `ask_once_per_session` | Prompts the first time per session. Auto-allows subsequent calls. |")
    lines.append("| `always_ask` | Prompts every time. Never auto-allows. |")
    lines.append("| `deny` | Always blocked. Agent receives `refused`. |")
    lines.append("")
    lines.append("## Workspace Trust")
    lines.append("")
    lines.append(
        "Some capabilities require VS Code Workspace Trust. "
        "If the workspace is not trusted, capabilities with "
        "`requires_workspace_trust: true` are refused and the "
        "receipt records `workspace_trusted: false`."
    )
    lines.append("")
    lines.append("## Receipt Model")
    lines.append("")
    lines.append(
        "Every capability execution emits a receipt (schema: "
        "`rig.ide.capability.receipt.v1`). Receipts record: "
        "capability name, input/output SHA256, user approval status, "
        "approval method, mutation status, workspace trust, and timestamp."
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Generated {OUTPUT_PATH}")
    print(f"  {len(capabilities)} capabilities across {len(by_plane)} planes")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

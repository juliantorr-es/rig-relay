from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_opencode_instructions_prioritize_rig_governance_docs() -> None:
    config = json.loads((REPO_ROOT / "opencode.json").read_text(encoding="utf-8"))
    instructions = config["instructions"]

    assert instructions[:6] == [
        "AGENTS.md",
        "docs/governance/mission-envelope.md",
        "docs/governance/cross-session-coordination.md",
        "docs/governance/usage-data-doctrine.md",
        "docs/governance/reviewer-orchestrator.md",
        "docs/governance/delegate-fleet-orchestration.md",
    ]
    assert instructions[6:] == ["README.md", "pyproject.toml"]

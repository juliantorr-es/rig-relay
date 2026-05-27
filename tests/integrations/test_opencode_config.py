from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_opencode_instructions_prioritize_rig_governance_docs() -> None:
    config = json.loads((REPO_ROOT / "opencode.json").read_text(encoding="utf-8"))
    instructions = config["instructions"]

    assert instructions[:10] == [
        "PROJECT.md",
        "AGENTS.md",
        "docs/governance/mission-envelope.md",
        "docs/governance/cross-session-coordination.md",
        "docs/governance/step-up-authorization.md",
        "docs/governance/identity-provider-policy.md",
        "docs/governance/usage-data-doctrine.md",
        "docs/governance/reviewer-orchestrator.md",
        "docs/governance/prepublication-falsifier-contract.md",
        "docs/governance/delegate-fleet-orchestration.md",
    ]
    assert instructions[10:] == ["README.md", "pyproject.toml"]


def test_opencode_task_permissions_allow_only_prepublication_gate_agents() -> None:
    config = json.loads((REPO_ROOT / "opencode.json").read_text(encoding="utf-8"))
    task_permissions = config["permission"]["task"]

    assert task_permissions["*"] == "deny"
    assert "builder" not in task_permissions
    assert "orchestrator" not in task_permissions
    assert task_permissions["execution"] == "allow"
    assert task_permissions["validator"] == "allow"
    assert task_permissions["plan"] == "allow"
    assert task_permissions["explore"] == "allow"
    assert task_permissions["scout"] == "allow"
    assert task_permissions["prepublication-conductor"] == "allow"
    assert task_permissions["publisher"] == "allow"
    assert task_permissions["cleaner"] == "allow"
    assert task_permissions["repairer"] == "allow"
    assert task_permissions["claim-scope-adversary"] == "allow"
    assert task_permissions["evidence-adversary"] == "allow"
    assert task_permissions["production-proof-adversary"] == "allow"
    assert task_permissions["authority-adversary"] == "allow"
    assert task_permissions["recovery-adversary"] == "allow"
    assert task_permissions["claim-adversary"] == "allow"
    assert task_permissions["publication-truth-adversary"] == "allow"
    assert task_permissions["lane-collision-adversary"] == "allow"
    assert task_permissions["security-adversary"] == "allow"
    assert task_permissions["remote-main-reviewer"] == "allow"


def test_opencode_defaults_do_not_prompt_for_tool_permission() -> None:
    config = json.loads((REPO_ROOT / "opencode.json").read_text(encoding="utf-8"))
    permissions = config["permission"]

    assert config["default_agent"] == "orchestrator"
    assert permissions["edit"] == "deny"
    assert permissions["bash"] == "deny"
    assert permissions["skill"]["*"] == "deny"
    assert permissions["doom_loop"] == "deny"
    assert permissions["lsp"] == "deny"

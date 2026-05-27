from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / ".opencode" / "agents"
COMMANDS_DIR = REPO_ROOT / ".opencode" / "commands"


def _frontmatter(path: Path) -> dict[str, object]:
    raw = path.read_text(encoding="utf-8")
    assert raw.startswith("---\n"), f"{path} missing YAML frontmatter"
    _, frontmatter, _ = raw.split("---", 2)
    return yaml.safe_load(frontmatter) or {}


def test_prepublication_agents_exist() -> None:
    names = {
        "orchestrator.md",
        "execution.md",
        "prepublication-conductor.md",
        "claim-adversary.md",
        "publication-truth-adversary.md",
        "claim-scope-adversary.md",
        "authority-adversary.md",
        "evidence-adversary.md",
        "production-proof-adversary.md",
        "recovery-adversary.md",
        "security-adversary.md",
        "lane-collision-adversary.md",
        "remote-main-reviewer.md",
        "publisher.md",
    }
    assert names.issubset({path.name for path in AGENTS_DIR.glob("*.md")})


def test_prepublication_command_targets_conductor() -> None:
    fm = _frontmatter(COMMANDS_DIR / "prepublication-review.md")
    assert fm["subagent"] == "prepublication-conductor"
    assert fm["subtask"] is True


def test_remote_main_command_targets_independent_reviewer() -> None:
    fm = _frontmatter(COMMANDS_DIR / "remote-main-review.md")
    assert fm["subagent"] == "remote-main-reviewer"
    assert fm["subtask"] is True


def test_publish_command_targets_publisher() -> None:
    fm = _frontmatter(COMMANDS_DIR / "publish-admitted-candidate.md")
    assert fm["subagent"] == "publisher"
    assert fm["subtask"] is True


def test_publication_truth_adversary_requires_canonical_prepublication_chronology() -> None:
    prompt = (AGENTS_DIR / "publication-truth-adversary.md").read_text(encoding="utf-8")

    assert "canonical prepublication review-cycle record" in prompt
    assert "postdated, or co-committed" in prompt
    assert "invalidate the publication claim" in prompt


def test_evidence_adversary_requires_canonical_schema_authority() -> None:
    prompt = (AGENTS_DIR / "evidence-adversary.md").read_text(encoding="utf-8")

    assert "published canonical schema authority" in prompt
    assert "weaker inline or divergent schema" in prompt
    assert "block until authority is repaired" in prompt


def test_remote_main_reviewer_rejects_weaker_schema_and_retroactive_chronology() -> None:
    prompt = (AGENTS_DIR / "remote-main-reviewer.md").read_text(encoding="utf-8")

    assert "canonical prepublication review record is missing, postdated, or co-committed" in prompt
    assert "weaker inline schema" in prompt


def test_publisher_requires_prepublication_record_chronology() -> None:
    prompt = (AGENTS_DIR / "publisher.md").read_text(encoding="utf-8")

    assert "canonical prepublication review-cycle record predates the publication action" in prompt
    assert "If the record is missing, postdated, or co-committed, refuse to push" in prompt


def test_conductor_invocation_is_specialist_only() -> None:
    fm = _frontmatter(AGENTS_DIR / "prepublication-conductor.md")
    permissions = fm["permission"]
    task_permissions = permissions["task"]

    assert task_permissions["*"] == "deny"
    assert task_permissions["publication-truth-adversary"] == "allow"
    assert task_permissions["claim-scope-adversary"] == "allow"
    assert task_permissions["authority-adversary"] == "allow"
    assert task_permissions["evidence-adversary"] == "allow"
    assert task_permissions["production-proof-adversary"] == "allow"
    assert task_permissions["recovery-adversary"] == "allow"
    assert task_permissions["security-adversary"] == "allow"
    assert task_permissions["lane-collision-adversary"] == "allow"


def test_orchestrator_only_reads_searches_and_delegates() -> None:
    fm = _frontmatter(AGENTS_DIR / "orchestrator.md")
    permissions = fm["permission"]

    assert permissions["edit"] == "deny"
    assert permissions["bash"] == "deny"
    assert permissions["websearch"] == "allow"
    assert permissions["webfetch"] == "deny"
    assert permissions["lsp"] == "deny"
    assert permissions["task"]["*"] == "deny"
    assert permissions["task"]["plan"] == "allow"
    assert permissions["task"]["explore"] == "allow"
    assert permissions["task"]["scout"] == "allow"
    assert permissions["task"]["execution"] == "allow"
    assert permissions["task"]["validator"] == "allow"
    assert permissions["task"]["prepublication-conductor"] == "allow"
    assert permissions["task"]["publisher"] == "allow"


def test_execution_is_the_editing_wave() -> None:
    fm = _frontmatter(AGENTS_DIR / "execution.md")
    permissions = fm["permission"]

    assert permissions["edit"] == "allow"
    assert permissions["bash"] == "allow"
    assert permissions["task"] == "deny"
    assert permissions["websearch"] == "deny"
    assert permissions["webfetch"] == "deny"

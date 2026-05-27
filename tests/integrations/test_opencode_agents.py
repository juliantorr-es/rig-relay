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

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


def _schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def test_plan_schema_accepts_canonical_plan() -> None:
    plan = {
        "schema_version": "opencode.plan.v1",
        "plan_id": "opencode-plan-20260528T120000Z-demo-r1-abcdef12",
        "revision": 1,
        "created_at": "2026-05-28T12:00:00Z",
        "title": "Demo plan",
        "objective": "Exercise the new OpenCode-native planning tools.",
        "summary": "Initial plan for the new tool chain.",
        "assumptions": ["OpenCode loads local tools from .opencode/tools"],
        "constraints": ["Keep the artifact canonical and repo-local"],
        "execution_waves": [
            {
                "wave_id": "learn",
                "name": "Learning",
                "purpose": "Understand current state",
                "parallelism": "parallel",
                "target_agents": ["plan", "explore"],
                "exit_criteria": ["State mapped"],
                "notes": "",
            }
        ],
        "acceptance_criteria": ["Plan artifact written"],
        "risks": [
            {
                "risk": "schema drift",
                "impact": "tools stop validating",
                "mitigation": "validate with tests",
            }
        ],
        "open_questions": ["Should comment ledgers be per-plan or shared?"],
        "revision_notes": [],
        "parent_plan_id": None,
        "parent_plan_path": None,
        "canonical_path": "docs/json/opencode/plans/opencode-plan-20260528T120000Z-demo-r1-abcdef12.json",
        "comment_ledger_path": "docs/json/opencode/plans/opencode-plan-20260528T120000Z-demo-r1-abcdef12.comments.jsonl",
        "content_light": True,
    }

    jsonschema.validate(instance=plan, schema=_schema("opencode.plan.v1"))


def test_plan_comment_schema_accepts_ledger_row() -> None:
    comment = {
        "schema_version": "opencode.plan_comment.v1",
        "comment_id": "opencode-comment-20260528T120100Z-abcdef12",
        "created_at": "2026-05-28T12:01:00Z",
        "plan_id": "opencode-plan-20260528T120000Z-demo-r1-abcdef12",
        "plan_revision": 1,
        "plan_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "critic_name": "constructive-critic",
        "wave_id": "critique",
        "severity": "major",
        "category": "feasibility",
        "comment": "The plan needs a stronger validation gate.",
        "suggested_change": "Add an explicit review_criticism step before revise_plan.",
        "references": ["docs/governance/reviewer-orchestrator.md"],
        "content_light": True,
    }

    jsonschema.validate(instance=comment, schema=_schema("opencode.plan_comment.v1"))


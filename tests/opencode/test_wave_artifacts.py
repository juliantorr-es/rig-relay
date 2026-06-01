from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


def _schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def test_execution_artifact_schema_accepts_canonical_record() -> None:
    artifact = {
        "schema_version": "opencode.execution_artifact.v1",
        "artifact_id": "opencode-execution-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "plan_id": "opencode-plan-20260528T120000Z-demo-r1-abcdef12",
        "plan_revision": 1,
        "plan_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "wave_id": "execution",
        "executor_name": "executor-a",
        "task_summary": "Implemented tool plumbing.",
        "files_changed": [".opencode/tools/record_execution_wave.ts"],
        "implementation_notes": ["Added canonical artifact output."],
        "commands_run": ["node --test tests/opencode_wave_tools.test.mjs"],
        "proof_artifacts": [
            {"label": "test", "path": "tests/opencode_wave_tools.test.mjs", "digest": "sha256:abc"}
        ],
        "deferred_seams": [],
        "open_risks": [],
        "boundary_claim": "executor records an implementation artifact",
        "content_light": True,
    }
    jsonschema.validate(instance=artifact, schema=_schema("opencode.execution_artifact.v1"))


def test_validation_artifact_schema_accepts_canonical_record() -> None:
    artifact = {
        "schema_version": "opencode.validation_artifact.v1",
        "artifact_id": "opencode-validation-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "plan_id": "opencode-plan-20260528T120000Z-demo-r1-abcdef12",
        "plan_revision": 1,
        "plan_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "wave_id": "validation",
        "validator_name": "validator-a",
        "commands_run": ["uv run pytest tests/opencode/test_plan_artifacts.py -q"],
        "pass": True,
        "tested_boundary": "OpenCode plan artifacts",
        "failed_seams": [],
        "missing_evidence": [],
        "recommendations": ["Keep schema and artifact names aligned."],
        "content_light": True,
    }
    jsonschema.validate(instance=artifact, schema=_schema("opencode.validation_artifact.v1"))


def test_stress_artifact_schema_accepts_canonical_record() -> None:
    artifact = {
        "schema_version": "opencode.stress_artifact.v1",
        "artifact_id": "opencode-stress-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "plan_id": "opencode-plan-20260528T120000Z-demo-r1-abcdef12",
        "plan_revision": 1,
        "plan_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "wave_id": "stress",
        "red_team_name": "red-team-a",
        "attacks": ["missing digest", "mutable artifact"],
        "attack_surface": ["plan", "comment ledger", "report"],
        "survived": True,
        "breakages": [],
        "repaired_seams": ["mutable artifact path"],
        "recommendations": ["Use immutable plan revisions."],
        "content_light": True,
    }
    jsonschema.validate(instance=artifact, schema=_schema("opencode.stress_artifact.v1"))


def test_publication_artifact_schema_accepts_canonical_record() -> None:
    artifact = {
        "schema_version": "opencode.publication_artifact.v1",
        "artifact_id": "opencode-publication-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "plan_id": "opencode-plan-20260528T120000Z-demo-r1-abcdef12",
        "plan_revision": 1,
        "plan_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "wave_id": "publication",
        "publisher_name": "publisher-a",
        "target_ref": "origin/main",
        "pushed_sha": "deadbeef",
        "remote_verified": True,
        "publication_notes": ["Published the current plan slice."],
        "files_published": ["docs/json/opencode/waves/example.json"],
        "post_push_checks": ["remote SHA matched"],
        "content_light": True,
    }
    jsonschema.validate(instance=artifact, schema=_schema("opencode.publication_artifact.v1"))


def test_session_report_schema_accepts_canonical_record() -> None:
    report = {
        "schema_version": "opencode.session_report.v1",
        "artifact_id": "opencode-session-report-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "plan_id": "opencode-plan-20260528T120000Z-demo-r1-abcdef12",
        "plan_revision": 1,
        "plan_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "plan_path": "docs/json/opencode/plans/opencode-plan-20260528T120000Z-demo-r1-abcdef12.json",
        "comment_ledger_path": "docs/json/opencode/plans/opencode-plan-20260528T120000Z-demo-r1-abcdef12.comments.jsonl",
        "execution_artifacts": [
            {
                "artifact_id": "opencode-execution-20260528T120000Z-acde1234",
                "path": "docs/json/opencode/waves/example.json",
                "digest": "sha256:1",
            }
        ],
        "validation_artifacts": [],
        "stress_artifacts": [],
        "checkpoint_preparations": [],
        "checkpoint_commits": [],
        "publication_artifacts": [],
        "plan_comment_count": 1,
        "plan_comment_summaries": [
            {
                "comment_id": "comment-1",
                "critic_name": "critic-a",
                "severity": "major",
                "category": "feasibility",
                "wave_id": "critique",
                "comment": "Plan needs a revision stage.",
                "suggested_change": "Add revise_plan to the control flow.",
                "references": ["docs/governance/reviewer-orchestrator.md"],
            }
        ],
        "report_summary": "All wave artifacts exist and the plan story is coherent.",
        "next_steps": ["Review the report"],
        "blocked_seams": [],
        "content_light": True,
    }
    jsonschema.validate(instance=report, schema=_schema("opencode.session_report.v1"))

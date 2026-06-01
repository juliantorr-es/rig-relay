from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


def _schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def test_checkpoint_publication_schema_accepts_canonical_record() -> None:
    artifact = {
        "schema_version": "opencode.checkpoint_publication.v1",
        "artifact_id": "opencode-checkpoint-publication-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "publisher_name": "publisher-a",
        "remote_name": "origin",
        "target_ref": "main",
        "plan_id": "opencode-plan-20260528T120000Z-demo-r1-abcdef12",
        "plan_revision": 1,
        "checkpoint_commit_receipt_sha256": "sha256:feedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeed",
        "checkpoint_commit_artifact_path": "docs/json/opencode/checkpoints/commits/example.json",
        "checkpoint_commit_sha": "0123456789abcdef0123456789abcdef01234567",
        "checkpoint_sequence": 2,
        "parent_checkpoint_receipt_sha256": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "candidate_packet_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "review_artifact_path": "review.json",
        "review_artifact_sha256": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "admitted_review_status": "prepublication_admitted",
        "pre_push_head": "0123456789abcdef0123456789abcdef01234567",
        "post_push_head": "89abcdef0123456789abcdef0123456789abcdef",
        "pushed_commit_sha": "89abcdef0123456789abcdef0123456789abcdef",
        "remote_verified": True,
        "publication_notes": ["Published the checkpoint."],
        "files_published": ["src/tool.ts"],
        "post_push_checks": ["remote SHA matched HEAD"],
        "content_light": True,
    }
    jsonschema.validate(instance=artifact, schema=_schema("opencode.checkpoint_publication.v1"))


def test_published_checkpoint_report_schema_accepts_canonical_record() -> None:
    artifact = {
        "schema_version": "opencode.published_checkpoint_report.v1",
        "artifact_id": "opencode-published-checkpoint-report-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "plan_id": "opencode-plan-20260528T120000Z-demo-r1-abcdef12",
        "plan_revision": 1,
        "plan_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "plan_path": "docs/json/opencode/plans/opencode-plan-20260528T120000Z-demo-r1-abcdef12.json",
        "plan_comment_count": 1,
        "plan_comment_summaries": [
            {
                "comment_id": "comment-1",
                "critic_name": "critic-a",
                "severity": "major",
                "category": "feasibility",
                "wave_id": "critique",
                "comment": "Plan needs a publication step.",
                "suggested_change": "Add publish_checkpoint and generate_published_checkpoint_report.",
                "references": ["docs/governance/reviewer-orchestrator.md"],
            }
        ],
        "publisher_name": "publisher-a",
        "remote_name": "origin",
        "target_ref": "main",
        "publication_artifact_path": "docs/json/opencode/checkpoint_publications/example.json",
        "publication_artifact_sha256": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        "candidate_packet_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "review_artifact_path": "review.json",
        "review_artifact_sha256": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "admitted_review_status": "prepublication_admitted",
        "checkpoint_commit_artifact_path": "docs/json/opencode/checkpoints/commits/example.json",
        "checkpoint_commit_receipt_sha256": "sha256:feedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeed",
        "checkpoint_commit_sha": "0123456789abcdef0123456789abcdef01234567",
        "checkpoint_sequence": 2,
        "parent_checkpoint_receipt_sha256": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "published_commit_sha": "89abcdef0123456789abcdef0123456789abcdef",
        "checkpoint_commit_lineage": [
            {"artifact_id": "opencode-checkpoint-1", "path": "docs/json/opencode/checkpoints/commits/1.json", "digest": "sha256:1"}
        ],
        "checkpoint_preparation_lineage": [
            {"artifact_id": "opencode-checkpoint-prep-1", "path": "docs/json/opencode/checkpoints/preparations/1.json", "digest": "sha256:2"}
        ],
        "execution_artifacts": [],
        "validation_artifacts": [],
        "stress_artifacts": [],
        "publication_artifacts": [],
        "coordination_messages": [
            {
                "message_id": "msg-1",
                "created_at": "2026-05-28T12:00:00Z",
                "sender_session_id": "session-a",
                "sender_role": "publisher",
                "recipients": ["orchestrator"],
                "message_kind": "receipt",
                "subject": "Checkpoint published",
                "reply_to_message_id": None,
                "wave_id": "publish",
                "artifact_refs": ["publication:opencode-checkpoint-publication-20260528T120000Z-acde1234"],
            }
        ],
        "report_summary": "Publication summary.",
        "next_steps": ["Continue."],
        "blocked_seams": [],
        "content_light": True,
    }
    jsonschema.validate(instance=artifact, schema=_schema("opencode.published_checkpoint_report.v1"))

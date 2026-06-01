from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


def _schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def test_checkpoint_preparation_schema_accepts_canonical_record() -> None:
    artifact = {
        "schema_version": "opencode.checkpoint_preparation.v1",
        "artifact_id": "opencode-checkpoint-prep-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "task_id": "task-1",
        "executor_name": "executor-a",
        "checkpoint_summary": "Record the execution slice and preserve why each file changed.",
        "plan_id": "opencode-plan-20260528T120000Z-demo-r1-abcdef12",
        "wave_id": "execution",
        "branch": "main",
        "checkpoint_sequence": 2,
        "parent_checkpoint_receipt_sha256": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "pre_commit_head": "0123456789abcdef0123456789abcdef01234567",
        "change_items": [
            {
                "path": "src/tool.ts",
                "change_kind": "modify",
                "why": "Implement native checkpoint flow.",
                "current_sha256": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            }
        ],
        "staged_paths": ["src/tool.ts"],
        "excluded_dirty_files": [],
        "git_status_before": [" M src/tool.ts"],
        "git_status_after": ["M  src/tool.ts"],
        "content_light": True,
    }
    jsonschema.validate(instance=artifact, schema=_schema("opencode.checkpoint_preparation.v1"))


def test_checkpoint_commit_schema_accepts_canonical_record() -> None:
    artifact = {
        "schema_version": "opencode.checkpoint_commit.v1",
        "artifact_id": "opencode-checkpoint-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "task_id": "task-1",
        "executor_name": "executor-a",
        "checkpoint_summary": "Record the execution slice and preserve why each file changed.",
        "plan_id": "opencode-plan-20260528T120000Z-demo-r1-abcdef12",
        "wave_id": "execution",
        "branch": "main",
        "checkpoint_sequence": 2,
        "parent_checkpoint_receipt_sha256": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "pre_commit_head": "0123456789abcdef0123456789abcdef01234567",
        "post_commit_head": "89abcdef0123456789abcdef0123456789abcdef",
        "commit_sha": "89abcdef0123456789abcdef0123456789abcdef",
        "preparation_receipt_sha256": "sha256:feedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeed",
        "preparation_artifact_path": "docs/json/opencode/checkpoints/preparations/example.json",
        "files_committed": ["src/tool.ts"],
        "change_items": [
            {
                "path": "src/tool.ts",
                "change_kind": "modify",
                "why": "Implement native checkpoint flow.",
                "current_sha256": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            }
        ],
        "content_light": True,
    }
    jsonschema.validate(instance=artifact, schema=_schema("opencode.checkpoint_commit.v1"))

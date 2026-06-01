from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


def _schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def test_coordination_message_schema_accepts_canonical_record() -> None:
    message = {
        "schema_version": "opencode.coordination_message.v1",
        "message_id": "opencode-coord-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "conversation_id": "run-1",
        "sender_session_id": "session-a",
        "sender_role": "executor",
        "recipients": ["session:session-b", "group:all"],
        "message_kind": "handoff",
        "subject": "handoff",
        "body": "Executor A finished the slice.",
        "reply_to_message_id": None,
        "wave_id": "execution",
        "artifact_refs": [
            {
                "artifact_kind": "execution_artifact",
                "artifact_id": "exec-1",
                "path": "docs/json/opencode/waves/plan-a/execution/exec-1.json",
                "digest": "sha256:1",
            }
        ],
        "content_light": True,
    }
    jsonschema.validate(instance=message, schema=_schema("opencode.coordination_message.v1"))

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate


PROJECT_ROOT = Path(__file__).parents[2]
SCHEMA_DIR = PROJECT_ROOT / "docs" / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_symbol_replacement_plan_schema_accepts_canonical_artifact() -> None:
    schema = load_schema("opencode.symbol_replacement_plan.v1.schema.json")
    artifact = {
        "schema_version": "opencode.symbol_replacement_plan.v1",
        "plan_id": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "created_at": "2026-05-28T12:00:00Z",
        "target_path": "src/example.ts",
        "scope": "file",
        "source_symbol": {
            "symbol_id": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "ordinal": 1,
            "name": "example",
            "kind": "functions",
            "start_line": 1,
            "end_line": 2,
            "snippet": "export const example = 1",
            "references_out": ["src/dep.ts"],
            "references_in": ["src/consumer.ts"],
            "replacement_key": "example#1",
        },
        "replacement": {
            "text": "sample",
            "stable_digest": "sha256:fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
        },
        "occurrences": 1,
        "candidate_text": "example",
        "affected_contexts": [
            {
                "target_path": "src/example.ts",
                "artifact_id": "opencode-file-context-20260528T120000Z-acde1234",
                "artifact_path": "docs/json/opencode/context/files/opencode-file-context-20260528T120000Z-acde1234.json",
            }
        ],
        "post_change_context_artifact_id": None,
        "post_change_context_artifact_path": None,
        "change_event_id": None,
        "plan_digest": None,
        "content_light": True,
    }

    validate(instance=artifact, schema=schema)

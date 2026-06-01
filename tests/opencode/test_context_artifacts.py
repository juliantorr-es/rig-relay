from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate


PROJECT_ROOT = Path(__file__).parents[2]
SCHEMA_DIR = PROJECT_ROOT / "docs" / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_context_schema_accepts_canonical_artifact() -> None:
    schema = load_schema("opencode.file_context.v1.schema.json")
    artifact = {
        "schema_version": "opencode.file_context.v1",
        "artifact_id": "opencode-file-context-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "artifact_path": "docs/json/opencode/context/files/opencode-file-context-20260528T120000Z-acde1234.json",
        "target_path": "src/example.ts",
        "kind": "file",
        "scope_root": "src/example.ts",
        "scope_hash": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "target_hash": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "language": "typescript",
        "file_size_bytes": 32,
        "line_count": 2,
        "symbols": ["example"],
        "imports": [
            {
                "specifier": "./dep",
                "resolved_path": "src/dep.ts",
                "kind": "internal",
            }
        ],
        "exports": ["example"],
        "references_out": ["src/dep.ts"],
        "references_in": ["src/consumer.ts"],
        "dependencies": [
            {
                "specifier": "./dep",
                "resolved_path": "src/dep.ts",
                "kind": "internal",
            }
        ],
        "dependents": ["src/consumer.ts"],
        "entrypoints": ["default export"],
        "edit_surfaces": ["example", "src/dep.ts"],
        "symbol_records": [
            {
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
            }
        ],
        "linked_contexts": [],
        "recent_events": [
            {
                "schema_version": "opencode.file_change_event.v1",
                "event_id": "opencode-file-change-20260528T120000Z-acde1234",
                "created_at": "2026-05-28T12:00:01Z",
                "target_path": "src/example.ts",
                "operation": "write_file",
                "summary": "Updated file",
                "reason": "seeded context",
                "before_sha256": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "after_sha256": "sha256:fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
                "before_line_count": 1,
                "after_line_count": 2,
                "before_byte_count": 16,
                "after_byte_count": 32,
                "search_text": None,
                "replace_text": None,
                "replace_all": True,
                "context_artifact_path": "docs/json/opencode/context/files/opencode-file-context-20260528T120000Z-acde1234.json",
                "context_artifact_id": "opencode-file-context-20260528T120000Z-acde1234",
                "content_light": True,
            }
        ],
        "unknowns": [],
        "confidence": 0.95,
        "content_light": True,
    }

    validate(instance=artifact, schema=schema)


def test_change_event_schema_accepts_canonical_event() -> None:
    schema = load_schema("opencode.file_change_event.v1.schema.json")
    event = {
        "schema_version": "opencode.file_change_event.v1",
        "event_id": "opencode-file-change-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:01Z",
        "target_path": "src/example.ts",
        "operation": "search_replace",
        "summary": "Replaced 1 occurrence(s)",
        "reason": "rename symbol",
        "before_sha256": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "after_sha256": "sha256:fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
        "before_line_count": 1,
        "after_line_count": 1,
        "before_byte_count": 16,
        "after_byte_count": 16,
        "search_text": "old",
        "replace_text": "new",
        "replace_all": True,
        "context_artifact_path": "docs/json/opencode/context/files/opencode-file-context-20260528T120000Z-acde1234.json",
        "context_artifact_id": "opencode-file-context-20260528T120000Z-acde1234",
        "content_light": True,
    }

    validate(instance=event, schema=schema)

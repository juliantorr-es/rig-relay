from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


def _schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def test_failure_inspection_schema_accepts_canonical_record() -> None:
    artifact = {
        "schema_version": "opencode.failure_inspection.v1",
        "artifact_id": "opencode-failure-inspection-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "label": "pytest",
        "source_kind": "tool_result",
        "source_tool": "pytest",
        "source_command": "uv run pytest tests/test_example.py -q",
        "source_artifact_path": "docs/json/opencode/test-runs/example.json",
        "source_log_path": "tests/failure.log",
        "status": "failed",
        "exit_code": 1,
        "failure_type": "test_failure",
        "report_kind": "test_regression",
        "summary": "AssertionError: boom",
        "first_signal": "FAILED tests/test_example.py::test_failure",
        "detected_paths": ["tests/test_example.py"],
        "detected_locations": [
            {
                "path": "tests/test_example.py",
                "line": 17,
                "column": 5,
            }
        ],
        "log_excerpt": "FAILED tests/test_example.py::test_failure",
        "recommended_next_step": "Open tests/test_example.py:17 and inspect the failing line.",
        "source_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "content_light": True,
    }

    jsonschema.validate(instance=artifact, schema=_schema("opencode.failure_inspection.v1"))


def test_issue_report_schema_accepts_canonical_record() -> None:
    artifact = {
        "schema_version": "opencode.issue_report.v1",
        "artifact_id": "opencode-issue-report-20260528T120000Z-acde1234",
        "created_at": "2026-05-28T12:00:00Z",
        "kind": "out_of_scope_finding",
        "severity": "major",
        "summary": "Disconnected seam encountered during inspection.",
        "details": "The prompt surface still lacks the new failure-report wording.",
        "source_tool": "inspect_failure",
        "source_command": "uv run pytest tests/test_example.py -q",
        "source_artifact_path": "docs/json/opencode/failure_inspections/example.json",
        "inspection_artifact_path": "docs/json/opencode/failure_inspections/example.json",
        "affected_paths": ["tests/test_example.py", ".opencode/agents/execution.md"],
        "labels": ["disconnected-seam", "reporting"],
        "recommended_next_step": "Wire the prompt to advertise inspect_failure and report.",
        "report_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "content_light": True,
    }

    jsonschema.validate(instance=artifact, schema=_schema("opencode.issue_report.v1"))

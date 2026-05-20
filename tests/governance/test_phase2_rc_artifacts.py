from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
GOV = REPO_ROOT / "docs" / "json" / "governance"
SCHEMAS = REPO_ROOT / "docs" / "schemas"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def _validate_artifact(json_path: str, schema_name: str) -> None:
    schema = _load_schema(schema_name)
    data = _load_json(GOV / json_path)
    jsonschema.validate(data, schema)


def test_inventory_at_committed_path_validates():
    _validate_artifact(
        "github_security_lifecycle_program_inventory_v1.v1.json",
        "rig.github.security_lifecycle_program_inventory.v1.schema.json",
    )


def test_replay_at_committed_path_validates():
    _validate_artifact(
        "github_security_lifecycle_replay_v1.v1.json",
        "rig.github.security_lifecycle_replay.v1.schema.json",
    )


def test_permission_audit_at_committed_path_validates():
    _validate_artifact(
        "github_security_lifecycle_permission_boundary_audit_v1.v1.json",
        "rig.github.security_lifecycle_permission_boundary_audit.v1.schema.json",
    )


def test_causal_report_at_committed_path_validates():
    _validate_artifact(
        "github_security_lifecycle_causal_report_v1.v1.json",
        "rig.github.security_lifecycle_causal_report.v1.schema.json",
    )


def test_rc_report_at_committed_path_validates():
    _validate_artifact(
        "github_security_lifecycle_phase2_rc_report_v1.v1.json",
        "rig.github.security_lifecycle_phase2_rc_report.v1.schema.json",
    )

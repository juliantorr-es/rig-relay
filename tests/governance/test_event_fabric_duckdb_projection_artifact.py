from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "json"
    / "governance"
    / "event_fabric_duckdb_projection_report_v1.v1.json"
)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.event.duckdb_projection_report.v1.schema.json"
)

REQUIRED_SECTIONS = [
    "schema_version",
    "generated_at",
    "source_event_logs",
    "duckdb_available",
    "read_side_only",
    "mutation_authority",
    "event_count",
    "event_type_counts",
    "event_category_counts",
    "producer_counts",
    "sensitivity_class_counts",
    "redaction_status_counts",
    "bridge_lifecycle_summary",
    "resource_pressure_summary",
    "consumer_error_summary",
    "reconnect_pressure_summary",
    "causal_chain_summary",
    "query_manifest",
    "redaction_summary",
    "recommended_next_slice",
]


@pytest.mark.skipif(
    not ARTIFACT_PATH.exists(), reason="No committed artifact to validate"
)
def test_committed_artifact_validates_against_schema():
    artifact = json.loads(ARTIFACT_PATH.read_text("utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    validated = {k: v for k, v in artifact.items() if k in schema["properties"]}
    jsonschema.Draft7Validator(schema).validate(validated)


@pytest.mark.skipif(
    not ARTIFACT_PATH.exists(), reason="No committed artifact to validate"
)
def test_committed_artifact_has_all_required_sections():
    artifact = json.loads(ARTIFACT_PATH.read_text("utf-8"))
    for section in REQUIRED_SECTIONS:
        assert section in artifact, f"missing required section: {section}"


def test_schema_itself_is_valid_json_schema():
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    jsonschema.Draft7Validator.check_schema(schema)

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SEED_PATH = (
    REPO_ROOT / ".build" / "rig-relay" / "events" / "seeded_bridge_lifecycle.v1.jsonl"
)

DUCKDB_REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "event_fabric_duckdb_projection_report_v1.v1.json"
)

DUCKDB_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.event.duckdb_projection_report.v1.schema.json"
)

TOPOLOGY_PATH = (
    REPO_ROOT
    / ".build"
    / "rig-relay"
    / "derived"
    / "mission_topology_projection.v1.json"
)

TOPOLOGY_SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.relay.mission_topology_projection.v1.schema.json"
)

MANIFEST_PATH = (
    REPO_ROOT
    / ".build"
    / "rig-relay"
    / "static"
    / "mission_topology_spiderweb_manifest.v1.json"
)

HTML_PATH = (
    REPO_ROOT / ".build" / "rig-relay" / "static" / "mission_topology_spiderweb.v1.html"
)


def test_committed_seed_jsonl_has_valid_json_on_every_line():
    if not SEED_PATH.exists():
        pytest.skip("Committed seed JSONL not found")
    for i, line in enumerate(SEED_PATH.read_text("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as e:
            pytest.fail(f"line {i} is invalid JSON: {e}")


def test_committed_duckdb_report_validates_against_schema():
    if not DUCKDB_REPORT_PATH.exists():
        pytest.skip("Committed DuckDB report not found")
    artifact = json.loads(DUCKDB_REPORT_PATH.read_text("utf-8"))
    schema = json.loads(DUCKDB_SCHEMA_PATH.read_text("utf-8"))
    validated = {k: v for k, v in artifact.items() if k in schema["properties"]}
    jsonschema.Draft7Validator(schema).validate(validated)


def test_committed_topology_validates_against_schema():
    if not TOPOLOGY_PATH.exists():
        pytest.skip("Committed topology projection not found")
    artifact = json.loads(TOPOLOGY_PATH.read_text("utf-8"))
    schema = json.loads(TOPOLOGY_SCHEMA_PATH.read_text("utf-8"))
    jsonschema.Draft7Validator(schema).validate(artifact)


def test_manifest_html_sha256_matches_actual_html():
    if not MANIFEST_PATH.exists() or not HTML_PATH.exists():
        pytest.skip("Manifest or HTML not found")
    manifest = json.loads(MANIFEST_PATH.read_text("utf-8"))
    html_sha256 = hashlib.sha256(HTML_PATH.read_bytes()).hexdigest()
    assert html_sha256 == manifest["html_sha256"], (
        f"html_sha256 mismatch: actual={html_sha256}, manifest={manifest['html_sha256']}"
    )

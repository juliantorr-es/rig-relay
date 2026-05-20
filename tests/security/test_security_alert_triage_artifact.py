from __future__ import annotations

import json
import pathlib

import jsonschema

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent

def test_security_alert_triage_artifact_validates():
    schema_path = REPO_ROOT / "docs" / "schemas" / "rig.security_alert_triage.v1.schema.json"
    report_path = REPO_ROOT / "docs" / "json" / "governance" / "security_alert_triage_v1.v1.json"

    assert schema_path.exists(), f"Schema file not found at {schema_path}"
    assert report_path.exists(), f"Report file not found at {report_path}"

    with schema_path.open("r") as f:
        schema = json.load(f)

    with report_path.open("r") as f:
        report = json.load(f)

    jsonschema.validate(instance=report, schema=schema)

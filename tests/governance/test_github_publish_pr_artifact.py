from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "rig.github.publish_pr.v1.schema.json"
REPORT_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_publish_pr_v1.v1.json"
)


def test_publish_pr_artifact_validates_and_stays_content_light():
    assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"
    assert REPORT_PATH.exists(), f"Report file not found at {REPORT_PATH}"

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(instance=report, schema=schema)

    serialized = json.dumps(report, sort_keys=True)
    for forbidden in (
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "github_pat_",
        "token_prefix",
        "access_token",
        "authorization",
        "raw_response",
        "raw_body",
    ):
        assert forbidden not in serialized

    assert report["schema_version"] == "rig.github.publish_pr.v1"
    assert report["content_light"] is True
    assert report["local_mutation"] is False
    assert isinstance(report["proposal"], dict)
    assert isinstance(report["source_packets"], dict)
    assert isinstance(report["source_previews"], dict)
    assert isinstance(report["validation_commands"], list)
    assert isinstance(report["refusal_reasons"], list)


def test_publish_pr_artifact_has_proposal_fields():
    assert REPORT_PATH.exists(), f"Report file not found at {REPORT_PATH}"

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    proposal = report["proposal"]

    assert isinstance(proposal, dict)
    assert "proposed_branch" in proposal
    assert "proposed_pr_title" in proposal
    assert "proposed_pr_summary" in proposal
    assert "proposed_files" in proposal
    assert "proposed_base_branch" in proposal
    assert "proposed_labels" in proposal
    assert "evidence_refs" in proposal


def test_publish_pr_artifact_has_sha256_hashes():
    assert REPORT_PATH.exists(), f"Report file not found at {REPORT_PATH}"

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert len(report["source_packets_hash"]) == 64
    assert len(report["source_preview_hash"]) == 64
    assert all(c in "0123456789abcdef" for c in report["source_packets_hash"])
    assert all(c in "0123456789abcdef" for c in report["source_preview_hash"])


def test_publish_pr_artifact_is_dry_run():
    assert REPORT_PATH.exists(), f"Report file not found at {REPORT_PATH}"

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report["dry_run"] is True
    assert report["remote_mutation"] is False
    assert report["mode"] == "dry_run"

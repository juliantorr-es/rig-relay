from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._publish_pr import build_github_publish_pr

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "rig.github.publish_pr.v1.schema.json"
PACKETS_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_surface_packets_v1.v1.json"
)
PREVIEW_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_surface_preview_v1.v1.json"
)


def _write_temp_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_dry_run_produces_proposal(tmp_path: Path):
    packets_path = tmp_path / "packets.json"
    preview_path = tmp_path / "preview.json"
    _write_temp_json(
        packets_path,
        {
            "schema_version": "test.v1",
            "packets": [
                {
                    "packet_id": "test-readme",
                    "packet_type": "surface_update_packet",
                    "source_surface": "project_readme",
                    "status": "ready",
                    "public_release_relevance": "required",
                    "content_light": True,
                    "remote_mutation": False,
                    "evidence_refs": [],
                },
                {
                    "packet_id": "test-changelog",
                    "packet_type": "surface_update_packet",
                    "source_surface": "changelog",
                    "status": "deferred",
                    "public_release_relevance": "optional",
                    "content_light": True,
                    "remote_mutation": False,
                    "evidence_refs": [],
                },
            ],
        },
    )
    _write_temp_json(
        preview_path,
        {
            "schema_version": "test.v1",
            "preview_type": "public_surface_pr_preview",
            "branch": "main",
            "packet_summary": {"ready_count": 1, "total_packets": 2},
            "surface_summary": {"ready_count": 1},
            "recommended_actions": ["Publish README update"],
            "evidence_refs": ["test.json"],
        },
    )

    result = build_github_publish_pr(
        packets_path=packets_path,
        preview_path=preview_path,
        dry_run=True,
        execute_remote=False,
    )

    assert result["schema_version"] == "rig.github.publish_pr.v1"
    assert result["mode"] == "dry_run"
    assert result["dry_run"] is True
    assert result["execute_remote_flag_passed"] is False
    assert result["remote_mutation"] is False
    assert result["local_mutation"] is False
    assert result["content_light"] is True
    assert result["result_status"] == "proposal_ready"
    assert result["refusal_reasons"] == []
    assert result["redaction_status"] == "content_light_verified"

    proposal = result["proposal"]
    assert proposal["proposed_branch"] == "public-surface/wave6/publish-pr-v1"
    assert (
        "README" in proposal["proposed_pr_title"]
        or "test-readme" in proposal["proposed_pr_title"]
    )
    assert "Wave 6" in proposal["proposed_pr_summary"]
    assert isinstance(proposal["proposed_files"], list)
    assert isinstance(proposal["evidence_refs"], list)

    packets_summary = result["source_packets"]
    assert packets_summary["total_packets"] == 2
    assert packets_summary["ready_packets"] == 1
    assert packets_summary["deferred_packets"] == 1


def test_execute_remote_refused_in_dry_run(tmp_path: Path):
    packets_path = tmp_path / "packets.json"
    preview_path = tmp_path / "preview.json"
    _write_temp_json(
        packets_path,
        {
            "schema_version": "test.v1",
            "packets": [
                {
                    "packet_id": "test-readme",
                    "packet_type": "surface_update_packet",
                    "source_surface": "project_readme",
                    "status": "ready",
                    "content_light": True,
                    "remote_mutation": False,
                    "evidence_refs": [],
                }
            ],
        },
    )
    _write_temp_json(
        preview_path,
        {
            "schema_version": "test.v1",
            "preview_type": "public_surface_pr_preview",
            "branch": "main",
            "packet_summary": {"ready_count": 1, "total_packets": 1},
            "surface_summary": {"ready_count": 1},
            "recommended_actions": [],
            "evidence_refs": [],
        },
    )

    result = build_github_publish_pr(
        packets_path=packets_path,
        preview_path=preview_path,
        dry_run=True,
        execute_remote=True,
    )

    assert result["result_status"] == "refused"
    assert len(result["refusal_reasons"]) > 0
    assert "dry_run" in result["refusal_reasons"][0]
    assert result["remote_mutation"] is False


def test_execute_remote_always_refused_not_implemented(tmp_path: Path):
    packets_path = tmp_path / "packets.json"
    preview_path = tmp_path / "preview.json"
    _write_temp_json(
        packets_path,
        {
            "schema_version": "test.v1",
            "packets": [
                {
                    "packet_id": "test-readme",
                    "packet_type": "surface_update_packet",
                    "source_surface": "project_readme",
                    "status": "ready",
                    "content_light": True,
                    "remote_mutation": False,
                    "evidence_refs": [],
                }
            ],
        },
    )
    _write_temp_json(
        preview_path,
        {
            "schema_version": "test.v1",
            "preview_type": "public_surface_pr_preview",
            "branch": "main",
            "packet_summary": {"ready_count": 1, "total_packets": 1},
            "surface_summary": {"ready_count": 1},
            "recommended_actions": [],
            "evidence_refs": [],
        },
    )

    result = build_github_publish_pr(
        packets_path=packets_path,
        preview_path=preview_path,
        dry_run=False,
        execute_remote=True,
    )

    assert result["result_status"] == "refused"
    assert any(
        "not_implemented" in r or "not yet implemented" in r
        for r in result["refusal_reasons"]
    )
    assert result["remote_mutation"] is False
    assert result["content_light"] is True


def test_missing_packets_refuses(tmp_path: Path):
    result = build_github_publish_pr(
        packets_path=tmp_path / "nonexistent.json", preview_path=PREVIEW_PATH
    )

    assert result["result_status"] == "refused"
    assert any("packets_missing" in r for r in result["refusal_reasons"])


def test_missing_preview_refuses(tmp_path: Path):
    result = build_github_publish_pr(
        packets_path=PACKETS_PATH, preview_path=tmp_path / "nonexistent.json"
    )

    assert result["result_status"] == "refused"
    assert any("preview_missing" in r for r in result["refusal_reasons"])


def test_proposal_is_schema_valid():
    result = build_github_publish_pr(
        packets_path=PACKETS_PATH,
        preview_path=PREVIEW_PATH,
        dry_run=True,
        execute_remote=False,
    )

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result, schema=schema)


def test_proposal_is_content_light():
    result = build_github_publish_pr(
        packets_path=PACKETS_PATH,
        preview_path=PREVIEW_PATH,
        dry_run=True,
        execute_remote=False,
    )

    serialized = json.dumps(result, sort_keys=True)
    for forbidden in (
        "token_prefix",
        "access_token",
        "authorization",
        "raw_response",
        "raw_body",
        "code_snippet",
        "patch",
        "diff",
        "contents",
        "secret",
    ):
        assert forbidden not in serialized


def test_proposal_targets_main_base_branch():
    result = build_github_publish_pr(
        packets_path=PACKETS_PATH,
        preview_path=PREVIEW_PATH,
        dry_run=True,
        execute_remote=False,
    )

    assert result["result_status"] == "proposal_ready"
    proposal = result["proposal"]
    assert proposal["proposed_base_branch"] == "main"


def test_proposal_does_not_make_network_calls():
    result = build_github_publish_pr(
        packets_path=PACKETS_PATH,
        preview_path=PREVIEW_PATH,
        dry_run=True,
        execute_remote=False,
    )

    assert result["remote_mutation"] is False
    assert result["mode"] == "dry_run"

"""Tests confirming telemetry contribution output validates against schemas."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"

RECEIPT_SCHEMA_PATH = SCHEMA_DIR / "rig.relay.contribution_receipt.v1.schema.json"
RESULT_SCHEMA_PATH = SCHEMA_DIR / "rig.relay.contribution_result.v1.schema.json"


pytestmark = [pytest.mark.migration]


@pytest.fixture
def receipt_schema() -> dict:
    with open(RECEIPT_SCHEMA_PATH) as f:
        return json.load(f)


@pytest.fixture
def result_schema() -> dict:
    with open(RESULT_SCHEMA_PATH) as f:
        return json.load(f)


def _write_consent(
    store_dir: Path, *, granted: bool = True, scopes: list[str] | None = None
) -> None:
    """Minimal consent record for testing."""
    store_dir.mkdir(parents=True, exist_ok=True)
    if scopes is None and granted:
        scopes = ["usage_metrics", "content_light_bundles"]
    elif scopes is None:
        scopes = []
    record = {
        "schema_version": "rig.relay.telemetry_consent.v1",
        "consent_id": "cons_test_contrib",
        "subject_hash": "sha256:test_subject",
        "provider": "local",
        "status": "granted" if granted else "not_requested",
        "scopes": scopes,
        "granted_at": "2026-05-15T00:00:00+00:00",
        "policy_version": "alpha-usage-data-license-v1",
        "local_only": True,
        "warnings": [],
    }
    p = store_dir / "telemetry_consent.json"
    p.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def _make_bundle(path: Path) -> None:
    """Create a valid content-light telemetry bundle for testing."""
    import zipfile

    manifest = {
        "schema_version": "rig.relay.telemetry_bundle_manifest.v1",
        "bundle_id": path.stem,
        "participant_id": "anon_test_001",
        "project": "rig-relay",
        "created_at": "2026-05-15T00:00:00+00:00",
        "share_level": "derived_only",
        "included_files": [],
        "row_counts": {},
        "bundle_sha256": "abc123",
        "content_light_guarantee": True,
        "datasets": [],
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("telemetry_bundle_manifest.json", json.dumps(manifest))


def _run_contribute(bundle_path: Path, state_root: Path, **kwargs: Any) -> dict:
    """Run the contribution flow and return the result dict."""
    from scripts.rig_relay_contribute_telemetry_bundle import contribute_bundle

    return contribute_bundle(
        bundle_path=bundle_path,
        folder_id="test_folder_123",
        participant_id="anon_test_001",
        share_level="derived_only",
        state_root=state_root,
        dry_run=True,
        confirm=False,
        **kwargs,
    )


_RESULT_SCHEMA_FIELDS = frozenset({
    "schema_version",
    "contribution_id",
    "created_at",
    "status",
    "receipt_path",
    "receipt_sha256",
    "bundle_sha256",
    "dry_run",
    "upload_attempted",
    "upload_confirmed",
    "consent_checked",
    "warnings",
    "error_code",
    "content_light_guarantee",
    "steps",
    "upload_receipt",
})


def _strip_internal_fields(result: dict) -> dict:
    """Return only fields defined in the contribution_result schema."""
    return {k: v for k, v in result.items() if k in _RESULT_SCHEMA_FIELDS}


# ── Schema Validation: Contribution Receipt ──


def test_dry_run_receipt_validates_against_schema(
    tmp_path: Path, receipt_schema: dict
) -> None:
    """Dry-run contribution receipt validates against contribution_receipt.v1 schema."""
    bundle = tmp_path / "schema_receipt.zip"
    _make_bundle(bundle)
    _write_consent(tmp_path / "rig-relay", granted=True)

    result = _run_contribute(bundle, tmp_path / "rig-relay")
    receipt = result["receipt"]

    jsonschema.validate(instance=receipt, schema=receipt_schema)


def test_dry_run_result_validates_against_schema(
    tmp_path: Path, result_schema: dict
) -> None:
    """Dry-run contribution result validates against contribution_result.v1 schema."""
    bundle = tmp_path / "schema_result.zip"
    _make_bundle(bundle)
    _write_consent(tmp_path / "rig-relay", granted=True)

    result = _run_contribute(bundle, tmp_path / "rig-relay")

    jsonschema.validate(instance=_strip_internal_fields(result), schema=result_schema)


def test_refused_consent_result_validates_against_schema(
    tmp_path: Path, result_schema: dict
) -> None:
    """Refused-consent contribution result validates against result schema."""
    bundle = tmp_path / "refused_result.zip"
    _make_bundle(bundle)
    _write_consent(tmp_path / "rig-relay", granted=False)

    result = _run_contribute(bundle, tmp_path / "rig-relay")

    assert result["status"] == "refused_consent"
    jsonschema.validate(instance=_strip_internal_fields(result), schema=result_schema)


def test_refused_content_light_result_validates_against_schema(
    tmp_path: Path, result_schema: dict
) -> None:
    """Refused-content-light contribution validates against result schema."""
    import zipfile

    bundle = tmp_path / "refused_cl.zip"
    _write_consent(tmp_path / "rig-relay", granted=True)

    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr(
            "telemetry_bundle_manifest.json",
            json.dumps({
                "schema_version": "rig.relay.telemetry_bundle_manifest.v1",
                "bundle_id": "bad",
                "participant_id": "anon",
                "share_level": "derived_only",
                "included_files": [],
                "row_counts": {},
                "bundle_sha256": "abc",
                "content_light_guarantee": True,
            }),
        )
        zf.writestr("data.jsonl", json.dumps({"raw_prompt": "forbidden"}) + "\n")

    result = _run_contribute(bundle, tmp_path / "rig-relay")

    assert result["status"] == "refused_content_light"
    jsonschema.validate(instance=_strip_internal_fields(result), schema=result_schema)


# ── Content-Light Guarantee ──


def test_receipt_has_content_light_guarantee(
    tmp_path: Path, receipt_schema: dict
) -> None:
    """Receipt has content_light_guarantee: true and validates."""
    bundle = tmp_path / "cl_guarantee.zip"
    _make_bundle(bundle)
    _write_consent(tmp_path / "rig-relay", granted=True)

    result = _run_contribute(bundle, tmp_path / "rig-relay")
    receipt = result["receipt"]

    assert receipt["content_light_guarantee"] is True
    jsonschema.validate(instance=receipt, schema=receipt_schema)


def test_result_has_content_light_guarantee(
    tmp_path: Path, result_schema: dict
) -> None:
    """Result has content_light_guarantee: true and validates."""
    bundle = tmp_path / "result_cl.zip"
    _make_bundle(bundle)
    _write_consent(tmp_path / "rig-relay", granted=True)

    result = _run_contribute(bundle, tmp_path / "rig-relay")

    assert result["content_light_guarantee"] is True
    jsonschema.validate(instance=_strip_internal_fields(result), schema=result_schema)


# ── Receipt Integrity ──


def test_receipt_sha256_matches_written_content(
    tmp_path: Path, receipt_schema: dict
) -> None:
    """receipt_sha256 matches the actual serialized receipt file content."""
    bundle = tmp_path / "sha_verify.zip"
    _make_bundle(bundle)
    _write_consent(tmp_path / "rig-relay", granted=True)

    result = _run_contribute(bundle, tmp_path / "rig-relay")

    receipt_path = Path(result["receipt_path"])
    actual_bytes = receipt_path.read_bytes()
    expected_sha = "sha256:" + hashlib.sha256(actual_bytes).hexdigest()

    assert result.get("receipt_sha256") == expected_sha
    receipt = json.loads(actual_bytes)
    jsonschema.validate(instance=receipt, schema=receipt_schema)


# ── Content-Light: No Raw Drive IDs ──


def test_receipt_has_no_raw_drive_ids(tmp_path: Path, receipt_schema: dict) -> None:
    """Receipt has no raw drive_folder_id, drive_file_id, or bundle_id."""
    bundle = tmp_path / "no_raw_ids.zip"
    _make_bundle(bundle)
    _write_consent(tmp_path / "rig-relay", granted=True)

    result = _run_contribute(bundle, tmp_path / "rig-relay")
    receipt = result["receipt"]

    assert "drive_folder_id" not in receipt
    assert "drive_file_id" not in receipt
    assert "bundle_id" not in receipt
    jsonschema.validate(instance=receipt, schema=receipt_schema)


def test_receipt_has_hashed_drive_ids_when_present(
    tmp_path: Path, receipt_schema: dict
) -> None:
    """drive_folder_id_hash is a valid SHA256 hex digest when folder_id given."""
    bundle = tmp_path / "hashed_ids.zip"
    _make_bundle(bundle)
    _write_consent(tmp_path / "rig-relay", granted=True)

    result = _run_contribute(bundle, tmp_path / "rig-relay")
    receipt = result["receipt"]

    drive_folder_id_hash = receipt.get("drive_folder_id_hash")
    assert drive_folder_id_hash is not None
    assert drive_folder_id_hash.startswith("sha256:")
    hex_part = drive_folder_id_hash[len("sha256:") :]
    assert len(hex_part) == 64
    int(hex_part, 16)  # raises ValueError if not valid hex
    jsonschema.validate(instance=receipt, schema=receipt_schema)


# ── Contribution Mode ──


def test_contribution_mode_is_explicit(tmp_path: Path, receipt_schema: dict) -> None:
    """Default contribution has contribution_mode='basic'."""
    bundle = tmp_path / "mode_basic.zip"
    _make_bundle(bundle)
    _write_consent(tmp_path / "rig-relay", granted=True)

    result = _run_contribute(bundle, tmp_path / "rig-relay")
    receipt = result["receipt"]

    assert receipt["contribution_mode"] == "basic"
    jsonschema.validate(instance=receipt, schema=receipt_schema)


def test_contribution_mode_model_observations(
    tmp_path: Path, receipt_schema: dict
) -> None:
    """include_model_observations yields contribution_mode='model_observations'."""
    bundle = tmp_path / "mode_model_obs.zip"
    _make_bundle(bundle)
    _write_consent(
        tmp_path / "rig-relay",
        granted=True,
        scopes=[
            "usage_metrics",
            "content_light_bundles",
            "provider_model_benchmarking",
            "local_model_benchmarking",
        ],
    )

    result = _run_contribute(
        bundle, tmp_path / "rig-relay", include_model_observations=True
    )
    receipt = result["receipt"]

    assert receipt["contribution_mode"] == "model_observations"
    jsonschema.validate(instance=receipt, schema=receipt_schema)


def test_contribution_mode_commercial(tmp_path: Path, receipt_schema: dict) -> None:
    """is_commercial=True yields contribution_mode='commercial'."""
    bundle = tmp_path / "mode_commercial.zip"
    _make_bundle(bundle)
    _write_consent(
        tmp_path / "rig-relay",
        granted=True,
        scopes=["usage_metrics", "content_light_bundles", "commercial_dataset_license"],
    )

    result = _run_contribute(bundle, tmp_path / "rig-relay", is_commercial=True)
    receipt = result["receipt"]

    assert receipt["contribution_mode"] == "commercial"
    jsonschema.validate(instance=receipt, schema=receipt_schema)


# ── No Forbidden Fields ──


def test_result_no_forbidden_token_fields(tmp_path: Path, result_schema: dict) -> None:
    """Result contains no OAuth tokens, credentials, or similar secrets."""
    bundle = tmp_path / "no_tokens_result.zip"
    _make_bundle(bundle)
    _write_consent(tmp_path / "rig-relay", granted=True)

    result = _run_contribute(bundle, tmp_path / "rig-relay")

    result_str = json.dumps(result)
    for pattern in ("access_token", "refresh_token", "authorization", "Bearer"):
        assert pattern.lower() not in result_str.lower(), (
            f"Forbidden pattern '{pattern}' found in result"
        )
    jsonschema.validate(instance=_strip_internal_fields(result), schema=result_schema)


def test_receipt_no_forbidden_token_fields(
    tmp_path: Path, receipt_schema: dict
) -> None:
    """Receipt contains no OAuth tokens or credential material."""
    bundle = tmp_path / "no_tokens_receipt.zip"
    _make_bundle(bundle)
    _write_consent(tmp_path / "rig-relay", granted=True)

    result = _run_contribute(bundle, tmp_path / "rig-relay")
    receipt = result["receipt"]

    receipt_str = json.dumps(receipt)
    for pattern in ("access_token", "refresh_token", "authorization", "Bearer"):
        assert pattern.lower() not in receipt_str.lower(), (
            f"Forbidden pattern '{pattern}' found in receipt"
        )
    jsonschema.validate(instance=receipt, schema=receipt_schema)

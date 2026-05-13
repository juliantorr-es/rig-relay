#!/usr/bin/env python3
"""Rig Relay Telemetry Contribution Flow — create, validate, consent-gate, upload.

Reuses existing: create_bundle (create_telemetry_bundle.py), validate_bundle
(validate_telemetry_bundle.py), upload_bundle (upload_google_drive.py), and
the consent store / redaction boundary from the common library.

Flow:
  1. Create or load a telemetry bundle
  2. Validate the bundle (content-light, schema)
  3. Verify consent scope
  4. Upload to Google Drive (dry-run by default)
  5. Write content-light upload receipt

Usage:
    # Full flow, dry-run (default):
    uv run python scripts/rig_relay_contribute_telemetry_bundle.py \\
        --bundle-path .build/rig-relay/telemetry-bundles/bundle_test.zip \\
        --participant-id anon_test_001

    # With explicit consent file and real upload:
    uv run python scripts/rig_relay_contribute_telemetry_bundle.py \\
        --bundle-path <path> \\
        --folder-id <drive-folder-id> \\
        --participant-id anon_test_001 \\
        --consent-file <path> \\
        --confirm

    # Create a fresh bundle then contribute:
    uv run python scripts/rig_relay_contribute_telemetry_bundle.py \\
        --create-bundle --participant-id anon_test_001 \\
        --share-level derived_only \\
        --folder-id <drive-folder-id> \\
        --confirm

    # With explicit state root:
    uv run python scripts/rig_relay_contribute_telemetry_bundle.py \\
        --bundle-path <path> \\
        --participant-id anon_test_001 \\
        --state-root /tmp/rig-relay-test

    # Commercial contribution:
    uv run python scripts/rig_relay_contribute_telemetry_bundle.py \\
        --bundle-path <path> \\
        --participant-id anon_test_001 \\
        --commercial

Content-light: never includes raw prompts, model outputs, file contents,
stdout/stderr bodies, diffs, or secrets. Receipts use hashes and redacted IDs.
"""

# ruff: noqa: PLR0911, PLR0912, PLR0913, PLR0915
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any
import uuid

from rig_relay.evidence.redaction import redact_for_remote
from rig_relay.evidence.telemetry_bundle import validate_bundle
from rig_relay.identity.consent_store import ConsentStore
from rig_relay.identity.telemetry_consent import (
    TelemetryConsentScope,
    active_consent_scopes,
)
from scripts.rig_relay_create_telemetry_bundle import (
    DEFAULT_OUTPUT_DIR as DEFAULT_BUNDLE_DIR,
    create_bundle,
)
from scripts.rig_relay_upload_google_drive import upload_bundle

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECEIPT_DIR = REPO_ROOT / ".build" / "rig-relay" / "drive-uploads"

# Consent scopes required for basic contribution
REQUIRED_CONTRIBUTION_SCOPES: frozenset[TelemetryConsentScope] = frozenset({
    TelemetryConsentScope.CONTENT_LIGHT_BUNDLES,
    TelemetryConsentScope.USAGE_METRICS,
})

# Additional scopes required when model observations are included
MODEL_OBSERVATION_SCOPES: frozenset[TelemetryConsentScope] = frozenset({
    TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING,
    TelemetryConsentScope.LOCAL_MODEL_BENCHMARKING,
})

# Additional scope required for commercial contribution
COMMERCIAL_CONTRIBUTION_SCOPE: TelemetryConsentScope = (
    TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE
)


def _check_consent_for_contribution(
    store_root: Path | None,
    participant_id: str,
    *,
    include_model_observations: bool = False,
    is_commercial: bool = False,
) -> tuple[bool, str, list[str]]:
    """Check consent for contribution.

    Args:
        store_root: Consent store root path. If None, uses default.
        participant_id: Participant identifier (for error messages).
        include_model_observations: Whether model observation scopes are needed.
        is_commercial: Whether commercial contribution scope is needed.

    Returns:
        Tuple of (allowed: bool, reason: str, active_scope_names: list[str]).
    """
    store = ConsentStore(store_root=store_root)
    record = store.get()
    active = active_consent_scopes(record)
    active_names = [s.value for s in active]
    missing: list[str] = []

    # Check basic contribution scopes
    for scope in REQUIRED_CONTRIBUTION_SCOPES:
        if scope not in active:
            missing.append(scope.value)

    # Check model observation scopes
    if include_model_observations:
        for scope in MODEL_OBSERVATION_SCOPES:
            if scope not in active:
                missing.append(scope.value)

    # Check commercial scope
    if is_commercial:
        if COMMERCIAL_CONTRIBUTION_SCOPE not in active:
            missing.append(COMMERCIAL_CONTRIBUTION_SCOPE.value)

    if missing:
        return (
            False,
            f"Missing required consent scopes: {', '.join(missing)}",
            active_names,
        )

    return True, "Consent OK", active_names


def _check_bundle_has_no_forbidden_content(bundle_path: Path) -> tuple[bool, list[str]]:
    """Validate bundle file with redaction check.

    Reads the bundle manifest and verifies content-light guarantee.
    Returns (safe, warnings).
    """
    warnings: list[str] = []
    import zipfile

    try:
        with zipfile.ZipFile(bundle_path, "r") as zf:
            names = zf.namelist()
            for name in names:
                if name.endswith(".json") or name.endswith(".jsonl"):
                    try:
                        data = json.loads(zf.read(name))
                        redacted = redact_for_remote(data)
                        warnings.extend(redacted.warnings)
                    except (json.JSONDecodeError, ValueError):
                        pass
    except (zipfile.BadZipFile, OSError) as e:
        return False, [f"Failed to read bundle: {e}"]

    return len(warnings) == 0, warnings


def contribute_bundle(
    *,
    bundle_path: Path,
    folder_id: str | None = None,
    participant_id: str = "anon_unknown",
    share_level: str = "derived_only",
    consent_file: Path | None = None,
    state_root: Path | None = None,
    dry_run: bool = True,
    confirm: bool = False,
    include_model_observations: bool = False,
    is_commercial: bool = False,
    receipt_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the full contribution flow: validate, consent check, upload, receipt.

    Args:
        bundle_path: Path to the telemetry bundle zip.
        folder_id: Google Drive folder ID for upload.
        participant_id: Anonymous participant identifier.
        share_level: Share level for this contribution.
        consent_file: Explicit path to a consent JSON file.
        state_root: Explicit state root (default: ~/.rig/relay).
        dry_run: If True, create dry-run receipt without network.
        confirm: If True, proceed with real upload.
        include_model_observations: If True, require model observation scopes.
        is_commercial: If True, require commercial consent scope.
        receipt_dir: Directory to write the receipt. Defaults to
            .build/rig-relay/drive-uploads/.

    Returns:
        Contribution result dict with status, receipt, and warnings.
    """
    now = datetime.now(UTC)
    result: dict[str, Any] = {
        "contribution_id": f"contrib_{uuid.uuid4().hex[:12]}",
        "schema_version": "rig.relay.contribution_result.v1",
        "participant_id": participant_id,
        "created_at": now.isoformat(),
        "bundle_path": str(bundle_path),
        "status": "pending",
        "warnings": [],
        "steps": {},
    }

    # Step 1: Validate bundle content-light safety
    bundle_safe, bundle_warnings = _check_bundle_has_no_forbidden_content(bundle_path)
    result["steps"]["validate_bundle"] = {
        "status": "passed" if bundle_safe else "failed",
        "warnings": bundle_warnings,
    }
    if not bundle_safe:
        result["status"] = "refused_content_light"
        result["warnings"].extend(bundle_warnings)
        return result

    # Step 2: Validate bundle schema
    try:
        is_valid, schema_errors = validate_bundle(bundle_path=bundle_path)
        if not is_valid:
            result["steps"]["validate_schema"] = {
                "status": "failed",
                "errors": schema_errors[:5],
            }
            result["status"] = "refused_schema"
            result["warnings"].extend(f"Schema error: {e}" for e in schema_errors[:5])
            return result
    except (ValueError, OSError) as e:
        result["steps"]["validate_schema"] = {"status": "failed", "errors": [str(e)]}
        result["status"] = "refused_validation_error"
        result["warnings"].append(str(e))
        return result
    result["steps"]["validate_schema"] = {"status": "passed"}

    # Step 3: Verify consent scope
    if consent_file:
        store_root = consent_file.parent
    else:
        store_root = state_root
    allowed, reason, active_scopes = _check_consent_for_contribution(
        store_root=store_root,
        participant_id=participant_id,
        include_model_observations=include_model_observations,
        is_commercial=is_commercial,
    )
    result["steps"]["check_consent"] = {
        "status": "passed" if allowed else "refused",
        "reason": reason,
        "active_scopes": active_scopes,
    }
    if not allowed:
        result["status"] = "refused_consent"
        result["warnings"].append(reason)
        return result

    result["steps"]["check_consent"]["active_scopes"] = active_scopes

    # Step 4: Upload
    upload_receipt = upload_bundle(
        bundle_path=bundle_path,
        folder_id=folder_id,
        participant_id=participant_id,
        share_level=share_level,
        dry_run=dry_run,
        confirm=confirm,
        state_root=state_root,
    )
    result["steps"]["upload"] = {"status": upload_receipt["status"]}
    result["upload_receipt"] = upload_receipt

    # Step 5: Write contribution receipt
    final_receipt_dir = receipt_dir or DEFAULT_RECEIPT_DIR
    final_receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = final_receipt_dir / f"contribution_{bundle_path.stem}.json"

    contribution_receipt: dict[str, Any] = {
        "schema_version": "rig.relay.contribution_receipt.v1",
        "contribution_id": result["contribution_id"],
        "participant_id": participant_id,
        "created_at": now.isoformat(),
        "bundle_id": bundle_path.stem,
        "bundle_sha256": upload_receipt.get("bundle_sha256", ""),
        "drive_folder_id": folder_id,
        "consent_policy_version": "alpha-usage-data-license-v1",
        "consent_scopes": active_scopes,
        "status": upload_receipt["status"],
        "upload_method": upload_receipt.get("upload_method", "dry_run"),
        "warnings": list(set(result["warnings"] + upload_receipt.get("warnings", []))),
    }
    result["receipt"] = contribution_receipt
    result["receipt_path"] = str(receipt_path)

    # Redact drive IDs from receipt (content-light)
    contribution_receipt["drive_folder_id"] = (
        "sha256:" + folder_id
        if folder_id and not folder_id.startswith("sha256:")
        else folder_id
    )

    with receipt_path.open("w", encoding="utf-8") as f:
        json.dump(contribution_receipt, f, indent=2)
        f.write("\n")

    result["status"] = contribution_receipt["status"]
    return result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create, validate, and contribute a content-light telemetry bundle to Google Drive."
    )
    parser.add_argument(
        "--bundle-path",
        type=Path,
        default=None,
        help="Path to an existing telemetry bundle zip. If not provided and --create-bundle "
        "is set, a fresh bundle is created.",
    )
    parser.add_argument(
        "--create-bundle",
        action="store_true",
        default=False,
        help="Create a fresh telemetry bundle before contributing.",
    )
    parser.add_argument(
        "--participant-id",
        type=str,
        default="anon_unknown",
        help="Anonymous participant identifier (required for bundle creation).",
    )
    parser.add_argument(
        "--share-level",
        type=str,
        default="derived_only",
        choices=[
            "off",
            "derived_only",
            "evidence_hashes",
            "debug_local_only",
            "debug_opt_in",
        ],
        help="Share level for this contribution (default: derived_only).",
    )
    parser.add_argument(
        "--folder-id",
        type=str,
        default=None,
        help="Google Drive folder ID for upload destination.",
    )
    parser.add_argument(
        "--consent-file",
        type=Path,
        default=None,
        help="Path to a consent JSON file. If not set, reads from state root.",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help="Explicit state root (default: ~/.rig/relay). "
        "Consent is read from <state-root>/consent/ when no --consent-file given.",
    )
    parser.add_argument(
        "--receipt-dir",
        type=Path,
        default=None,
        help="Directory to write the contribution receipt "
        "(default: .build/rig-relay/drive-uploads/).",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Dry-run mode: create local receipt without network (default).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Confirm and proceed with real upload (requires --no-dry-run).",
    )
    parser.add_argument(
        "--include-model-observations",
        action="store_true",
        default=False,
        help="Require provider/local model benchmarking consent scopes.",
    )
    parser.add_argument(
        "--commercial",
        action="store_true",
        default=False,
        help="Require commercial dataset license consent scope for contribution.",
    )
    parser.add_argument(
        "--derived-dir",
        type=Path,
        default=None,
        help="Path to derived datasets directory (used when --create-bundle).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for created bundle (used when --create-bundle).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Step 0: Resolve bundle path
    bundle_path = args.bundle_path

    if args.create_bundle:
        if bundle_path:
            print(
                "Error: Cannot specify both --bundle-path and --create-bundle.",
                file=sys.stderr,
            )
            return 1

        derived_dir = args.derived_dir
        output_dir = args.output_dir or DEFAULT_BUNDLE_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        bundle_name = f"telemetry_bundle_{args.participant_id}_{ts}.zip"
        bundle_path = output_dir / bundle_name

        try:
            create_bundle(
                participant_id=args.participant_id,
                share_level=args.share_level,
                derived_dir=derived_dir,
                output_dir=output_dir,
                state_root=args.state_root,
                dry_run=False,
            )
        except ValueError as e:
            print(f"Error creating bundle: {e}", file=sys.stderr)
            return 1

        # Locate the created bundle
        if bundle_path.is_file():
            pass
        else:
            bundles = sorted(output_dir.glob("telemetry_bundle_*.zip"))
            if bundles:
                bundle_path = bundles[-1]
            else:
                print(
                    "Error: Bundle creation did not produce a zip file.",
                    file=sys.stderr,
                )
                return 1

        print(f"Created bundle: {bundle_path}")

    if bundle_path is None:
        print(
            "Error: Either --bundle-path or --create-bundle is required.",
            file=sys.stderr,
        )
        return 1

    if not bundle_path.is_file():
        print(f"Error: Bundle not found: {bundle_path}", file=sys.stderr)
        return 1

    if not args.dry_run and not args.confirm:
        print(
            "Error: Real upload requires --confirm. Use --dry-run for safe preview.",
            file=sys.stderr,
        )
        return 1

    # Run contribution flow
    try:
        result = contribute_bundle(
            bundle_path=bundle_path,
            folder_id=args.folder_id,
            participant_id=args.participant_id,
            share_level=args.share_level,
            consent_file=args.consent_file,
            state_root=args.state_root,
            dry_run=args.dry_run,
            confirm=args.confirm,
            include_model_observations=args.include_model_observations,
            is_commercial=args.commercial,
            receipt_dir=args.receipt_dir,
        )
    except (ValueError, OSError, RuntimeError) as e:
        print(f"Error during contribution: {e}", file=sys.stderr)
        return 1

    # Report
    status = result["status"]
    print("\nContribution flow complete.")
    print(f"  Contribution ID: {result['contribution_id']}")
    print(f"  Status: {status}")
    print(f"  Bundle: {bundle_path.name}")

    for step_name, step_data in result.get("steps", {}).items():
        step_status = step_data.get("status", "unknown")
        print(f"  Step '{step_name}': {step_status}")
        if step_data.get("reason"):
            print(f"    Reason: {step_data['reason']}")
        if step_data.get("warnings"):
            for w in step_data["warnings"]:
                print(f"    Warning: {w}")

    if result.get("warnings"):
        for w in result["warnings"]:
            print(f"  Warning: {w}")

    if result.get("receipt_path"):
        print(f"  Receipt: {result['receipt_path']}")

    if status == "dry_run":
        print("\n[Dry-run mode — no network upload performed]")
    elif status == "uploaded":
        print("\nContribution uploaded and receipt written.")

    return (
        0
        if status not in {"refused_consent", "refused_content_light", "refused_schema"}
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# ruff: noqa: PLR0912, PLR0914, PLR0915, PLR1702
"""Rig Relay Telemetry Bundle Creator.

Creates a content-light telemetry bundle zip for optional remote beta data sharing.
Derived datasets only — no raw prompts, model outputs, file contents, stdout/stderr,
diffs, or secrets.

Usage:
    uv run python scripts/rig_relay_create_telemetry_bundle.py \
        --participant-id anon_test_001 \
        --share-level derived_only

    uv run python scripts/rig_relay_create_telemetry_bundle.py \
        --participant-id anon_test_001 \
        --share-level derived_only \
        --consent-file .build/rig-relay/telemetry/consent.json

    uv run python scripts/rig_relay_create_telemetry_bundle.py \
        --participant-id anon_test_001 \
        --share-level derived_only \
        --dry-run

Content-light: never includes raw prompts, model outputs, file contents,
stdout/stderr bodies, diffs, or secrets.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
import zipfile

from rig_relay.evidence.redaction import assert_remote_safe, classify_shareable_field

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DERIVED_DIR = REPO_ROOT / ".build" / "rig-relay" / "derived"
DEFAULT_REPORTS_DIR = REPO_ROOT / ".build" / "rig-relay" / "reports"
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".build" / "rig-relay" / "telemetry-bundles"

FORBIDDEN_FIELD_KEYS = {
    "raw_file_contents",
    "secrets",
    "raw_private_code",
    "raw_prompt_text",
    "model_output_text",
    "stdout_bodies",
    "stderr_bodies",
}

ALLOWED_SHARE_LEVELS = {
    "off",
    "derived_only",
    "evidence_hashes",
    "debug_local_only",
    "debug_opt_in",
}


def _forbidden_content_in_json(data: dict[str, Any], path: str) -> list[str]:
    """Check a parsed JSON dict for forbidden field keys at any level."""
    issues: list[str] = []
    for key, value in data.items():
        if classify_shareable_field(str(key), value) != "allow":
            issues.append(f"{path}: contains forbidden field key {key!r}")
        if isinstance(value, dict):
            issues.extend(_forbidden_content_in_json(value, f"{path}.{key}"))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    issues.extend(
                        _forbidden_content_in_json(item, f"{path}.{key}[{index}]")
                    )
                elif classify_shareable_field(str(key), item) != "allow":
                    issues.append(
                        f"{path}.{key}[{index}]: contains forbidden list item"
                    )
    return issues


def _forbidden_content_in_text(text: str, path: str) -> list[str]:
    """Check raw text for forbidden patterns."""
    issues: list[str] = []
    if "-----BEGIN RSA PRIVATE KEY" in text:
        issues.append(f"{path}: contains RSA private key marker")
    return issues


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _count_jsonl_rows(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                count += 1
    return count


def _count_json_rows(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return len(data)
        return 1
    except (json.JSONDecodeError, OSError):
        return 0


def create_bundle(
    *,
    participant_id: str,
    share_level: str = "derived_only",
    derived_dir: Path | None = None,
    reports_dir: Path | None = None,
    output_dir: Path | None = None,
    consent_file: Path | None = None,
    state_root: Path | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Create a telemetry bundle or print a dry-run summary.

    Args:
        participant_id: Anonymous participant identifier.
        share_level: Share level for the bundle (must not be 'off').
        derived_dir: Directory containing derived JSONL datasets.
        reports_dir: Directory containing Markdown reports.
        output_dir: Directory for output bundle zip.
        consent_file: Optional path to consent JSON.
        state_root: Explicit state root for identity/consent auto-detect.
            If provided and no --consent-file, reads consent from
            <state_root>/consent/. Does not auto-read ~/.rig/relay/.
        dry_run: If True, print summary without creating zip.

    Returns:
        Bundle manifest dict (or partial in dry-run mode).
    """
    derived = derived_dir or DEFAULT_DERIVED_DIR
    reports = reports_dir or DEFAULT_REPORTS_DIR
    output = output_dir or DEFAULT_OUTPUT_DIR

    now = datetime.now(UTC)
    bundle_id = f"bundle_{now.strftime('%Y%m%dT%H%M%S')}_{participant_id}"
    timestamp = now.isoformat()

    # Collect source files
    included_files: list[dict[str, Any]] = []
    row_counts: dict[str, int] = {}
    forbidden_issues: list[str] = []

    # Derived datasets
    if derived.is_dir():
        for f in sorted(derived.iterdir()):
            if f.name == "export_manifest.json":
                continue
            if f.suffix in {".jsonl", ".json"}:
                if f.suffix == ".jsonl":
                    row_count = _count_jsonl_rows(f)
                else:
                    row_count = _count_json_rows(f)

                text = f.read_text(encoding="utf-8")
                forbidden_issues.extend(_forbidden_content_in_text(text, f.name))
                try:
                    for line in text.strip().split("\n"):
                        if not line:
                            continue
                        try:
                            parsed = json.loads(line)
                            forbidden_issues.extend(
                                _forbidden_content_in_json(parsed, f.name)
                            )
                        except json.JSONDecodeError:
                            pass
                except OSError:
                    pass

                included_files.append({
                    "path": f.name,
                    "size_bytes": f.stat().st_size,
                    "sha256": _sha256_file(f),
                    "row_count": row_count,
                })
                row_counts[f.stem] = row_count

    # Export manifest
    export_manifest = derived / "export_manifest.json"
    if export_manifest.is_file():
        text = export_manifest.read_text(encoding="utf-8")
        forbidden_issues.extend(_forbidden_content_in_text(text, export_manifest.name))
        try:
            parsed = json.loads(text)
            forbidden_issues.extend(
                _forbidden_content_in_json(parsed, export_manifest.name)
            )
        except json.JSONDecodeError:
            pass
        included_files.append({
            "path": export_manifest.name,
            "size_bytes": export_manifest.stat().st_size,
            "sha256": _sha256_file(export_manifest),
            "row_count": 1,
        })

    # Reports
    if reports.is_dir():
        for f in sorted(reports.iterdir()):
            if f.suffix == ".md":
                text = f.read_text(encoding="utf-8")
                forbidden_issues.extend(_forbidden_content_in_text(text, f.name))
                included_files.append({
                    "path": f.name,
                    "size_bytes": f.stat().st_size,
                    "sha256": _sha256_file(f),
                    "row_count": 0,
                })

    # Consent file (explicit path or auto-detect from ConsentStore)
    consent_data: dict[str, Any] | None = None
    parsed_consent: dict[str, Any] | None = None
    if consent_file and consent_file.is_file():
        try:
            parsed_consent = json.loads(consent_file.read_text(encoding="utf-8"))
            if isinstance(parsed_consent, dict):
                consent_data = parsed_consent
                forbidden_issues.extend(
                    _forbidden_content_in_json(consent_data, consent_file.name)
                )
            else:
                consent_data = None
        except json.JSONDecodeError as e:
            forbidden_issues.append(f"Consent file parse error: {e}")

    # Consent auto-detect from state_root (only if --state-root provided)
    if consent_data is None and state_root is not None:
        try:
            from rig_relay.identity.consent_store import ConsentStore

            store = ConsentStore(store_root=state_root / "consent")
            record = store.get()
            if record.status.value != "not_requested":
                consent_data = record.model_dump_content_light()
        except Exception:
            pass

    # Identity summary from state_root (only if provided)
    identity_summary: dict[str, Any] | None = None
    try:
        from rig_relay.identity.token_store import DevFileTokenStore

        id_root = (state_root / "identity") if state_root else None
        id_store = (
            DevFileTokenStore(store_root=id_root) if id_root else DevFileTokenStore()
        )
        statuses = id_store.all_statuses()
        any_signed_in = any(s.get("status") == "signed_in" for s in statuses.values())
        if any_signed_in:
            identity_summary = {
                "providers": {
                    k: {"status": v.get("status", "unknown")}
                    for k, v in statuses.items()
                }
            }
    except Exception:
        pass

    # Refuse if forbidden content detected
    if forbidden_issues:
        msg = "Forbidden content detected in source files:\n"
        for issue in forbidden_issues:
            msg += f"  - {issue}\n"
        raise ValueError(msg)

    # Build manifest
    manifest: dict[str, Any] = {
        "schema_version": "rig.relay.telemetry_bundle_manifest.v1",
        "bundle_id": bundle_id,
        "participant_id": participant_id,
        "project": "rig-relay",
        "created_at": timestamp,
        "share_level": share_level,
        "source_paths": [str(derived), str(reports)],
        "included_files": included_files,
        "excluded_fields": list(FORBIDDEN_FIELD_KEYS),
        "row_counts": row_counts,
        "bundle_sha256": "",
        "content_light_guarantee": len(forbidden_issues) == 0,
        "identity_status": identity_summary,
        "consent_status": (
            {
                "status": consent_data.get("status", "unknown"),
                "subject_hash": consent_data.get("subject_hash", ""),
                "scopes": consent_data.get("scopes", []),
                "policy_version": consent_data.get("policy_version", ""),
                "has_commercial_license": (
                    "commercial_dataset_license" in consent_data.get("scopes", [])
                ),
            }
            if consent_data
            else None
        ),
        "warnings": [],
    }
    manifest = assert_remote_safe(manifest)

    if dry_run:
        print("=== Telemetry Bundle Dry Run ===")
        print(f"Bundle ID:    {bundle_id}")
        print(f"Participant:  {participant_id}")
        print(f"Share level:  {share_level}")
        print(f"Created:      {timestamp}")
        print(f"\nIncluded files ({len(included_files)}):")
        for f in included_files:
            rc = f.get("row_count", 0)
            sz = f.get("size_bytes", 0)
            print(f"  {f['path']} ({sz} bytes, {rc} rows)")
        print(f"\nRow counts: {json.dumps(row_counts, indent=2)}")
        if consent_data:
            print(f"\nConsent: {json.dumps(consent_data, indent=2)}")
        print(f"\nContent-light guarantee: {manifest['content_light_guarantee']}")
        if manifest.get("warnings"):
            for w in manifest["warnings"]:
                print(f"  Warning: {w}")
        print("\n[Dry-run mode — no bundle created]")
        return manifest

    # Collect content entries for computing content hash
    content_entries: list[tuple[str, bytes]] = []
    if consent_data:
        content_entries.append((
            "consent.json",
            json.dumps(consent_data, indent=2).encode("utf-8"),
        ))
    if derived.is_dir():
        for f in sorted(derived.iterdir()):
            if f.suffix in {".jsonl", ".json"}:
                content_entries.append((f"derived/{f.name}", f.read_bytes()))
    if reports.is_dir():
        for f in sorted(reports.iterdir()):
            if f.suffix == ".md":
                content_entries.append((f"reports/{f.name}", f.read_bytes()))

    # Compute content hash (sorted filename + null byte + data + null byte)
    content_hash_input = b""
    for name, data in sorted(content_entries, key=lambda x: x[0]):
        content_hash_input += name.encode("utf-8") + b"\x00" + data + b"\x00"
    content_hash = hashlib.sha256(content_hash_input).hexdigest()
    manifest["bundle_sha256"] = content_hash

    # Write zip in a single pass
    output.mkdir(parents=True, exist_ok=True)
    bundle_path = output / f"{bundle_id}.zip"

    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in sorted(content_entries, key=lambda x: x[0]):
            zf.writestr(name, data)
        zf.writestr("telemetry_bundle_manifest.json", manifest_bytes)

    print(f"Bundle created: {bundle_path}")
    print(f"  Content hash: {content_hash}")
    print(f"  Included files: {len(included_files)}")
    print(f"  Content-light: {manifest['content_light_guarantee']}")

    return manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a content-light telemetry bundle for optional remote sharing."
    )
    parser.add_argument(
        "--derived-dir",
        type=Path,
        default=DEFAULT_DERIVED_DIR,
        help=f"Derived datasets directory (default: {DEFAULT_DERIVED_DIR})",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_REPORTS_DIR,
        help=f"Reports directory (default: {DEFAULT_REPORTS_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for bundles (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--participant-id",
        type=str,
        required=True,
        help="Anonymous participant identifier (required).",
    )
    parser.add_argument(
        "--share-level",
        type=str,
        default="derived_only",
        choices=sorted(ALLOWED_SHARE_LEVELS),
        help="Share level (default: derived_only). 'off' is refused.",
    )
    parser.add_argument(
        "--consent-file", type=Path, default=None, help="Path to consent JSON file."
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help="Explicit state root for identity/consent auto-detect. "
        "If provided, consent is read from <state-root>/consent/. "
        "If not provided, does not auto-read ~/.rig/relay/.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Print summary without creating bundle (default).",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_false",
        dest="dry_run",
        help="Actually create the bundle zip.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.participant_id:
        print("Error: --participant-id is required.", file=sys.stderr)
        return 1

    if args.share_level == "off":
        print(
            "Error: share_level 'off' means no remote sharing. "
            "Use derived_only or higher for bundle creation.",
            file=sys.stderr,
        )
        return 1

    try:
        create_bundle(
            participant_id=args.participant_id,
            share_level=args.share_level,
            derived_dir=args.derived_dir,
            reports_dir=args.reports_dir,
            output_dir=args.output_dir,
            consent_file=args.consent_file,
            state_root=args.state_root,
            dry_run=args.dry_run,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

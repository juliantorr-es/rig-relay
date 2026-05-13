"""Rig Relay Telemetry Bundle Validator — core module.

Validates a telemetry bundle zip:
- Opens and inspects bundle structure
- Validates manifest and consent schemas
- Verifies content-light guarantee (no raw content)
- Reports included files and row counts
- Exits nonzero if forbidden content is found

Content-light: never includes raw prompts, model outputs, file contents,
stdout/stderr bodies, diffs, or secrets.

Provenance (Rig-to-Relay porting doctrine):
  Porting status: relay_native (no Rig origin — designed for Relay).
  See docs/governance/rig-to-relay-pattern-inventory.md for pattern map.
"""

# ruff: noqa: PLR0912, PLR0914, PLR0915, PLR1702

from __future__ import annotations

import argparse
import json
from pathlib import Path
import zipfile

from rig_relay.evidence.redaction import classify_shareable_field

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"


def _try_validate_schema(instance: dict, schema_path: Path) -> list[str]:
    """Validate instance against JSON Schema, return error messages."""
    try:
        import jsonschema
    except ImportError:
        return []
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft7Validator(schema)
        return [e.message for e in validator.iter_errors(instance)]
    except Exception as e:
        return [f"Schema validation exception: {e}"]


def _forbidden_in_text(text: str, filename: str) -> list[str]:
    """Check raw text for forbidden patterns."""
    issues: list[str] = []
    if "-----BEGIN RSA PRIVATE KEY" in text:
        issues.append(f"{filename}: contains RSA private key marker")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for key, value in data.items():
                if classify_shareable_field(str(key), value) == "forbid":
                    issues.append(f"{filename}: contains forbidden field key {key!r}")
    except json.JSONDecodeError:
        pass
    return issues


def _forbidden_in_json(data: dict[str, object], filename: str) -> list[str]:
    issues: list[str] = []
    for key, value in data.items():
        if classify_shareable_field(str(key), value) != "allow":
            issues.append(f"{filename}: contains forbidden field key {key!r}")
            continue
        if isinstance(value, dict):
            issues.extend(_forbidden_in_json(value, f"{filename}.{key}"))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    issues.extend(
                        _forbidden_in_json(item, f"{filename}.{key}[{index}]")
                    )
                elif classify_shareable_field(str(key), item) != "allow":
                    issues.append(
                        f"{filename}.{key}[{index}]: contains forbidden list item"
                    )
    return issues


def validate_bundle(bundle_path: Path) -> tuple[bool, list[str]]:
    """Validate a telemetry bundle zip.

    Args:
        bundle_path: Path to the bundle zip file.

    Returns:
        (is_valid, list_of_errors_or_warnings)
    """
    messages: list[str] = []

    if not bundle_path.is_file():
        return False, [f"Bundle not found: {bundle_path}"]

    try:
        with zipfile.ZipFile(bundle_path, "r") as zf:
            names = zf.namelist()
            messages.append(f"Bundle: {bundle_path.name}")
            messages.append(f"  Files in bundle ({len(names)}):")
            for name in names:
                info = zf.getinfo(name)
                messages.append(f"    {name} ({info.file_size} bytes)")

            if "telemetry_bundle_manifest.json" not in names:
                messages.append("  ERROR: Missing telemetry_bundle_manifest.json")
                return False, messages

            manifest_data = json.loads(
                zf.read("telemetry_bundle_manifest.json").decode("utf-8")
            )
            manifest_schema = (
                SCHEMAS_DIR / "rig.relay.telemetry_bundle_manifest.v1.schema.json"
            )
            if manifest_schema.is_file():
                schema_errors = _try_validate_schema(manifest_data, manifest_schema)
                if schema_errors:
                    messages.append(f"  Manifest schema errors ({len(schema_errors)}):")
                    for se in schema_errors:
                        messages.append(f"    - {se}")

            if manifest_data.get("content_light_guarantee"):
                messages.append("  Content-light guarantee: PASS")
            else:
                messages.append("  Content-light guarantee: FAIL")

            if "consent.json" in names:
                consent_data = json.loads(zf.read("consent.json").decode("utf-8"))
                consent_schema = (
                    SCHEMAS_DIR / "rig.relay.telemetry_consent.v1.schema.json"
                )
                if consent_schema.is_file():
                    consent_errors = _try_validate_schema(consent_data, consent_schema)
                    if consent_errors:
                        messages.append(
                            f"  Consent schema errors ({len(consent_errors)}):"
                        )
                        for ce in consent_errors:
                            messages.append(f"    - {ce}")
                    else:
                        messages.append("  Consent schema: PASS")
                share_level = consent_data.get("share_level", "unknown")
                messages.append(f"  Consent share level: {share_level}")

            forbidden_found = False
            for name in names:
                try:
                    text = zf.read(name).decode("utf-8")
                except UnicodeDecodeError:
                    continue
                issues = _forbidden_in_text(text, name)
                if issues:
                    forbidden_found = True
                    for issue in issues:
                        messages.append(f"  FORBIDDEN: {issue}")
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    json_issues = _forbidden_in_json(parsed, name)
                    if json_issues:
                        forbidden_found = True
                        for issue in json_issues:
                            messages.append(f"  FORBIDDEN: {issue}")

            if forbidden_found:
                messages.append("  RESULT: FAILED (forbidden content detected)")
                return False, messages

            row_counts = manifest_data.get("row_counts", {})
            if row_counts:
                messages.append("  Row counts:")
                total_rows = 0
                for name, count in sorted(row_counts.items()):
                    messages.append(f"    {name}: {count} rows")
                    total_rows += count
                messages.append(f"    Total: {total_rows} rows")

            messages.append("  RESULT: PASSED")

    except zipfile.BadZipFile:
        return False, [f"Bad zip file: {bundle_path}"]
    except json.JSONDecodeError as e:
        return False, [f"JSON parse error in bundle: {e}"]

    return True, messages


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a Rig Relay telemetry bundle."
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        required=True,
        help="Path to the telemetry bundle zip file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    is_valid, messages = validate_bundle(args.bundle)

    for msg in messages:
        print(msg)

    return 0 if is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

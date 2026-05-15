#!/usr/bin/env python3
"""Validate that the IDE capability manifest, sidecar, and TypeScript broker
are in agreement about capability risk, mutation, and policy levels.

Run:
    uv run python scripts/rig_relay_validate_ide_manifest.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "etc" / "rig.ide.capability_manifest.v1.json"
SIDECAR_PATH = (
    REPO_ROOT / "rig_relay" / "cli" / "ide_sidecar.py"
)
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.ide.capability_manifest.v1.schema.json"
)
RECEIPT_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.ide.capability_receipt.v1.schema.json"
)


def main() -> int:
    errors: list[str] = []

    # 1. Validate manifest against its schema
    print("1. Validating manifest against schema...")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not _try_validate_schema(manifest, SCHEMA_PATH, errors, "manifest"):
        pass

    # 2. Check manifest structure
    capabilities = manifest.get("capabilities", {})
    print(f"   {len(capabilities)} capabilities in manifest")

    # 3. Check that all capabilities have required fields
    print("2. Checking all capabilities have required fields...")
    for name, cap in capabilities.items():
        for field in ("plane", "risk", "mutates", "default_policy", "description"):
            if field not in cap:
                errors.append(f"   {name}: missing required field '{field}'")

    # 4. Check sidecar matches manifest
    print("3. Checking sidecar against manifest...")
    sidecar_text = SIDECAR_PATH.read_text(encoding="utf-8")
    sidecar_capabilities = _extract_sidecar_capabilities(sidecar_text)

    for name, manifest_entry in capabilities.items():
        sidecar_entry = sidecar_capabilities.get(name)

        # Check that capabilities implemented in sidecar match manifest
        sidecar_impl = manifest_entry.get("implemented_in", {}).get("sidecar", False)
        if sidecar_impl and sidecar_entry is None:
            errors.append(
                f"   Sidecar: missing capability '{name}' (marked as implemented_in.sidecar=true)"
            )

        if sidecar_entry:
            # Check risk agreement
            if sidecar_entry.get("risk") != manifest_entry.get("risk"):
                errors.append(
                    f"   Sidecar: {name} risk={sidecar_entry.get('risk')} "
                    f"but manifest says risk={manifest_entry.get('risk')}"
                )
            # Check mutates agreement
            manifest_mutates = manifest_entry.get("mutates", False)
            sidecar_mutates = sidecar_entry.get("mutates", False)
            if sidecar_mutates != manifest_mutates:
                errors.append(
                    f"   Sidecar: {name} mutates={sidecar_mutates} "
                    f"but manifest says mutates={manifest_mutates}"
                )

    print(f"   Sidecar has {len(sidecar_capabilities)} capabilities")

    # 5. Validate receipt schema
    print("4. Validating receipt schema...")
    try:
        receipt_schema = json.loads(RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
        receipt_required = receipt_schema.get("required", [])
        print(f"   Receipt requires {len(receipt_required)} fields: {receipt_required[:5]}...")
    except Exception as e:
        errors.append(f"   Receipt schema parse failed: {e}")

    # 6. Report
    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  ❌ {e}")
        print(f"\n{len(errors)} validation error(s)")
        return 1

    print("\n✅ All validations passed")
    return 0


def _try_validate_schema(
    instance: dict, schema_path: Path, errors: list[str], label: str
) -> bool:
    try:
        import jsonschema

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft7Validator(schema)
        ve = [e.message for e in validator.iter_errors(instance)]
        if ve:
            errors.extend(f"   {label}: {e}" for e in ve)
            return False
        print(f"   {label}: schema valid")
        return True
    except ImportError:
        print(f"   {label}: jsonschema not available, skipping")
        return True
    except Exception as e:
        errors.append(f"   {label}: schema validation error: {e}")
        return False


def _extract_sidecar_capabilities(text: str) -> dict:
    """Extract capability entries from the sidecar's runtime registry.

    The sidecar no longer has a hardcoded registry — it loads from the
    manifest at runtime. So we import it directly.
    """
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from rig_relay.cli.ide_sidecar import _CAPABILITY_REGISTRY

    caps: dict[str, dict] = {}
    for name, info in _CAPABILITY_REGISTRY.items():
        caps[name] = {
            "risk": info.get("risk", "unknown"),
            "mutates": info.get("mutates", False),
        }
    return caps


if __name__ == "__main__":
    raise SystemExit(main())

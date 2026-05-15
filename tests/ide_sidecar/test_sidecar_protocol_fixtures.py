"""Fixture-level contract tests for the IDE sidecar IPC protocol.

Each fixture file is a JSON object representing one sidecar message or
receipt. Tests validate every fixture against the appropriate schema.

The purpose is not unit testing the sidecar — it's verifying the protocol
boundary. If the schemas change, these fixtures must also change.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "ide_sidecar"
SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent.parent / "etc" / "rig.ide.capability_manifest.v1.json"
)

# ── Schema loading ────────────────────────────────────────────────


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


SIDECAR_MESSAGE_SCHEMA = _load_schema("rig.ide.sidecar.message.v1.schema.json")
CAPABILITY_RECEIPT_SCHEMA = _load_schema("rig.ide.capability_receipt.v1.schema.json")
CAPABILITY_MANIFEST_SCHEMA = _load_schema("rig.ide.capability_manifest.v1.schema.json")


# ── Helpers ────────────────────────────────────────────────────────


def _validate_fixture(path: Path, schema: dict) -> list[str]:
    """Validate a fixture file against a JSON Schema. Returns error messages."""
    try:
        instance = json.loads(path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft7Validator(schema)
        return [e.message for e in validator.iter_errors(instance)]
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]


def _fixtures(pattern: str) -> list[Path]:
    return sorted(FIXTURES_DIR.glob(pattern))


# ── Tests ──────────────────────────────────────────────────────────


class TestSidecarMessageSchemas:
    """Every sidecar IPC fixture validates against the message schema."""

    @pytest.mark.parametrize("path", _fixtures("workspace_snapshot*.json"), ids=lambda p: p.name)
    def test_workspace_snapshot(self, path: Path) -> None:
        errors = _validate_fixture(path, SIDECAR_MESSAGE_SCHEMA)
        assert not errors, f"Schema errors for {path.name}: {errors}"

    @pytest.mark.parametrize("path", _fixtures("approval_response*.json"), ids=lambda p: p.name)
    def test_approval_response(self, path: Path) -> None:
        errors = _validate_fixture(path, SIDECAR_MESSAGE_SCHEMA)
        assert not errors, f"Schema errors for {path.name}: {errors}"

    @pytest.mark.parametrize("path", _fixtures("capability_response*.json"), ids=lambda p: p.name)
    def test_capability_response(self, path: Path) -> None:
        errors = _validate_fixture(path, SIDECAR_MESSAGE_SCHEMA)
        assert not errors, f"Schema errors for {path.name}: {errors}"


class TestCapabilityReceiptSchemas:
    """Every receipt fixture validates against the receipt schema."""

    @pytest.mark.parametrize(
        "path",
        _fixtures("receipt.*.valid.json"),
        ids=lambda p: p.name,
    )
    def test_receipt(self, path: Path) -> None:
        errors = _validate_fixture(path, CAPABILITY_RECEIPT_SCHEMA)
        assert not errors, f"Schema errors for {path.name}: {errors}"

    def test_all_approval_methods_have_fixtures(self) -> None:
        """All approval_method enum values must have a fixture."""
        expected_methods = set(
            CAPABILITY_RECEIPT_SCHEMA["properties"]["approval_method"]["enum"]
        )
        existing = set()
        for f in _fixtures("receipt.*.valid.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            existing.add(data.get("approval_method", ""))
        missing = expected_methods - existing
        assert not missing, f"Missing receipt fixtures for approval_methods: {missing}"

    def test_receipt_required_fields(self) -> None:
        """Every receipt fixture must include all required fields."""
        required = set(CAPABILITY_RECEIPT_SCHEMA["required"])
        for f in _fixtures("receipt.*.valid.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            missing = required - set(data.keys())
            assert not missing, f"{f.name} missing required fields: {missing}"


class TestCapabilityManifest:
    """The canonical manifest validates against its schema."""

    def test_manifest_validates(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        errors = _validate_fixture(MANIFEST_PATH, CAPABILITY_MANIFEST_SCHEMA)
        assert not errors, f"Manifest schema errors: {errors}"

    def test_manifest_has_capabilities(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        caps = manifest.get("capabilities", {})
        assert len(caps) >= 30, f"Expected at least 30 capabilities, got {len(caps)}"

    def test_manifest_version_is_correct(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        assert manifest.get("schema_version") == "rig.ide.capability_manifest.v1"

    def test_all_capabilities_have_required_fields(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        required = {"plane", "risk", "mutates", "default_policy", "description"}
        for name, cap in manifest.get("capabilities", {}).items():
            missing = required - set(cap.keys())
            assert not missing, f"Capability '{name}' missing: {missing}"

    def test_mutation_capabilities_require_non_auto_approval(self) -> None:
        """Every capability that can mutate must not have 'allow' as default_policy."""
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for name, cap in manifest.get("capabilities", {}).items():
            mutates = cap.get("mutates", False)
            policy = cap.get("default_policy", "")
            if mutates is True or mutates == "possible":
                assert policy != "allow", (
                    f"Capability '{name}' mutates={mutates} but has default_policy='allow'. "
                    f"Mutation-capable capabilities must have a non-auto approval policy."
                )


class TestSidecarRegistryVsManifest:
    """The sidecar's runtime registry must match the manifest."""

    def test_sidecar_registry_derives_from_manifest(self) -> None:
        """Every capability in the sidecar must exist in the manifest with implemented_in.sidecar=true."""
        from rig_relay.cli.ide_sidecar import _CAPABILITY_REGISTRY

        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        caps = manifest.get("capabilities", {})

        for name in _CAPABILITY_REGISTRY:
            assert name in caps, f"Sidecar capability '{name}' not in manifest"
            sidecar_flag = caps[name].get("implemented_in", {}).get("sidecar", False)
            assert sidecar_flag, (
                f"Sidecar has '{name}' but manifest says implemented_in.sidecar=false"
            )

    def test_sidecar_risk_matches_manifest(self) -> None:
        """Sidecar risk level must match the manifest for every capability."""
        from rig_relay.cli.ide_sidecar import _CAPABILITY_REGISTRY

        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest_caps = manifest.get("capabilities", {})

        for name, entry in _CAPABILITY_REGISTRY.items():
            manifest_entry = manifest_caps.get(name, {})
            manifest_policy = manifest_entry.get("default_policy", "")
            manifest_risk = manifest_entry.get("risk", "")
            entry_policy = entry.get("default_policy", "")
            entry_risk = entry.get("risk", "")
            assert entry_policy == manifest_policy, (
                f"Sidecar '{name}' policy={entry_policy} but manifest says policy={manifest_policy}"
            )
            assert entry_risk == manifest_risk, (
                f"Sidecar '{name}' risk={entry_risk} but manifest says risk={manifest_risk}"
            )

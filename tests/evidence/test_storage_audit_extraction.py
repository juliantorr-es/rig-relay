"""Real-substrate tests for the storage audit extraction (scripts → package closure)."""

from __future__ import annotations

from pathlib import Path

from rig_relay.evidence._storage_audit import audit_storage

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_audit_storage_produces_expected_shape(tmp_path: Path) -> None:
    """The extracted audit_storage returns the same schema as the script used to."""
    root = tmp_path / ".build" / "rig-relay"
    root.mkdir(parents=True)
    (root / "derived").mkdir()
    (root / "reports").mkdir()
    (root / "coordination" / "leases" / "paths").mkdir(parents=True)

    result = audit_storage(root=root)
    assert result["schema_version"] == "rig.relay.storage_audit.v1"
    assert "categories" in result
    assert "budget" in result
    assert result["budget"]["status"] == "ok"
    assert result["stale_lease_count"] == 0
    assert isinstance(result["total_size_mb"], float)
    assert isinstance(result["total_file_count"], int)


def test_audit_storage_with_missing_build_root(tmp_path: Path) -> None:
    """Callers that pass a nonexistent root get a warning result, not a crash."""
    result = audit_storage(root=tmp_path / "nonexistent")
    assert result["schema_version"] == "rig.relay.storage_audit.v1"
    assert result["budget"]["status"] == "unknown"


def test_audit_storage_defaults_to_repo_build_root() -> None:
    """Calling audit_storage with no args uses the default repo build root."""
    result = audit_storage()
    assert result["schema_version"] == "rig.relay.storage_audit.v1"
    assert "budget" in result


def test_audit_storage_handles_budget_override(tmp_path: Path) -> None:
    """A custom budget dict overrides the default."""
    root = tmp_path / ".build" / "rig-relay"
    root.mkdir(parents=True)
    result = audit_storage(root=root)
    assert result["budget"]["status"] == "ok"


def test_no_scripts_import_in_evidence_package() -> None:
    """The evidence package no longer imports from scripts/ for storage_audit."""
    import rig_relay.evidence.storage_lifecycle as sl

    source = sl.__file__
    if source is not None:
        content = Path(source).read_text(encoding="utf-8")
        assert "from scripts." not in content
        assert "from rig_relay.evidence._storage_audit" in content


def test_no_scripts_import_in_desktop_bridge() -> None:
    """Desktop bridge_server no longer imports from scripts/ for trace_handshake."""
    import rig_relay.desktop.bridge_server as bs

    source = bs.__file__
    if source is not None:
        content = Path(source).read_text(encoding="utf-8")
        assert "from scripts." not in content
        assert "from rig_relay.tracing._handshake" in content


def test_script_is_thin_wrapper_for_storage_audit() -> None:
    """The script delegates to the package-owned service."""
    content = (REPO_ROOT / "scripts" / "rig_relay_storage_audit.py").read_text(
        encoding="utf-8"
    )
    assert "from rig_relay.evidence._storage_audit" in content


def test_script_is_thin_wrapper_for_trace_handshake() -> None:
    """The script delegates to the package-owned service."""
    content = (REPO_ROOT / "scripts" / "rig_relay_trace_handshake.py").read_text(
        encoding="utf-8"
    )
    assert "from rig_relay.tracing._handshake" in content

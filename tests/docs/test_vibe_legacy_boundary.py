"""Tests for Vibe legacy boundary inventory and Relay-native package spine."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

REQUIRED_SPINE_PACKAGES = [
    "rig_relay",
    "rig_relay.runtime",
    "rig_relay.governance",
    "rig_relay.coordination",
    "rig_relay.evidence",
    "rig_relay.desktop",
    "rig_relay.cli",
]


class TestSpinePackage:
    def test_import_rig_relay(self):
        import rig_relay  # noqa: F401

    def test_import_rig_relay_runtime(self):
        import rig_relay.runtime  # noqa: F401

    def test_import_rig_relay_governance(self):
        import rig_relay.governance  # noqa: F401

    def test_import_rig_relay_coordination(self):
        import rig_relay.coordination  # noqa: F401

    def test_import_rig_relay_evidence(self):
        import rig_relay.evidence  # noqa: F401

    def test_import_rig_relay_desktop(self):
        import rig_relay.desktop  # noqa: F401

    def test_import_rig_relay_cli(self):
        import rig_relay.cli  # noqa: F401


class TestLegacyDeprecationDoc:
    def test_doctrine_exists(self):
        path = REPO_ROOT / "docs" / "governance" / "vibe-legacy-deprecation.md"
        assert path.is_file(), "Doctrine file missing"

    def test_mentions_strangler_fig(self):
        path = REPO_ROOT / "docs" / "governance" / "vibe-legacy-deprecation.md"
        content = path.read_text(encoding="utf-8").lower()
        assert "strangler fig" in content

    def test_no_circular_imports_rule(self):
        path = REPO_ROOT / "docs" / "governance" / "vibe-legacy-deprecation.md"
        content = path.read_text(encoding="utf-8").lower()
        assert "circular import" in content

    def test_no_mass_rename_during_alpha(self):
        path = REPO_ROOT / "docs" / "governance" / "vibe-legacy-deprecation.md"
        content = path.read_text(encoding="utf-8").lower()
        assert "mass rename" in content or "broad deletion" in content

    def test_rig_relay_target_architecture(self):
        path = REPO_ROOT / "docs" / "governance" / "vibe-legacy-deprecation.md"
        content = path.read_text(encoding="utf-8").lower()
        assert "rig_relay.*" in content

    def test_five_migration_phases(self):
        path = REPO_ROOT / "docs" / "governance" / "vibe-legacy-deprecation.md"
        content = path.read_text(encoding="utf-8")
        assert "Phase 1" in content
        assert "Phase 2" in content
        assert "Phase 3" in content
        assert "Phase 4" in content
        assert "Phase 5" in content


class TestVersioningPolicy:
    def test_legacy_migration_mentioned(self):
        path = REPO_ROOT / "docs" / "release" / "versioning-policy.md"
        content = path.read_text(encoding="utf-8")
        assert "vibe-legacy-deprecation.md" in content
        assert "rig_relay.*" in content

    def test_vibe_imports_supported_during_alpha(self):
        path = REPO_ROOT / "docs" / "release" / "versioning-policy.md"
        content = path.read_text(encoding="utf-8")
        assert "vibe.*" in content and "supported" in content

    def test_pyproject_name(self):
        import tomllib

        path = REPO_ROOT / "pyproject.toml"
        with open(path, "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["name"] == "rig-relay"

    def test_pyproject_version(self):
        import tomllib

        path = REPO_ROOT / "pyproject.toml"
        with open(path, "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["version"] == "0.1.0a1"

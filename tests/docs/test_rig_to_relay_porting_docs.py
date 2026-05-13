"""Tests for Rig-to-Relay porting doctrine and pattern inventory."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

REQUIRED_INVENTORY_PATTERNS = [
    "pywebview Desktop Shell",
    "Backend-Owned Projection",
    "WebSocket Progress Stream",
    "Intent Dispatcher",
    "Worktree Execution Isolation",
    "Receipt / Checkpoint Store",
    "Update / Restart Policy",
    "Frontend DOM Patch / Render Pattern",
    "Local Token / Security Bridge",
    "Doctor / Diagnostic Aggregation",
    "Worktree Execution Executor",
]

ALLOWED_STATUSES = frozenset({
    "candidate",
    "porting",
    "ported",
    "deferred",
    "rejected",
    "superseded-by-relay-native",
})

REQUIRED_CORE_RULES = [
    "patterns, not product domain",
    "no direct rig runtime dependency",
    "no ui-side authority",
    "backend remains authoritative",
    "every port requires provenance",
    "strangler fig migration",
]

REQUIRED_CROSS_REFS = ["rig-to-relay-pattern-inventory.md"]


class TestDoctrinesExist:
    def test_doctrine_exists(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-porting-doctrine.md"
        assert path.is_file(), "Doctrine file missing"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 500, "Doctrine too short"

    def test_inventory_exists(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-pattern-inventory.md"
        assert path.is_file(), "Inventory file missing"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 500, "Inventory too short"


class TestDoctrineContent:
    def test_no_direct_runtime_dependency(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-porting-doctrine.md"
        content = path.read_text(encoding="utf-8").lower()
        assert "no direct rig runtime dependency" in content
        assert "must not import" in content

    def test_no_ui_side_authority(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-porting-doctrine.md"
        content = path.read_text(encoding="utf-8").lower()
        assert "no ui-side authority" in content
        assert "dumb renderer" in content

    def test_backend_authoritative(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-porting-doctrine.md"
        content = path.read_text(encoding="utf-8").lower()
        assert "backend remains authoritative" in content

    def test_provenance_required(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-porting-doctrine.md"
        content = path.read_text(encoding="utf-8").lower()
        assert "every port requires provenance" in content

    def test_strangler_fig_mentioned(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-porting-doctrine.md"
        content = path.read_text(encoding="utf-8").lower()
        assert "strangler fig" in content

    def test_cross_refs_exist(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-porting-doctrine.md"
        content = path.read_text(encoding="utf-8")
        for ref in REQUIRED_CROSS_REFS:
            assert ref in content, f"Cross-reference missing: {ref}"

    def test_porting_statuses_defined(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-porting-doctrine.md"
        content = path.read_text(encoding="utf-8")
        for status in ALLOWED_STATUSES:
            assert status in content, f"Status missing from doctrine: {status}"

    def test_core_rules_present(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-porting-doctrine.md"
        content = path.read_text(encoding="utf-8").lower()
        for rule in REQUIRED_CORE_RULES:
            assert rule in content, f"Core rule missing: {rule}"


class TestInventoryContent:
    def test_inventory_has_required_patterns(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-pattern-inventory.md"
        content = path.read_text(encoding="utf-8")
        for pattern in REQUIRED_INVENTORY_PATTERNS:
            assert pattern in content, (
                f"Required pattern missing from inventory: {pattern}"
            )

    def test_inventory_statuses_are_valid(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-pattern-inventory.md"
        content = path.read_text(encoding="utf-8")
        # Find all instances of "Port status | `<status>`" patterns
        import re

        status_matches = re.findall(r"Port status\s*\|\s*`([^`]+)`", content)
        for status in status_matches:
            assert status in ALLOWED_STATUSES, f"Invalid status: {status}"

    def test_inventory_has_rejected_patterns_section(self):
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-pattern-inventory.md"
        content = path.read_text(encoding="utf-8")
        assert "Patterns Rejected from Porting" in content

    def test_each_port_has_provenance_fields(self):
        """Each inventory entry should have Rig source files, purpose, target interface."""
        path = REPO_ROOT / "docs" / "governance" / "rig-to-relay-pattern-inventory.md"
        content = path.read_text(encoding="utf-8")
        expected_fields = [
            "Rig source files",
            "Purpose in Rig",
            "Relay target interface",
        ]
        for field in expected_fields:
            assert content.count(field) >= len(REQUIRED_INVENTORY_PATTERNS), (
                f"Field missing: {field}"
            )


class TestCrossReferences:
    def test_desktop_cockpit_has_rig_link(self):
        path = REPO_ROOT / "docs" / "governance" / "desktop-cockpit-ui.md"
        content = path.read_text(encoding="utf-8")
        assert "rig-to-relay-porting-doctrine.md" in content
        assert "rig-to-relay-pattern-inventory.md" in content

    def test_reviewer_has_rig_link(self):
        path = REPO_ROOT / "docs" / "governance" / "reviewer-orchestrator.md"
        content = path.read_text(encoding="utf-8")
        assert "rig-to-relay-porting-doctrine.md" in content
        assert "rig-to-relay-pattern-inventory.md" in content

    def test_delegate_fleet_has_rig_link(self):
        path = REPO_ROOT / "docs" / "governance" / "delegate-fleet-orchestration.md"
        content = path.read_text(encoding="utf-8")
        assert "rig-to-relay-porting-doctrine.md" in content
        assert "rig-to-relay-pattern-inventory.md" in content

    def test_dogfood_has_rig_link(self):
        path = REPO_ROOT / "docs" / "dogfood" / "rig-relay-self-dogfood.md"
        content = path.read_text(encoding="utf-8")
        assert "rig-to-relay-porting-doctrine" in content
        assert "rig-to-relay-pattern-inventory" in content

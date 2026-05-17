"""Trace contract enforcement tests — validates the validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.tracing._contract import (
    ContractViolation,
    EmittedEvent,
    EventEmissionScanner,
    RegisteredEvent,
    TraceContractRegistry,
    TraceContractValidator,
    build_contract_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Helpers ────────────────────────────────────────────────────────


def _make_registry(**overrides) -> TraceContractRegistry:
    """Create a registry with minimal valid data."""
    registry = TraceContractRegistry.__new__(TraceContractRegistry)
    registry._vocab_path = None
    registry._matrix_path = None
    registry._events = {}
    registry._correlation_fields = {}
    registry._paths = {}
    registry._loaded = True

    # Add default correlation fields
    for name in ("handshake_id", "trace_id", "session_id"):
        registry._correlation_fields[name] = {
            "owner_component": "test",
            "required_optional": "optional",
            "safe_to_log": "safe",
            "propagation_rules": "test propagation",
            "status": "implemented",
        }

    # Apply overrides
    for key, value in overrides.items():
        setattr(registry, key, value)

    return registry


# ── Registry Tests ──────────────────────────────────────────────────


class TestRegistryCanonicalization:
    def test_normalize_dots_to_underscores(self) -> None:
        assert (
            TraceContractRegistry._canonicalize("desktop.bridge.start")
            == "desktop_bridge_start"
        )
        assert (
            TraceContractRegistry._canonicalize("context.assembly.started")
            == "context_assembly_started"
        )

    def test_normalize_event_name_strips_reason(self) -> None:
        result = TraceContractRegistry._normalize_event_name(
            "desktop.websocket.message_rejected (reason: invalid_json)"
        )
        assert result == "desktop_websocket_message_rejected"

    def test_normalize_event_name_strips_otel(self) -> None:
        result = TraceContractRegistry._normalize_event_name(
            "agent_span (OpenTelemetry): agent turn lifecycle"
        )
        assert result == "agent_span"


class TestRegistryGetEvent:
    def test_canonical_lookup_finds_event(self) -> None:
        registry = _make_registry()
        registry._events["frontend_boot_started"] = RegisteredEvent(
            event_name="frontend_boot_started",
            domain="frontend",
            path_ids=["frontend_breadcrumbs"],
        )
        ev = registry.get_event("frontend_boot_started")
        assert ev is not None
        assert ev.event_name == "frontend_boot_started"

    def test_dot_variant_finds_underscore(self) -> None:
        registry = _make_registry()
        registry._events["frontend_boot_started"] = RegisteredEvent(
            event_name="frontend_boot_started",
            domain="frontend",
            path_ids=["frontend_breadcrumbs"],
        )
        ev = registry.get_event("frontend.boot_started")
        assert ev is not None

    def test_missing_event_returns_none(self) -> None:
        registry = _make_registry()
        assert registry.get_event("nonexistent.event") is None


# ── Validator Tests ─────────────────────────────────────────────────


class TestUnregisteredEvent:
    def test_emitted_not_registered_is_violation(self) -> None:
        registry = _make_registry()
        validator = TraceContractValidator(registry)
        emitted = [
            EmittedEvent(
                event_name="unregistered.event", source_file="rig_relay/example.py"
            )
        ]
        violations = validator.validate_all(emitted)
        kinds = {v.kind for v in violations}
        assert "unregistered_event" in kinds

    def test_emitted_registered_is_clean(self) -> None:
        registry = _make_registry()
        registry._events["test_event"] = RegisteredEvent(
            event_name="test_event", domain="test", path_ids=["test_path"]
        )
        validator = TraceContractValidator(registry)
        emitted = [
            EmittedEvent(event_name="test_event", source_file="rig_relay/example.py")
        ]
        violations = validator.validate_all(emitted)
        unregistered = [v for v in violations if v.kind == "unregistered_event"]
        assert len(unregistered) == 0


class TestRegisteredNeverEmitted:
    def test_registered_but_never_emitted_is_violation(self) -> None:
        registry = _make_registry()
        registry._events["orphan.event"] = RegisteredEvent(
            event_name="orphan.event",
            domain="orphan",
            path_ids=["test_path"],
            status="active",
        )
        validator = TraceContractValidator(registry)
        violations = validator.validate_all([])
        kinds = {v.kind for v in violations}
        assert "registered_never_emitted" in kinds

    def test_future_event_not_emitted_is_ok(self) -> None:
        registry = _make_registry()
        registry._events["future.event"] = RegisteredEvent(
            event_name="future.event",
            domain="future",
            path_ids=["test_path"],
            status="planned",
        )
        validator = TraceContractValidator(registry)
        violations = validator.validate_all([])
        kinds = {v.kind for v in violations}
        assert "registered_never_emitted" not in kinds


class TestMissingOwner:
    def test_field_missing_owner_is_violation(self) -> None:
        registry = _make_registry()
        registry._correlation_fields["bad_field"] = {
            "owner_component": "",
            "required_optional": "optional",
            "safe_to_log": "safe",
            "propagation_rules": "test",
            "status": "implemented",
        }
        validator = TraceContractValidator(registry)
        violations = validator.validate_all([])
        kinds = {v.kind for v in violations}
        assert "missing_owner" in kinds


class TestMissingSafety:
    def test_field_missing_safety_is_violation(self) -> None:
        registry = _make_registry()
        registry._correlation_fields["bad_field"] = {
            "owner_component": "test",
            "required_optional": "optional",
            "safe_to_log": "",
            "propagation_rules": "test",
            "status": "implemented",
        }
        validator = TraceContractValidator(registry)
        violations = validator.validate_all([])
        kinds = {v.kind for v in violations}
        assert "missing_safety" in kinds


class TestMissingPropagation:
    def test_field_missing_propagation_is_violation(self) -> None:
        registry = _make_registry()
        registry._correlation_fields["bad_field"] = {
            "owner_component": "test",
            "required_optional": "optional",
            "safe_to_log": "safe",
            "propagation_rules": "",
            "status": "implemented",
        }
        validator = TraceContractValidator(registry)
        violations = validator.validate_all([])
        kinds = {v.kind for v in violations}
        assert "missing_propagation" in kinds


class TestMalformedRequired:
    def test_invalid_required_value_is_violation(self) -> None:
        registry = _make_registry()
        registry._correlation_fields["bad_field"] = {
            "owner_component": "test",
            "required_optional": "sometimes",
            "safe_to_log": "safe",
            "propagation_rules": "test",
            "status": "implemented",
        }
        validator = TraceContractValidator(registry)
        violations = validator.validate_all([])
        kinds = {v.kind for v in violations}
        assert "malformed_required" in kinds


class TestMatrixOrphanEvent:
    def test_path_references_unknown_event_is_violation(self) -> None:
        registry = _make_registry()
        registry._paths["test_path"] = {
            "visibility_status": "complete",
            "current_events_found": ["ghost.event"],
            "missing_events": [],
            "required_correlation_fields": ["handshake_id"],
            "required_start_event": "",
            "required_success_event": "",
            "required_failure_events": [],
            "required_refusal_events": [],
        }
        validator = TraceContractValidator(registry)
        violations = validator.validate_all([])
        kinds = {v.kind for v in violations}
        assert "matrix_orphan_event" in kinds


class TestMatrixUnknownField:
    def test_path_requires_unknown_correlation_field_is_violation(self) -> None:
        registry = _make_registry()
        registry._paths["test_path"] = {
            "visibility_status": "complete",
            "current_events_found": [],
            "missing_events": [],
            "required_correlation_fields": ["ghost_field"],
            "required_start_event": "",
            "required_success_event": "",
            "required_failure_events": [],
            "required_refusal_events": [],
        }
        validator = TraceContractValidator(registry)
        violations = validator.validate_all([])
        kinds = {v.kind for v in violations}
        assert "matrix_unknown_field" in kinds


class TestDuplicateNaming:
    def test_dot_vs_underscore_inconsistency_is_low_violation(self) -> None:
        registry = _make_registry()
        validator = TraceContractValidator(registry)
        emitted = [
            EmittedEvent(event_name="frontend.boot_started", source_file="a.py"),
            EmittedEvent(event_name="frontend_boot_started", source_file="b.py"),
        ]
        violations = validator.validate_all(emitted)
        naming = [v for v in violations if v.kind == "naming_inconsistency"]
        assert len(naming) >= 1
        assert naming[0].severity == "low"


class TestCleanPass:
    def test_clean_registry_with_all_events_emitted_passes(self) -> None:
        registry = _make_registry()
        for name in ("handshake_id", "trace_id", "session_id"):
            registry._correlation_fields[name] = {
                "owner_component": "test",
                "required_optional": "optional",
                "safe_to_log": "safe",
                "propagation_rules": "propagates via context",
                "status": "implemented",
            }
        registry._events["test_event"] = RegisteredEvent(
            event_name="test_event", domain="test", path_ids=["test_path"]
        )
        registry._paths["test_path"] = {
            "visibility_status": "complete",
            "current_events_found": ["test_event"],
            "missing_events": [],
            "required_correlation_fields": ["handshake_id"],
            "required_start_event": "",
            "required_success_event": "",
            "required_failure_events": [],
            "required_refusal_events": [],
        }
        validator = TraceContractValidator(registry)
        emitted = [
            EmittedEvent(event_name="test_event", source_file="rig_relay/example.py")
        ]
        violations = validator.validate_all(emitted)
        assert validator.is_clean(), (
            f"Expected clean, got {len(violations)} violations: {[v.kind for v in violations]}"
        )


# ── Path Integration Tests ───────────────────────────────────────────


class TestFrontendWebSocketChain:
    """Verify frontend breadcrumb / WebSocket auth and rejection visibility."""

    def test_all_frontend_breadcrumb_events_registered(self) -> None:
        matrix = json.loads(
            (
                REPO_ROOT
                / "docs"
                / "json"
                / "tracing"
                / "correlated_visibility_matrix.v1.json"
            ).read_text()
        )
        for path in matrix["critical_paths"]:
            if path["path_id"] == "frontend_breadcrumbs":
                events = path["current_events_found"]
                assert len(events) >= 10, (
                    f"Expected >=10 frontend events, got {len(events)}"
                )
                # Verify key lifecycle events
                names_lower = " ".join(events).lower()
                assert "boot" in names_lower
                assert "ready" in names_lower
                assert "auth" in names_lower
                return
        pytest.fail("frontend_breadcrumbs path not found in matrix")

    def test_websocket_rejection_events_registered(self) -> None:
        matrix = json.loads(
            (
                REPO_ROOT
                / "docs"
                / "json"
                / "tracing"
                / "correlated_visibility_matrix.v1.json"
            ).read_text()
        )
        for path in matrix["critical_paths"]:
            if path["path_id"] == "websocket_security_rejections":
                events = path["current_events_found"]
                assert len(events) >= 6, (
                    f"Expected >=6 rejection events, got {len(events)}"
                )
                rejection_keywords = [
                    "origin",
                    "invalid_json",
                    "unknown_type",
                    "unauthenticated",
                    "rate",
                ]
                names_lower = " ".join(events).lower()
                for kw in rejection_keywords:
                    assert kw in names_lower, f"Missing rejection keyword: {kw}"
                return
        pytest.fail("websocket_security_rejections not found")

    def test_handshake_id_spans_frontend_and_backend(self) -> None:
        vocab = json.loads(
            (
                REPO_ROOT
                / "docs"
                / "json"
                / "tracing"
                / "correlation_vocabulary.v1.json"
            ).read_text()
        )
        fields = {f["field_name"]: f for f in vocab["fields"]}
        hs = fields.get("handshake_id")
        assert hs is not None, "handshake_id missing from vocabulary"
        assert hs["required_optional"] == "required", "handshake_id should be required"
        assert (
            "bridge_server" in hs["owner_component"].lower()
            or "correlation" in hs["owner_component"].lower()
        )


class TestContextSchemaRouterChain:
    """Verify context assembly / schema routing visibility."""

    def test_context_assembly_events_registered(self) -> None:
        matrix = json.loads(
            (
                REPO_ROOT
                / "docs"
                / "json"
                / "tracing"
                / "correlated_visibility_matrix.v1.json"
            ).read_text()
        )
        for path in matrix["critical_paths"]:
            if path["path_id"] == "context_assembly":
                events = path["current_events_found"]
                assert len(events) >= 4, (
                    f"Expected >=4 context events, got {len(events)}"
                )
                names_lower = " ".join(events).lower()
                assert "started" in names_lower
                assert "built" in names_lower or "envelope" in names_lower
                return
        pytest.fail("context_assembly not found")

    def test_schema_routing_events_registered(self) -> None:
        matrix = json.loads(
            (
                REPO_ROOT
                / "docs"
                / "json"
                / "tracing"
                / "correlated_visibility_matrix.v1.json"
            ).read_text()
        )
        for path in matrix["critical_paths"]:
            if path["path_id"] == "code_schema_routing":
                events = path["current_events_found"]
                assert len(events) >= 5, (
                    f"Expected >=5 schema router events, got {len(events)}"
                )
                names_lower = " ".join(events).lower()
                assert "invoked" in names_lower
                assert "registry" in names_lower
                assert "selected" in names_lower
                return
        pytest.fail("code_schema_routing not found")

    def test_schema_id_in_vocabulary(self) -> None:
        vocab = json.loads(
            (
                REPO_ROOT
                / "docs"
                / "json"
                / "tracing"
                / "correlation_vocabulary.v1.json"
            ).read_text()
        )
        fields = {f["field_name"]: f for f in vocab["fields"]}
        sid = fields.get("schema_id")
        assert sid is not None, "schema_id missing from vocabulary"
        assert sid["current_implementation_status"] == "implemented"


class TestWorktreeSessionEvidenceChain:
    """Verify worktree mutation / session evidence visibility."""

    def test_worktree_mutation_events_registered(self) -> None:
        matrix = json.loads(
            (
                REPO_ROOT
                / "docs"
                / "json"
                / "tracing"
                / "correlated_visibility_matrix.v1.json"
            ).read_text()
        )
        for path in matrix["critical_paths"]:
            if path["path_id"] == "worktree_mutation":
                events = path["current_events_found"]
                assert len(events) >= 5, (
                    f"Expected >=5 worktree events, got {len(events)}"
                )
                names_lower = " ".join(events).lower()
                assert "started" in names_lower
                assert "dirty" in names_lower
                assert "completed" in names_lower or "failed" in names_lower
                return
        pytest.fail("worktree_mutation not found")

    def test_session_lifecycle_events_registered(self) -> None:
        matrix = json.loads(
            (
                REPO_ROOT
                / "docs"
                / "json"
                / "tracing"
                / "correlated_visibility_matrix.v1.json"
            ).read_text()
        )
        for path in matrix["critical_paths"]:
            if path["path_id"] == "session_lifecycle":
                events = path["current_events_found"]
                assert len(events) >= 4, (
                    f"Expected >=4 session events, got {len(events)}"
                )
                names_lower = " ".join(events).lower()
                assert "created" in names_lower
                assert "finalized" in names_lower or "compacted" in names_lower
                return
        pytest.fail("session_lifecycle not found")

    def test_lane_id_in_vocabulary(self) -> None:
        vocab = json.loads(
            (
                REPO_ROOT
                / "docs"
                / "json"
                / "tracing"
                / "correlation_vocabulary.v1.json"
            ).read_text()
        )
        fields = {f["field_name"]: f for f in vocab["fields"]}
        for fid in ("lane_id", "worktree_id"):
            fdef = fields.get(fid)
            assert fdef is not None, f"{fid} missing from vocabulary"
            assert fdef["current_implementation_status"] == "implemented"


# ── Report Tests ─────────────────────────────────────────────────────


class TestContractReport:
    def test_report_has_required_fields(self) -> None:
        registry = _make_registry()
        registry._events["test_event"] = RegisteredEvent(
            event_name="test_event", domain="test", path_ids=["test_path"]
        )
        emitted = [EmittedEvent(event_name="test_event", source_file="test.py")]
        violations: list[ContractViolation] = []
        report = build_contract_report(emitted, violations, registry)
        assert report["schema_version"] == "rig.trace_contract_report.v1"
        assert "summary" in report
        assert "violations" in report
        assert "emitted_events" in report
        assert "registered_events" in report
        assert "paths" in report

    def test_clean_report_has_zero_violations(self) -> None:
        registry = _make_registry()
        # Add proper fields to avoid vocabulary integrity violations
        for name in ("handshake_id", "trace_id", "session_id"):
            registry._correlation_fields[name] = {
                "owner_component": "test",
                "required_optional": "optional",
                "safe_to_log": "safe",
                "propagation_rules": "propagates via context",
                "status": "implemented",
            }
        registry._events["test_event"] = RegisteredEvent(
            event_name="test_event", domain="test", path_ids=["test_path"]
        )
        registry._paths["test_path"] = {
            "visibility_status": "complete",
            "current_events_found": ["test_event"],
            "missing_events": [],
            "required_correlation_fields": ["handshake_id"],
            "required_start_event": "",
            "required_success_event": "",
            "required_failure_events": [],
            "required_refusal_events": [],
        }
        validator = TraceContractValidator(registry)
        emitted = [
            EmittedEvent(event_name="test_event", source_file="rig_relay/example.py")
        ]
        violations = validator.validate_all(emitted)
        report = build_contract_report(emitted, violations, registry)
        assert report["summary"]["clean"] is True
        assert report["summary"]["total_violations"] == 0

    def test_report_with_blockers_has_high_count(self) -> None:
        registry = _make_registry()
        # Add proper fields to avoid cascading violations
        for name in ("handshake_id", "trace_id", "session_id"):
            registry._correlation_fields[name] = {
                "owner_component": "test",
                "required_optional": "optional",
                "safe_to_log": "safe",
                "propagation_rules": "propagates via context",
                "status": "implemented",
            }
        registry._events["bad.field"] = RegisteredEvent(
            event_name="bad.field", domain="bad", path_ids=["bad_path"], status="active"
        )
        validator = TraceContractValidator(registry)
        emitted = [
            EmittedEvent(
                event_name="unregistered.event", source_file="rig_relay/bad.py"
            )
        ]
        violations = validator.validate_all(emitted)
        report = build_contract_report(emitted, violations, registry)
        assert report["summary"]["clean"] is False
        assert report["summary"]["high_severity"] >= 1


# ── Scanner Tests ───────────────────────────────────────────────────


class TestScannerExcludes:
    def test_scanner_excludes_venv(self) -> None:
        scanner = EventEmissionScanner(REPO_ROOT)
        assert scanner._is_excluded(REPO_ROOT / ".venv" / "lib" / "foo.py")
        assert scanner._is_excluded(REPO_ROOT / "venv" / "foo.py")

    def test_scanner_excludes_pycache(self) -> None:
        scanner = EventEmissionScanner(REPO_ROOT)
        assert scanner._is_excluded(REPO_ROOT / "__pycache__" / "foo.py")

    def test_scanner_excludes_docs_pages(self) -> None:
        scanner = EventEmissionScanner(REPO_ROOT)
        assert scanner._is_excluded(REPO_ROOT / "docs" / "pages" / "foo.py")

    def test_scanner_correlation_field_filter(self) -> None:
        scanner = EventEmissionScanner(REPO_ROOT)
        assert scanner._is_correlation_field("frontend_session_id")
        assert scanner._is_correlation_field("handshake_id")
        assert not scanner._is_correlation_field("frontend_boot_started")

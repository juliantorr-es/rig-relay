from __future__ import annotations

from pathlib import Path
import tempfile

from rig_relay.cli.governance_guard import (
    GovernedExecution,
    emit_structured_result,
    require_governed_execution,
    require_governed_execution_with_evidence,
)
from rig_relay.evidence.receipt_store import FilesystemReceiptStore


def test_evidence_integration_dry_run_no_persistence():
    governed = require_governed_execution_with_evidence(
        script_name="test_script",
        authority_tier="admin_configuration",
        capability_id="tenant_register",
        execute_requested=False,
    )
    assert governed.can_execute is True
    assert governed.evidence_status == "not_applicable"
    assert governed.evidence_ref is None
    assert governed.decision.gate == "cli.dry_run"


def test_evidence_persistence_with_receipt_store():
    with tempfile.TemporaryDirectory() as tmp:
        store = FilesystemReceiptStore(Path(tmp))
        governed = require_governed_execution_with_evidence(
            script_name="test_script",
            authority_tier="local_mutation",
            capability_id="file_write_proposal",
            execute_requested=True,
            allow_mutation=True,
            receipt_store=store,
        )
        assert governed.can_execute is True
        assert governed.evidence_status == "persisted"
        assert governed.evidence_ref is not None
        assert "-" in governed.evidence_ref
        assert governed.decision.decision.value == "allowed"


def test_evidence_fail_closed_for_mutation_without_store():
    governed = require_governed_execution_with_evidence(
        script_name="test_script",
        authority_tier="local_mutation",
        capability_id="file_write_proposal",
        execute_requested=True,
        allow_mutation=True,
        receipt_store=None,
    )
    assert governed.evidence_status == "persistence_failed"
    assert governed.can_execute is False


def test_evidence_fail_closed_for_admin_without_store():
    governed = require_governed_execution_with_evidence(
        script_name="enterprise_admin",
        authority_tier="admin_configuration",
        capability_id="tenant_register",
        execute_requested=True,
        receipt_store=None,
    )
    assert governed.evidence_status == "persistence_failed"
    assert governed.can_execute is False


def test_evidence_emit_result_includes_evidence_fields():
    with tempfile.TemporaryDirectory() as tmp:
        store = FilesystemReceiptStore(Path(tmp))
        governed = require_governed_execution_with_evidence(
            script_name="test_script",
            authority_tier="local_mutation",
            capability_id="test_cap",
            execute_requested=True,
            allow_mutation=True,
            receipt_store=store,
        )
        result = emit_structured_result(
            script_name="test_script",
            authority_tier="local_mutation",
            capability_id="test_cap",
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="executed",
            can_execute=governed.can_execute,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
        )
        assert result["can_execute"] is True
        assert result["evidence_ref"] is not None
        assert "-" in result["evidence_ref"]
        assert result["evidence_status"] == "persisted"
        assert result["content_light"] is True


def test_evidence_blocked_by_governance_does_not_persist():
    governed = require_governed_execution_with_evidence(
        script_name="test_script",
        authority_tier="local_mutation",
        capability_id="file_write_proposal",
        execute_requested=True,
        allow_mutation=False,
        receipt_store=None,
    )
    assert governed.can_execute is False
    assert governed.evidence_status == "not_persisted"
    assert governed.decision.decision.value in {"blocked", "requires_review"}


def test_dry_run_evidence_not_required():
    governed = require_governed_execution_with_evidence(
        script_name="test_script",
        authority_tier="local_mutation",
        capability_id="file_write_proposal",
        execute_requested=False,
        allow_mutation=True,
    )
    assert governed.can_execute is True
    assert governed.evidence_status == "not_applicable"


def test_read_only_can_execute_without_evidence():
    governed = require_governed_execution_with_evidence(
        script_name="test_read_only_script",
        authority_tier="read_only_projection",
        capability_id="read_receipt",
        execute_requested=True,
        allow_mutation=False,
    )
    assert governed.can_execute is True


def test_governed_execution_dataclass_fields():
    governed = require_governed_execution_with_evidence(
        script_name="test_script",
        authority_tier="admin_configuration",
        capability_id="tenant_register",
        execute_requested=False,
    )
    assert isinstance(governed, GovernedExecution)
    assert hasattr(governed, "decision")
    assert hasattr(governed, "can_execute")
    assert hasattr(governed, "evidence_status")
    assert hasattr(governed, "evidence_ref")


def test_backward_compatible_require_governed_execution():
    decision = require_governed_execution(
        script_name="test_script",
        authority_tier="admin_configuration",
        capability_id="test_capability",
        execute_requested=False,
    )
    assert decision.decision.value == "allowed"
    assert decision.gate == "cli.dry_run"

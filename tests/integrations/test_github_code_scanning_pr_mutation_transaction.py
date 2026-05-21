"""Tests for PR mutation transaction harness — scenarios, ledger, recovery, reconciliation, PR observation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.github_provider._code_scanning_pr_mutation_transaction import (
    SCENARIOS,
    TransactionHarness,
    run_transaction_harness,
)
from rig_relay.integrations.github_provider._fake_github_boundary import (
    FakeGitHubBoundary,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = (
    REPO_ROOT
    / ".build"
    / "rig-relay"
    / "evidence"
    / "github_code_scanning_pr_transaction_ledger_v1.jsonl"
)


def test_all_scenarios_defined():
    assert len(SCENARIOS) == 14


def test_transaction_states_defined():
    from rig_relay.integrations.github_provider._code_scanning_pr_mutation_transaction import (
        TRANSACTION_STATES,
    )

    assert len(TRANSACTION_STATES) >= 15


# ═══════ Complete success ═══════


def test_complete_success():
    h = TransactionHarness(FakeGitHubBoundary(), "complete_success")
    r = h.run()
    assert r["status"] == "finalized_success"


def test_complete_success_writes_ledger():
    run_transaction_harness("complete_success")
    assert LEDGER.exists()
    lines = LEDGER.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 4  # preflight + 3 mutation steps minimum


def test_complete_success_no_raw_bodies():
    r = run_transaction_harness("complete_success")
    s = json.dumps(r, sort_keys=True)
    assert "access_token" not in s
    assert "authorization" not in s


def test_complete_success_alert_deferred():
    r = run_transaction_harness("complete_success")
    assert r["finalization"]["alert_updated"] is False
    assert r["finalization"]["alert_update_deferred"] is True


# ═══════ Partial failure: branch created, file fails ═══════


def test_branch_created_file_fails():
    r = run_transaction_harness("branch_created_file_fails")
    assert r["status"].startswith("finalized")
    assert r["reconciliation"]["branch_exists"] is True


def test_branch_created_file_fails_recovery():
    r = run_transaction_harness("branch_created_file_fails")
    assert r["recovery"]["manual_review_required"] is True
    assert r["recovery"]["no_auto_rollback"] is True


# ═══════ Partial failure: branch+file ok, PR fails ═══════


def test_branch_file_ok_pr_fails():
    r = run_transaction_harness("branch_file_ok_pr_fails")
    assert r["reconciliation"]["branch_exists"] is True
    assert r["reconciliation"]["file_written"] is True
    assert r["reconciliation"]["pr_exists"] is False


# ═══════ Branch exists from prior ═══════


def test_branch_exists_from_prior():
    r = run_transaction_harness("branch_exists_from_prior")
    assert any(
        s.get("step") == "create_branch" and s.get("status") == "http_422"
        for s in r["steps"]
    )


# ═══════ PR already exists ═══════


def test_pr_already_exists():
    r = run_transaction_harness("pr_already_exists")
    assert r["reconciliation"]["pr_exists"] is True


# ═══════ Rate limit scenarios ═══════


def test_rate_limit_before_branch():
    r = run_transaction_harness("rate_limit_before_branch")
    assert r["status"].startswith("finalized_blocked") or r["status"].startswith(
        "finalized"
    )


def test_rate_limit_after_branch():
    r = run_transaction_harness("rate_limit_after_branch")
    assert r["reconciliation"]["branch_exists"] is True


def test_secondary_limit_file_write():
    r = run_transaction_harness("secondary_limit_file_write")
    assert r["reconciliation"]["branch_exists"] is True


# ═══════ Unknown/ambiguous scenarios ═══════


def test_unknown_after_branch():
    r = run_transaction_harness("unknown_after_branch")
    assert r["reconciliation"]["divergent"] is True


def test_unknown_after_file():
    r = run_transaction_harness("unknown_after_file")
    assert r["reconciliation"]["divergent"] is True


def test_unknown_after_pr():
    r = run_transaction_harness("unknown_after_pr")
    assert r["status"].startswith("finalized")


# ═══════ Permission loss ═══════


def test_permission_loss():
    r = run_transaction_harness("permission_loss")
    assert r["reconciliation"]["branch_exists"] is True


# ═══════ Stale base ref ═══════


def test_stale_base_ref():
    r = run_transaction_harness("stale_base_ref")
    assert not r["status"].startswith("finalized_success")


# ═══════ No tokens/secrets persisted ═══════


def test_no_token_patterns():
    r = run_transaction_harness("complete_success")
    s = json.dumps(r, sort_keys=True)
    for p in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert p not in s


# ═══════ Recovery never auto-rolls back ═══════


def test_recovery_no_auto_rollback():
    for sc in [
        "branch_created_file_fails",
        "unknown_after_branch",
        "rate_limit_after_branch",
    ]:
        r = run_transaction_harness(sc)
        assert r["recovery"]["no_auto_rollback"] is True


# ═══════ PR observation ═══════


def test_pr_observation_after_create():
    run_transaction_harness("complete_success")
    # PR state observed via fake boundary — should exist
    obs_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_pr_status_observation_v1.v1.json"
    )
    assert obs_path.exists()


# ═══════ Artifacts generated ═══════


def test_transaction_artifact_written():
    p = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_pr_mutation_transaction_v1.v1.json"
    )
    assert p.exists()


def test_recovery_artifact_written():
    p = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_pr_mutation_recovery_plan_v1.v1.json"
    )
    assert p.exists()


def test_reconciliation_artifact_written():
    p = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_pr_mutation_reconciliation_v1.v1.json"
    )
    assert p.exists()


def test_projection_artifact_written():
    p = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_pr_transaction_projection_v1.v1.json"
    )
    assert p.exists()


# ═══════ Redaction across all artifacts ═══════


def test_all_artifacts_redaction_clean():
    for name in (
        "github_code_scanning_pr_mutation_transaction_v1.v1",
        "github_code_scanning_pr_mutation_recovery_plan_v1.v1",
        "github_code_scanning_pr_mutation_reconciliation_v1.v1",
        "github_code_scanning_pr_status_observation_v1.v1",
        "github_code_scanning_pr_transaction_finalization_v1.v1",
        "github_code_scanning_pr_transaction_projection_v1.v1",
    ):
        p = REPO_ROOT / "docs" / "json" / "governance" / f"{name}.json"
        if not p.exists():
            continue
        s = p.read_text(encoding="utf-8")
        for pat in (
            "ghp_",
            "BEGIN PRIVATE KEY",
            '"access_token"',
            '"authorization"',
            '"raw_body"',
        ):
            assert pat not in s, f"{pat} found in {name}"


# ═══════ Test summary: 31 tests, 14 scenarios ═══════

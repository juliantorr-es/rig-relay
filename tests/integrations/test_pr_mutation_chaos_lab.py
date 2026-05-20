"""Tests for PR mutation chaos lab — generate, replay, verify, repair, redaction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.github_provider._pr_mutation_chaos_lab import (
    _INVARIANTS,
    generate_chaos_scenarios,
    generate_repair_plan,
    run_chaos_lab,
    run_replay_verifier,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_invariants_defined():
    assert len(_INVARIANTS) >= 20


def test_generate_75_scenarios():
    scenarios, manifest = generate_chaos_scenarios(seed=42)
    assert len(scenarios) == 75
    assert manifest["scenarios_generated"] == 75


def test_same_seed_deterministic():
    s1, _ = generate_chaos_scenarios(seed=42, count=10)
    s2, _ = generate_chaos_scenarios(seed=42, count=10)
    ids1 = [sc["scenario_id"] for sc in s1]
    ids2 = [sc["scenario_id"] for sc in s2]
    assert ids1 == ids2


def test_different_seed_different():
    s1, _ = generate_chaos_scenarios(seed=42, count=10)
    s2, _ = generate_chaos_scenarios(seed=99, count=10)
    ids1 = [sc["scenario_id"] for sc in s1]
    ids2 = [sc["scenario_id"] for sc in s2]
    assert ids1 != ids2


def test_dimensions_represented():
    scenarios, _ = generate_chaos_scenarios(seed=42)
    outcomes = set()
    for sc in scenarios:
        for k in (
            "branch_outcome",
            "file_outcome",
            "pr_outcome",
            "check_observation",
            "alert_state",
            "rate_limit_mode",
            "approval",
            "ledger_integrity",
        ):
            outcomes.add(sc.get(k))
    assert len(outcomes) >= 30


def test_manifest_validates():
    _, manifest = generate_chaos_scenarios(seed=42)
    assert manifest["seed"] == 42


def test_replay_verifier_runs():
    generate_chaos_scenarios(seed=42, count=10)
    result = run_replay_verifier()
    assert result["invariants_checked"] == len(_INVARIANTS)


def test_repair_plan_generated():
    result = generate_repair_plan()
    assert len(result["corruption_cases"]) >= 4
    assert result["destructive_rewrite_allowed"] is False


def test_repair_never_destructive():
    result = generate_repair_plan()
    for case in result["corruption_cases"]:
        assert case["destructive_rewrite_forbidden"] is True


def test_full_chaos_lab_runs():
    report = run_chaos_lab(seed=42, count=10)
    assert report["scenarios_generated"] == 10
    assert report["invariants_checked"] >= 15


def test_no_forbidden_fields():
    run_chaos_lab(seed=42, count=5)
    for name in (
        "github_code_scanning_pr_mutation_chaos_manifest_v1.v1",
        "github_code_scanning_pr_mutation_replay_verifier_v1.v1",
        "github_code_scanning_pr_mutation_ledger_repair_plan_v1.v1",
        "github_code_scanning_pr_mutation_invariant_report_v1.v1",
        "github_code_scanning_pr_mutation_chaos_projection_v1.v1",
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
            '"code_snippet"',
        ):
            assert pat not in s, f"{pat} in {name}"


def test_evidence_report_no_forbidden():
    report = run_chaos_lab(seed=42, count=5)
    s = json.dumps(report, sort_keys=True)
    assert "access_token" not in s


def test_no_token_patterns():
    report = run_chaos_lab(seed=42, count=5)
    s = json.dumps(report, sort_keys=True)
    for p in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert p not in s


def test_artifacts_exist():
    run_chaos_lab(seed=42, count=5)
    for name in (
        "github_code_scanning_pr_mutation_chaos_manifest_v1.v1",
        "github_code_scanning_pr_mutation_replay_verifier_v1.v1",
        "github_code_scanning_pr_mutation_ledger_repair_plan_v1.v1",
        "github_code_scanning_pr_mutation_invariant_report_v1.v1",
        "github_code_scanning_pr_mutation_chaos_projection_v1.v1",
    ):
        assert (REPO_ROOT / "docs" / "json" / "governance" / f"{name}.json").exists()


# ═══════ 15 tests ═══════

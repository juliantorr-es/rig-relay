from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any

import jsonschema
import pytest

from rig_relay.core.paths import _vibe_home as vibe_home
from rig_relay.core.telemetry.artifacts import (
    TaskSessionLinkArtifact,
    ToolOutputArtifactWriter,
)
from rig_relay.integrations.deepseek_routing import (
    DeepSeekRoutingTask,
    build_deepseek_routing_decision,
    build_router_promotion_report,
    format_router_promotion_report_table,
    load_deepseek_lane_policy,
    load_router_promotion_policy,
    validate_deepseek_lane_policy,
    validate_router_promotion_policy,
    validate_router_promotion_report,
    write_deepseek_routing_decision,
)
from scripts.rig_deepseek_router_promotion_gate import main as promotion_main

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
POLICY_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "deepseek_router_promotion_policy.v1.json"
)
LANE_POLICY_PATH = (
    REPO_ROOT / "docs" / "json" / "integrations" / "deepseek_lane_policy.v1.json"
)
USAGE_SUMMARY_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "deepseek_opencode_usage_summary.v1.json"
)


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _policy() -> dict[str, Any]:
    return load_router_promotion_policy(POLICY_PATH)


def _lane_policy() -> dict[str, Any]:
    return load_deepseek_lane_policy(LANE_POLICY_PATH)


@pytest.fixture(autouse=True)
def _temp_session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        vibe_home.SESSIONS_ROOT, "_resolver", lambda: tmp_path / "sessions"
    )


def _lane_task_kwargs(lane_id: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "task_text": "short docs polish",
        "estimated_context_tokens": 5_000,
        "requested_output_kind": "prose",
        "touches_code": False,
        "touches_tests": False,
        "touches_schemas": False,
        "touches_provider_auth": False,
        "touches_release_claims": False,
        "touches_public_site": False,
        "live_network": False,
        "mutation_risk": "none",
        "concurrency_risk": "none",
        "requires_json_output": False,
        "requires_tool_calls": False,
        "requires_multi_file_reasoning": False,
        "requires_strict_tool_beta": False,
        "strict_tool_schema_compatible": False,
        "user_override_lane": None,
    }
    if lane_id == "cheap_inspect":
        return base
    if lane_id == "normal_repo_work":
        return base | {
            "task_text": "update schemas and tests for the promotion gate",
            "estimated_context_tokens": 50_000,
            "touches_tests": True,
            "touches_schemas": True,
        }
    if lane_id == "hard_convergence":
        return base | {
            "task_text": "reconcile release claim mismatches",
            "estimated_context_tokens": 200_000,
            "touches_release_claims": True,
            "mutation_risk": "high",
        }
    if lane_id == "json_artifact":
        return base | {
            "task_text": "emit canonical json artifact",
            "estimated_context_tokens": 3_000,
            "requested_output_kind": "json",
            "requires_json_output": True,
        }
    if lane_id == "strict_tool_beta":
        return base | {
            "task_text": "use strict tool calls for a schema-safe tool loop",
            "touches_code": True,
            "requires_tool_calls": True,
            "requires_strict_tool_beta": True,
            "strict_tool_schema_compatible": True,
        }
    raise AssertionError(f"unknown lane: {lane_id}")


def _write_route_receipt(
    root: Path,
    lane_id: str,
    index: int,
    *,
    generated_at: str = "2026-05-19T00:00:00Z",
    override_lane: str | None = None,
) -> Path:
    task_kwargs = _lane_task_kwargs(lane_id)
    if override_lane is not None:
        task_kwargs["user_override_lane"] = override_lane
    task = DeepSeekRoutingTask(**task_kwargs)
    decision = build_deepseek_routing_decision(
        task, policy=_lane_policy(), generated_at=generated_at
    )
    route_dir = root / ".build" / "rig-relay" / "deepseek-routing"
    route_dir.mkdir(parents=True, exist_ok=True)
    path = route_dir / f"{index:04d}_{lane_id}.json"
    write_deepseek_routing_decision(decision, path)
    return path


def _write_task_receipt(
    *,
    session_id: str,
    task_id: str,
    model: str = "deepseek-v4-pro",
    reasoning_effort: str = "high",
    status: str = "completed",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    warnings: list[str] | None = None,
) -> Path:
    writer = ToolOutputArtifactWriter(session_id)
    artifact = TaskSessionLinkArtifact(
        parent_session_id="parent-session",
        parent_turn_id="turn-1",
        parent_tool_call_id="call-1",
        task_id=task_id,
        child_session_id=session_id,
        provider="deepseek",
        model=model,
        thinking_requested=True,
        thinking_enabled=True,
        thinking_type="enabled",
        reasoning_effort=reasoning_effort,
        tool_access_policy="reasoning_only",
        result_compression_policy="final_only",
        timeout_seconds=30.0,
        input_prompt_sha256="sha256:" + "a" * 64,
        output_result_sha256="sha256:" + "b" * 64,
        child_artifact_manifest_sha256="sha256:" + "c" * 64,
        linkage_sha256="sha256:" + "d" * 64,
        status=status,
        started_at=(
            started_at.isoformat().replace("+00:00", "Z")
            if started_at is not None
            else None
        ),
        completed_at=(
            completed_at.isoformat().replace("+00:00", "Z")
            if completed_at is not None
            else None
        ),
        warnings=warnings or [],
    )
    result = writer.write_task_session_link_artifact(
        artifact=artifact, tool_call_id=task_id
    )
    return Path(result.path)


def _write_usage_summary_override(root: Path, cache_hit_ratio: float) -> Path:
    summary = json.loads(USAGE_SUMMARY_PATH.read_text(encoding="utf-8"))
    summary["cache_hit_ratio"] = cache_hit_ratio
    summary_path = root / "deepseek_opencode_usage_summary.v1.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary_path


def _build_low_risk_corpus(root: Path, *, cache_hit_ratio: float | None = None) -> None:
    for index in range(25):
        _write_route_receipt(root, "cheap_inspect", index)
    for index in range(25, 100):
        _write_route_receipt(root, "json_artifact", index)
    base = datetime(2026, 5, 1, tzinfo=UTC)
    for index in range(10):
        _write_task_receipt(
            session_id=f"session-{index % 3}",
            task_id=f"task-{index}",
            model="deepseek-v4-pro",
            reasoning_effort="high",
            started_at=base + timedelta(days=index),
            completed_at=base + timedelta(days=index, seconds=1),
        )
    if cache_hit_ratio is not None:
        _write_usage_summary_override(root, cache_hit_ratio)


def _write_override_corpus(root: Path) -> None:
    for index in range(30):
        _write_route_receipt(
            root, "normal_repo_work", index, override_lane="cheap_inspect"
        )
    for index in range(30, 100):
        _write_route_receipt(root, "json_artifact", index)
    base = datetime(2026, 5, 1, tzinfo=UTC)
    for index in range(10):
        _write_task_receipt(
            session_id=f"override-session-{index % 3}",
            task_id=f"override-task-{index}",
            model="deepseek-v4-pro",
            reasoning_effort="high",
            started_at=base + timedelta(days=index),
            completed_at=base + timedelta(days=index, seconds=1),
        )


@pytest.mark.contract
def test_promotion_policy_schema_validates() -> None:
    jsonschema.Draft7Validator.check_schema(
        _schema("rig.deepseek.router_promotion_policy.v1")
    )


@pytest.mark.contract
def test_promotion_report_schema_validates() -> None:
    jsonschema.Draft7Validator.check_schema(
        _schema("rig.deepseek.router_promotion_gate.v1")
    )


@pytest.mark.real_artifact
@pytest.mark.contract
def test_real_policy_artifact_validates() -> None:
    policy = _policy()
    jsonschema.validate(policy, _schema("rig.deepseek.router_promotion_policy.v1"))
    assert validate_router_promotion_policy(policy) == []


@pytest.mark.real_artifact
@pytest.mark.contract
def test_real_lane_policy_artifact_validates() -> None:
    policy = _lane_policy()
    jsonschema.validate(policy, _schema("rig.deepseek.lane_policy.v1"))
    assert validate_deepseek_lane_policy(policy) == []


@pytest.mark.contract
def test_insufficient_sample_produces_hold_report(tmp_path: Path) -> None:
    root = tmp_path
    _write_route_receipt(root, "cheap_inspect", 0)
    report = build_router_promotion_report(root, policy=_policy())
    assert report["recommendation"] == "hold"
    assert report["threshold_results"]["sample_thresholds_met"] is False
    assert validate_router_promotion_report(report) == []
    assert "recommendation" in format_router_promotion_report_table(report)


@pytest.mark.integration
def test_cli_emits_hold_report_from_insufficient_sample(tmp_path: Path) -> None:
    root = tmp_path
    _write_route_receipt(root, "cheap_inspect", 0)
    output_json = (
        root
        / ".build"
        / "rig-relay"
        / "deepseek-routing"
        / "router_promotion_report.v1.json"
    )

    exit_code = promotion_main([
        "--receipts-dir",
        str(root),
        "--policy",
        str(POLICY_PATH),
        "--output-json",
        str(output_json),
    ])

    assert exit_code == 0
    report = json.loads(output_json.read_text(encoding="utf-8"))
    jsonschema.validate(report, _schema("rig.deepseek.router_promotion_gate.v1"))
    assert report["recommendation"] == "hold"


@pytest.mark.integration
@pytest.mark.real_artifact
def test_cli_emits_auto_apply_low_risk_from_healthy_fixture(tmp_path: Path) -> None:
    root = tmp_path
    _build_low_risk_corpus(root)
    output_json = (
        root
        / ".build"
        / "rig-relay"
        / "deepseek-routing"
        / "router_promotion_report.v1.json"
    )

    exit_code = promotion_main([
        "--receipts-dir",
        str(root),
        "--policy",
        str(POLICY_PATH),
        "--output-json",
        str(output_json),
    ])

    assert exit_code == 0
    report = json.loads(output_json.read_text(encoding="utf-8"))
    jsonschema.validate(report, _schema("rig.deepseek.router_promotion_gate.v1"))
    assert report["recommendation"] == "auto_apply_low_risk"
    assert report["allowed_auto_apply_lanes"] == ["cheap_inspect"]
    assert "strict_tool_beta" not in report["allowed_auto_apply_lanes"]
    assert report["threshold_results"]["strict_tool_beta_auto_promote_blocked"] is True


@pytest.mark.contract
def test_raw_task_text_is_redacted_and_forces_rollback(tmp_path: Path) -> None:
    root = tmp_path
    _build_low_risk_corpus(root)
    _write_task_receipt(
        session_id="leak-session",
        task_id="leak-task",
        warnings=["task_text: leaked prompt contents"],
        started_at=datetime(2026, 5, 11, tzinfo=UTC),
        completed_at=datetime(2026, 5, 11, tzinfo=UTC),
    )
    report = build_router_promotion_report(root, policy=_policy())
    dumped = json.dumps(report, sort_keys=True)
    assert "leaked prompt contents" not in dumped
    assert report["metrics"]["raw_task_text_persisted_count"] >= 1
    assert report["rollback_required"] is True


@pytest.mark.adversarial
def test_secret_like_strings_are_not_persisted(tmp_path: Path) -> None:
    root = tmp_path
    _build_low_risk_corpus(root)
    _write_task_receipt(
        session_id="secret-session",
        task_id="secret-task",
        warnings=["sk-secret-test-value"],
        started_at=datetime(2026, 5, 11, tzinfo=UTC),
        completed_at=datetime(2026, 5, 11, tzinfo=UTC),
    )
    report = build_router_promotion_report(root, policy=_policy())
    dumped = json.dumps(report, sort_keys=True)
    assert "sk-secret-test-value" not in dumped
    assert report["metrics"]["raw_secret_violation_count"] >= 1
    assert report["rollback_required"] is True


@pytest.mark.substrate
def test_open_code_config_and_sqlite_are_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("sqlite3.connect should not be called")

    monkeypatch.setattr(sqlite3, "connect", _boom)
    root = tmp_path
    _build_low_risk_corpus(root)
    report = build_router_promotion_report(root, policy=_policy())
    assert report["recommendation"] == "auto_apply_low_risk"


@pytest.mark.substrate
def test_same_corpus_produces_deterministic_report_id(tmp_path: Path) -> None:
    root = tmp_path
    _build_low_risk_corpus(root)
    first = build_router_promotion_report(
        root, policy=_policy(), generated_at="2026-05-19T00:00:00Z"
    )
    second = build_router_promotion_report(
        root, policy=_policy(), generated_at="2026-05-19T00:00:01Z"
    )
    assert first["report_id"] == second["report_id"]
    assert first["recommendation"] == second["recommendation"]
    assert first["metrics"] == second["metrics"]


@pytest.mark.contract
def test_cache_ratio_below_threshold_blocks_promotion(tmp_path: Path) -> None:
    root = tmp_path
    _build_low_risk_corpus(root, cache_hit_ratio=0.88)
    report = build_router_promotion_report(root, policy=_policy())
    assert report["recommendation"] == "hold"
    assert report["threshold_results"]["cache_threshold_met"] is False
    assert report["rollback_required"] is False


@pytest.mark.contract
def test_high_override_rate_blocks_promotion(tmp_path: Path) -> None:
    root = tmp_path
    _write_override_corpus(root)
    report = build_router_promotion_report(root, policy=_policy())
    assert report["metrics"]["override_rate"] is not None
    assert report["metrics"]["override_rate"] >= 0.25
    assert report["rollback_required"] is True
    assert report["recommendation"] == "rollback"


@pytest.mark.contract
def test_strict_tool_beta_never_auto_promotes(tmp_path: Path) -> None:
    root = tmp_path
    _build_low_risk_corpus(root)
    report = build_router_promotion_report(root, policy=_policy())
    assert report["threshold_results"]["strict_tool_beta_auto_promote_blocked"] is True
    assert "strict_tool_beta" not in report["allowed_auto_apply_lanes"]

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import jsonschema
import pytest

from rig_relay.integrations.deepseek_routing import (
    DeepSeekRoutingTask,
    build_deepseek_routing_decision,
    format_deepseek_routing_decision_table,
    load_deepseek_lane_policy,
    validate_deepseek_lane_policy,
    validate_deepseek_routing_decision,
    write_deepseek_routing_decision,
)
from scripts.rig_deepseek_route_task import main as route_main

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
POLICY_PATH = (
    REPO_ROOT / "docs" / "json" / "integrations" / "deepseek_lane_policy.v1.json"
)


def _schema(schema_id: str) -> dict[str, Any]:
    return json.loads(
        (SCHEMAS_DIR / f"{schema_id}.schema.json").read_text(encoding="utf-8")
    )


def _policy() -> dict[str, Any]:
    return load_deepseek_lane_policy(POLICY_PATH)


def _task(**overrides: Any) -> DeepSeekRoutingTask:
    payload: dict[str, Any] = {
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
    payload.update(overrides)
    return DeepSeekRoutingTask(**payload)


def _decision(
    task: DeepSeekRoutingTask, *, generated_at: str = "2026-05-19T12:00:00Z"
) -> dict[str, Any]:
    return build_deepseek_routing_decision(
        task, policy=_policy(), generated_at=generated_at
    )


@pytest.mark.contract
def test_lane_policy_schema_validates() -> None:
    jsonschema.Draft7Validator.check_schema(_schema("rig.deepseek.lane_policy.v1"))


@pytest.mark.contract
def test_routing_decision_schema_validates() -> None:
    jsonschema.Draft7Validator.check_schema(_schema("rig.deepseek.routing_decision.v1"))


@pytest.mark.real_artifact
@pytest.mark.contract
def test_policy_artifact_validates_against_schema() -> None:
    policy = _policy()
    jsonschema.validate(policy, _schema("rig.deepseek.lane_policy.v1"))


@pytest.mark.real_artifact
def test_policy_loader_reads_real_artifact() -> None:
    policy = _policy()
    assert policy["schema_version"] == "rig.deepseek.lane_policy.v1"
    assert policy["default_lane"] == "normal_repo_work"
    assert len(policy["lanes"]) == 5


@pytest.mark.contract
def test_short_low_risk_task_selects_cheap_inspect() -> None:
    decision = _decision(_task())
    assert decision["selected_lane"] == "cheap_inspect"
    assert decision["selected_model"] == "deepseek-v4-flash"
    assert decision["thinking_mode"] == "disabled"
    assert decision["reasoning_effort"] == "none"


@pytest.mark.contract
def test_schemas_and_tests_with_moderate_context_select_normal_repo_work() -> None:
    decision = _decision(
        _task(
            task_text="update schemas and tests for the policy router",
            estimated_context_tokens=50_000,
            touches_tests=True,
            touches_schemas=True,
        )
    )
    assert decision["selected_lane"] == "normal_repo_work"
    assert decision["selected_model"] == "deepseek-v4-pro"
    assert decision["thinking_mode"] == "enabled"
    assert decision["reasoning_effort"] == "high"


@pytest.mark.contract
@pytest.mark.parametrize(
    ("task_kwargs", "expected_reason"),
    [
        (
            {
                "task_text": "reconcile release claim mismatches",
                "touches_release_claims": True,
            },
            "release_claim_or_audit",
        ),
        (
            {"task_text": "fake-green audit pass with evidence gaps"},
            "release_claim_or_audit",
        ),
        (
            {
                "task_text": "rotate provider auth flow and review tokens",
                "touches_provider_auth": True,
            },
            "provider_auth_or_live_network",
        ),
        (
            {"task_text": "exercise live network request path", "live_network": True},
            "provider_auth_or_live_network",
        ),
        (
            {
                "task_text": "multi-file refactor with deep context",
                "estimated_context_tokens": 130_000,
                "requires_multi_file_reasoning": True,
            },
            "multi_file_or_large_context",
        ),
    ],
)
def test_high_risk_tasks_select_hard_convergence(
    task_kwargs: dict[str, Any], expected_reason: str
) -> None:
    decision = _decision(_task(mutation_risk="high", **task_kwargs))
    assert decision["selected_lane"] == "hard_convergence"
    assert decision["selected_model"] == "deepseek-v4-pro"
    assert expected_reason in decision["reason_codes"]


@pytest.mark.contract
def test_read_only_dry_run_live_network_task_can_escape_hard_convergence() -> None:
    decision = _decision(
        _task(
            task_text="read-only dry-run against live network service",
            live_network=True,
            estimated_context_tokens=5_000,
        )
    )
    assert decision["selected_lane"] in {"cheap_inspect", "normal_repo_work"}
    assert "provider_auth_or_live_network" not in decision["reason_codes"]


@pytest.mark.contract
def test_json_output_task_selects_json_artifact_and_enables_json_mode() -> None:
    decision = _decision(
        _task(
            task_text="emit canonical json artifact",
            requested_output_kind="json",
            estimated_context_tokens=3_000,
            requires_json_output=True,
        )
    )
    assert decision["selected_lane"] == "json_artifact"
    assert decision["selected_model"] == "deepseek-v4-flash"
    assert decision["json_mode_enabled"] is True
    assert decision["beta_endpoint_required"] is False


@pytest.mark.contract
def test_valid_override_is_honored_with_warning() -> None:
    decision = _decision(
        _task(
            task_text="release claim reconciliation under override",
            touches_release_claims=True,
            estimated_context_tokens=200_000,
            user_override_lane="cheap_inspect",
        )
    )
    assert decision["selected_lane"] == "cheap_inspect"
    assert decision["override_used"] is True
    assert any("override" in warning.lower() for warning in decision["warnings"])


@pytest.mark.adversarial
def test_dynamic_ordering_requests_emit_stable_prefix_warning() -> None:
    decision = _decision(
        _task(
            task_text="randomize provider and tool ordering for this run",
            estimated_context_tokens=4_000,
        )
    )
    assert "stable prefix" in decision["stable_prefix_warning"].lower()
    assert any("stable prefix" in warning.lower() for warning in decision["warnings"])


@pytest.mark.contract
def test_strict_tool_beta_requires_explicit_request_and_compatibility() -> None:
    decision = _decision(
        _task(
            task_text="use strict tool calls for a schema-safe tool loop",
            touches_code=True,
            requires_tool_calls=True,
            requires_strict_tool_beta=True,
            strict_tool_schema_compatible=True,
        )
    )
    assert decision["selected_lane"] == "strict_tool_beta"
    assert decision["selected_model"] == "deepseek-v4-pro"
    assert decision["strict_tool_beta_enabled"] is True
    assert decision["beta_endpoint_required"] is True


@pytest.mark.adversarial
def test_secret_like_task_text_is_not_persisted(tmp_path: Path) -> None:
    task_text = "use api key sk-secret-test-value and ghp_fake_token now"
    decision = _decision(
        _task(task_text=task_text, user_override_lane="normal_repo_work")
    )
    dumped = json.dumps(decision, sort_keys=True)
    assert task_text not in dumped
    assert "sk-secret-test-value" not in dumped
    assert "ghp_fake_token" not in dumped
    assert len(decision["task_text_hash"]) == 64


@pytest.mark.substrate
def test_decision_is_deterministic() -> None:
    task = _task(task_text="short docs polish", estimated_context_tokens=5_000)
    first = _decision(task, generated_at="2026-05-19T12:00:00Z")
    second = _decision(task, generated_at="2026-05-19T12:00:00Z")
    assert first["decision_id"] == second["decision_id"]
    assert first["selected_lane"] == second["selected_lane"]
    assert first["reason_codes"] == second["reason_codes"]
    assert first["selected_model"] == second["selected_model"]


@pytest.mark.real_artifact
@pytest.mark.contract
def test_written_decision_validates_against_schema(tmp_path: Path) -> None:
    decision = _decision(_task())
    output_path = tmp_path / "decision.json"
    write_deepseek_routing_decision(decision, output_path)
    jsonschema.validate(
        json.loads(output_path.read_text(encoding="utf-8")),
        _schema("rig.deepseek.routing_decision.v1"),
    )


@pytest.mark.integration
def test_cli_json_emits_schema_valid_decision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = tmp_path / "decision.json"
    exit_code = route_main([
        "--task",
        "short docs polish",
        "--context-tokens",
        "5000",
        "--output-kind",
        "prose",
        "--json",
        "--write-artifact",
        str(output_path),
        "--generated-at",
        "2026-05-19T12:00:00Z",
    ])
    captured = capsys.readouterr()
    assert exit_code == 0
    decision = json.loads(captured.out)
    jsonschema.validate(decision, _schema("rig.deepseek.routing_decision.v1"))
    assert output_path.is_file()
    assert decision["selected_lane"] == "cheap_inspect"


@pytest.mark.integration
@pytest.mark.adversarial
def test_cli_table_output_redacts_task_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = tmp_path / "decision.json"
    task_text = "use api key sk-secret-test-value and /Users/user/Private/Repo now"
    exit_code = route_main([
        "--task",
        task_text,
        "--context-tokens",
        "4000",
        "--write-artifact",
        str(output_path),
        "--generated-at",
        "2026-05-19T12:00:00Z",
    ])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert task_text not in captured.out
    assert "sk-secret-test-value" not in captured.out
    assert "/Users/user/Private/Repo" not in captured.out


@pytest.mark.substrate
def test_routing_does_not_touch_opencode_db_or_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    config_dir = home / ".config" / "opencode"
    db_dir = home / ".local" / "share" / "opencode"
    config_dir.mkdir(parents=True)
    db_dir.mkdir(parents=True)
    config_path = config_dir / "opencode.json"
    db_path = db_dir / "opencode.db"
    config_path.write_text("stay-put-config", encoding="utf-8")
    db_path.write_text("stay-put-db", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("sqlite3.connect called")
        ),
    )

    decision = _decision(
        _task(task_text="short docs polish", estimated_context_tokens=5_000)
    )

    assert decision["selected_lane"] == "cheap_inspect"
    assert config_path.read_text(encoding="utf-8") == "stay-put-config"
    assert db_path.read_text(encoding="utf-8") == "stay-put-db"


@pytest.mark.contract
def test_validate_helpers_accept_real_artifacts() -> None:
    policy = _policy()
    errors = validate_deepseek_lane_policy(policy)
    assert not errors
    decision = _decision(_task())
    decision_errors = validate_deepseek_routing_decision(decision)
    assert not decision_errors
    rendered = format_deepseek_routing_decision_table(decision)
    assert "cheap_inspect" in rendered

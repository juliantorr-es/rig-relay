from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [
    pytest.mark.contract,
    pytest.mark.integration,
    pytest.mark.real_artifact,
    pytest.mark.adversarial,
    pytest.mark.substrate,
]

from rig_relay.otel_dataset._proposal import build_tool_hardening_proposal
from scripts.rig_otel_tool_hardening_proposal import main as proposal_main

REPO_ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str) -> dict[str, object]:
    return json.loads(
        (REPO_ROOT / "docs" / "schemas" / f"{name}.schema.json").read_text(
            encoding="utf-8"
        )
    )


def _write_trend_artifacts(
    trend_dir: Path, *, trend_report: dict[str, object], deltas: dict[str, object]
) -> None:
    trend_dir.mkdir(parents=True, exist_ok=True)
    (trend_dir / "otel_trend_report.v1.json").write_text(
        json.dumps(trend_report, indent=2, sort_keys=True), encoding="utf-8"
    )
    (trend_dir / "otel_hardening_deltas.v1.json").write_text(
        json.dumps(deltas, indent=2, sort_keys=True), encoding="utf-8"
    )


def _trend_report(
    *,
    trend_run_id: str = "trend-1",
    deltas_path: str = "trend-1/otel_hardening_deltas.v1.json",
    trend_summary: dict[str, object] | None = None,
    input_manifest_hashes: list[dict[str, str]] | None = None,
    input_shortlist_hashes: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "rig.otel.trend_report.v1",
        "trend_run_id": trend_run_id,
        "generated_at": "2026-05-19T00:00:00+00:00",
        "input_aggregate_run_ids": ["agg-1", "agg-2"],
        "input_aggregate_count": 2,
        "input_manifest_hashes": input_manifest_hashes
        or [
            {
                "aggregate_run_id": "agg-1",
                "sha256": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
            },
            {
                "aggregate_run_id": "agg-2",
                "sha256": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
            },
        ],
        "input_shortlist_hashes": input_shortlist_hashes
        or [
            {
                "aggregate_run_id": "agg-1",
                "sha256": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
            },
            {
                "aggregate_run_id": "agg-2",
                "sha256": "sha256:4444444444444444444444444444444444444444444444444444444444444444",
            },
        ],
        "comparison_window": {
            "baseline_run_id": "agg-1",
            "latest_run_id": "agg-2",
            "run_order": ["agg-1", "agg-2"],
            "method": "chronological",
        },
        "trend_verdict": "pass",
        "trend_summary": trend_summary
        or {
            "persistent_pain_count": 1,
            "new_regression_count": 0,
            "improved_category_count": 0,
            "one_off_noise_count": 0,
            "insufficient_sample_count": 0,
            "highest_priority_categories": [],
            "redaction_pressure_trend": "stable",
            "trace_context_quality_trend": "stable",
            "latency_trend": "worsening",
            "error_rate_trend": "stable",
        },
        "deltas_path": deltas_path,
        "warnings": [],
        "errors": [],
        "local_only": True,
        "content_light": True,
        "coordination_ledger_mutated": False,
        "release_gate_mutated": False,
    }


def _delta(
    *,
    delta_id: str,
    affected_tool_category: str = "shell",
    signal_kind: str = "latency",
    trend_class: str = "persistent_pain",
    severity: str = "high",
    confidence: str = "high",
    affected_event_count: int = 3,
    redaction_drop_count: int = 0,
    missing_trace_id_count: int = 0,
    missing_parent_span_id_count: int = 0,
    retry_count: int = 0,
    timeout_count: int = 0,
    cancellation_count: int = 0,
) -> dict[str, object]:
    base_metrics = {
        "candidate_count": 1,
        "affected_event_count": affected_event_count,
        "p50_duration_ms": 1000.0,
        "p95_duration_ms": 2000.0,
        "p99_duration_ms": 3000.0,
        "error_count": 0,
        "retry_count": retry_count,
        "timeout_count": timeout_count,
        "cancellation_count": cancellation_count,
        "missing_trace_id_count": missing_trace_id_count,
        "missing_parent_span_id_count": missing_parent_span_id_count,
        "redaction_drop_count": redaction_drop_count,
        "unknown_tool_category_count": 0,
    }
    return {
        "delta_id": delta_id,
        "affected_tool_category": affected_tool_category,
        "signal_kind": signal_kind,
        "trend_class": trend_class,
        "severity": severity,
        "first_seen_run_id": "agg-1",
        "latest_seen_run_id": "agg-2",
        "evidence_run_ids": ["agg-1", "agg-2"],
        "baseline_metrics": base_metrics,
        "latest_metrics": base_metrics,
        "delta_metrics": {key: 0 for key in base_metrics},
        "confidence": confidence,
        "recommended_hardening_action": "Review the tool path",
        "content_light_evidence_hashes": [
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        ],
    }


def _deltas(*items: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "rig.otel.hardening_delta.v1",
        "trend_run_id": "trend-1",
        "generated_at": "2026-05-19T00:00:00+00:00",
        "deltas": list(items),
        "local_only": True,
        "content_light": True,
    }


def test_proposal_schema_validates(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
        ),
    )

    result = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-1",
        output_root=tmp_path / "tool-hardening",
    )
    proposal = json.loads(
        Path(result["proposal_path_absolute"]).read_text(encoding="utf-8")
    )

    jsonschema.validate(proposal, _schema("rig.tool_hardening.proposal.v1"))
    assert proposal["local_only"] is True
    assert proposal["content_light"] is True
    assert proposal["coordination_ledger_mutated"] is False
    assert proposal["release_gate_mutated"] is False
    assert proposal["runtime_mutated"] is False
    assert proposal["redaction_status"] == "content_light"


def test_proposal_item_schema_validates(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
        ),
    )

    result = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-2",
        output_root=tmp_path / "tool-hardening",
    )
    items_path = Path(result["items_path_absolute"])
    rows = [
        json.loads(line)
        for line in items_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert rows
    for row in rows:
        jsonschema.validate(row, _schema("rig.tool_hardening.proposal_item.v1"))
        assert row["local_only"] is True
        assert row["content_light"] is True
        assert row["redaction_status"] == "content_light"


def test_builder_reads_real_trend_artifacts_from_temp_files(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
        ),
    )

    result = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-3",
        output_root=tmp_path / "tool-hardening",
    )

    assert result["source_trend_run_id"] == "trend-1"
    assert result["proposal_verdict"] == "pass"
    assert Path(result["proposal_path_absolute"]).is_file()
    assert Path(result["items_path_absolute"]).is_file()


def test_persistent_pain_delta_creates_action_item(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                trend_class="persistent_pain",
                severity="critical",
                confidence="high",
            )
        ),
    )

    result = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-4",
        output_root=tmp_path / "tool-hardening",
    )

    assert result["item_count"] == 1
    item = json.loads(
        Path(result["items_path_absolute"]).read_text(encoding="utf-8").splitlines()[0]
    )
    assert item["trend_class"] == "persistent_pain"
    assert item["recommended_lane"] == "tool_runtime_hardening"


def test_new_regression_delta_creates_action_item(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                trend_class="new_regression",
                severity="high",
            )
        ),
    )

    result = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-5",
        output_root=tmp_path / "tool-hardening",
    )

    assert result["proposal_verdict"] == "pass"
    assert result["item_count"] == 1


def test_insufficient_sample_only_deltas_produce_hold(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(
            trend_summary={
                "persistent_pain_count": 0,
                "new_regression_count": 0,
                "improved_category_count": 0,
                "one_off_noise_count": 0,
                "insufficient_sample_count": 1,
                "highest_priority_categories": [],
                "redaction_pressure_trend": "insufficient_sample",
                "trace_context_quality_trend": "insufficient_sample",
                "latency_trend": "insufficient_sample",
                "error_rate_trend": "insufficient_sample",
            }
        ),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                trend_class="insufficient_sample",
                severity="low",
                confidence="low",
            )
        ),
    )

    result = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-6",
        output_root=tmp_path / "tool-hardening",
    )

    assert result["proposal_verdict"] == "hold"
    assert result["item_count"] == 0


def test_one_off_noise_only_deltas_produce_hold(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                trend_class="one_off_noise",
                severity="low",
                confidence="low",
            )
        ),
    )

    result = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-7",
        output_root=tmp_path / "tool-hardening",
    )

    assert result["proposal_verdict"] == "hold"
    assert result["item_count"] == 0


def test_improved_only_deltas_do_not_create_action_items(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(
            trend_summary={
                "persistent_pain_count": 0,
                "new_regression_count": 0,
                "improved_category_count": 1,
                "one_off_noise_count": 0,
                "insufficient_sample_count": 0,
                "highest_priority_categories": [],
                "redaction_pressure_trend": "improving",
                "trace_context_quality_trend": "improving",
                "latency_trend": "improving",
                "error_rate_trend": "improving",
            }
        ),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                trend_class="improved",
                severity="low",
                confidence="high",
            )
        ),
    )

    result = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-8",
        output_root=tmp_path / "tool-hardening",
    )

    assert result["proposal_verdict"] == "hold"
    assert result["item_count"] == 0


@pytest.mark.parametrize(
    ("signal_kind", "expected_lane"),
    [
        ("missing_trace_context", "trace_context_hardening"),
        ("redaction_pressure", "redaction_policy_hardening"),
        ("retry_loop", "retry_policy_hardening"),
        ("timeout", "timeout_policy_hardening"),
        ("cancellation", "cancellation_policy_hardening"),
        ("unknown_tool_category", "unknown_tool_classification"),
        ("malformed_input", "schema_contract_hardening"),
    ],
)
def test_signal_kind_maps_to_expected_lane(
    tmp_path: Path, signal_kind: str, expected_lane: str
) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                signal_kind=signal_kind,
                affected_tool_category="unknown"
                if signal_kind in {"missing_trace_context", "unknown_tool_category"}
                else "shell",
                retry_count=3 if signal_kind == "retry_loop" else 0,
                timeout_count=2 if signal_kind == "timeout" else 0,
                cancellation_count=2 if signal_kind == "cancellation" else 0,
                missing_trace_id_count=2
                if signal_kind == "missing_trace_context"
                else 0,
                redaction_drop_count=2 if signal_kind == "redaction_pressure" else 0,
            )
        ),
    )

    result = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-9",
        output_root=tmp_path / "tool-hardening",
    )

    if result["item_count"] == 0:
        pytest.fail("Expected an actionable item")
    item = json.loads(
        Path(result["items_path_absolute"]).read_text(encoding="utf-8").splitlines()[0]
    )
    if signal_kind == "malformed_input":
        assert item["recommended_lane"] in {
            "schema_contract_hardening",
            "tool_invocation_boundary",
        }
    else:
        assert item["recommended_lane"] == expected_lane


def test_priority_scoring_is_deterministic(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                signal_kind="redaction_pressure",
                severity="critical",
                confidence="high",
                redaction_drop_count=5,
            ),
            _delta(
                delta_id="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                signal_kind="retry_loop",
                severity="high",
                confidence="medium",
                retry_count=4,
            ),
        ),
    )

    result_a = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-10",
        output_root=tmp_path / "tool-hardening-a",
    )
    result_b = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-10",
        output_root=tmp_path / "tool-hardening-b",
    )

    assert result_a["ranked_item_ids"] == result_b["ranked_item_ids"]
    assert result_a["proposal_verdict"] == result_b["proposal_verdict"]


def test_malformed_trend_artifact_is_rejected(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    trend_dir.mkdir(parents=True, exist_ok=True)
    (trend_dir / "otel_trend_report.v1.json").write_text("{", encoding="utf-8")
    (trend_dir / "otel_hardening_deltas.v1.json").write_text(
        json.dumps(_deltas()), encoding="utf-8"
    )

    with pytest.raises(ValueError):
        build_tool_hardening_proposal(
            trend_dir=trend_dir,
            proposal_run_id="proposal-11",
            output_root=tmp_path / "tool-hardening",
        )


def test_output_artifacts_validate_against_schemas(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
        ),
    )

    result = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-12",
        output_root=tmp_path / "tool-hardening",
    )

    proposal = json.loads(
        Path(result["proposal_path_absolute"]).read_text(encoding="utf-8")
    )
    items = [
        json.loads(line)
        for line in Path(result["items_path_absolute"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    jsonschema.validate(proposal, _schema("rig.tool_hardening.proposal.v1"))
    for item in items:
        jsonschema.validate(item, _schema("rig.tool_hardening.proposal_item.v1"))


def test_cli_writes_proposal_and_item_jsonl(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
        ),
    )

    exit_code = proposal_main([
        "--trend-dir",
        str(trend_dir),
        "--run-id",
        "proposal-13",
        "--output-root",
        str(tmp_path / "tool-hardening"),
    ])

    assert exit_code == 0
    assert (
        tmp_path / "tool-hardening" / "proposal-13" / "tool_hardening_proposal.v1.json"
    ).is_file()
    assert (
        tmp_path / "tool-hardening" / "proposal-13" / "tool_hardening_items.v1.jsonl"
    ).is_file()


def test_cli_exits_2_when_no_actionable_items_exist(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(
            trend_summary={
                "persistent_pain_count": 0,
                "new_regression_count": 0,
                "improved_category_count": 0,
                "one_off_noise_count": 1,
                "insufficient_sample_count": 0,
                "highest_priority_categories": [],
                "redaction_pressure_trend": "stable",
                "trace_context_quality_trend": "stable",
                "latency_trend": "stable",
                "error_rate_trend": "stable",
            }
        ),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                trend_class="one_off_noise",
                severity="low",
                confidence="low",
            )
        ),
    )

    exit_code = proposal_main([
        "--trend-dir",
        str(trend_dir),
        "--run-id",
        "proposal-14",
        "--output-root",
        str(tmp_path / "tool-hardening"),
    ])

    assert exit_code == 2


def test_no_raw_absolute_paths_or_secret_like_values_in_outputs(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
        ),
    )

    result = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-15",
        output_root=tmp_path / "tool-hardening",
    )
    proposal = Path(result["proposal_path_absolute"]).read_text(encoding="utf-8")
    items = Path(result["items_path_absolute"]).read_text(encoding="utf-8")
    raw = proposal + items

    assert str(tmp_path) not in raw
    assert "/Users/user" not in raw
    assert "sk-test" not in raw
    assert "private thing" not in raw


def test_proposal_does_not_write_to_coordination_ledger(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
        ),
    )

    build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-16",
        output_root=tmp_path / "tool-hardening",
    )

    assert not (tmp_path / "tool-hardening" / "proposal-16" / "coordination").exists()


def test_proposal_does_not_mutate_release_gate(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
        ),
    )

    build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-17",
        output_root=tmp_path / "tool-hardening",
    )

    assert not (tmp_path / "tool-hardening" / "proposal-17" / "release_gate").exists()


def test_proposal_does_not_mutate_runtime_or_tool_files(tmp_path: Path) -> None:
    trend_dir = tmp_path / "trends" / "trend-1"
    _write_trend_artifacts(
        trend_dir,
        trend_report=_trend_report(),
        deltas=_deltas(
            _delta(
                delta_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
        ),
    )

    result = build_tool_hardening_proposal(
        trend_dir=trend_dir,
        proposal_run_id="proposal-18",
        output_root=tmp_path / "tool-hardening",
    )
    raw = Path(result["proposal_path_absolute"]).read_text(encoding="utf-8") + Path(
        result["items_path_absolute"]
    ).read_text(encoding="utf-8")

    assert "rig_relay/runtime" not in raw
    assert "rig_relay/desktop" not in raw

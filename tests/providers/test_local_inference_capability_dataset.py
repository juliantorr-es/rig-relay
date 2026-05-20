"""Capability evidence dataset tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from rig_relay.providers.local_inference.dataset_export import build_export_policy
from rig_relay.providers.local_inference.ev_aggregation import aggregate_rows
from rig_relay.providers.local_inference.evidence_builder import build_evidence_row
from rig_relay.providers.local_inference.recommendation_policy import recommend

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"


class TestEvidenceRow:
    def test_local_first_when_all_evidence(self) -> None:
        row = build_evidence_row(
            machine_class="apple_silicon_medium",
            task_profile="chat_light",
            contract_passed=True,
            benchmark_available=True,
            shadow_passed=True,
            local_latency_ms=200,
            local_ttft_ms=50,
            local_tokens_per_sec=30.0,
        )
        assert row.recommended_route == "local_first"
        assert row.confidence == "high"

    def test_cloud_escalation_on_failure(self) -> None:
        row = build_evidence_row(
            task_profile="chat_light",
            contract_passed=False,
            benchmark_available=True,
            shadow_passed=False,
        )
        assert row.recommended_route == "cloud_escalation"

    def test_shadow_first_with_partial(self) -> None:
        row = build_evidence_row(
            task_profile="chat_light",
            contract_passed=False,
            shadow_passed=True,
            benchmark_available=False,
        )
        assert row.recommended_route == "shadow_first"

    def test_human_review_on_mutation_risk(self) -> None:
        row = build_evidence_row(
            task_profile="tool_planning",
            mutation_risk="critical",
            contract_passed=False,
            benchmark_available=False,
            shadow_passed=False,
        )
        assert row.recommended_route == "human_review_required"

    def test_insufficient_evidence_default(self) -> None:
        row = build_evidence_row(task_profile="chat_light")
        assert row.recommended_route == "insufficient_evidence"

    def test_content_light(self) -> None:
        row = build_evidence_row(task_profile="chat_light")
        data = json.loads(row.model_dump_json())
        assert data["raw_prompt_persisted"] is False
        assert data["raw_completion_persisted"] is False

    def test_no_latency_only_local_first(self) -> None:
        row = build_evidence_row(
            task_profile="chat_light",
            local_latency_ms=1,
            contract_passed=False,
            benchmark_available=False,
            shadow_passed=False,
        )
        assert row.recommended_route != "local_first"


class TestAggregation:
    def test_aggregate_computes_rates(self) -> None:
        rows = [
            build_evidence_row(
                task_profile="chat_light",
                contract_passed=True,
                local_latency_ms=100,
                local_tokens_per_sec=25.0,
            ).model_dump()
            for _ in range(10)
        ]
        report = aggregate_rows(rows=rows)
        assert report.total_rows == 10
        assert report.contract_pass_rate == 1.0
        assert report.local_latency_p50 == 100.0

    def test_empty_rows(self) -> None:
        report = aggregate_rows(rows=[])
        assert report.total_rows == 0


class TestRecommendation:
    def test_recommend_routes_correctly(self) -> None:
        row = build_evidence_row(
            task_profile="chat_light",
            contract_passed=True,
            benchmark_available=True,
            shadow_passed=True,
        )
        rec = recommend(row=row)
        assert rec.recommended_route == "local_first"
        assert rec.confidence == "high"


class TestExportPolicy:
    def test_default_aggregate_only(self) -> None:
        pol = build_export_policy()
        assert pol.mode == "aggregate_only"
        assert pol.raw_prompt_exported is False

    def test_non_exportable_includes_raw(self) -> None:
        pol = build_export_policy()
        assert "raw_prompt" in pol.non_exportable_fields
        assert "raw_completion" in pol.non_exportable_fields


class TestSubstrate:
    def test_no_models_no_servers(self) -> None:
        row = build_evidence_row(task_profile="chat_light")
        data = json.loads(row.model_dump_json())
        assert data["raw_prompt_persisted"] is False
        assert data["raw_completion_persisted"] is False
        assert "download" not in json.dumps(data).lower()


class TestCLI:
    SCRIPT = str(
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "rig_local_inference_capability_dataset.py"
    )

    def _run(self, *a: str, **kw: object) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, self.SCRIPT] + list(a)
        for k, v in kw.items():
            if v is True:
                cmd.append(f"--{k.replace('_', '-')}")
            elif v is not False and v is not None:
                cmd.append(f"--{k.replace('_', '-')}")
                cmd.append(str(v))
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_build_rows(self, tmp_path: Path) -> None:
        r = self._run("build-rows", output_dir=str(tmp_path), json=True, count=3)
        data = json.loads(r.stdout)
        assert len(data["rows"]) == 3

    def test_aggregate(self, tmp_path: Path) -> None:
        r = self._run("aggregate", output_dir=str(tmp_path), json=True)
        data = json.loads(r.stdout)
        assert data["total_rows"] >= 1

    def test_recommend(self, tmp_path: Path) -> None:
        r = self._run("recommend", output_dir=str(tmp_path), json=True)
        data = json.loads(r.stdout)
        assert data["recommended_route"]

    def test_export_policy(self, tmp_path: Path) -> None:
        r = self._run("export-policy", output_dir=str(tmp_path), json=True)
        data = json.loads(r.stdout)
        assert data["mode"] == "aggregate_only"

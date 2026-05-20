"""Selection policy, task profiles, capability matching, benchmark summarizer,
fallback, and CLI tests for local inference.

Test classifications: contract, unit, integration, real-artifact, adversarial, substrate.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from rig_relay.providers.local_inference import (
    BenchmarkEvidenceSummary,
    CapabilityProbeCapabilities,
    CapabilityProbeResult,
    CapabilityStatus,
    ExplanationCode,
    LocalRuntimeKind,
    PolicyResultKind,
    ProbeStatus,
    build_benchmark_sample,
    decide_fallback,
    evaluate_selection_policy,
    get_task_profile,
    list_task_profiles,
    match_capabilities,
    summarize_benchmark_jsonl,
    validate_benchmark_content_light,
    write_sample_to_jsonl,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"


def _make_dry_run_probe(url: str = "http://localhost:8080") -> CapabilityProbeResult:
    return CapabilityProbeResult(
        probe_id="p_dry_run",
        runtime_url=url,
        runtime_engine=LocalRuntimeKind.LLAMA_CPP,
        probed_at="2026-06-01T00:00:00Z",
        probe_duration_ms=50,
        reachable=True,
        capabilities=CapabilityProbeCapabilities(
            chat_completions=CapabilityStatus.SUPPORTED,
            streaming=CapabilityStatus.SUPPORTED,
            tool_calling=CapabilityStatus.SUPPORTED,
            structured_json_output=CapabilityStatus.SUPPORTED,
            models_list=CapabilityStatus.SUPPORTED,
            health_endpoint=CapabilityStatus.SUPPORTED,
        ),
    )


def _make_minimal_probe() -> CapabilityProbeResult:
    return CapabilityProbeResult(
        probe_id="p_minimal",
        runtime_url="http://localhost:8080",
        runtime_engine=LocalRuntimeKind.VLLM,
        probed_at="2026-06-01T00:00:00Z",
        probe_duration_ms=100,
        reachable=True,
    )


class TestSelectionPolicyContract:
    def test_schema_exists(self) -> None:
        schema_path = SCHEMA_DIR / "rig.local_inference.selection_policy.v1.schema.json"
        assert schema_path.exists()

    def test_schema_validates(self) -> None:
        import jsonschema

        schema_path = SCHEMA_DIR / "rig.local_inference.selection_policy.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        result = evaluate_selection_policy(endpoint_configured=False)
        jsonschema.validate(result, schema)

    def test_result_has_required_top_level_fields(self) -> None:
        result = evaluate_selection_policy(endpoint_configured=False)
        for field in ["schema_version", "selection_id", "result_kind", "confidence"]:
            assert field in result


class TestSelectionPolicyUnit:
    def test_not_configured(self) -> None:
        result = evaluate_selection_policy(endpoint_configured=False)
        assert result["result_kind"] == PolicyResultKind.NOT_CONFIGURED.value
        assert (
            ExplanationCode.ENDPOINT_UNCONFIGURED.value in result["explanation_codes"]
        )
        assert not result["manual_selection_allowed"]

    def test_configured_but_unprobed(self) -> None:
        result = evaluate_selection_policy(endpoint_configured=True)
        assert result["result_kind"] == PolicyResultKind.CONFIGURED_BUT_UNPROBED.value
        assert ExplanationCode.PROBE_FAILED.value in result["explanation_codes"]

    def test_probe_failed_blocks(self) -> None:
        probe = _make_minimal_probe()
        probe.reachable = False
        result = evaluate_selection_policy(
            endpoint_configured=True, endpoint_sha256="abc", probe_result=probe
        )
        assert result["result_kind"] == PolicyResultKind.BLOCKED_BY_FAILED_PROBE.value

    def test_probe_stale_blocks(self) -> None:
        probe = _make_dry_run_probe()
        probe.probed_at = "2020-01-01T00:00:00Z"
        result = evaluate_selection_policy(endpoint_configured=True, probe_result=probe)
        assert result["result_kind"] == PolicyResultKind.BLOCKED_BY_STALE_EVIDENCE.value

    def test_diagnostics_disabled_blocks(self) -> None:
        probe = _make_dry_run_probe()
        result = evaluate_selection_policy(
            endpoint_configured=True, probe_result=probe, diagnostics_enabled=False
        )
        assert (
            result["result_kind"]
            == PolicyResultKind.BLOCKED_BY_DEGRADED_DIAGNOSTICS.value
        )

    def test_missing_capability_blocks(self) -> None:
        probe = _make_dry_run_probe()
        task = get_task_profile("embedding_or_retrieval")
        c_match = match_capabilities(probe.capabilities, task)
        result = evaluate_selection_policy(
            endpoint_configured=True,
            probe_result=probe,
            task_profile=task,
            capability_match=c_match,
        )
        assert (
            result["result_kind"]
            == PolicyResultKind.BLOCKED_BY_MISSING_CAPABILITY.value
        )

    def test_no_approval_probed_not_benchmarked(self) -> None:
        probe = _make_dry_run_probe()
        result = evaluate_selection_policy(endpoint_configured=True, probe_result=probe)
        assert (
            result["result_kind"] == PolicyResultKind.PROBED_BUT_NOT_BENCHMARKED.value
        )

    def test_no_approval_with_benchmark_becomes_manual(self) -> None:
        probe = _make_dry_run_probe()
        sha = "abc123def456_match"
        bench = BenchmarkEvidenceSummary(
            summary_id="s1",
            sample_count=10,
            endpoint_sha256=sha,
            evidence_status="available",
        )
        result = evaluate_selection_policy(
            endpoint_configured=True,
            endpoint_sha256=sha,
            probe_result=probe,
            benchmark_summary=bench,
        )
        assert (
            result["result_kind"]
            == PolicyResultKind.ELIGIBLE_FOR_MANUAL_SELECTION.value
        )

    def test_explicit_approval_with_benchmark_policy_eligible(self) -> None:
        probe = _make_dry_run_probe()
        sha = probe.runtime_url[:0] or "abc"
        bench = BenchmarkEvidenceSummary(
            summary_id="s1",
            sample_count=10,
            endpoint_sha256=sha,
            evidence_status="available",
        )
        result = evaluate_selection_policy(
            endpoint_configured=True,
            endpoint_sha256=sha,
            probe_result=probe,
            benchmark_summary=bench,
            explicit_approval=True,
        )
        assert (
            result["result_kind"]
            == PolicyResultKind.ELIGIBLE_FOR_POLICY_SELECTION.value
        )

    def test_stale_benchmark_degraded(self) -> None:
        probe = _make_dry_run_probe()
        bench = BenchmarkEvidenceSummary(
            summary_id="s1",
            sample_count=0,
            endpoint_sha256="abc",
            evidence_status="stale",
            stale=True,
        )
        result = evaluate_selection_policy(
            endpoint_configured=True,
            endpoint_sha256="abc",
            probe_result=probe,
            benchmark_summary=bench,
        )
        assert result["result_kind"] in {
            PolicyResultKind.ELIGIBLE_FOR_MANUAL_SELECTION.value,
            PolicyResultKind.PROBED_BUT_NOT_BENCHMARKED.value,
        }

    def test_endpoint_hash_mismatch_adds_code(self) -> None:
        probe = _make_dry_run_probe()
        bench = BenchmarkEvidenceSummary(
            summary_id="s1",
            sample_count=10,
            endpoint_sha256="different_hash",
            evidence_status="available",
        )
        result = evaluate_selection_policy(
            endpoint_configured=True,
            endpoint_sha256="my_hash",
            probe_result=probe,
            benchmark_summary=bench,
        )
        assert (
            ExplanationCode.ENDPOINT_HASH_MISMATCH.value in result["explanation_codes"]
        )


class TestTaskProfiles:
    def test_all_eight_profiles_exist(self) -> None:
        profiles = list_task_profiles()
        names = {p.profile_name for p in profiles}
        expected = {
            "chat_light",
            "code_review_light",
            "structured_json",
            "tool_planning",
            "long_context_summary",
            "embedding_or_retrieval",
            "vision_or_multimodal",
            "unknown",
        }
        assert names == expected

    def test_unknown_profile_falls_back(self) -> None:
        p = get_task_profile("nonexistent")
        assert p.profile_name == "unknown"
        assert not p.manual_selection_allowed

    def test_unknown_is_conservative(self) -> None:
        p = get_task_profile("unknown")
        assert not p.manual_selection_allowed
        assert not p.policy_selection_allowed

    def test_structured_json_requires_structured_output(self) -> None:
        p = get_task_profile("structured_json")
        assert p.structured_output_required
        assert "structured_json_output" in p.required_capabilities

    def test_tool_planning_requires_tool_calling(self) -> None:
        p = get_task_profile("tool_planning")
        assert p.tool_call_required
        assert "tool_calling" in p.required_capabilities

    def test_long_context_has_min_window(self) -> None:
        p = get_task_profile("long_context_summary")
        assert p.min_context_window_tokens == 32768

    def test_embedding_requires_embeddings(self) -> None:
        p = get_task_profile("embedding_or_retrieval")
        assert "embeddings" in p.required_capabilities

    def test_vision_requires_vision(self) -> None:
        p = get_task_profile("vision_or_multimodal")
        assert "vision" in p.required_capabilities

    def test_task_profile_artifact_validates(self) -> None:
        import jsonschema

        schema_path = SCHEMA_DIR / "rig.local_inference.task_profile.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        for profile in list_task_profiles():
            data = json.loads(profile.model_dump_json())
            data["schema_version"] = "rig.local_inference.task_profile.v1"
            jsonschema.validate(data, schema)


class TestCapabilityMatching:
    def test_all_required_matched(self) -> None:
        caps = _make_dry_run_probe().capabilities
        task = get_task_profile("chat_light")
        result = match_capabilities(caps, task)
        assert result.missing_required == []
        assert "chat_completions" in result.matched_required

    def test_missing_required_reported(self) -> None:
        caps = CapabilityProbeCapabilities()
        task = get_task_profile("embedding_or_retrieval")
        result = match_capabilities(caps, task)
        assert "embeddings" in result.missing_required
        assert ExplanationCode.EMBEDDINGS_MISSING.value in result.explanation_codes

    def test_missing_preferred_reported(self) -> None:
        caps = CapabilityProbeCapabilities(chat_completions=CapabilityStatus.SUPPORTED)
        task = get_task_profile("chat_light")
        result = match_capabilities(caps, task)
        assert "streaming" in result.missing_preferred

    def test_tool_calling_missing_code(self) -> None:
        caps = CapabilityProbeCapabilities(chat_completions=CapabilityStatus.SUPPORTED)
        task = get_task_profile("tool_planning")
        result = match_capabilities(caps, task)
        assert ExplanationCode.TOOL_CALLING_MISSING.value in result.explanation_codes

    def test_structured_json_missing_code(self) -> None:
        caps = CapabilityProbeCapabilities(chat_completions=CapabilityStatus.SUPPORTED)
        task = get_task_profile("structured_json")
        result = match_capabilities(caps, task)
        assert ExplanationCode.STRUCTURED_JSON_MISSING.value in result.explanation_codes

    def test_context_window_unknown_flag(self) -> None:
        caps = _make_dry_run_probe().capabilities
        task = get_task_profile("long_context_summary")
        result = match_capabilities(caps, task)
        assert "context_window_not_verified" in result.risk_flags

    def test_vision_missing_code(self) -> None:
        caps = CapabilityProbeCapabilities(chat_completions=CapabilityStatus.SUPPORTED)
        task = get_task_profile("vision_or_multimodal")
        result = match_capabilities(caps, task)
        assert ExplanationCode.VISION_MISSING.value in result.explanation_codes


class TestBenchmarkSummarizer:
    def test_empty_jsonl_returns_missing(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            pass
        path = Path(f.name)
        summary = summarize_benchmark_jsonl(path)
        assert summary.sample_count == 0
        assert summary.evidence_status == "missing"
        path.unlink()

    def test_summarize_sample_jsonl(self, tmp_path: Path) -> None:
        path = tmp_path / "samples.jsonl"
        for i in range(5):
            sample = build_benchmark_sample(
                run_id="r1",
                prompt_text=f"test prompt {i}",
                completion_text=f"response {i}",
                prompt_token_count=10 + i * 5,
                completion_token_count=5 + i,
                time_to_first_token_ms=100.0 + i * 20,
                tokens_per_sec_decode=30.0 + i,
                duration_ms=200 + i * 50,
            )
            write_sample_to_jsonl(sample, path)

        summary = summarize_benchmark_jsonl(path)
        assert summary.sample_count == 5
        assert summary.evidence_status == "available"
        assert summary.error_count_total == 0
        assert summary.time_to_first_token_ms_p50 is not None
        assert summary.tokens_per_sec_decode_p50 is not None

    def test_summarize_with_errors(self, tmp_path: Path) -> None:
        path = tmp_path / "samples.jsonl"
        for i in range(3):
            sample = build_benchmark_sample(
                run_id="r1",
                prompt_text=f"test {i}",
                status=ProbeStatus.FAILED,
                error_class="TestError",
                error_safe_message="test failure",
            )
            write_sample_to_jsonl(sample, path)

        summary = summarize_benchmark_jsonl(path)
        assert summary.error_count_total == 3
        assert "TestError" in summary.error_count_by_class

    def test_content_light_validation(self, tmp_path: Path) -> None:
        path = tmp_path / "samples.jsonl"
        sample = build_benchmark_sample(run_id="r1", prompt_text="test")
        write_sample_to_jsonl(sample, path)
        warnings = validate_benchmark_content_light(path)
        assert len(warnings) == 0

    def test_forbidden_field_detected(self, tmp_path: Path) -> None:
        path = tmp_path / "samples.jsonl"
        path.write_text(
            json.dumps({"schema_version": "x", "prompt": "leaked content"}) + "\n",
            encoding="utf-8",
        )
        warnings = validate_benchmark_content_light(path)
        assert len(warnings) >= 1
        assert any("prompt" in w.lower() for w in warnings)

    def test_benchmark_summary_schema_validates(self) -> None:
        import jsonschema

        schema_path = (
            SCHEMA_DIR / "rig.local_inference.benchmark_summary.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        summary = BenchmarkEvidenceSummary(
            summary_id="bs_test", sample_count=10, evidence_status="available"
        )
        data = json.loads(summary.model_dump_json())
        jsonschema.validate(data, schema)


class TestFallbackDecision:
    def test_unconfigured_fallback(self) -> None:
        result = evaluate_selection_policy(endpoint_configured=False)
        fb = decide_fallback(selection_policy_result=result)
        assert fb.local_inference_blocked
        assert not fb.local_inference_selected
        assert fb.fallback_provider_class == "remote_provider"

    def test_failed_probe_fallback(self) -> None:
        result = evaluate_selection_policy(endpoint_configured=True)
        fb = decide_fallback(selection_policy_result=result)
        assert fb.local_inference_blocked
        assert fb.requires_fallback_for_failed_probe

    def test_degraded_diagnostics_fallback(self) -> None:
        probe = _make_dry_run_probe()
        result = evaluate_selection_policy(
            endpoint_configured=True, probe_result=probe, diagnostics_enabled=False
        )
        fb = decide_fallback(selection_policy_result=result)
        assert fb.requires_fallback_for_degraded_diagnostics

    def test_missing_capability_fallback(self) -> None:
        probe = _make_dry_run_probe()
        task = get_task_profile("embedding_or_retrieval")
        c_match = match_capabilities(probe.capabilities, task)
        result = evaluate_selection_policy(
            endpoint_configured=True,
            probe_result=probe,
            task_profile=task,
            capability_match=c_match,
        )
        fb = decide_fallback(selection_policy_result=result)
        assert fb.requires_fallback_for_missing_capability

    def test_missing_approval_flagged(self) -> None:
        probe = _make_dry_run_probe()
        result = evaluate_selection_policy(endpoint_configured=True, probe_result=probe)
        fb = decide_fallback(selection_policy_result=result)
        assert fb.requires_fallback_for_missing_approval

    def test_eligible_no_fallback(self) -> None:
        sha = "abc123"
        bench = BenchmarkEvidenceSummary(
            summary_id="s1",
            sample_count=10,
            endpoint_sha256=sha,
            evidence_status="available",
        )
        probe = _make_dry_run_probe()
        result = evaluate_selection_policy(
            endpoint_configured=True,
            endpoint_sha256=sha,
            probe_result=probe,
            benchmark_summary=bench,
            explicit_approval=True,
        )
        fb = decide_fallback(selection_policy_result=result)
        assert fb.local_inference_selected
        assert not fb.local_inference_blocked

    def test_fallback_schema_validates(self) -> None:
        import jsonschema

        schema_path = (
            SCHEMA_DIR / "rig.local_inference.provider_fallback_decision.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        result = evaluate_selection_policy(endpoint_configured=False)
        fb = decide_fallback(selection_policy_result=result)
        data = json.loads(fb.model_dump_json())
        jsonschema.validate(data, schema)


class TestSubstrateContentLight:
    def test_no_prompts_in_selection_result(self) -> None:
        result = evaluate_selection_policy(endpoint_configured=False)
        js = json.dumps(result, sort_keys=True)
        assert "prompt" not in js.lower()

    def test_no_completions_in_selection_result(self) -> None:
        result = evaluate_selection_policy(endpoint_configured=False)
        js = json.dumps(result, sort_keys=True)
        assert "completion" not in js.lower()

    def test_no_tokens_in_selection_result(self) -> None:
        result = evaluate_selection_policy(endpoint_configured=False)
        js = json.dumps(result, sort_keys=True)
        assert "api_key" not in js.lower()

    def test_benchmark_summary_no_raw_prompt(self) -> None:
        summary = BenchmarkEvidenceSummary(
            summary_id="s1", sample_count=1, evidence_status="available"
        )
        data = json.loads(summary.model_dump_json())
        assert "prompt" not in data
        assert "completion" not in data
        assert "content" not in data

    def test_no_runtime_started_anywhere(self) -> None:
        result = evaluate_selection_policy(endpoint_configured=False)
        assert "subprocess" not in json.dumps(result).lower()


class TestCLI:
    SCRIPT = str(
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "rig_local_inference_selection_policy.py"
    )

    def _run_cli(
        self, *args: str, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, self.SCRIPT]
        cmd.extend(args)
        for k, v in kwargs.items():
            if v is True:
                cmd.append(f"--{k.replace('_', '-')}")
            elif v is not False:
                cmd.append(f"--{k.replace('_', '-')}")
                cmd.append(str(v))
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_cli_not_configured(self, tmp_path: Path) -> None:
        result = self._run_cli(
            config_root=str(tmp_path / "li_config"),
            output_dir=str(tmp_path / "output"),
            json=True,
        )
        data = json.loads(result.stdout)
        assert data["selection_policy"]["result_kind"] == "not_configured"

    def test_cli_no_runtime_started(self, tmp_path: Path) -> None:
        result = self._run_cli(
            config_root=str(tmp_path / "li_config"),
            output_dir=str(tmp_path / "output"),
            json=True,
        )
        assert "running" not in result.stderr.lower()

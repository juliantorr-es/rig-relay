"""Orchestrator tests — backend registry, model acquisition, server lifecycle,
auto routing, retention policy, proposal adapter, CLI E2E.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from rig_relay.providers.local_inference import (
    AutoRoutingStatus,
    build_retention_policy,
    classify_and_propose,
    evaluate_auto_routing,
    get_backend,
    list_backends,
    plan_model_download,
    plan_server_start,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"


class TestBackendRegistry:
    def test_four_backends(self) -> None:
        backends = list_backends()
        ids = {b.backend_id for b in backends}
        assert ids >= {"ollama", "llama_cpp_server", "vllm", "custom_openai_compatible"}

    def test_get_backend(self) -> None:
        b = get_backend("ollama")
        assert b is not None
        assert b.default_port == 11434

    def test_unknown_backend_none(self) -> None:
        assert get_backend("nonexistent") is None

    def test_backends_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.runtime_backend_registry.v1.schema.json"
        assert p.exists()


class TestModelAcquisition:
    def test_plan_blocked_by_default(self) -> None:
        plan = plan_model_download(backend_id="ollama", model_id="llama3")
        assert "approval_required" in plan.blocked_reasons
        assert plan.download_executed is False

    def test_plan_with_approval_dry_run(self) -> None:
        plan = plan_model_download(
            backend_id="ollama", model_id="llama3", approval=True, dry_run=True
        )
        assert "dry_run_enabled" in plan.blocked_reasons

    def test_plan_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.model_acquisition_plan.v1.schema.json"
        assert p.exists()

    def test_model_id_hash_stable(self) -> None:
        p1 = plan_model_download(backend_id="o", model_id="llama3")
        p2 = plan_model_download(backend_id="o", model_id="llama3")
        assert p1.model_id_hash == p2.model_id_hash


class TestServerLifecycle:
    def test_start_plan_blocked_by_default(self) -> None:
        b = get_backend("ollama")
        assert b is not None
        receipt = plan_server_start(backend=b)
        assert "auto_start_not_allowed" in receipt.blocked_reasons

    def test_plan_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.server_lifecycle_receipt.v1.schema.json"
        assert p.exists()

    def test_non_localhost_blocked(self) -> None:
        b = get_backend("ollama")
        assert b is not None
        receipt = plan_server_start(backend=b, host="0.0.0.0", approval=True)
        assert "host_not_localhost" in receipt.blocked_reasons

    def test_privileged_port_blocked(self) -> None:
        b = get_backend("ollama")
        assert b is not None
        receipt = plan_server_start(backend=b, port=80, approval=True)
        assert "privileged_port_blocked" in receipt.blocked_reasons

    def test_lifecycle_action_is_plan(self) -> None:
        b = get_backend("ollama")
        assert b is not None
        receipt = plan_server_start(backend=b)
        assert receipt.lifecycle_action == "plan"

    def test_command_hash_stable(self) -> None:
        from rig_relay.providers.local_inference.model_acquisition import (
            compute_command_hash,
        )

        h1 = compute_command_hash("ollama pull llama3")
        h2 = compute_command_hash("ollama pull llama3")
        assert h1 == h2


class TestAutoRouting:
    def test_disabled_by_default(self) -> None:
        d = evaluate_auto_routing()
        assert d.status == AutoRoutingStatus.AUTO_ROUTING_DISABLED.value

    def test_enabled_but_no_backend_blocks(self) -> None:
        d = evaluate_auto_routing(routing_enabled=True)
        assert d.status == AutoRoutingStatus.BLOCKED_BY_NO_RUNTIME.value

    def test_missing_model_blocks(self) -> None:
        d = evaluate_auto_routing(routing_enabled=True, backend_id="ollama")
        assert d.status == AutoRoutingStatus.BLOCKED_BY_MODEL_MISSING.value

    def test_health_failed_blocks(self) -> None:
        d = evaluate_auto_routing(
            routing_enabled=True, backend_id="ollama", model_id_hash="abc"
        )
        assert d.status == AutoRoutingStatus.BLOCKED_BY_FAILED_HEALTH.value

    def test_diagnostics_disabled_blocks(self) -> None:
        d = evaluate_auto_routing(
            routing_enabled=True,
            backend_id="ollama",
            model_id_hash="abc",
            health_check_passed=True,
            diagnostics_enabled=False,
        )
        assert d.status == AutoRoutingStatus.BLOCKED_BY_POLICY.value

    def test_eligible_all_gates_pass(self) -> None:
        d = evaluate_auto_routing(
            routing_enabled=True,
            backend_id="ollama",
            model_id_hash="abc",
            health_check_passed=True,
            capability_match_passed=True,
            benchmark_evidence_available=True,
            shadow_evidence_available=True,
        )
        assert d.status == AutoRoutingStatus.ELIGIBLE_FOR_AUTO_ROUTING.value

    def test_high_risk_requires_shadow(self) -> None:
        d = evaluate_auto_routing(
            routing_enabled=True,
            backend_id="ollama",
            model_id_hash="abc",
            health_check_passed=True,
            capability_match_passed=True,
            benchmark_evidence_available=True,
            shadow_evidence_available=False,
            task_profile="tool_planning",
        )
        assert d.status == AutoRoutingStatus.BLOCKED_BY_MISSING_SHADOW_EVIDENCE.value

    def test_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.auto_routing_decision.v1.schema.json"
        assert p.exists()


class TestRetentionPolicy:
    def test_disabled_default(self) -> None:
        policy = build_retention_policy()
        assert policy.mode == "disabled"
        assert policy.export_to_telemetry_allowed is False

    def test_metadata_only_mode(self) -> None:
        policy = build_retention_policy(mode="metadata_only")
        assert policy.ttl_seconds == 0

    def test_raw_ttl_sets_values(self) -> None:
        policy = build_retention_policy(mode="raw_local_ttl")
        assert policy.ttl_seconds == 3600
        assert policy.max_bytes_per_session > 0

    def test_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.raw_retention_policy.v1.schema.json"
        assert p.exists()


class TestProposalAdapter:
    def test_answer_only(self) -> None:
        proposal = classify_and_propose(completion_text="The answer is 42.")
        assert proposal.proposed_action_type == "answer_only"
        assert proposal.tool_execution_allowed is False

    def test_tool_call_proposal(self) -> None:
        proposal = classify_and_propose(
            completion_text='{"tool_calls": [{"function": {"name": "add"}}]}'
        )
        assert proposal.proposed_action_type == "tool_call_proposal"
        assert proposal.required_gate == "tool_permission"

    def test_file_mutation_proposal(self) -> None:
        proposal = classify_and_propose(
            completion_text='{"write_file": true, "file_path": "/tmp/test"}'
        )
        assert proposal.proposed_action_type == "file_mutation_proposal"
        assert proposal.required_gate == "patch_gate"

    def test_shell_proposal(self) -> None:
        proposal = classify_and_propose(
            completion_text='{"bash": true, "command": "ls"}'
        )
        assert proposal.proposed_action_type == "shell_command_proposal"
        assert proposal.required_gate == "bash_policy"

    def test_all_proposals_blocked(self) -> None:
        proposal = classify_and_propose(completion_text='{"bash": true}')
        assert proposal.tool_execution_allowed is False
        assert proposal.file_mutation_allowed is False
        assert proposal.shell_execution_allowed is False

    def test_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.local_output_proposal.v1.schema.json"
        assert p.exists()


class TestCLI:
    SCRIPT = str(
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "rig_local_inference_orchestrator.py"
    )

    def _run(self, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, self.SCRIPT]
        cmd.extend(args)
        for k, v in kwargs.items():
            kk = k.replace("_", "-")
            if v is True:
                cmd.append(f"--{kk}")
            elif v is not False and v is not None:
                cmd.append(f"--{kk}")
                cmd.append(str(v))
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_list_backends(self, tmp_path: Path) -> None:
        r = self._run("list-backends", output_dir=str(tmp_path), json=True)
        assert "ollama" in r.stdout

    def test_plan_model_download(self, tmp_path: Path) -> None:
        r = self._run(
            "plan-model-download",
            model_id="llama3",
            output_dir=str(tmp_path),
            json=True,
        )
        data = json.loads(r.stdout)
        assert data["download_executed"] is False

    def test_start_server_plan(self, tmp_path: Path) -> None:
        r = self._run("start-server-plan", output_dir=str(tmp_path), json=True)
        data = json.loads(r.stdout)
        assert data["lifecycle_action"] == "plan"

    def test_retention_policy(self, tmp_path: Path) -> None:
        r = self._run(
            "retention-policy", mode="disabled", output_dir=str(tmp_path), json=True
        )
        data = json.loads(r.stdout)
        assert data["mode"] == "disabled"

    def test_route_decision(self, tmp_path: Path) -> None:
        r = self._run("route-decision", output_dir=str(tmp_path), json=True)
        data = json.loads(r.stdout)
        assert data["status"] == "auto_routing_disabled"

    def test_proposal_adapt(self, tmp_path: Path) -> None:
        r = self._run(
            "proposal-adapt",
            completion_text="Hello",
            output_dir=str(tmp_path),
            json=True,
        )
        data = json.loads(r.stdout)
        assert data["proposed_action_type"] == "answer_only"


class TestSubstrate:
    def test_no_download_by_default(self) -> None:
        plan = plan_model_download(backend_id="ollama", model_id="llama3")
        assert plan.download_executed is False

    def test_no_server_start_by_default(self) -> None:
        b = get_backend("ollama")
        assert b is not None
        receipt = plan_server_start(backend=b)
        assert receipt.started_by_rig is False

    def test_no_raw_logs_by_default(self) -> None:
        policy = build_retention_policy()
        assert policy.mode == "disabled"

    def test_proposals_blocked_by_default(self) -> None:
        proposal = classify_and_propose(completion_text='{"bash": true}')
        assert proposal.tool_execution_allowed is False
        assert proposal.file_mutation_allowed is False
        assert proposal.shell_execution_allowed is False

    def test_no_telemetry_export_by_default(self) -> None:
        policy = build_retention_policy(mode="raw_local_ttl")
        assert policy.export_to_telemetry_allowed is False

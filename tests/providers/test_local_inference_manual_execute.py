"""Manual execution gate tests — approval, request envelope, receipt,
execution client, redaction, and CLI scenarios.

Classifications: contract, unit, integration, real-artifact, adversarial, substrate.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import respx  # noqa: I202

from rig_relay.providers.local_inference import (
    ApprovalStatus,
    ApprovedByMode,
    ExecutionStatusKind,
    ManualExecutionApproval,
    ManualExecutionRequest,
    ManualExecutionResponseReceipt,
    PersistencePolicy,
    RequestClass,
    build_approval,
    build_blocked_receipt,
    build_executed_receipt,
    compute_approval_hash,
    evaluate_execution_gate,
    evaluate_selection_policy,
    execute_chat_completion,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"


class TestApprovalContract:
    def test_approval_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.manual_execution_approval.v1.schema.json"
        assert p.exists()

    def test_approval_validates(self) -> None:
        import jsonschema

        schema_path = (
            SCHEMA_DIR / "rig.local_inference.manual_execution_approval.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        approval = build_approval()
        data = json.loads(approval.model_dump_json())
        jsonschema.validate(data, schema)

    def test_request_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.manual_execution_request.v1.schema.json"
        assert p.exists()

    def test_request_validates(self) -> None:
        import jsonschema

        schema_path = (
            SCHEMA_DIR / "rig.local_inference.manual_execution_request.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        req = make_request()
        data = json.loads(req.model_dump_json())
        jsonschema.validate(data, schema)

    def test_receipt_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.manual_execution_receipt.v1.schema.json"
        assert p.exists()

    def test_receipt_validates(self) -> None:
        import jsonschema

        schema_path = (
            SCHEMA_DIR / "rig.local_inference.manual_execution_receipt.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        receipt = build_blocked_receipt(["endpoint_not_configured"])
        data = json.loads(receipt.model_dump_json())
        jsonschema.validate(data, schema)


def make_request(**kwargs: object) -> ManualExecutionRequest:
    prompt = "What is 1+1?"
    b = prompt.encode("utf-8")
    defaults = {
        "request_id": "req_test",
        "prompt_sha256": hashlib.sha256(b).hexdigest(),
        "prompt_byte_count": len(b),
        "task_profile": "chat_light",
        "created_at": "2026-06-01T00:00:00Z",
    }
    defaults.update(kwargs)
    return ManualExecutionRequest(**defaults)


def make_selection(manual_allowed: bool = False) -> dict:
    return (
        evaluate_selection_policy(endpoint_configured=False)
        if not manual_allowed
        else {
            "result_kind": "eligible_for_manual_selection",
            "manual_selection_allowed": True,
            "policy_selection_allowed": False,
        }
    )


class TestExecutionGateUnit:
    def test_unconfigured_blocks(self) -> None:
        receipt = evaluate_execution_gate(
            endpoint_configured=False,
            endpoint_hash="",
            selection_policy_result=None,
            approval=None,
            request=None,
        )
        assert receipt.status == ExecutionStatusKind.BLOCKED
        assert "endpoint_not_configured" in receipt.blocked_reasons

    def test_missing_selection_policy_blocks(self) -> None:
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="abc",
            selection_policy_result=None,
            approval=None,
            request=None,
        )
        assert "no_selection_policy_result" in receipt.blocked_reasons

    def test_not_manual_eligible_blocks(self) -> None:
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="abc",
            selection_policy_result=make_selection(manual_allowed=False),
            approval=None,
            request=None,
        )
        assert any("not_manual_eligible" in r for r in receipt.blocked_reasons)

    def test_missing_approval_blocks(self) -> None:
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="abc",
            selection_policy_result=make_selection(manual_allowed=True),
            approval=None,
            request=make_request(),
        )
        assert "approval_missing" in receipt.blocked_reasons

    def test_endpoint_hash_mismatch_blocks(self) -> None:
        approval = build_approval(scope_endpoint_hash="abc123")
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="different",
            selection_policy_result=make_selection(manual_allowed=True),
            approval=approval,
            request=make_request(),
        )
        assert "endpoint_hash_mismatch" in receipt.blocked_reasons

    def test_task_profile_mismatch_blocks(self) -> None:
        approval = build_approval(scope_task_profile="tool_planning")
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="",
            selection_policy_result=make_selection(manual_allowed=True),
            approval=approval,
            request=make_request(task_profile="chat_light"),
        )
        assert "task_profile_mismatch" in receipt.blocked_reasons

    def test_request_class_mismatch_blocks(self) -> None:
        approval = build_approval(scope_request_class=RequestClass.EMBEDDING)
        req = make_request(request_class=RequestClass.CHAT)
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="",
            selection_policy_result=make_selection(manual_allowed=True),
            approval=approval,
            request=req,
        )
        assert "request_class_mismatch" in receipt.blocked_reasons

    def test_prompt_too_large_blocks(self) -> None:
        approval = build_approval(scope_max_prompt_bytes=10)
        big = "x" * 100
        req = make_request(
            prompt_sha256=hashlib.sha256(big.encode()).hexdigest(),
            prompt_byte_count=len(big.encode()),
        )
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="",
            selection_policy_result=make_selection(manual_allowed=True),
            approval=approval,
            request=req,
        )
        assert "prompt_too_large" in receipt.blocked_reasons

    def test_output_tokens_too_large_blocks(self) -> None:
        approval = build_approval(scope_max_output_tokens=100)
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="",
            selection_policy_result=make_selection(manual_allowed=True),
            approval=approval,
            request=make_request(max_output_tokens=500),
        )
        assert "output_tokens_too_large" in receipt.blocked_reasons

    def test_streaming_not_approved_blocks(self) -> None:
        approval = build_approval(scope_streaming_allowed=False)
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="",
            selection_policy_result=make_selection(manual_allowed=True),
            approval=approval,
            request=make_request(streaming_requested=True),
        )
        assert "streaming_not_approved" in receipt.blocked_reasons

    def test_tool_calling_not_approved_blocks(self) -> None:
        approval = build_approval(scope_tool_calling_allowed=False)
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="",
            selection_policy_result=make_selection(manual_allowed=True),
            approval=approval,
            request=make_request(tool_calling_requested=True),
        )
        assert "tool_calling_not_approved" in receipt.blocked_reasons

    def test_structured_output_not_approved_blocks(self) -> None:
        approval = build_approval(scope_structured_output_allowed=False)
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="",
            selection_policy_result=make_selection(manual_allowed=True),
            approval=approval,
            request=make_request(structured_output_requested=True),
        )
        assert "structured_output_not_approved" in receipt.blocked_reasons

    def test_expired_approval_blocks(self) -> None:
        approval = build_approval(ttl_seconds=-1)
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="",
            selection_policy_result=make_selection(manual_allowed=True),
            approval=approval,
            request=make_request(),
        )
        assert "approval_expired" in receipt.blocked_reasons

    def test_all_gates_pass_produces_executed(self) -> None:
        approval = build_approval(scope_task_profile="chat_light")
        receipt = evaluate_execution_gate(
            endpoint_configured=True,
            endpoint_hash="",
            selection_policy_result=make_selection(manual_allowed=True),
            approval=approval,
            request=make_request(),
        )
        assert receipt.status == ExecutionStatusKind.EXECUTED
        assert receipt.blocked_reasons == []

    def test_approval_hash_stable(self) -> None:
        a1 = build_approval(scope_endpoint_hash="abc", scope_task_profile="chat_light")
        a2 = build_approval(scope_endpoint_hash="abc", scope_task_profile="chat_light")
        assert a1.approval_hash == a2.approval_hash

    def test_approval_hash_changes_with_scope(self) -> None:
        a1 = build_approval(scope_endpoint_hash="abc")
        a2 = build_approval(scope_endpoint_hash="def")
        assert a1.approval_hash != a2.approval_hash

    def test_auto_execution_always_false_in_receipts(self) -> None:
        receipt = build_blocked_receipt(["test"])
        assert receipt.automatic_agent_execution is False
        assert receipt.raw_prompt_persisted is False
        assert receipt.raw_completion_persisted is False


class TestExecutionClientIntegration:
    @pytest.mark.asyncio
    async def test_successful_chat_completion(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:19999/v1/chat/completions").respond(
                200,
                json={
                    "model": "test-model",
                    "choices": [{"message": {"content": "2"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 1},
                },
            )
            result = await execute_chat_completion(
                endpoint_url="http://127.0.0.1:19999",
                messages=[{"role": "user", "content": "What is 1+1?"}],
            )
        assert result["status"] == "executed"
        assert result["completion_sha256"]

    @pytest.mark.asyncio
    async def test_timeout_produces_timed_out(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:29999/v1/chat/completions").mock(
                side_effect=httpx.TimeoutException("timeout")
            )
            result = await execute_chat_completion(
                endpoint_url="http://127.0.0.1:29999",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "timed_out"

    @pytest.mark.asyncio
    async def test_http_500_produces_failed(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:39999/v1/chat/completions").respond(500)
            result = await execute_chat_completion(
                endpoint_url="http://127.0.0.1:39999",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_malformed_json_produces_malformed(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:49999/v1/chat/completions").respond(
                200, content=b"not json"
            )
            result = await execute_chat_completion(
                endpoint_url="http://127.0.0.1:49999",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "malformed_response"

    @pytest.mark.asyncio
    async def test_empty_choices_produces_malformed(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:59999/v1/chat/completions").respond(
                200, json={"choices": []}
            )
            result = await execute_chat_completion(
                endpoint_url="http://127.0.0.1:59999",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "malformed_response"


class TestSubstrateRedaction:
    def test_blocked_receipt_no_raw_prompt(self) -> None:
        receipt = build_blocked_receipt(["test"])
        data = json.loads(receipt.model_dump_json())
        assert "raw_prompt" not in data or data.get("raw_prompt_persisted") is False
        for val in data.values():
            if isinstance(val, str) and len(val) > 30:
                assert "What is" not in val

    def test_executed_receipt_no_raw_prompt(self) -> None:
        prompt = "What is 1+1?"
        b = prompt.encode("utf-8")
        req = make_request(
            prompt_sha256=hashlib.sha256(b).hexdigest(), prompt_byte_count=len(b)
        )
        receipt = build_executed_receipt(
            req,
            status=ExecutionStatusKind.EXECUTED,
            completion_sha256=hashlib.sha256("2".encode()).hexdigest(),
            completion_byte_count=1,
            output_token_count=1,
            latency_ms=100,
        )
        data = json.loads(receipt.model_dump_json())
        assert data["raw_prompt_persisted"] is False
        assert data["raw_completion_persisted"] is False
        assert "What is 1+1" not in json.dumps(data)

    def test_blocked_receipt_content_light(self) -> None:
        receipt = build_blocked_receipt(["test"])
        data = json.loads(receipt.model_dump_json())
        for key in data:
            assert "secret" not in key.lower()
            if isinstance(data[key], str):
                assert "token" not in data[key].lower() or "token_count" in key

    def test_prompt_hash_in_receipt(self) -> None:
        prompt = "test"
        b = prompt.encode("utf-8")
        p_sha = hashlib.sha256(b).hexdigest()
        req = make_request(prompt_sha256=p_sha, prompt_byte_count=len(b))
        receipt = build_executed_receipt(req, status=ExecutionStatusKind.EXECUTED)
        assert receipt.prompt_sha256 == p_sha

    def test_no_runtime_no_model_no_db(self) -> None:
        receipt = build_blocked_receipt(["test"])
        data = json.loads(receipt.model_dump_json())
        assert "subprocess" not in json.dumps(data).lower()
        assert "download" not in json.dumps(data).lower()


class TestCLI:
    SCRIPT = str(
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "rig_local_inference_manual_execute.py"
    )

    def _run(self, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, self.SCRIPT]
        cmd.extend(args)
        for k, v in kwargs.items():
            if v is True:
                cmd.append(f"--{k.replace('_', '-')}")
            elif v is not False:
                cmd.append(f"--{k.replace('_', '-')}")
                cmd.append(str(v))
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_cli_without_approval_emits_blocked(self, tmp_path: Path) -> None:
        result = self._run(
            config_root=str(tmp_path / "lc"),
            output_dir=str(tmp_path / "out"),
            json=True,
        )
        data = json.loads(result.stdout)
        assert data["status"] == "blocked"
        assert any(
            "endpoint_not_configured" in r for r in data.get("blocked_reasons", [])
        )

    def test_cli_print_output_does_not_persist(self, tmp_path: Path) -> None:
        result = self._run(
            config_root=str(tmp_path / "lc"),
            output_dir=str(tmp_path / "out"),
            prompt="test",
            json=True,
        )
        data = json.loads(result.stdout)
        assert data["raw_prompt_persisted"] is False

    def test_cli_no_auto_execution(self, tmp_path: Path) -> None:
        result = self._run(
            config_root=str(tmp_path / "lc"),
            output_dir=str(tmp_path / "out"),
            json=True,
        )
        data = json.loads(result.stdout)
        assert data["automatic_agent_execution"] is False

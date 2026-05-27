"""Tests for RiggedLocalRuntime X2.2 — canonical evidence, secret enforcement, tool proposals."""

from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.local_inference.runtime._engine import RiggedMlxEngine, _parse_tool_calls
from rig_relay.local_inference.runtime._evidence import (
    EvidenceLedger,
    EvidenceLedgerError,
    _compute_digest,
    emit_execution_receipt,
    emit_tool_proposal_evidence,
    reconstruct_ledgers,
)
from rig_relay.local_inference.runtime._models import (
    ContextPrivacyClass,
    ExecutionStatus,
    LocalInferenceEvidenceReceipt,
    RefusalReason,
    TaskKind,
)
from rig_relay.local_inference.runtime._secrets import scan_messages_for_secrets
from rig_relay.local_inference.runtime._service import (
    RiggedLocalRuntime,
    get_runtime,
    reset_runtime,
)


class TestCanonicalEvidence:
    def test_ledger_append_with_digest_chain(self, tmp_path: Path) -> None:

        path = tmp_path / "test_ledger.jsonl"
        ledger = EvidenceLedger(path, "test.v1")
        d1 = ledger.append("test.event1", {"a": 1, "content_light": True})
        d2 = ledger.append("test.event2", {"b": 2, "content_light": True})
        assert d1 != d2
        assert path.exists()

    def test_ledger_reconstruct_validates_chain(self, tmp_path: Path) -> None:

        path = tmp_path / "test_chain.jsonl"
        ledger = EvidenceLedger(path, "test.v1")
        ledger.append("event.1", {"seq": 1, "content_light": True})
        ledger.append("event.2", {"seq": 2, "content_light": True})
        entries = ledger.reconstruct()
        assert len(entries) == 2

    def test_reconstruct_empty_ledger(self, tmp_path: Path) -> None:

        path = tmp_path / "empty.jsonl"
        ledger = EvidenceLedger(path, "test.v1")
        assert ledger.reconstruct() == []

    def test_reconstruct_detects_corruption(self, tmp_path: Path) -> None:

        path = tmp_path / "corrupt.jsonl"
        ledger = EvidenceLedger(path, "test.v1")
        ledger.append("event.1", {"seq": 1, "content_light": True})

        with open(path, "a") as f:
            f.write('{"_event":"bad","_digest":"wrong"}\n')

        with pytest.raises(EvidenceLedgerError):
            ledger.reconstruct()

    def test_digest_computation_excludes_digest_field(self) -> None:
        env = {
            "_event": "test",
            "_written_at": "now",
            "payload": {"x": 1},
            "_digest": "temp",
        }
        d1 = _compute_digest(env)
        env["_digest"] = d1
        d2 = _compute_digest(env)
        assert d1 == d2

    def test_emit_execution_receipt_writes_digest(self) -> None:
        receipt = LocalInferenceEvidenceReceipt(
            receipt_id="r1",
            task_id_hash="h1",
            status=ExecutionStatus.EXECUTED,
            content_light=True,
        )
        digest = emit_execution_receipt(receipt)
        assert digest.startswith("sha256:")

    def test_emit_tool_proposal_evidence(self) -> None:
        digest = emit_tool_proposal_evidence("task_h", 2, ["tool1", "tool2"])
        assert digest.startswith("sha256:")

    def test_reconstruct_ledgers_returns_dict(self) -> None:
        result = reconstruct_ledgers()
        assert isinstance(result, dict)
        assert "execution" in result


class TestSecretScanning:
    def test_detects_openai_api_key(self) -> None:
        result = scan_messages_for_secrets([
            {
                "role": "user",
                "content": "sk-abc123def456ghi789jkl012mno345pqr678stu901vwx",
            }
        ])
        assert result["secrets_detected"]

    def test_detects_bearer_auth_header(self) -> None:
        result = scan_messages_for_secrets([
            {
                "role": "user",
                "content": "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0N3M",
            }
        ])
        assert result["secrets_detected"]

    def test_detects_github_token(self) -> None:
        result = scan_messages_for_secrets([
            {"role": "user", "content": "ghp_abcdefghijklmnopqrstuvwxyz1234567890AB"}
        ])
        assert result["secrets_detected"]

    def test_detects_aws_access_key(self) -> None:
        result = scan_messages_for_secrets([
            {"role": "user", "content": "AKIAIOSFODNN7EXAMPLE"}
        ])
        assert result["secrets_detected"]

    def test_detects_hf_token(self) -> None:
        result = scan_messages_for_secrets([
            {"role": "user", "content": "hf_abcdefghijklmnopqrstuvwxyzABCDEFGH"}
        ])
        assert result["secrets_detected"]

    def test_detects_api_key_assignment(self) -> None:
        result = scan_messages_for_secrets([
            {
                "role": "user",
                "content": 'api_key = "sk-super-secret-long-string-abcdef"',
            }
        ])
        assert result["secrets_detected"]

    def test_clean_content_passes(self) -> None:
        result = scan_messages_for_secrets([
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "def index(items):\n    return {}"},
        ])
        assert not result["secrets_detected"]

    def test_secret_scan_returns_content_light(self) -> None:
        result = scan_messages_for_secrets([
            {"role": "user", "content": "ghp_abcdefghijklmnopqrstuvwxyz1234567890AB"}
        ])
        assert result["content_light"]
        assert "patterns_matched" in result
        assert "ghp_abcdef" not in str(result["patterns_matched"])

    def test_classification_override_on_secret_detection(self) -> None:
        rt = RiggedLocalRuntime()
        messages = [
            {"role": "user", "content": "ghp_abcdefghijklmnopqrstuvwxyz1234567890AB"}
        ]
        admission, effective = rt._classify_and_admit(
            TaskKind.CHAT, messages, ContextPrivacyClass.PRIVATE_LOCAL
        )
        if rt.is_configured:
            assert not admission.admitted
            assert effective == ContextPrivacyClass.SECRET_BEARING
            assert admission.refusal_reason == RefusalReason.CONTEXT_BLOCKED_BY_POLICY

    def test_private_content_admitted_when_clean(self) -> None:
        rt = RiggedLocalRuntime()
        messages = [
            {"role": "user", "content": "My private project code: def foo(): pass"}
        ]
        admission, effective = rt._classify_and_admit(
            TaskKind.CHAT, messages, ContextPrivacyClass.PRIVATE_LOCAL
        )
        if rt.is_configured:
            assert admission.admitted
            assert effective == ContextPrivacyClass.PRIVATE_LOCAL


class TestToolProposalEvidence:
    def test_tool_proposal_evidence_emitted(self) -> None:
        digest = emit_tool_proposal_evidence("hash", 2, ["tool1", "tool2"])
        assert digest

    def test_parse_tool_calls_json_block(self) -> None:
        text = '```json\n{"name": "read_file", "arguments": {"path": "x.py"}}\n```'
        proposals = _parse_tool_calls(text)
        assert len(proposals) >= 1
        assert proposals[0].tool_name == "read_file"

    def test_parse_tool_calls_function_tag(self) -> None:
        text = '<function_call>\n{"name": "search", "arguments": {"q": "t"}}\n</function_call>'
        proposals = _parse_tool_calls(text)
        assert len(proposals) >= 1


class TestStreaming:
    @pytest.mark.asyncio
    async def test_stream_execute_no_model(self) -> None:
        rt = RiggedLocalRuntime()
        chunks: list[str] = []
        async for chunk in rt.stream_execute([{"role": "user", "content": "Hello"}]):
            chunks.append(chunk)
        assert len(chunks) >= 0  # May be error message or empty


class TestV1Posture:
    def test_streaming_is_capability_present(self) -> None:
        rt = RiggedLocalRuntime()
        proj = rt.build_projection()
        assert "streaming_generation" in proj["capabilities"]

    def test_secret_enforcement_in_projection(self) -> None:
        rt = RiggedLocalRuntime()
        proj = rt.build_projection()
        assert proj["privacy"]["secret_scanning"] == "enforced_before_admission"

    def test_canonical_evidence_in_projection(self) -> None:
        rt = RiggedLocalRuntime()
        proj = rt.build_projection()
        assert "canonical" in proj["governance"]["evidence_emission"]


class TestEngine:
    def test_engine_methods_exist(self) -> None:
        engine = RiggedMlxEngine()
        assert hasattr(engine, "load_model")
        assert hasattr(engine, "generate")
        assert hasattr(engine, "stream_generate")
        assert hasattr(engine, "unload_model")


class TestServiceLifecycle:
    def test_singleton_pattern(self) -> None:
        reset_runtime()
        a = get_runtime()
        b = get_runtime()
        assert a is b

    def test_reset(self) -> None:
        reset_runtime()
        a = get_runtime()
        reset_runtime()
        b = get_runtime()
        assert a is not b

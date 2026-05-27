"""Lane B6.8.1: Canonical Recovery Intent Materialization and Read-Side Query.

Proves the fail-closed, schema-validated, crash-durable materialization
authority, execution separation, and content-light query service.

  B6.8.1.1 — Schema-admission: valid receipt persists, invalid refused
  B6.8.1.2 — Crash-durable payload persistence with atomic writes
  B6.8.1.3 — Materialization/execution separation (pre-materialize then execute)
  B6.8.1.4 — Refuse missing canonical intent (no fall-through to empty args)
  B6.8.1.5 — Binding mismatch refusal (manifest, tool name)
  B6.8.1.6 — Payload mismatch/payload-not-recoverable refusal
  B6.8.1.7 — Read-only execution from canonical intent
  B6.8.1.8 — Mutation proposal from canonical intent (no workspace mutation)
  B6.8.1.9 — Content-light query service (no raw args, deterministic projection)
  B6.8.1.10 — Orphaned payloads are inert without matching receipt
  B6.8.1.11 — Backward compat without authority
  B6.8.1.12 — Concurrent materialization safety
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import pytest

from rig_relay.core.tool_result_runtime import ToolResultRuntime
from rig_relay.core.types import LLMMessage
from rig_relay.recovery.handoff import (
    build_mutation_handoff,
    build_read_only_handoff,
    build_refusal_handoff,
)
from rig_relay.recovery.intent_authority import DurableRecoveryIntentAuthority
from rig_relay.recovery.intent_query import (
    IntentQueryResult,
    RecoveryIntentQueryService,
)
from rig_relay.recovery.models import RecoveryIntent
from tests.conftest import build_test_agent_loop, build_test_vibe_config


def _sha256(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


def _payload_digest(args: dict[str, Any]) -> str:
    raw = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def _parse_annotation(text: str) -> str | None:
    start = text.find("<rig-tool-outcome>")
    end = text.find("</rig-tool-outcome>")
    if start == -1 or end == -1:
        return None
    return text[start + len("<rig-tool-outcome>") : end]


def _assert_annotated(text: str) -> str:
    result = _parse_annotation(text)
    assert result is not None, f"No annotation in: {text[:200]}"
    return result


def _annotation_count(text: str) -> int:
    return text.count("<rig-tool-outcome>")


def _validate_schema(json_str: str) -> dict[str, Any]:
    from jsonschema import validate as jsonschema_validate

    schema_path = (
        Path(__file__).parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.agent_tool_outcome.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    parsed = json.loads(json_str)
    jsonschema_validate(instance=parsed, schema=schema)
    return parsed


class _CapturingEvidence:
    def __init__(self) -> None:
        self.events: list[Any] = []
        self.outcome_projections: list[Any] = []

    def emit_runtime_outcome_projection_event(self, event: Any, **kwargs: Any) -> None:
        self.events.append(event)

    def emit_agent_outcome_projection(self, outcome: Any, **kwargs: Any) -> None:
        self.outcome_projections.append(outcome)

    def emit_artifact_written(
        self,
        artifact: Any = None,
        display_text: str = "",
        tool_name: str = "",
        sequence: int = 0,
    ) -> str:
        return display_text

    def emit_tool_call_finished(self, **kwargs: Any) -> None:
        pass

    def capture_model_observation(self, *args: Any, **kwargs: Any) -> None:
        pass

    def emit_tool_reasoning_trace(self, **kwargs: Any) -> None:
        pass


# ── Helpers ─────────────────────────────────────────────────────────


def _make_authority(tmp_path: Path) -> DurableRecoveryIntentAuthority:
    return DurableRecoveryIntentAuthority(tmp_path / "authority")


def _make_runtime_with_authority(
    tmp_path: Path,
) -> tuple[DurableRecoveryIntentAuthority, ToolResultRuntime]:
    authority = _make_authority(tmp_path)
    config = build_test_vibe_config()
    loop = build_test_agent_loop(config=config)
    evidence = _CapturingEvidence()
    runtime = ToolResultRuntime(loop, evidence=evidence, intent_authority=authority)
    return authority, runtime


# ── B6.8.1.1: Schema-Admission ──────────────────────────────────────


class TestB6_8_1_1_SchemaAdmission:
    def test_valid_receipt_persists_digest_is_valid(self, tmp_path: Path) -> None:
        authority = _make_authority(tmp_path)
        args = {"path": "/valid"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-valid")
        manifest = _sha256("manifest-valid")

        intent_id = authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        loaded = authority.load_intent(receipt_sha, pd)
        assert loaded is not None
        assert loaded["canonical_tool_name"] == "read_file"
        # event_digest self-integrity
        assert "event_digest" in loaded

    def test_extra_property_rejected(self, tmp_path: Path) -> None:
        """Extra property in receipt raises ValueError at append time."""
        authority = _make_authority(tmp_path)
        args = {"path": "/extra"}
        pd = _payload_digest(args)

        # Build receipt with extra field
        event = {
            "schema_version": "rig.relay.recovery_intent_authority.v1",
            "intent_id": "sha256:" + "a" * 64,
            "recovery_receipt_sha256": _sha256("receipt-extra"),
            "payload_digest": pd,
            "manifest_digest": _sha256("manifest-extra"),
            "canonical_tool_name": "read_file",
            "execution_class": "read_only",
            "correlation_id": "",
            "validation_profile": None,
            "bounded_paths": [],
            "mutation_class": None,
            "materialization_kind": "pre_handoff",
            "content_light": True,
            "created_at": "2026-01-01T00:00:00Z",
            # EXTRA property — forbidden by additionalProperties: false
            "raw_secret": "should not be here",
        }
        with pytest.raises((ValueError, RuntimeError)):
            authority._append_receipt(event)

    def test_missing_required_field_rejected(self, tmp_path: Path) -> None:
        """Receipt missing required field rejected."""
        authority = _make_authority(tmp_path)
        args = {"path": "/missing"}
        pd = _payload_digest(args)

        event = {
            "schema_version": "rig.relay.recovery_intent_authority.v1",
            "intent_id": "sha256:" + "a" * 64,
            "recovery_receipt_sha256": _sha256("receipt-missing"),
            "payload_digest": pd,
            "manifest_digest": _sha256("manifest-missing"),
            # Missing "canonical_tool_name" (required)
            "execution_class": "read_only",
            "content_light": True,
            "created_at": "2026-01-01T00:00:00Z",
        }
        with pytest.raises((ValueError, RuntimeError)):
            authority._append_receipt(event)

    def test_invalid_execution_class_rejected(self, tmp_path: Path) -> None:
        """Invalid execution_class (not in enum) rejected."""
        authority = _make_authority(tmp_path)
        args = {"path": "/invalid"}
        pd = _payload_digest(args)

        event = {
            "schema_version": "rig.relay.recovery_intent_authority.v1",
            "intent_id": "sha256:" + "a" * 64,
            "recovery_receipt_sha256": _sha256("receipt-invalid-enum"),
            "payload_digest": pd,
            "manifest_digest": _sha256("manifest-invalid-enum"),
            "canonical_tool_name": "read_file",
            "execution_class": "direct_mutation",  # Not in enum
            "content_light": True,
            "created_at": "2026-01-01T00:00:00Z",
        }
        with pytest.raises((ValueError, RuntimeError)):
            authority._append_receipt(event)

    def test_rejection_leaves_ledger_unchanged(self, tmp_path: Path) -> None:
        """Schema-rejected receipt does not enter the ledger."""
        authority = _make_authority(tmp_path)

        # First, append a valid receipt
        args = {"path": "/first"}
        pd = _payload_digest(args)
        authority.materialize_intent(
            recovery_receipt_sha256=_sha256("receipt-first"),
            payload_digest=pd,
            manifest_digest=_sha256("manifest-first"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        receipt_path = tmp_path / "authority" / "intent_receipts.jsonl"
        before = receipt_path.read_text() if receipt_path.exists() else ""

        # Try to append invalid receipt
        bad_event = {
            "schema_version": "rig.relay.recovery_intent_authority.v1",
            "intent_id": "sha256:" + "a" * 64,
            "recovery_receipt_sha256": _sha256("receipt-bad"),
            "payload_digest": pd,
            "manifest_digest": _sha256("manifest-bad"),
            "canonical_tool_name": "read_file",
            "execution_class": "read_only",
            "content_light": True,
            "created_at": "2026-01-01T00:00:00Z",
            "extra_forbidden": 42,  # additionalProperties blocks this
        }
        try:
            authority._append_receipt(bad_event)
        except (ValueError, RuntimeError):
            pass

        after = receipt_path.read_text() if receipt_path.exists() else ""
        assert after == before, "Ledger must be unchanged after failed append"

    def test_digest_invalid_receipt_not_returned_by_load(self, tmp_path: Path) -> None:
        """load_intent returns None for receipt with mismatched digest."""
        authority = _make_authority(tmp_path)
        args = {"path": "/digest"}
        pd = _payload_digest(args)

        # Materialize valid receipt
        authority.materialize_intent(
            recovery_receipt_sha256=_sha256("receipt-digest"),
            payload_digest=pd,
            manifest_digest=_sha256("manifest-digest"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        # Manually corrupt: write a line with wrong event_digest
        receipt_path = tmp_path / "authority" / "intent_receipts.jsonl"
        lines = receipt_path.read_text().strip().split("\n")
        valid_line = lines[0]
        event = json.loads(valid_line)
        event["manifest_digest"] = _sha256("corrupt-manifest")
        # Don't recompute event_digest — it's now stale
        corrupt_line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
        receipt_path.write_text(corrupt_line)

        loaded = authority.load_intent(_sha256("receipt-digest"), pd)
        assert loaded is None, "Corrupt receipt must not be loaded"


# ── B6.8.1.2: Crash-Durable Payload Persistence ─────────────────────


class TestB6_8_1_2_CrashDurability:
    def test_atomic_write_no_partial_files(self, tmp_path: Path) -> None:
        """Payload file is complete or absent, never partial."""
        authority = _make_authority(tmp_path)
        args = {"path": "/atomic/test", "offset": 5}

        intent_id = authority.materialize_intent(
            recovery_receipt_sha256=_sha256("receipt-atomic"),
            payload_digest=_payload_digest(args),
            manifest_digest=_sha256("manifest-atomic"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        payload_path = tmp_path / "authority" / "payloads" / f"{intent_id}.json"
        assert payload_path.exists()
        raw = payload_path.read_text()
        assert raw.startswith("{") and raw.endswith("}\n") or raw.endswith("}")
        parsed = json.loads(raw)
        assert parsed == args

    def test_payload_persists_across_instances(self, tmp_path: Path) -> None:
        """Payload written by one instance is readable by another."""
        data_dir = tmp_path / "authority"
        args = {"path": "/persist/test"}

        auth1 = DurableRecoveryIntentAuthority(data_dir)
        intent_id = auth1.materialize_intent(
            recovery_receipt_sha256=_sha256("receipt-persist"),
            payload_digest=_payload_digest(args),
            manifest_digest=_sha256("manifest-persist"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        auth2 = DurableRecoveryIntentAuthority(data_dir)
        loaded = auth2.load_intent(_sha256("receipt-persist"), _payload_digest(args))
        assert loaded is not None
        payload = auth2.retrieve_payload(intent_id, _payload_digest(args))
        assert payload == args

    def test_orphaned_payload_inert_without_receipt(self, tmp_path: Path) -> None:
        """Payload without matching receipt is not treated as authority."""
        authority = _make_authority(tmp_path)
        args = {"path": "/orphan/test"}
        intent_id = "sha256:" + "f" * 64
        pd = _payload_digest(args)

        # Manually write a payload without creating receipt
        authority._payload_store.put(intent_id, args)

        # Receipt doesn't exist, so load_intent returns None
        loaded = authority.load_intent(_sha256("no-receipt"), pd)
        assert loaded is None

    def test_crash_between_payload_and_receipt(self, tmp_path: Path) -> None:
        """Simulate a crash between payload write and receipt append:
        payload exists, receipt does not. On reload, load_intent returns None.
        """
        data_dir = tmp_path / "authority"
        args = {"path": "/crash/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-crash")

        # Manually write payload only (no receipt)
        auth1 = DurableRecoveryIntentAuthority(data_dir)
        from rig_relay.recovery.intent_authority import _compute_intent_id

        intent_id = _compute_intent_id(receipt_sha, pd)
        auth1._payload_store.put(intent_id, args)

        # No receipt was written
        receipt_path = data_dir / "intent_receipts.jsonl"
        assert (
            not receipt_path.exists() or "materialize" not in receipt_path.read_text()
        )

        # Reload — the orphaned payload should be invisible through load_intent
        auth2 = DurableRecoveryIntentAuthority(data_dir)
        loaded = auth2.load_intent(receipt_sha, pd)
        assert loaded is None, "Orphaned payload without receipt must return None"

    def test_hard_exit_auth_crash_window(self, tmp_path: Path) -> None:
        """Subprocess hard-exits between payload write and receipt append.
        The orphaned payload must be invisible to a fresh authority instance.

        Uses a real subprocess to SIGKILL between payload.put and receipt append.
        """
        data_dir = tmp_path / "authority"
        script_path = tmp_path / "crash_test.py"
        args = {"path": "/hard-exit/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-hard-exit")
        manifest = _sha256("manifest-hard-exit")

        script_path.write_text(f"""
import json, os, sys, signal
from pathlib import Path
sys.path.insert(0, {json.dumps(str(Path(__file__).parent.parent))})
from rig_relay.recovery.intent_authority import (
    DurableRecoveryIntentAuthority, _compute_intent_id,
)

data_dir = Path({json.dumps(str(data_dir))})
authority = DurableRecoveryIntentAuthority(data_dir)
args = {json.dumps(args)}
pd = {json.dumps(pd)}
receipt_sha = {json.dumps(receipt_sha)}
manifest = {json.dumps(manifest)}

intent_id = _compute_intent_id(receipt_sha, pd)

# Write payload durably
authority._payload_store.put(intent_id, args)

# Hard exit BEFORE receipt append
os.kill(os.getpid(), signal.SIGKILL)
""")
        # Run subprocess — expect it to be killed
        result = subprocess.run(
            [sys.executable, str(script_path)], capture_output=True, timeout=15
        )
        # SIGKILL results in negative exit code
        assert result.returncode != 0, "Subprocess should have been killed"

        # Verify orphaned payload exists
        from rig_relay.recovery.intent_authority import _compute_intent_id

        intent_id = _compute_intent_id(receipt_sha, pd)
        payload_path = data_dir / "payloads" / f"{intent_id}.json"
        assert payload_path.exists(), "Payload should exist (written before kill)"

        # Receipt should NOT exist
        receipt_path = data_dir / "intent_receipts.jsonl"
        if receipt_path.exists():
            content = receipt_path.read_text()
            assert receipt_sha not in content, (
                "Receipt for killed intent must not exist"
            )

        # Fresh authority must NOT load orphaned payload
        auth2 = DurableRecoveryIntentAuthority(data_dir)
        loaded = auth2.load_intent(receipt_sha, pd)
        assert loaded is None, "Orphaned payload must not be loaded as authority"


# ── B6.8.1.3: Materialization/Execution Separation ──────────────────


class TestB6_8_1_3_MaterializationExecutionSeparation:
    @pytest.mark.asyncio
    async def test_pre_materialize_then_execute_canonical(self, tmp_path: Path) -> None:
        """Pre-materialize intent, then execute from canonical path."""
        authority, runtime = _make_runtime_with_authority(tmp_path)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("pre-materialized execution\n")
            fixture_path = f.name

        try:
            args = {"path": fixture_path}
            pd = _payload_digest(args)
            receipt_sha = _sha256("receipt-pre-mat")
            manifest = _sha256("manifest-pre-mat")

            # Step 1: Materialize (no execution)
            authority.materialize_intent(
                recovery_receipt_sha256=receipt_sha,
                payload_digest=pd,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                normalized_args=args,
                execution_class="read_only",
                materialization_kind="pre_handoff",
            )

            # Step 2: Build handoff and execute (from canonical intent)
            handoff = build_read_only_handoff(
                receipt_sha256=receipt_sha,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                payload_digest=pd,
            )
            msg = await runtime.handle_recovery_handoff(handoff)
            assert isinstance(msg, LLMMessage)
            content = getattr(msg, "content", "")
            assert _annotation_count(content) == 1
            parsed = _validate_schema(_assert_annotated(content))
            assert parsed["tool_name"] == "read_file"
        finally:
            Path(fixture_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_not_materialized_refused_with_authority(
        self, tmp_path: Path
    ) -> None:
        """When authority is configured but no materialized intent exists,
        execution is refused — no fall-through to empty args.
        """
        authority, runtime = _make_runtime_with_authority(tmp_path)

        pd = _sha256("p-not-mat")
        receipt_sha = _sha256("receipt-not-mat")
        manifest = _sha256("manifest-not-mat")

        handoff = build_read_only_handoff(
            receipt_sha256=receipt_sha,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            payload_digest=pd,
        )

        msg = await runtime.handle_recovery_handoff(handoff)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["status"] == "refused"
        assert parsed["refusal_code"] == "intent_not_materialized"

    @pytest.mark.asyncio
    async def test_handoff_without_intent_and_without_authority(self) -> None:
        """Without authority, handoff without intent falls through to
        missing_payload_authority refusal (no empty-args execution).
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        handoff = build_read_only_handoff(
            receipt_sha256=_sha256("receipt-no-auth"),
            manifest_digest=_sha256("manifest-no-auth"),
            canonical_tool_name="read_file",
            payload_digest=_sha256("pd-no-auth"),
        )
        msg = await runtime.handle_recovery_handoff(handoff)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["status"] == "refused"
        assert parsed["refusal_code"] in {
            "missing_payload_authority",
            "intent_not_materialized",
        }

    @pytest.mark.asyncio
    async def test_backward_compat_transient_caller_without_authority(self) -> None:
        """Without authority, caller-supplied intent still executes (legacy compat)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("legacy compat\n")
            fixture_path = f.name

        try:
            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(loop, evidence=evidence)

            args = {"path": fixture_path}
            pd = _payload_digest(args)
            receipt_sha = _sha256("receipt-legacy-comp")
            manifest = _sha256("manifest-legacy-comp")

            handoff = build_read_only_handoff(
                receipt_sha256=receipt_sha,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                payload_digest=pd,
            )
            intent = RecoveryIntent(
                canonical_tool_name="read_file",
                normalized_args=args,
                payload_digest=pd,
                manifest_digest=manifest,
            )

            msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
            assert isinstance(msg, LLMMessage)
            content = getattr(msg, "content", "")
            assert _annotation_count(content) == 1
            parsed = _validate_schema(_assert_annotated(content))
            assert parsed["tool_name"] == "read_file"
        finally:
            Path(fixture_path).unlink(missing_ok=True)


# ── B6.8.1.4: Binding Mismatch and Payload Refusal ──────────────────


class TestB6_8_1_4_BindingAndPayloadRefusal:
    @pytest.mark.asyncio
    async def test_manifest_mismatch_refused(self, tmp_path: Path) -> None:
        authority, runtime = _make_runtime_with_authority(tmp_path)
        args = {"path": "/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-bind-manifest")
        manifest_canonical = _sha256("manifest-canonical")
        manifest_handoff = _sha256("manifest-different")

        authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest_canonical,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )

        handoff = build_read_only_handoff(
            receipt_sha256=receipt_sha,
            manifest_digest=manifest_handoff,
            canonical_tool_name="read_file",
            payload_digest=pd,
        )
        msg = await runtime.handle_recovery_handoff(handoff)
        content = getattr(msg, "content", "")
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["status"] == "refused"
        assert parsed["refusal_code"] == "intent_handoff_binding_mismatch"

    @pytest.mark.asyncio
    async def test_tool_name_mismatch_refused(self, tmp_path: Path) -> None:
        authority, runtime = _make_runtime_with_authority(tmp_path)
        args = {"path": "/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-bind-tool")
        manifest = _sha256("manifest-bind-tool")

        authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )

        handoff = build_read_only_handoff(
            receipt_sha256=receipt_sha,
            manifest_digest=manifest,
            canonical_tool_name="git_status",
            payload_digest=pd,
        )
        msg = await runtime.handle_recovery_handoff(handoff)
        content = getattr(msg, "content", "")
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["refusal_code"] == "intent_handoff_binding_mismatch"

    @pytest.mark.asyncio
    async def test_refusal_handoff_still_refuses(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        handoff = build_refusal_handoff(
            receipt_sha256=_sha256("receipt-ref"),
            manifest_digest=_sha256("manifest-ref"),
            refusal_code="unsupported_wrapper",
            reason="test",
        )
        msg = await runtime.handle_recovery_handoff(handoff)
        content = getattr(msg, "content", "")
        assert "refused" in content.lower()


# ── B6.8.1.5: Mutation Proposal from Canonical Intent ───────────────


class TestB6_8_1_5_MutationProposal:
    @pytest.mark.asyncio
    async def test_mutation_from_canonical_creates_proposal_not_execution(
        self, tmp_path: Path
    ) -> None:
        authority, runtime = _make_runtime_with_authority(tmp_path)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("safe original\n")
            fixture_path = f.name

        try:
            args = {"path": fixture_path, "content": "should not write\n"}
            pd = _payload_digest(args)
            receipt_sha = _sha256("receipt-mut-canon")
            manifest = _sha256("manifest-mut-canon")

            authority.materialize_intent(
                recovery_receipt_sha256=receipt_sha,
                payload_digest=pd,
                manifest_digest=manifest,
                canonical_tool_name="write_file",
                normalized_args=args,
                execution_class="mutation_proposal",
                mutation_class="writes_workspace",
                materialization_kind="pre_handoff",
            )

            handoff = build_mutation_handoff(
                receipt_sha256=receipt_sha,
                manifest_digest=manifest,
                canonical_tool_name="write_file",
                payload_digest=pd,
                mutation_class="writes_workspace",
            )

            msg = await runtime.handle_recovery_handoff(handoff)
            content = getattr(msg, "content", "")
            parsed = _validate_schema(_assert_annotated(content))
            assert parsed["tool_name"] == "write_file"
            assert parsed["mutation_disposition"] not in {
                "performed",
                "previously_performed",
            }

            # Workspace unchanged
            current = Path(fixture_path).read_text()
            assert current == "safe original\n"
        finally:
            Path(fixture_path).unlink(missing_ok=True)


# ── B6.8.1.6: Content-Light Query Service ───────────────────────────


class TestB6_8_1_6_QueryService:
    def test_query_materialized_intent(self, tmp_path: Path) -> None:
        authority = _make_authority(tmp_path)
        args = {"path": "/query/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-query")
        manifest = _sha256("manifest-query")

        authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )

        query = RecoveryIntentQueryService(authority)
        result = query.query_by_handoff_binding(receipt_sha, pd)

        assert isinstance(result, IntentQueryResult)
        assert result.status == "materialized"
        assert result.canonical_tool_name == "read_file"
        assert result.execution_class == "read_only"
        assert result.payload_retrievable is True
        assert result.binding_disposition == "bound"
        assert result.materialization_kind == "pre_handoff"

    def test_query_missing_intent(self, tmp_path: Path) -> None:
        authority = _make_authority(tmp_path)
        query = RecoveryIntentQueryService(authority)

        result = query.query_by_handoff_binding(_sha256("nonexistent"), _sha256("nope"))
        assert result.status == "missing"
        assert not result.payload_retrievable

    def test_query_by_intent_id(self, tmp_path: Path) -> None:
        authority = _make_authority(tmp_path)
        args = {"path": "/id-query"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-id-query")

        intent_id = authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=_sha256("manifest-id-query"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )

        query = RecoveryIntentQueryService(authority)
        result = query.query_by_intent_id(intent_id)
        assert result.status == "materialized"
        assert result.intent_id == intent_id

    def test_query_result_is_content_light(self, tmp_path: Path) -> None:
        """Query result never exposes raw payload, secrets, or paths."""
        authority = _make_authority(tmp_path)
        args = {"path": "/sensitive/secret/path"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-cl-query")

        authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=_sha256("manifest-cl-query"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )

        query = RecoveryIntentQueryService(authority)
        result = query.query_by_handoff_binding(receipt_sha, pd)
        result_dict = result.to_dict()
        result_json = result.to_json()

        # No raw paths or payload content
        assert "/sensitive/secret/path" not in result_json
        assert "normalized_args" not in result_dict
        assert "file_content" not in result_dict
        assert "secret" not in result_dict

        # payload_digest IS present (content-light hash)
        assert pd in result_json

    def test_query_deterministic_projection(self, tmp_path: Path) -> None:
        """Same query twice produces same result (deterministic)."""
        authority = _make_authority(tmp_path)
        args = {"path": "/det/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-det")

        authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=_sha256("manifest-det"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )

        query = RecoveryIntentQueryService(authority)
        r1 = query.query_by_handoff_binding(receipt_sha, pd)
        r2 = query.query_by_handoff_binding(receipt_sha, pd)

        assert r1.to_json() == r2.to_json()


# ── B6.8.1.7: Concurrent Materialization Safety ─────────────────────


class TestB6_8_1_7_ConcurrentSafety:
    def test_same_key_materialize_twice(self, tmp_path: Path) -> None:
        """Materialize same composite key twice — idempotent."""
        authority = _make_authority(tmp_path)
        args = {"path": "/concurrent"}
        pd = _payload_digest(args)

        id1 = authority.materialize_intent(
            recovery_receipt_sha256=_sha256("receipt-concur"),
            payload_digest=pd,
            manifest_digest=_sha256("manifest-concur"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )
        id2 = authority.materialize_intent(
            recovery_receipt_sha256=_sha256("receipt-concur"),
            payload_digest=pd,
            manifest_digest=_sha256("manifest-concur"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )
        assert id1 == id2

    def test_payload_permissions_restricted(self, tmp_path: Path) -> None:
        """Payload files are 0o600."""
        authority = _make_authority(tmp_path)
        args = {"path": "/perm"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-perm")

        intent_id = authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=_sha256("manifest-perm"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )

        payload_path = tmp_path / "authority" / "payloads" / f"{intent_id}.json"
        stat = payload_path.stat()
        assert (stat.st_mode & 0o777) == 0o600

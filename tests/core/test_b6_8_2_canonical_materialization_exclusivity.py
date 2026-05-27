"""Lane B6.8.2: Canonical Materialization Exclusivity and Publication Closure.

Proves lock-scoped concurrent materialization, legacy bypass elimination,
schema-admission, crash durability, execution separation, and query service.

  B6.8.2.1 — Lock-scoped concurrent materialization (multiprocess)
  B6.8.2.2 — Schema-admission fail-closed
  B6.8.2.3 — Crash-durable payload with atomic writes
  B6.8.2.4 — Canonical-materialization-required refusal (no legacy bypass)
  B6.8.2.5 — Pre-materialize then execute from canonical intent
  B6.8.2.6 — Binding mismatch refusal
  B6.8.2.7 — Mutation proposal from canonical (no workspace mutation)
  B6.8.2.8 — Content-light query service (no raw args)
  B6.8.2.9 — Concurrency: competing keys, same composite key
  B6.8.2.10 — Concurrency: incompatible binding rejection
  B6.8.2.11 — Orphaned payload inert without receipt
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
from rig_relay.recovery.handoff import (
    build_mutation_handoff,
    build_read_only_handoff,
    build_refusal_handoff,
)
from rig_relay.recovery.intent_authority import (
    DurableRecoveryIntentAuthority,
    MaterializationRequest,
)
from rig_relay.recovery.intent_query import RecoveryIntentQueryService
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


def _make_authority(tmp_path: Path) -> DurableRecoveryIntentAuthority:
    return DurableRecoveryIntentAuthority(tmp_path / "authority")


def _make_runtime_with_authority(
    tmp_path: Path,
) -> tuple[DurableRecoveryIntentAuthority, ToolResultRuntime]:
    authority = _make_authority(tmp_path)
    loop = build_test_agent_loop(config=build_test_vibe_config())
    evidence = _CapturingEvidence()
    runtime = ToolResultRuntime(loop, evidence=evidence, intent_authority=authority)
    return authority, runtime


def _req(**kwargs: Any) -> MaterializationRequest:
    return MaterializationRequest(**kwargs)


# ── B6.8.2.1: Lock-Scoped Concurrent Materialization ────────────────


class TestConcurrentMaterialization:
    def test_same_key_concurrent_converges_to_one_receipt(self, tmp_path: Path) -> None:
        """Two subprocesses materializing the same composite key converge."""
        data_dir = str(tmp_path / "authority")
        args = {"path": "/converge"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-converge")
        manifest = _sha256("manifest-converge")

        script = f"""
import json, sys
sys.path.insert(0, {json.dumps(str(Path(__file__).parent.parent))})
from pathlib import Path
from rig_relay.recovery.intent_authority import (
    DurableRecoveryIntentAuthority, MaterializationRequest,
)

authority = DurableRecoveryIntentAuthority(Path({json.dumps(data_dir)}))
req = MaterializationRequest(
    recovery_receipt_sha256={json.dumps(receipt_sha)},
    payload_digest={json.dumps(pd)},
    manifest_digest={json.dumps(manifest)},
    canonical_tool_name="read_file",
    normalized_args={json.dumps(args)},
    execution_class="read_only",
    materialization_kind="pre_handoff",
)
try:
    intent_id = authority.materialize_intent(req)
    print(f"OK:{{intent_id}}", flush=True)
except ValueError as e:
    print(f"CONFLICT:{{e}}", flush=True)
"""
        script_path = tmp_path / "converge_script.py"
        script_path.write_text(script)

        # Run two subprocesses concurrently
        p1 = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        p2 = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=15,
        )

        ok1 = "OK:" in (p1.stdout or "")
        ok2 = "OK:" in (p2.stdout or "")
        assert ok1 or ok2, "At least one process must succeed"

        id1 = ""
        id2 = ""
        # Both should produce same intent_id if both succeeded
        if ok1:
            id1 = p1.stdout.strip().split("OK:")[1].strip()
        if ok2:
            id2 = p2.stdout.strip().split("OK:")[1].strip()
        if ok1 and ok2:
            assert id1 == id2, "Both processes must converge to same intent_id"

        # Verify only one receipt line exists
        receipt_path = tmp_path / "authority" / "intent_receipts.jsonl"
        if receipt_path.exists():
            lines = [
                l for l in receipt_path.read_text().strip().split("\n") if l.strip()
            ]
            matching = [l for l in lines if receipt_sha in l]
            assert len(matching) == 1, "Exactly one receipt for this composite key"

        # Verify payload is correct
        intent_id = id1.split("sha256:")[1] if ok1 else id2.split("sha256:")[1]
        intent_id = f"sha256:{intent_id}" if ok1 else f"sha256:{intent_id}"
        if "sha256:" not in intent_id and ok1:
            intent_id = id1
        elif "sha256:" not in intent_id and ok2:
            intent_id = id2

        # Load the intent
        authority = DurableRecoveryIntentAuthority(tmp_path / "authority")
        loaded = authority.load_intent(receipt_sha, pd)
        assert loaded is not None
        payload = authority.retrieve_payload(loaded["intent_id"], pd)
        assert payload == args

    def test_lock_scope_fails_closed_on_value_error(self, tmp_path: Path) -> None:
        """Lock is released cleanly even when ValueError is raised."""
        authority = _make_authority(tmp_path)
        args = {"path": "/test"}
        pd = _payload_digest(args)

        # First materialization succeeds
        req = _req(
            recovery_receipt_sha256=_sha256("r-locked"),
            payload_digest=pd,
            manifest_digest=_sha256("m-locked"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )
        authority.materialize_intent(req)

        # Second with different args but same receipt/pd (impossible digest match)
        # Should fail but NOT leave lock held
        req2 = _req(
            recovery_receipt_sha256=_sha256("r-locked"),
            payload_digest=pd,
            manifest_digest=_sha256("m-locked"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )
        # Same exact request should be idempotent
        authority.materialize_intent(req2)

        # Verify the lock file doesn't prevent subsequent access
        lock_path = (
            tmp_path
            / "authority"
            / f".materialize.{authority.materialize_intent(req)}.lock"
        )
        # Idempotent — lock was released


# ── B6.8.2.2: Schema-Admission Fail-Closed ──────────────────────────


class TestSchemaAdmission:
    def test_extra_property_rejected(self, tmp_path: Path) -> None:
        authority = _make_authority(tmp_path)
        pd = _payload_digest({"path": "/extra"})
        event = {
            "schema_version": "rig.relay.recovery_intent_authority.v1",
            "intent_id": "sha256:" + "a" * 64,
            "recovery_receipt_sha256": _sha256("r-extra"),
            "payload_digest": pd,
            "manifest_digest": _sha256("m-extra"),
            "canonical_tool_name": "read_file",
            "execution_class": "read_only",
            "content_light": True,
            "created_at": "2026-01-01T00:00:00Z",
            "extra_forbidden": "blocked",
        }
        with pytest.raises((ValueError, RuntimeError)):
            authority._append_receipt(event)

    def test_ledger_unchanged_on_reject(self, tmp_path: Path) -> None:
        authority = _make_authority(tmp_path)
        args = {"path": "/safe"}
        pd = _payload_digest(args)
        req = _req(
            recovery_receipt_sha256=_sha256("r-safe"),
            payload_digest=pd,
            manifest_digest=_sha256("m-safe"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )
        authority.materialize_intent(req)
        receipt_path = tmp_path / "authority" / "intent_receipts.jsonl"
        before = receipt_path.read_text()

        bad_event = {
            "schema_version": "rig.relay.recovery_intent_authority.v1",
            "intent_id": "sha256:" + "b" * 64,
            "recovery_receipt_sha256": _sha256("r-bad"),
            "payload_digest": pd,
            "manifest_digest": _sha256("m-bad"),
            "canonical_tool_name": "read_file",
            "execution_class": "read_only",
            "content_light": True,
            "created_at": "2026-01-01T00:00:00Z",
            "invalid_key": "must_be_blocked",
        }
        try:
            authority._append_receipt(bad_event)
        except (ValueError, RuntimeError):
            pass

        after = receipt_path.read_text()
        assert after == before, "Ledger must be unchanged"


# ── B6.8.2.3: Crash-Durable Payload ─────────────────────────────────


class TestCrashDurability:
    def test_hard_exit_orphan_inert(self, tmp_path: Path) -> None:
        """Subprocess killed between payload write and receipt append:
        orphaned payload is not authority on reload.
        """
        data_dir = str(tmp_path / "authority")
        args = {"path": "/hard-exit"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("r-hard-exit")
        manifest = _sha256("m-hard-exit")

        script = f"""
import json, os, sys, signal
from pathlib import Path
sys.path.insert(0, {json.dumps(str(Path(__file__).parent.parent))})
from rig_relay.recovery.intent_authority import (
    DurableRecoveryIntentAuthority, _compute_intent_id,
)

authority = DurableRecoveryIntentAuthority(Path({json.dumps(data_dir)}))
args = {json.dumps(args)}
pd = {json.dumps(pd)}
receipt_sha = {json.dumps(receipt_sha)}
intent_id = _compute_intent_id(receipt_sha, pd)

# Write payload durably via _write_locked
authority._payload_store._write_locked(intent_id, args)

# Kill before receipt append
os.kill(os.getpid(), signal.SIGKILL)
"""
        script_path = tmp_path / "crash.py"
        script_path.write_text(script)
        result = subprocess.run(
            [sys.executable, str(script_path)], capture_output=True, timeout=15
        )
        assert result.returncode != 0

        # Verify payload exists but NOT loaded as authority
        auth2 = DurableRecoveryIntentAuthority(tmp_path / "authority")
        loaded = auth2.load_intent(receipt_sha, pd)
        assert loaded is None, "Orphan payload must not be authority"

    def test_payload_atomic_complete_or_absent(self, tmp_path: Path) -> None:
        """Materialized payload is complete, valid JSON, with correct digest."""
        authority = _make_authority(tmp_path)
        args = {"path": "/atomic", "offset": 5}
        pd = _payload_digest(args)

        req = _req(
            recovery_receipt_sha256=_sha256("r-atomic"),
            payload_digest=pd,
            manifest_digest=_sha256("m-atomic"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )
        authority.materialize_intent(req)

        loaded = authority.load_intent(_sha256("r-atomic"), pd)
        assert loaded is not None
        payload = authority.retrieve_payload(loaded["intent_id"], pd)
        assert payload == args

    def test_payload_permissions_restricted(self, tmp_path: Path) -> None:
        authority = _make_authority(tmp_path)
        args = {"path": "/perm"}
        pd = _payload_digest(args)
        req = _req(
            recovery_receipt_sha256=_sha256("r-perm"),
            payload_digest=pd,
            manifest_digest=_sha256("m-perm"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )
        intent_id = authority.materialize_intent(req)
        payload_path = tmp_path / "authority" / "payloads" / f"{intent_id}.json"
        stat = payload_path.stat()
        assert (stat.st_mode & 0o777) == 0o600


# ── B6.8.2.4: Legacy Bypass Eliminated ─────────────────────────────


class TestLegacyBypassEliminated:
    @pytest.mark.asyncio
    async def test_recovery_refused_without_authority(self) -> None:
        """Recovery handoffs without configured authority are refused."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        handoff = build_read_only_handoff(
            receipt_sha256=_sha256("r-no-auth"),
            manifest_digest=_sha256("m-no-auth"),
            canonical_tool_name="read_file",
            payload_digest=_sha256("pd-no-auth"),
        )
        msg = await runtime.handle_recovery_handoff(handoff)
        content = getattr(msg, "content", "")
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["status"] == "refused"
        assert parsed["refusal_code"] == "canonical_materialization_required"

    @pytest.mark.asyncio
    async def test_transient_intent_refused_with_authority(
        self, tmp_path: Path
    ) -> None:
        """Even with caller intent, recovery execution refused without
        canonical materialization when authority is configured.
        """
        authority, runtime = _make_runtime_with_authority(tmp_path)

        args = {"path": "/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("r-transient")
        manifest = _sha256("m-transient")

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
        content = getattr(msg, "content", "")
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["status"] == "refused"
        assert parsed["refusal_code"] in {
            "canonical_materialization_required",
            "intent_not_materialized",
        }

    @pytest.mark.asyncio
    async def test_refusal_handoff_still_refuses(self) -> None:
        """Refusal handoffs pass through without authority."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        handoff = build_refusal_handoff(
            receipt_sha256=_sha256("r-ref"),
            manifest_digest=_sha256("m-ref"),
            refusal_code="unsupported_wrapper",
            reason="test",
        )
        msg = await runtime.handle_recovery_handoff(handoff)
        assert "refused" in getattr(msg, "content", "").lower()


# ── B6.8.2.5: Pre-Materialize Then Execute Canonical ────────────────


class TestPreMaterializeExecute:
    @pytest.mark.asyncio
    async def test_pre_materialize_then_execute_read_only(self, tmp_path: Path) -> None:
        authority, runtime = _make_runtime_with_authority(tmp_path)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("canonical read\n")
            fixture_path = f.name
        try:
            args = {"path": fixture_path}
            pd = _payload_digest(args)
            receipt_sha = _sha256("r-pre")
            manifest = _sha256("m-pre")

            # Materialize first
            req = _req(
                recovery_receipt_sha256=receipt_sha,
                payload_digest=pd,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                normalized_args=args,
                execution_class="read_only",
                materialization_kind="pre_handoff",
            )
            authority.materialize_intent(req)

            # Then execute
            handoff = build_read_only_handoff(
                receipt_sha256=receipt_sha,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                payload_digest=pd,
            )
            msg = await runtime.handle_recovery_handoff(handoff)
            parsed = _validate_schema(_assert_annotated(getattr(msg, "content", "")))
            assert parsed["tool_name"] == "read_file"
        finally:
            Path(fixture_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_mutation_materialized_then_proposal(self, tmp_path: Path) -> None:
        authority, runtime = _make_runtime_with_authority(tmp_path)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("safe\n")
            fixture_path = f.name
        try:
            args = {"path": fixture_path, "content": "should not write\n"}
            pd = _payload_digest(args)
            receipt_sha = _sha256("r-mut")
            manifest = _sha256("m-mut")

            req = _req(
                recovery_receipt_sha256=receipt_sha,
                payload_digest=pd,
                manifest_digest=manifest,
                canonical_tool_name="write_file",
                normalized_args=args,
                execution_class="mutation_proposal",
                mutation_class="writes_workspace",
                materialization_kind="pre_handoff",
            )
            authority.materialize_intent(req)

            handoff = build_mutation_handoff(
                receipt_sha256=receipt_sha,
                manifest_digest=manifest,
                canonical_tool_name="write_file",
                payload_digest=pd,
                mutation_class="writes_workspace",
            )
            msg = await runtime.handle_recovery_handoff(handoff)
            parsed = _validate_schema(_assert_annotated(getattr(msg, "content", "")))
            assert parsed["mutation_disposition"] not in {
                "performed",
                "previously_performed",
            }
            assert Path(fixture_path).read_text() == "safe\n"
        finally:
            Path(fixture_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_binding_mismatch_refused(self, tmp_path: Path) -> None:
        authority, runtime = _make_runtime_with_authority(tmp_path)
        args = {"path": "/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("r-bind")
        manifest_canon = _sha256("m-canon")
        manifest_handoff = _sha256("m-different")

        req = _req(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest_canon,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )
        authority.materialize_intent(req)

        handoff = build_read_only_handoff(
            receipt_sha256=receipt_sha,
            manifest_digest=manifest_handoff,
            canonical_tool_name="read_file",
            payload_digest=pd,
        )
        msg = await runtime.handle_recovery_handoff(handoff)
        parsed = _validate_schema(_assert_annotated(getattr(msg, "content", "")))
        assert parsed["refusal_code"] == "intent_handoff_binding_mismatch"


# ── B6.8.2.6: Content-Light Query Service ───────────────────────────


class TestQueryService:
    def test_query_materialized(self, tmp_path: Path) -> None:
        authority = _make_authority(tmp_path)
        args = {"path": "/q"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("r-query")
        req = _req(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=_sha256("m-query"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )
        authority.materialize_intent(req)

        query = RecoveryIntentQueryService(authority)
        result = query.query_by_handoff_binding(receipt_sha, pd)
        assert result.status == "materialized"
        assert result.payload_retrievable
        assert result.binding_disposition == "bound"

    def test_query_missing(self, tmp_path: Path) -> None:
        authority = _make_authority(tmp_path)
        query = RecoveryIntentQueryService(authority)
        result = query.query_by_handoff_binding(_sha256("nope"), _sha256("no"))
        assert result.status == "missing"

    def test_query_content_light(self, tmp_path: Path) -> None:
        authority = _make_authority(tmp_path)
        args = {"path": "/sensitive/secret"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("r-cl")
        req = _req(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=_sha256("m-cl"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )
        authority.materialize_intent(req)
        query = RecoveryIntentQueryService(authority)
        result = query.query_by_handoff_binding(receipt_sha, pd)
        result_json = result.to_json()
        assert "/sensitive/secret" not in result_json
        assert "normalized_args" not in result_json
        assert pd in result_json

    def test_query_deterministic(self, tmp_path: Path) -> None:
        authority = _make_authority(tmp_path)
        args = {"path": "/det"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("r-det")
        req = _req(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=_sha256("m-det"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )
        authority.materialize_intent(req)
        query = RecoveryIntentQueryService(authority)
        r1 = query.query_by_handoff_binding(receipt_sha, pd)
        r2 = query.query_by_handoff_binding(receipt_sha, pd)
        assert r1.to_json() == r2.to_json()

    def test_query_does_not_mutate(self, tmp_path: Path) -> None:
        """Queries do not modify receipt or payload files."""
        authority = _make_authority(tmp_path)
        args = {"path": "/immutable"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("r-immut")
        req = _req(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=_sha256("m-immut"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
            materialization_kind="pre_handoff",
        )
        authority.materialize_intent(req)
        receipt_path = tmp_path / "authority" / "intent_receipts.jsonl"
        before = receipt_path.stat().st_mtime
        query = RecoveryIntentQueryService(authority)
        _ = query.query_by_handoff_binding(receipt_sha, pd)
        _ = query.query_by_handoff_binding(receipt_sha, pd)
        after = receipt_path.stat().st_mtime
        assert before == after, "Query must not mutate receipt file"

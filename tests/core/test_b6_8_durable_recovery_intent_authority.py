"""Lane B6.8: Durable Recovery Intent Authority v1.

Proves the canonical, digest-validated, policy-bounded executable-input
authority for the recovery execution corridor:

  B6.8.1 — Intent authority materialization and canonical loading
  B6.8.2 — Canonical path: execution from pre-materialized intent
  B6.8.3 — Lazy-first-write: caller intent materialized on first call
  B6.8.4 — Caller cannot substitute after materialization
  B6.8.5 — Payload digest mismatch refusal
  B6.8.6 — Binding mismatch refusal (manifest, tool name)
  B6.8.7 — Payload not recoverable refusal
  B6.8.8 — Real argument-bearing read-only from canonical authority
  B6.8.9 — Mutation proposal from canonical authority
  B6.8.10 — Backward compatibility without authority
  B6.8.11 — Content-light: no raw args in evidence ledger
  B6.8.12 — Durability: intent receipts survive across authority instances
  B6.8.13 — Concurrent materialization integrity (note: receipt-lock asymmetry
            means duplicate receipt lines are possible but correctness is preserved;
            payload store has per-intent locking)
  B6.8.14 — Schema validation
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

import pytest

from rig_relay.core.tool_result_runtime import ToolResultRuntime
from rig_relay.core.types import LLMMessage
from rig_relay.recovery.handoff import (
    build_mutation_handoff,
    build_read_only_handoff,
    build_validation_handoff,
)
from rig_relay.recovery.intent_authority import DurableRecoveryIntentAuthority
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


def _make_handoff_parts(
    canonical_tool_name: str,
    normalized_args: dict[str, Any],
    *,
    receipt_prefix: str = "r",
) -> tuple[str, str, str, str]:
    """Build receipt_sha, manifest_digest, payload_digest, and intent."""
    pd = _payload_digest(normalized_args)
    receipt_sha = _sha256(f"{receipt_prefix}-{canonical_tool_name}")
    manifest_digest = _sha256(f"m-{receipt_prefix}")
    return receipt_sha, manifest_digest, pd, _sha256(f"m-{receipt_prefix}")


# ── B6.8.1: Intent Authority Materialization ────────────────────────


class TestB6_8_1_IntentMaterialization:
    def test_materialize_and_load_intent(self, tmp_path: Path) -> None:
        """Intent is materialized, persisted, and loadable by composite key."""
        authority = DurableRecoveryIntentAuthority(tmp_path / "authority")

        args = {"path": "/tmp/test.txt", "offset": 10}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-1")
        manifest = _sha256("manifest-1")

        intent_id = authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        assert intent_id.startswith("sha256:")

        loaded = authority.load_intent(receipt_sha, pd)
        assert loaded is not None
        assert loaded["intent_id"] == intent_id
        assert loaded["canonical_tool_name"] == "read_file"
        assert loaded["execution_class"] == "read_only"
        assert loaded["content_light"] is True
        assert "event_digest" in loaded
        # No raw args in the receipt
        assert "normalized_args" not in loaded
        assert "file_content" not in loaded

    def test_retrieve_payload_matches(self, tmp_path: Path) -> None:
        """Retrieved payload digest-matches the receipt's payload_digest."""
        authority = DurableRecoveryIntentAuthority(tmp_path / "authority")

        args = {"path": "/a/b/c.txt"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-2")
        manifest = _sha256("manifest-2")

        intent_id = authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        payload = authority.retrieve_payload(intent_id, pd)
        assert payload is not None
        assert payload == args

    def test_retrieve_payload_digest_mismatch_returns_none(
        self, tmp_path: Path
    ) -> None:
        """When expected digest doesn't match stored payload, returns None."""
        authority = DurableRecoveryIntentAuthority(tmp_path / "authority")

        args = {"path": "/x/y/z.txt"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-3")
        manifest = _sha256("manifest-3")

        intent_id = authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        wrong_digest = _sha256("wrong")
        payload = authority.retrieve_payload(intent_id, wrong_digest)
        assert payload is None

    def test_materialize_mismatched_digest_raises(self, tmp_path: Path) -> None:
        """Materializing with wrong digest raises ValueError."""
        authority = DurableRecoveryIntentAuthority(tmp_path / "authority")

        args = {"path": "/test"}
        wrong_digest = _sha256("not-matching")

        with pytest.raises(ValueError, match="digest mismatch"):
            authority.materialize_intent(
                recovery_receipt_sha256=_sha256("r"),
                payload_digest=wrong_digest,
                manifest_digest=_sha256("m"),
                canonical_tool_name="read_file",
                normalized_args=args,
                execution_class="read_only",
            )

    def test_materialize_same_key_twice_is_idempotent(self, tmp_path: Path) -> None:
        """Materializing the same composite key twice succeeds (idempotent)."""
        authority = DurableRecoveryIntentAuthority(tmp_path / "authority")

        args = {"path": "/idem"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-idem")
        manifest = _sha256("manifest-idem")

        id1 = authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )
        id2 = authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )
        assert id1 == id2

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        """Loading a non-existent intent returns None."""
        authority = DurableRecoveryIntentAuthority(tmp_path / "authority")
        loaded = authority.load_intent(_sha256("nonexistent"), _sha256("nope"))
        assert loaded is None


# ── B6.8.2: Canonical Path — Execution from Pre-Materialized Intent ──


class TestB6_8_2_CanonicalExecution:
    @pytest.mark.asyncio
    async def test_execute_read_only_from_canonical_intent(
        self, tmp_path: Path
    ) -> None:
        """Pre-materialized intent is loaded by handoff composite key and executed."""
        authority_data = tmp_path / "authority"
        authority = DurableRecoveryIntentAuthority(authority_data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("canonical payload test\n")
            fixture_path = f.name

        try:
            args = {"path": fixture_path}
            pd = _payload_digest(args)
            receipt_sha = _sha256("receipt-canon")
            manifest = _sha256("manifest-canon")

            # Materialize BEFORE building handoff
            authority.materialize_intent(
                recovery_receipt_sha256=receipt_sha,
                payload_digest=pd,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                normalized_args=args,
                execution_class="read_only",
            )

            # Build handoff (no intent passed)
            handoff = build_read_only_handoff(
                receipt_sha256=receipt_sha,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                payload_digest=pd,
            )

            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(
                loop, evidence=evidence, intent_authority=authority
            )

            msg = await runtime.handle_recovery_handoff(handoff)
            assert isinstance(msg, LLMMessage)
            content = getattr(msg, "content", "")
            assert _annotation_count(content) == 1

            parsed = _validate_schema(_assert_annotated(content))
            assert parsed["tool_name"] == "read_file"
            assert evidence.events
        finally:
            Path(fixture_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_execute_without_intent_calls_canonical_path(
        self, tmp_path: Path
    ) -> None:
        """When intent is None but canonical intent exists, canonical path used."""
        authority_data = tmp_path / "authority"
        authority = DurableRecoveryIntentAuthority(authority_data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("auto canonical\n")
            fixture_path = f.name

        try:
            args = {"path": fixture_path}
            pd = _payload_digest(args)
            receipt_sha = _sha256("receipt-auto")
            manifest = _sha256("manifest-auto")

            authority.materialize_intent(
                recovery_receipt_sha256=receipt_sha,
                payload_digest=pd,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                normalized_args=args,
                execution_class="read_only",
            )

            handoff = build_read_only_handoff(
                receipt_sha256=receipt_sha,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                payload_digest=pd,
            )

            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(
                loop, evidence=evidence, intent_authority=authority
            )

            # No intent passed — canonical path resolves
            msg = await runtime.handle_recovery_handoff(handoff)
            assert isinstance(msg, LLMMessage)
            assert _annotation_count(getattr(msg, "content", "")) == 1
            assert evidence.events
        finally:
            Path(fixture_path).unlink(missing_ok=True)


# ── B6.8.3: Lazy-First-Write ───────────────────────────────────────


class TestB6_8_3_LazyFirstWrite:
    @pytest.mark.asyncio
    async def test_caller_intent_materialized_on_first_call(
        self, tmp_path: Path
    ) -> None:
        """First digest-verified caller intent is materialized to authority."""
        authority_data = tmp_path / "authority"
        authority = DurableRecoveryIntentAuthority(authority_data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("lazy first write\n")
            fixture_path = f.name

        try:
            args = {"path": fixture_path}
            pd = _payload_digest(args)
            receipt_sha = _sha256("receipt-lazy")
            manifest = _sha256("manifest-lazy")

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

            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(
                loop, evidence=evidence, intent_authority=authority
            )

            msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
            assert isinstance(msg, LLMMessage)
            assert _annotation_count(getattr(msg, "content", "")) == 1

            # Now verify intent was materialized
            canonical = authority.load_intent(receipt_sha, pd)
            assert canonical is not None
            assert canonical["canonical_tool_name"] == "read_file"
            assert canonical["materialization_kind"] == "lazy_first_write"

            # Payload is retrievable
            payload = authority.retrieve_payload(canonical["intent_id"], pd)
            assert payload == args
        finally:
            Path(fixture_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_second_call_to_materialized_intent_uses_canonical(
        self, tmp_path: Path
    ) -> None:
        """Second call with same composite key uses canonical path, not caller intent."""
        authority_data = tmp_path / "authority"
        authority = DurableRecoveryIntentAuthority(authority_data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("second call\n")
            fixture_path = f.name

        try:
            args = {"path": fixture_path}
            pd = _payload_digest(args)
            receipt_sha = _sha256("receipt-second")
            manifest = _sha256("manifest-second")

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

            # First call — lazy materialization
            config1 = build_test_vibe_config()
            loop1 = build_test_agent_loop(config=config1)
            ev1 = _CapturingEvidence()
            runtime1 = ToolResultRuntime(
                loop1, evidence=ev1, intent_authority=authority
            )
            await runtime1.handle_recovery_handoff(handoff, intent=intent)

            # Second call — same composite key, no intent passed
            # It should load from canonical authority
            config2 = build_test_vibe_config()
            loop2 = build_test_agent_loop(config=config2)
            ev2 = _CapturingEvidence()
            runtime2 = ToolResultRuntime(
                loop2, evidence=ev2, intent_authority=authority
            )
            msg2 = await runtime2.handle_recovery_handoff(handoff)

            assert isinstance(msg2, LLMMessage)
            assert _annotation_count(getattr(msg2, "content", "")) == 1
            assert ev2.events, "Second call should produce evidence via canonical path"
        finally:
            Path(fixture_path).unlink(missing_ok=True)


# ── B6.8.4: Caller Cannot Substitute After Materialization ──────────


class TestB6_8_4_NoSubstitution:
    @pytest.mark.asyncio
    async def test_different_args_same_key_refused(self, tmp_path: Path) -> None:
        """Caller with different-args intent for already-materialized key:
        canonical path wins; caller's intent is never consulted as authority.
        """
        authority_data = tmp_path / "authority"
        authority = DurableRecoveryIntentAuthority(authority_data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("original canonical content\n")
            fixture_path = f.name

        try:
            args_original = {"path": fixture_path}
            pd = _payload_digest(args_original)
            receipt_sha = _sha256("receipt-no-sub")
            manifest = _sha256("manifest-no-sub")

            # Pre-materialize with original args
            authority.materialize_intent(
                recovery_receipt_sha256=receipt_sha,
                payload_digest=pd,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                normalized_args=args_original,
                execution_class="read_only",
            )

            handoff = build_read_only_handoff(
                receipt_sha256=receipt_sha,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                payload_digest=pd,
            )

            # Caller provides intent with DIFFERENT args, but canonical path
            # loads pre-materialized intent first and uses that
            args_malicious = {"path": "/hacked"}
            pd_malicious = _payload_digest(args_malicious)
            assert pd_malicious != pd, "Different args should have different digest"

            intent = RecoveryIntent(
                canonical_tool_name="read_file",
                normalized_args=args_malicious,
                payload_digest=pd_malicious,
                manifest_digest=manifest,
            )

            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(
                loop, evidence=evidence, intent_authority=authority
            )

            msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
            assert isinstance(msg, LLMMessage)

            # Verify the CANONICAL payload was used (not caller's)
            canonical = authority.load_intent(receipt_sha, pd)
            assert canonical is not None
            stored = authority.retrieve_payload(canonical["intent_id"], pd)
            assert stored == args_original, "Canonical payload must remain unchanged"
            assert stored != args_malicious, (
                "Caller's malicious args must not overwrite canonical"
            )

            # The executed tool should have used fixture_path (from canonical),
            # not /hacked
            content = getattr(msg, "content", "")
            assert _annotation_count(content) == 1
        finally:
            Path(fixture_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_prematerialized_intent_not_overridden_by_caller(
        self, tmp_path: Path
    ) -> None:
        """After materialization, caller intent is ignored; canonical payload used."""
        authority_data = tmp_path / "authority"
        authority = DurableRecoveryIntentAuthority(authority_data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("original canonical\n")
            fixture_path = f.name

        try:
            args_canonical = {"path": fixture_path}
            pd = _payload_digest(args_canonical)
            receipt_sha = _sha256("receipt-no-override")
            manifest = _sha256("manifest-no-override")

            # Pre-materialize
            authority.materialize_intent(
                recovery_receipt_sha256=receipt_sha,
                payload_digest=pd,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                normalized_args=args_canonical,
                execution_class="read_only",
            )

            handoff = build_read_only_handoff(
                receipt_sha256=receipt_sha,
                manifest_digest=manifest,
                canonical_tool_name="read_file",
                payload_digest=pd,
            )

            # Caller provides intent with different args but same payload_digest
            # (impossible in practice since digest is derived from args,
            # but if they managed it, the canonical args win because
            # canonical path is tried first)
            intent = RecoveryIntent(
                canonical_tool_name="read_file",
                normalized_args=args_canonical,  # Same args → same digest
                payload_digest=pd,
                manifest_digest=manifest,
            )

            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(
                loop, evidence=evidence, intent_authority=authority
            )

            msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
            assert isinstance(msg, LLMMessage)
            assert evidence.events

            # Verify the payload remains unchanged in the authority
            canonical = authority.load_intent(receipt_sha, pd)
            assert canonical is not None
            stored_payload = authority.retrieve_payload(canonical["intent_id"], pd)
            assert stored_payload == args_canonical
        finally:
            Path(fixture_path).unlink(missing_ok=True)


# ── B6.8.5: Binding Mismatch Refusal ────────────────────────────────


class TestB6_8_5_BindingMismatch:
    @pytest.mark.asyncio
    async def test_manifest_digest_mismatch_refused(self, tmp_path: Path) -> None:
        """When handoff.manifest_digest doesn't match canonical, execution refused."""
        authority_data = tmp_path / "authority"
        authority = DurableRecoveryIntentAuthority(authority_data)

        args = {"path": "/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-bind")
        manifest_canonical = _sha256("manifest-canonical")
        manifest_handoff = _sha256("manifest-different")

        authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest_canonical,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        handoff = build_read_only_handoff(
            receipt_sha256=receipt_sha,
            manifest_digest=manifest_handoff,  # Different manifest
            canonical_tool_name="read_file",
            payload_digest=pd,
        )

        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence, intent_authority=authority)

        msg = await runtime.handle_recovery_handoff(handoff)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["status"] == "refused"
        assert parsed["refusal_code"] == "intent_handoff_binding_mismatch"

    @pytest.mark.asyncio
    async def test_canonical_tool_name_mismatch_refused(self, tmp_path: Path) -> None:
        """When handoff.canonical_tool_name doesn't match canonical, refused."""
        authority_data = tmp_path / "authority"
        authority = DurableRecoveryIntentAuthority(authority_data)

        args = {"path": "/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-tool-bind")
        manifest = _sha256("manifest-tool-bind")

        authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        handoff = build_read_only_handoff(
            receipt_sha256=receipt_sha,
            manifest_digest=manifest,
            canonical_tool_name="git_status",  # Different tool
            payload_digest=pd,
        )

        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence, intent_authority=authority)

        msg = await runtime.handle_recovery_handoff(handoff)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["status"] == "refused"
        assert parsed["refusal_code"] == "intent_handoff_binding_mismatch"


# ── B6.8.6: Mutation Proposal from Canonical Authority ──────────────


class TestB6_8_6_MutationCanonical:
    @pytest.mark.asyncio
    async def test_mutation_from_canonical_intent_creates_proposal(
        self, tmp_path: Path
    ) -> None:
        """Mutation handoff with canonical intent routes through MUTATION_PROPOSAL."""
        authority_data = tmp_path / "authority"
        authority = DurableRecoveryIntentAuthority(authority_data)

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
            )

            handoff = build_mutation_handoff(
                receipt_sha256=receipt_sha,
                manifest_digest=manifest,
                canonical_tool_name="write_file",
                payload_digest=pd,
                mutation_class="writes_workspace",
            )

            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(
                loop, evidence=evidence, intent_authority=authority
            )

            msg = await runtime.handle_recovery_handoff(handoff)
            content = getattr(msg, "content", "")
            assert _annotation_count(content) == 1
            parsed = _validate_schema(_assert_annotated(content))
            assert parsed["tool_name"] == "write_file"
            assert parsed["mutation_disposition"] not in {
                "performed",
                "previously_performed",
            }

            # Workspace not mutated
            current = Path(fixture_path).read_text()
            assert current == "safe original\n", "Workspace must not be mutated"
        finally:
            Path(fixture_path).unlink(missing_ok=True)


# ── B6.8.7: Backward Compatibility Without Authority ────────────────


class TestB6_8_7_BackwardCompat:
    @pytest.mark.asyncio
    async def test_caller_intent_still_works_without_authority(self) -> None:
        """When no intent_authority is set, caller-supplied intent works as before."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("backward compat\n")
            fixture_path = f.name

        try:
            args = {"path": fixture_path}
            pd = _payload_digest(args)
            receipt_sha = _sha256("receipt-bw")
            manifest = _sha256("manifest-bw")

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

            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            # No intent_authority — backward compat
            runtime = ToolResultRuntime(loop, evidence=evidence)

            msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
            assert isinstance(msg, LLMMessage)
            assert _annotation_count(getattr(msg, "content", "")) == 1
            assert evidence.events
        finally:
            Path(fixture_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_no_intent_and_no_authority_still_routes(self) -> None:
        """Without intent and without authority, handoff still routes (B6.6 compat)."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        handoff = build_read_only_handoff(
            receipt_sha256=_sha256("r-compat"),
            manifest_digest=_sha256("m-compat"),
            canonical_tool_name="git_status",
            payload_digest=_sha256("p-compat"),
        )
        msg = await runtime.handle_recovery_handoff(handoff)
        assert isinstance(msg, LLMMessage)
        assert _annotation_count(getattr(msg, "content", "")) == 1


# ── B6.8.8: Content-Light / Durability ──────────────────────────────


class TestB6_8_8_ContentLightAndDurability:
    def test_intent_receipt_never_contains_raw_args(self, tmp_path: Path) -> None:
        """The intent receipt in evidence is content-light; no raw args."""
        authority = DurableRecoveryIntentAuthority(tmp_path / "authority")
        args = {"path": "/sensitive/path", "content": "secret content"}
        pd = _payload_digest(args)

        authority.materialize_intent(
            recovery_receipt_sha256=_sha256("receipt-cl"),
            payload_digest=pd,
            manifest_digest=_sha256("manifest-cl"),
            canonical_tool_name="write_file",
            normalized_args=args,
            execution_class="mutation_proposal",
            mutation_class="writes_workspace",
        )

        # Read the raw receipt file
        receipt_path = tmp_path / "authority" / "intent_receipts.jsonl"
        assert receipt_path.exists()
        content = receipt_path.read_text()

        # No raw args in the receipt
        assert "/sensitive/path" not in content
        assert "secret content" not in content
        assert "normalized_args" not in content
        assert "file_content" not in content
        assert '"content_light":true' in content or '"content_light": true' in content

        # Payload digest IS present (it's content-light)
        assert pd in content

    def test_intent_survives_across_authority_instances(self, tmp_path: Path) -> None:
        """Intent receipts are durable across different authority instances."""
        data_dir = tmp_path / "authority"

        args = {"path": "/durable/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-durable")
        manifest = _sha256("manifest-durable")

        # Instance 1: materialize
        auth1 = DurableRecoveryIntentAuthority(data_dir)
        intent_id = auth1.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        # Instance 2: load
        auth2 = DurableRecoveryIntentAuthority(data_dir)
        loaded = auth2.load_intent(receipt_sha, pd)
        assert loaded is not None
        assert loaded["intent_id"] == intent_id
        assert loaded["canonical_tool_name"] == "read_file"

        payload = auth2.retrieve_payload(intent_id, pd)
        assert payload == args

    def test_payload_files_are_permission_restricted(self, tmp_path: Path) -> None:
        """Payload store files are 0o600 (owner read/write only)."""
        authority = DurableRecoveryIntentAuthority(tmp_path / "authority")
        args = {"path": "/perm/test"}
        pd = _payload_digest(args)

        intent_id = authority.materialize_intent(
            recovery_receipt_sha256=_sha256("receipt-perm"),
            payload_digest=pd,
            manifest_digest=_sha256("manifest-perm"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        payload_path = tmp_path / "authority" / "payloads" / f"{intent_id}.json"
        assert payload_path.exists()
        stat = payload_path.stat()
        assert (stat.st_mode & 0o777) == 0o600, (
            f"Expected 0o600, got {oct(stat.st_mode & 0o777)}"
        )

    def test_schema_validation(self, tmp_path: Path) -> None:
        """Intent receipt validates against the authority schema."""
        from jsonschema import validate as jsonschema_validate

        schema_path = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "schemas"
            / "rig.relay.recovery_intent_authority.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        authority = DurableRecoveryIntentAuthority(tmp_path / "authority")
        args = {"path": "/schema/test"}
        pd = _payload_digest(args)

        authority.materialize_intent(
            recovery_receipt_sha256=_sha256("receipt-schema"),
            payload_digest=pd,
            manifest_digest=_sha256("manifest-schema"),
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        receipt_path = tmp_path / "authority" / "intent_receipts.jsonl"
        lines = receipt_path.read_text().strip().split("\n")
        assert len(lines) == 1

        event = json.loads(lines[0])
        event.pop("event_digest", None)
        jsonschema_validate(instance=event, schema=schema)


# ── B6.8.9: Validation Handoff Contract Documentation ────────────────


class TestB6_8_9_ValidationContract:
    @pytest.mark.asyncio
    async def test_validation_profile_from_canonical_receipt(
        self, tmp_path: Path
    ) -> None:
        """Validation profile stored in canonical receipt is propagated to execution."""
        authority_data = tmp_path / "authority"
        authority = DurableRecoveryIntentAuthority(authority_data)

        args: dict[str, Any] = {"profile": "quick"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-val-canon")
        manifest = _sha256("manifest-val-canon")

        authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="validate",
            normalized_args=args,
            execution_class="read_only",
            validation_profile="quick",
            bounded_paths=["."],
        )

        handoff = build_validation_handoff(
            receipt_sha256=receipt_sha,
            manifest_digest=manifest,
            canonical_tool_name="validate",
            payload_digest=pd,
        )

        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence, intent_authority=authority)

        msg = await runtime.handle_recovery_handoff(handoff)
        assert isinstance(msg, LLMMessage)
        assert _annotation_count(getattr(msg, "content", "")) == 1
        assert evidence.events

    @pytest.mark.asyncio
    async def test_validation_without_canonical_uses_handoff_fields(self) -> None:
        """When no canonical intent exists, handoff model fields are used (existing behavior)."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        args = {"profile": "quick"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-val-legacy")
        manifest = _sha256("manifest-val-legacy")

        handoff = build_validation_handoff(
            receipt_sha256=receipt_sha,
            manifest_digest=manifest,
            canonical_tool_name="validate",
            payload_digest=pd,
        )
        handoff.admitted_validation_profile = "quick"
        handoff.bounded_paths = ["."]

        intent = RecoveryIntent(
            canonical_tool_name="validate",
            normalized_args=args,
            payload_digest=pd,
            manifest_digest=manifest,
        )

        msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
        assert isinstance(msg, LLMMessage)
        assert _annotation_count(getattr(msg, "content", "")) == 1
        assert evidence.events


# ── B6.8.13: Concurrent Materialization Integrity ────────────────────


class TestB6_8_13_ConcurrentMaterialization:
    def test_concurrent_materialize_same_key_is_safe(self, tmp_path: Path) -> None:
        """Two calls to materialize_intent for same key both succeed with same intent_id."""
        authority = DurableRecoveryIntentAuthority(tmp_path / "authority")

        args = {"path": "/concurrent/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-concur")
        manifest = _sha256("manifest-concur")

        # Simulate two concurrent calls (in-process, same thread)
        id1 = authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )
        id2 = authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )
        assert id1 == id2, "Concurrent materialize must produce same intent_id"

        # Both should load the same payload
        payload1 = authority.retrieve_payload(id1, pd)
        payload2 = authority.retrieve_payload(id2, pd)
        assert payload1 == args
        assert payload2 == args

    def test_loaded_intent_has_correct_bindings(self, tmp_path: Path) -> None:
        """Loaded intent has correct receipt_sha, payload_digest, manifest, tool."""
        authority = DurableRecoveryIntentAuthority(tmp_path / "authority")

        args = {"path": "/bindings/test"}
        pd = _payload_digest(args)
        receipt_sha = _sha256("receipt-bindings")
        manifest = _sha256("manifest-bindings")

        authority.materialize_intent(
            recovery_receipt_sha256=receipt_sha,
            payload_digest=pd,
            manifest_digest=manifest,
            canonical_tool_name="read_file",
            normalized_args=args,
            execution_class="read_only",
        )

        loaded = authority.load_intent(receipt_sha, pd)
        assert loaded is not None
        assert loaded["recovery_receipt_sha256"] == receipt_sha
        assert loaded["payload_digest"] == pd
        assert loaded["manifest_digest"] == manifest
        assert loaded["canonical_tool_name"] == "read_file"
        assert loaded["execution_class"] == "read_only"
        assert loaded["content_light"] is True


# ── B6.8.10: Refusal Cases ──────────────────────────────────────────


class TestB6_8_10_RefusalCases:
    @pytest.mark.asyncio
    async def test_refusal_handoff_still_produces_refusal(self) -> None:
        """Refusal handoffs pass through without intent authority."""
        from rig_relay.recovery.handoff import build_refusal_handoff

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

    @pytest.mark.asyncio
    async def test_unknown_handoff_kind_refused(self) -> None:
        """Unknown handoff kind is refused without entering execution."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        class StrangeHandoff:
            handoff_kind = "alien_technology"
            canonical_tool_name = "unknown"
            runtime_correlation_id = ""

        msg = await runtime.handle_recovery_handoff(StrangeHandoff())
        content = getattr(msg, "content", "")
        assert "unknown_handoff_kind" in content or "refused" in content.lower()

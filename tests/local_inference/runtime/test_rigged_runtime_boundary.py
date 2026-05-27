"""Tests for RiggedLocalRuntime X2.3 — evidence, scheduler, cache, secrets, tool proposals, lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.local_inference.runtime._cache_authority import RiggedCacheAuthority
from rig_relay.local_inference.runtime._evidence import (
    EvidenceLedger,
    EvidenceLedgerError,
)
from rig_relay.local_inference.runtime._models import ContextPrivacyClass, TaskKind
from rig_relay.local_inference.runtime._scheduler import (
    RequestState,
    RiggedInferenceScheduler,
)
from rig_relay.local_inference.runtime._secrets import scan_messages_for_secrets
from rig_relay.local_inference.runtime._service import (
    RiggedLocalRuntime,
    get_runtime,
    reset_runtime,
)


class TestCanonicalEvidence:
    def test_append_with_schema(self, tmp_path: Path) -> None:
        led = EvidenceLedger(
            tmp_path / "t.jsonl",
            {
                "type": "object",
                "required": ["x", "content_light"],
                "properties": {
                    "x": {"type": "integer"},
                    "content_light": {"const": True},
                },
            },
        )
        d = led.append("op1", "ev", {"x": 1, "content_light": True})
        assert d.startswith("sha256:")

    def test_schema_rejection(self, tmp_path: Path) -> None:
        led = EvidenceLedger(
            tmp_path / "t.jsonl",
            {
                "type": "object",
                "required": ["x", "content_light"],
                "properties": {
                    "x": {"type": "integer"},
                    "content_light": {"const": True},
                },
            },
        )
        with pytest.raises(EvidenceLedgerError):
            led.append("op1", "ev", {"x": "bad", "content_light": True})

    def test_idempotent_operation_id(self, tmp_path: Path) -> None:
        led = EvidenceLedger(tmp_path / "t.jsonl")
        d1 = led.append("op1", "ev", {"content_light": True})
        d2 = led.append("op1", "ev", {"content_light": True})
        assert d1 == d2
        assert len(led.reconstruct()) == 1

    def test_digest_chain(self, tmp_path: Path) -> None:
        led = EvidenceLedger(tmp_path / "t.jsonl")
        d1 = led.append("a", "e1", {"n": 1, "content_light": True})
        d2 = led.append("b", "e2", {"n": 2, "content_light": True})
        entries = led.reconstruct()
        assert len(entries) == 2
        assert entries[0]["_digest"] == d1
        assert entries[1]["_prev_digest"] == d1
        assert d1 != d2

    def test_corruption_detection(self, tmp_path: Path) -> None:
        led = EvidenceLedger(tmp_path / "t.jsonl")
        led.append("a", "e1", {"content_light": True})
        with open(tmp_path / "t.jsonl", "a") as f:
            f.write('{"_digest":"bad","_prev_digest":"bad"}\n')
        with pytest.raises(EvidenceLedgerError):
            led.reconstruct()

    def test_duplicate_row_detected(self, tmp_path: Path) -> None:
        led = EvidenceLedger(tmp_path / "t.jsonl")
        led.append("a", "e", {"content_light": True})
        enc = led.append("b", "e", {"content_light": True})
        with open(tmp_path / "t.jsonl", "a") as f:
            import json

            line = json.dumps({
                "_operation_id": "a",
                "_digest": enc,
                "_prev_digest": enc,
                "payload": {},
            })
            f.write(line + "\n")
        with pytest.raises(EvidenceLedgerError):
            led.reconstruct()

    def test_operation_id_missing_rejected(self, tmp_path: Path) -> None:
        led = EvidenceLedger(tmp_path / "t.jsonl")
        with pytest.raises(EvidenceLedgerError):
            led.append("", "ev", {"content_light": True})


class TestScheduler:
    @pytest.mark.asyncio
    async def test_enqueue_admit_complete(self) -> None:
        s = RiggedInferenceScheduler(max_concurrent=1)
        req = await s.enqueue(TaskKind.CHAT, [{"role": "user", "content": "hi"}])
        assert req.state == RequestState.QUEUED
        assert s.queue_depth == 1

        admitted = await s.admit_next()
        assert admitted is not None
        assert admitted.operation_id == req.operation_id
        assert admitted.state == RequestState.RUNNING

        from rig_relay.local_inference.runtime._models import (
            FinishReason,
            LocalInferenceResponse,
        )

        await s.complete(
            req.operation_id,
            LocalInferenceResponse(content="ok", finish_reason=FinishReason.STOP),
        )
        assert req.state == RequestState.COMPLETED
        assert s.total_processed == 1

    @pytest.mark.asyncio
    async def test_cancel_queued(self) -> None:
        s = RiggedInferenceScheduler()
        req = await s.enqueue(TaskKind.CHAT, [{"role": "user", "content": "hi"}])
        ok = await s.cancel(req.operation_id)
        assert ok
        assert req.state == RequestState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_running(self) -> None:
        s = RiggedInferenceScheduler()
        req = await s.enqueue(TaskKind.CHAT, [{"role": "user", "content": "hi"}])
        await s.admit_next()
        ok = await s.cancel(req.operation_id)
        assert ok
        assert req.state == RequestState.CANCELLED

    @pytest.mark.asyncio
    async def test_max_concurrent_blocks(self) -> None:
        s = RiggedInferenceScheduler(max_concurrent=1)
        await s.enqueue(TaskKind.CHAT, [{"role": "user", "content": "a"}])
        await s.enqueue(TaskKind.CHAT, [{"role": "user", "content": "b"}])
        await s.admit_next()
        assert s.running_count == 1
        assert s.queue_depth == 1

    def test_batching_status_truthful(self) -> None:
        s = RiggedInferenceScheduler()
        assert s.batching_status == "serialized_fallback"


class TestCacheAuthority:
    def test_kv_cache_reuse_not_claimed(self) -> None:
        c = RiggedCacheAuthority()
        assert not c.kv_cache_reuse_enabled

    def test_clear_increments_count(self) -> None:
        c = RiggedCacheAuthority()
        assert c.clear_count == 0

    def test_projection_truthful(self) -> None:
        c = RiggedCacheAuthority()
        proj = c.build_projection()
        assert proj["cache_capability"]["kv_cache_reuse"] == "not_implemented"


class TestSecrets:
    def test_detects_api_key(self) -> None:
        r = scan_messages_for_secrets([
            {
                "role": "user",
                "content": "sk-abc123def456ghi789jkl012mno345pqr678stu901vwx",
            }
        ])
        assert r["secrets_detected"]

    def test_clean_content(self) -> None:
        r = scan_messages_for_secrets([{"role": "user", "content": "def foo(): pass"}])
        assert not r["secrets_detected"]

    def test_content_light_result(self) -> None:
        r = scan_messages_for_secrets([
            {"role": "user", "content": "ghp_abcdefghijklmnopqrstuvwxyz1234"}
        ])
        assert r["content_light"]


class TestService:
    def test_runtime_kind(self) -> None:
        rt = RiggedLocalRuntime()
        assert rt.runtime_kind == "rigged_mlx_internal"

    def test_scheduler_accessible(self) -> None:
        rt = RiggedLocalRuntime()
        assert rt.scheduler is not None

    def test_cache_accessible(self) -> None:
        rt = RiggedLocalRuntime()
        assert rt.cache is not None

    def test_projection_has_schema_version(self) -> None:
        rt = RiggedLocalRuntime()
        proj = rt.build_projection()
        assert "schema_version" in proj
        assert "scheduler" in proj
        assert "cache" in proj

    def test_secret_bearing_context_refused(self) -> None:
        rt = RiggedLocalRuntime()
        admission, eff, _ = rt._classify_and_admit(
            TaskKind.CHAT,
            [{"role": "user", "content": "ghp_abcdefghijklmnopqrstuvwxyz1234567890AB"}],
            ContextPrivacyClass.PRIVATE_LOCAL,
        )
        if rt.is_configured:
            assert not admission.admitted
            assert eff == ContextPrivacyClass.SECRET_BEARING

    def test_private_content_admitted(self) -> None:
        rt = RiggedLocalRuntime()
        admission, eff, _ = rt._classify_and_admit(
            TaskKind.CHAT,
            [{"role": "user", "content": "my private code: def foo(): pass"}],
            ContextPrivacyClass.PRIVATE_LOCAL,
        )
        if rt.is_configured:
            assert admission.admitted
            assert eff == ContextPrivacyClass.PRIVATE_LOCAL

    def test_singleton(self) -> None:
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

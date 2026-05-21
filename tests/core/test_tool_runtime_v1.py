"""ToolRuntime v1 — span finalization, envelope propagation, and privacy tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from rig_relay.core.tool_runtime import ToolRuntime
from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeRefusal,
    ToolRuntimeRequest,
    ToolRuntimeResult,
    ToolRuntimeStatus,
)
from rig_relay.core.tool_subprocess import ToolSubprocessResult
from rig_relay.tracing.recorder import TraceRecorder


def _make_request(**kwargs) -> ToolRuntimeRequest:
    defaults = {
        "tool_name": "bash",
        "tool_args": {"command": "echo hi"},
        "tool_call_id": "call-1",
        "session_id": "sess-1",
    }
    defaults.update(kwargs)
    return ToolRuntimeRequest(**defaults)


async def _async_deny() -> tuple[bool, str]:
    return False, "denied"


async def _async_allow() -> tuple[bool, str]:
    return True, ""


def _invoke_returns(model: object):
    async def _gen():
        yield model

    return _gen()


def _invoke_raises(exc: Exception):
    async def _gen():
        raise exc
        yield

    return _gen()


def _invoke_empty():
    async def _gen():
        if False:
            yield

    return _gen()


def _recording_recorder():
    store = MagicMock()
    store.write = MagicMock()
    return TraceRecorder(store), store


class TestSpanFinalization:
    def test_cache_hit_closes_span(self) -> None:
        recorder, store = _recording_recorder()
        rt = ToolRuntime(
            cache_check=lambda t, a: (True, {"cached": "result"}),
            trace_recorder=recorder,
        )
        import asyncio

        result = asyncio.run(rt.execute_one(_make_request()))
        assert result.status == ToolRuntimeStatus.CACHED
        written = [c.args[0] for c in store.write.call_args_list]
        ends = [e for e in written if e.event_kind.value == "span.end"]
        assert len(ends) == 1

    def test_permission_denied_closes_span(self) -> None:
        recorder, store = _recording_recorder()
        rt = ToolRuntime(
            permission_decision=lambda t, a, c: _async_deny(), trace_recorder=recorder
        )
        import asyncio

        result = asyncio.run(rt.execute_one(_make_request()))
        assert result.status == ToolRuntimeStatus.REFUSED
        written = [c.args[0] for c in store.write.call_args_list]
        ends = [e for e in written if e.event_kind.value == "span.end"]
        assert len(ends) == 1

    def test_approval_denied_closes_span(self) -> None:
        recorder, store = _recording_recorder()
        rt = ToolRuntime(
            approval_request=lambda t, a, c: _async_deny(), trace_recorder=recorder
        )
        import asyncio

        result = asyncio.run(rt.execute_one(_make_request()))
        assert result.status == ToolRuntimeStatus.REFUSED
        written = [c.args[0] for c in store.write.call_args_list]
        ends = [e for e in written if e.event_kind.value == "span.end"]
        assert len(ends) == 1

    def test_patch_gate_closes_span(self) -> None:
        recorder, store = _recording_recorder()
        rt = ToolRuntime(
            patch_gate_check=lambda req, ti: "gated", trace_recorder=recorder
        )
        import asyncio

        result = asyncio.run(rt.execute_one(_make_request()))
        assert result.status == ToolRuntimeStatus.REFUSED
        written = [c.args[0] for c in store.write.call_args_list]
        ends = [e for e in written if e.event_kind.value == "span.end"]
        assert len(ends) == 1

    def test_invocation_exception_closes_span(self) -> None:
        recorder, store = _recording_recorder()
        rt = ToolRuntime(
            invoke_tool=lambda a: _invoke_raises(RuntimeError("boom")),
            permission_decision=lambda t, a, c: _async_allow(),
            approval_request=lambda t, a, c: _async_allow(),
            patch_gate_check=lambda tc, ti: None,
            trace_recorder=recorder,
        )
        import asyncio

        result = asyncio.run(rt.execute_one(_make_request()))
        assert result.status == ToolRuntimeStatus.FAILED
        written = [c.args[0] for c in store.write.call_args_list]
        ends = [e for e in written if e.event_kind.value == "span.end"]
        assert len(ends) == 1

    def test_no_result_closes_span(self) -> None:
        recorder, store = _recording_recorder()
        rt = ToolRuntime(
            invoke_tool=lambda a: _invoke_empty(),
            permission_decision=lambda t, a, c: _async_allow(),
            approval_request=lambda t, a, c: _async_allow(),
            patch_gate_check=lambda tc, ti: None,
            trace_recorder=recorder,
        )
        import asyncio

        result = asyncio.run(rt.execute_one(_make_request()))
        assert result.status == ToolRuntimeStatus.FAILED
        written = [c.args[0] for c in store.write.call_args_list]
        ends = [e for e in written if e.event_kind.value == "span.end"]
        assert len(ends) == 1

    def test_success_closes_span(self) -> None:
        recorder, store = _recording_recorder()

        class _Result:
            def model_dump(self, **kwargs):  # type: ignore[no-untyped-def]
                return {"ok": True}

            supervisor_result_envelope = None
            supervisor_result_envelope_sha256 = None
            supervisor_result_classification = None

        rt = ToolRuntime(
            invoke_tool=lambda a: _invoke_returns(_Result()),
            permission_decision=lambda t, a, c: _async_allow(),
            approval_request=lambda t, a, c: _async_allow(),
            patch_gate_check=lambda tc, ti: None,
            trace_recorder=recorder,
        )
        import asyncio

        result = asyncio.run(rt.execute_one(_make_request()))
        assert result.status in {
            ToolRuntimeStatus.COMPLETED,
            ToolRuntimeStatus.DEGRADED,
        }
        written = [c.args[0] for c in store.write.call_args_list]
        ends = [e for e in written if e.event_kind.value == "span.end"]
        assert len(ends) == 1


class TestEnvelopePropagation:
    def test_subprocess_result_carries_classification(self) -> None:
        result = ToolSubprocessResult(
            status="completed",
            exit_code=0,
            supervisor_result_classification="completed",
            supervisor_result_envelope_sha256="sha256:abc123",
        )
        assert result.supervisor_result_classification == "completed"

    def test_subprocess_result_classification_nullable(self) -> None:
        result = ToolSubprocessResult(status="completed", exit_code=0)
        assert result.supervisor_result_classification is None

    def test_tool_runtime_result_carries_envelope_fields(self) -> None:
        result = ToolRuntimeResult.completed(tool_name="bash", tool_call_id="c1")
        assert hasattr(result, "supervisor_result_envelope_sha256")
        assert hasattr(result, "supervisor_result_classification")


class TestToolRuntimePrivacy:
    def test_debug_dict_excludes_raw_output(self) -> None:
        result = ToolRuntimeResult.failed(
            tool_name="bash",
            tool_call_id="c1",
            error_kind="timeout",
            error_message="command timed out",
        )
        d = result.to_debug_dict()
        assert "stdout" not in d
        assert "stderr" not in d
        assert "argv" not in d
        assert "cwd" not in d

    def test_refusal_result_excludes_raw_output(self) -> None:
        result = ToolRuntimeResult.refused(
            tool_name="bash",
            tool_call_id="c1",
            refusal=ToolRuntimeRefusal(
                refusal_code=RefusalCode.APPROVAL_DENIED, message="User said no"
            ),
        )
        d = result.to_debug_dict()
        assert "stdout" not in d

    def test_cached_result_excludes_raw_output(self) -> None:
        result = ToolRuntimeResult.cached_result(
            tool_name="read_file",
            tool_call_id="c1",
            provider_tool_response={"lines": ["a", "b"]},
        )
        d = result.to_debug_dict()
        assert "stdout" not in d


class TestEnvelopeSha:
    def _make_envelope(self, **overrides):
        class _Mock:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

            def model_dump(self, mode=None):
                return self.__dict__

        return _Mock(
            result_id="id-1", state="completed", classification="completed", **overrides
        )

    def test_envelope_sha_format(self) -> None:
        from rig_relay.runtime.supervisor_invoker import _envelope_sha256

        sha = _envelope_sha256(self._make_envelope())
        assert sha.startswith("sha256:")
        assert len(sha) == 71

    def test_same_envelope_same_sha(self) -> None:
        from rig_relay.runtime.supervisor_invoker import _envelope_sha256

        e = self._make_envelope()
        assert _envelope_sha256(e) == _envelope_sha256(e)

    def test_different_envelope_different_sha(self) -> None:
        from rig_relay.runtime.supervisor_invoker import _envelope_sha256

        e1 = self._make_envelope()
        e2 = self._make_envelope()
        e2.__dict__["state"] = "failed"
        assert _envelope_sha256(e1) != _envelope_sha256(e2)

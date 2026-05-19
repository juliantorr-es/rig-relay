from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

from jsonschema import validate
import pytest

from rig_relay.acp._protocol import ProtocolMixin
from rig_relay.acp._refusal_adapter import build_acp_refusal
from rig_relay.acp._session_lifecycle import SessionLifecycleMixin
from rig_relay.acp.acp_agent_loop import VibeAcpAgentLoop
from rig_relay.acp.exceptions import NotImplementedMethodError, RefusalError

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


class _TestProtocolMixin(ProtocolMixin):
    def __init__(self) -> None:
        self.sessions: dict = {}
        self.client = None

    def _find_acp_session_by_vibe_session_id(self, session_id: str) -> None:
        return None

    def _load_session_logging_config(self) -> None:
        return None


class _TestSessionLifecycleMixin(SessionLifecycleMixin):
    def __init__(self) -> None:
        self.sessions: dict = {}
        self.client = None
        self.client_capabilities = None
        self.client_info = None


def _get_refusal(exc_info: pytest.ExceptionInfo[RefusalError]) -> dict:
    assert exc_info.value is not None
    err = cast(RefusalError, exc_info.value)
    assert err.data is not None
    return err.data["refusal"]


class TestAcpInitializeResponse:
    def test_initialize_returns_correct_protocol_version(
        self, acp_agent_loop: VibeAcpAgentLoop
    ):
        from acp import PROTOCOL_VERSION

        resp = asyncio.run(acp_agent_loop.initialize(protocol_version=PROTOCOL_VERSION))
        assert resp.protocol_version == PROTOCOL_VERSION

    def test_initialize_returns_agent_info(self, acp_agent_loop: VibeAcpAgentLoop):
        from acp import PROTOCOL_VERSION

        resp = asyncio.run(acp_agent_loop.initialize(protocol_version=PROTOCOL_VERSION))
        assert resp.agent_info is not None
        assert resp.agent_info.name == "@rig/rig-relay"

    def test_initialize_returns_capabilities(self, acp_agent_loop: VibeAcpAgentLoop):
        from acp import PROTOCOL_VERSION

        resp = asyncio.run(acp_agent_loop.initialize(protocol_version=PROTOCOL_VERSION))
        caps = resp.agent_capabilities
        assert caps is not None
        assert caps.load_session is True
        assert caps.session_capabilities is not None
        assert caps.prompt_capabilities is not None


class TestAcpNewSession:
    def test_new_session_creates_session(self, acp_agent_loop: VibeAcpAgentLoop):
        resp = asyncio.run(
            acp_agent_loop.new_session(cwd=str(Path.cwd()), mcp_servers=[])
        )
        assert resp.session_id is not None
        assert resp.session_id in acp_agent_loop.sessions

    def test_new_session_returns_models_and_modes(
        self, acp_agent_loop: VibeAcpAgentLoop
    ):
        resp = asyncio.run(
            acp_agent_loop.new_session(cwd=str(Path.cwd()), mcp_servers=[])
        )
        assert resp.models is not None
        assert resp.modes is not None

    def test_new_session_returns_config_options(self, acp_agent_loop: VibeAcpAgentLoop):
        resp = asyncio.run(
            acp_agent_loop.new_session(cwd=str(Path.cwd()), mcp_servers=[])
        )
        assert resp.config_options is not None


class TestAcpCancel:
    @pytest.mark.asyncio
    async def test_cancel_drains_tasks(self, acp_agent_loop: VibeAcpAgentLoop):
        resp = await acp_agent_loop.new_session(cwd=str(Path.cwd()), mcp_servers=[])
        session = acp_agent_loop.sessions[resp.session_id]

        async def never_ending() -> None:
            await asyncio.Event().wait()

        task = session.set_prompt_task(never_ending())
        await asyncio.sleep(0)

        await acp_agent_loop.cancel(resp.session_id)
        await asyncio.sleep(0.1)

        assert task.cancelled() or task.done()


class TestAcpAuthenticateRefused:
    def test_authenticate_returns_deferred_refusal(self):
        mixin = _TestProtocolMixin()
        result = asyncio.run(mixin.authenticate("fake_method_id"))
        assert result is not None
        assert result.field_meta is not None
        refusal = result.field_meta["refusal"]
        assert "acp.authenticate.deferred" in refusal["refusal_code"]
        assert refusal["content_light"] is True

    def test_authenticate_refusal_is_schema_valid(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        mixin = _TestProtocolMixin()
        result = asyncio.run(mixin.authenticate("fake_method_id"))
        assert result is not None
        assert result.field_meta is not None
        validate(result.field_meta["refusal"], refusal_schema)


class TestAcpResumeRefused:
    def test_resume_refuses_with_expected_code(self):
        mixin = _TestSessionLifecycleMixin()
        with pytest.raises(RefusalError) as exc_info:
            asyncio.run(mixin.resume_session(cwd="/tmp", session_id="s1"))
        refusal = _get_refusal(exc_info)
        assert refusal["content_light"] is True

    def test_resume_refusal_is_schema_valid(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        mixin = _TestSessionLifecycleMixin()
        with pytest.raises(RefusalError) as exc_info:
            asyncio.run(mixin.resume_session(cwd="/tmp", session_id="s1"))
        validate(_get_refusal(exc_info), refusal_schema)


class TestAcpFsMethodsRefused:
    def test_read_text_file_raises_method_not_found(
        self, acp_agent_loop: VibeAcpAgentLoop
    ):
        from acp import RequestError

        method = getattr(acp_agent_loop, "read_text_file", None)
        if method is not None:
            with pytest.raises((NotImplementedMethodError, RequestError)):
                asyncio.run(method("s1", "/some/path"))

    def test_write_text_file_raises_method_not_found(
        self, acp_agent_loop: VibeAcpAgentLoop
    ):
        from acp import RequestError

        method = getattr(acp_agent_loop, "write_text_file", None)
        if method is not None:
            with pytest.raises((NotImplementedMethodError, RequestError)):
                asyncio.run(method("s1", "/some/path", "content"))


class TestAcpTerminalMethodsRefused:
    def test_create_terminal_raises_method_not_found(
        self, acp_agent_loop: VibeAcpAgentLoop
    ):
        from acp import RequestError

        method = getattr(acp_agent_loop, "create_terminal", None)
        if method is not None:
            with pytest.raises((NotImplementedMethodError, RequestError)):
                asyncio.run(method("s1", []))

    def test_terminal_output_raises_method_not_found(
        self, acp_agent_loop: VibeAcpAgentLoop
    ):
        from acp import RequestError

        method = getattr(acp_agent_loop, "terminal_output", None)
        if method is not None:
            with pytest.raises((NotImplementedMethodError, RequestError)):
                asyncio.run(method("s1", "tid", "data"))

    def test_release_terminal_raises_method_not_found(
        self, acp_agent_loop: VibeAcpAgentLoop
    ):
        from acp import RequestError

        method = getattr(acp_agent_loop, "release_terminal", None)
        if method is not None:
            with pytest.raises((NotImplementedMethodError, RequestError)):
                asyncio.run(method("s1", "tid"))

    def test_wait_for_terminal_exit_raises_method_not_found(
        self, acp_agent_loop: VibeAcpAgentLoop
    ):
        from acp import RequestError

        method = getattr(acp_agent_loop, "wait_for_terminal_exit", None)
        if method is not None:
            with pytest.raises((NotImplementedMethodError, RequestError)):
                asyncio.run(method("s1", "tid"))

    def test_kill_terminal_raises_method_not_found(
        self, acp_agent_loop: VibeAcpAgentLoop
    ):
        from acp import RequestError

        method = getattr(acp_agent_loop, "kill_terminal", None)
        if method is not None:
            with pytest.raises((NotImplementedMethodError, RequestError)):
                asyncio.run(method("s1", "tid"))


class TestAcpUnknownExtMethodRefused:
    def test_unknown_ext_method_raises_refusal_error(self):
        mixin = _TestProtocolMixin()
        with pytest.raises(RefusalError) as exc_info:
            asyncio.run(mixin.ext_method("unknown/method", {}))
        refusal = _get_refusal(exc_info)
        assert refusal["refusal_code"] == "not_implemented_deferred"
        assert refusal["method"] == "unknown/method"

    def test_unknown_ext_method_refusal_is_schema_valid(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        mixin = _TestProtocolMixin()
        with pytest.raises(RefusalError) as exc_info:
            asyncio.run(mixin.ext_method("some/ext", {}))
        validate(_get_refusal(exc_info), refusal_schema)


class TestAcpRefusalSchemaValid:
    def test_build_acp_refusal_is_schema_valid(self):
        refusal_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
        result = build_acp_refusal(
            refusal_code="write_refused",
            reason="not allowed",
            method="prompt",
            trace_id="t1",
            session_id="s1",
        )
        validate(result, refusal_schema)

    def test_refusal_has_surface_acp(self):
        result = build_acp_refusal(
            refusal_code="test_code", reason="reason", method="method"
        )
        assert result["surface"] == "acp"

    def test_refusal_has_content_light_true(self):
        result = build_acp_refusal(
            refusal_code="test_code", reason="reason", method="method"
        )
        assert result["content_light"] is True

    def test_refusal_has_all_required_fields(self):
        result = build_acp_refusal(
            refusal_code="test_code", reason="reason", method="method"
        )
        required = {
            "schema_version",
            "trace_id",
            "session_id",
            "method",
            "refusal_code",
            "reason",
            "content_light",
            "generated_at",
            "surface",
        }
        assert required == set(result.keys())


class TestAcpTraceIdPropagated:
    def test_trace_id_propagated_in_refusal(self):
        result = build_acp_refusal(
            refusal_code="test_code",
            reason="reason",
            method="method",
            trace_id="trace-abc-123",
        )
        assert result["trace_id"] == "trace-abc-123"

    def test_session_id_propagated_in_refusal(self):
        result = build_acp_refusal(
            refusal_code="test_code",
            reason="reason",
            method="method",
            session_id="session-xyz-456",
        )
        assert result["session_id"] == "session-xyz-456"

    def test_empty_trace_id_when_not_provided(self):
        result = build_acp_refusal(
            refusal_code="test_code", reason="reason", method="method"
        )
        assert result["trace_id"] == ""

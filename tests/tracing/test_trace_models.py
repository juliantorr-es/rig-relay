from __future__ import annotations

import json

from rig_relay.tracing.models import (
    RigTraceEvent,
    TraceEventKind,
    TraceStatus,
    new_span_id,
    new_trace_id,
)
from rig_relay.tracing.redaction import sanitize_trace_attributes


class TestRigTraceEvent:
    def test_serializes_json_safe(self) -> None:
        event = RigTraceEvent(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            event_kind=TraceEventKind.span_start,
            name="test.operation",
            status=TraceStatus.ok,
            attributes={"key": "value", "num": 42},
        )
        d = event.to_dict()
        s = json.dumps(d)
        parsed = json.loads(s)
        assert parsed["schema_version"] == "rig.trace_event.v1"
        assert parsed["name"] == "test.operation"
        assert parsed["event_kind"] == "span.start"
        assert parsed["status"] == "ok"

    def test_to_dict_omits_none_fields(self) -> None:
        event = RigTraceEvent(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            event_kind=TraceEventKind.span_event,
            name="minimal",
        )
        d = event.to_dict()
        assert "parent_span_id" not in d
        assert "status" not in d


class TestRedaction:
    def test_token_redacted(self) -> None:
        attrs = {"token": "secret123", "ok": True, "nested": {"auth_token": "xyz"}}
        safe = sanitize_trace_attributes(attrs)
        assert safe["token"] == "<redacted>"
        assert safe["nested"]["auth_token"] == "<redacted>"
        assert safe["ok"] is True

    def test_api_key_redacted(self) -> None:
        attrs = {"api_key": "sk-12345"}
        safe = sanitize_trace_attributes(attrs)
        assert safe["api_key"] == "<redacted>"

    def test_password_redacted(self) -> None:
        attrs = {"password": "hunter2"}
        safe = sanitize_trace_attributes(attrs)
        assert safe["password"] == "<redacted>"

    def test_secret_redacted(self) -> None:
        attrs = {"client_secret": "abc"}
        safe = sanitize_trace_attributes(attrs)
        assert safe["client_secret"] == "<redacted>"

    def test_authorization_redacted(self) -> None:
        attrs = {"authorization": "Bearer xyz"}
        safe = sanitize_trace_attributes(attrs)
        assert safe["authorization"] == "<redacted>"

    def test_long_string_truncated(self) -> None:
        long_str = "A" * 2000
        attrs = {"data": long_str}
        safe = sanitize_trace_attributes(attrs)
        assert len(safe["data"]) < 2000
        assert "truncated" in safe["data"]

    def test_bytes_summarized(self) -> None:
        attrs = {"output": b"hello world " * 50}
        safe = sanitize_trace_attributes(attrs)
        assert "bytes len=" in safe["output"]

    def test_nested_list_redacted(self) -> None:
        attrs = {"items": [{"token": "t1"}, {"ok": "v1"}]}
        safe = sanitize_trace_attributes(attrs)
        assert safe["items"][0]["token"] == "<redacted>"
        assert safe["items"][1]["ok"] == "v1"

    def test_token_present_not_redacted(self) -> None:
        attrs = {"token_present": True, "token_length": 32}
        safe = sanitize_trace_attributes(attrs)
        assert safe["token_present"] is True
        assert safe["token_length"] == 32

    def test_raw_token_not_in_serialization(self) -> None:
        attrs = {"auth": "secret-token-value-12345"}
        event = RigTraceEvent(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            event_kind=TraceEventKind.span_event,
            name="test",
            attributes=attrs,
        )
        safe = sanitize_trace_attributes(event.to_dict())
        s = json.dumps(safe)
        assert "secret-token-value-12345" not in s

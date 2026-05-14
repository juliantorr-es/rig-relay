"""Tests for rig_relay.runtime.execution_request — P2c ExecutionRequest model."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from rig_relay.runtime.execution_request import ExecutionRequest
from rig_relay.runtime.models import RuntimeCapabilityKind

_SAMPLE_KWARGS = {
    "request_id": "req-001",
    "argv": ["pytest", "tests/"],
    "cwd": "/home/user/project",
    "timeout_ms": 30000,
    "purpose": "Run tests",
}


def _request(
    **overrides: str | list[str] | dict[str, str] | int | None,
) -> ExecutionRequest:
    kwargs = dict(_SAMPLE_KWARGS)
    kwargs.update(overrides)
    return ExecutionRequest(**kwargs)


class TestExecutionRequestValidation:
    def test_valid_request(self) -> None:
        req = _request()
        assert req.request_id == "req-001"
        assert req.argv == ["pytest", "tests/"]
        assert req.cwd == "/home/user/project"
        assert req.timeout_ms == 30000
        assert req.purpose == "Run tests"

    def test_unknown_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExecutionRequest(**{**_SAMPLE_KWARGS, "unknown_field": "bad"})

    def test_empty_argv_rejected(self) -> None:
        with pytest.raises(ValidationError, match="argv must be non-empty"):
            _request(argv=[])

    def test_empty_argv_item_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="argv\\[0\\] must be a non-empty string"
        ):
            _request(argv=[""])

    def test_blank_argv_item_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="argv\\[0\\] must be a non-empty string"
        ):
            _request(argv=["   "])

    def test_nonpositive_timeout_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timeout_ms must be positive"):
            _request(timeout_ms=0)

    def test_negative_timeout_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timeout_ms must be positive"):
            _request(timeout_ms=-1)

    def test_empty_cwd_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cwd must be a non-empty string"):
            _request(cwd="")

    def test_blank_cwd_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cwd must be a non-empty string"):
            _request(cwd="   ")


class TestExecutionRequestFingerprint:
    def test_request_sha256_set_on_valid(self) -> None:
        req = _request()
        assert req.request_sha256 is not None
        assert req.request_sha256.startswith("sha256:")
        assert len(req.request_sha256) == 64 + 7  # "sha256:" + 64 hex chars

    def test_identical_content_same_sha256(self) -> None:
        a = _request()
        b = _request()
        assert a.request_sha256 == b.request_sha256

    def test_different_argv_different_sha256(self) -> None:
        a = _request(argv=["pytest"])
        b = _request(argv=["ruff"])
        assert a.request_sha256 != b.request_sha256

    def test_different_timeout_different_sha256(self) -> None:
        a = _request(timeout_ms=10000)
        b = _request(timeout_ms=20000)
        assert a.request_sha256 != b.request_sha256

    def test_request_id_excluded_from_sha256(self) -> None:
        a = _request(request_id="req-a")
        b = _request(request_id="req-b")
        assert a.request_sha256 == b.request_sha256


class TestExecutionRequestSerialization:
    def test_dumps_to_json(self) -> None:
        req = _request()
        dumped = req.model_dump(mode="json")
        assert dumped["schema_version"] == "rig.relay.execution_request.v1"
        assert dumped["argv"] == ["pytest", "tests/"]
        assert dumped["timeout_ms"] == 30000
        assert dumped["request_sha256"].startswith("sha256:")

    def test_round_trip(self) -> None:
        req = _request()
        dumped = req.model_dump(mode="json")
        restored = ExecutionRequest.model_validate(dumped)
        assert restored.request_id == req.request_id
        assert restored.argv == req.argv
        assert restored.request_sha256 == req.request_sha256

    def test_forbidden_fields_not_present(self) -> None:
        req = _request()
        dumped = req.model_dump(mode="json")
        assert "stdout" not in dumped
        assert "stderr" not in dumped
        assert "output" not in dumped
        assert "content" not in dumped
        assert "diff" not in dumped
        assert "shell" not in dumped


class TestExecutionRequestCapabilities:
    def test_default_capabilities_empty(self) -> None:
        req = _request()
        assert req.requested_capabilities == []

    def test_with_capabilities(self) -> None:
        req = _request(
            requested_capabilities=[
                RuntimeCapabilityKind.FILE_READ,
                RuntimeCapabilityKind.VALIDATION,
            ]
        )
        assert RuntimeCapabilityKind.FILE_READ in req.requested_capabilities
        assert RuntimeCapabilityKind.VALIDATION in req.requested_capabilities

    def test_capabilities_round_trip(self) -> None:
        req = _request(requested_capabilities=[RuntimeCapabilityKind.WORKTREE_READ])
        dumped = req.model_dump(mode="json")
        assert dumped["requested_capabilities"] == ["worktree_read"]
        restored = ExecutionRequest.model_validate(dumped)
        assert restored.requested_capabilities == [RuntimeCapabilityKind.WORKTREE_READ]

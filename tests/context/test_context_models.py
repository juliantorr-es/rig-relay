"""Tests for context models — Pydantic validation, enum consistency, JSON round-trips."""

from __future__ import annotations

import json

from pydantic import ValidationError
import pytest

from rig_relay.context.models import (
    CollisionWarning,
    CompressionMode,
    ContextBudget,
    ContextFreshness,
    ContextMode,
    ContextOutput,
    ContextPacket,
    ContextReceipt,
    ContextRequest,
    ContextScope,
    DetailLevel,
    OutputFormat,
    PathRecommendation,
    ReceiptEntry,
    RepoInfo,
    SubsystemEntry,
    SymbolEntry,
)


class TestContextMode:
    def test_all_modes_defined(self) -> None:
        assert ContextMode.MAP == "map"
        assert ContextMode.PACKET == "packet"
        assert ContextMode.HANDOFF == "handoff"
        assert ContextMode.COLLISION == "collision"
        assert ContextMode.SYMBOLS == "symbols"

    def test_five_modes(self) -> None:
        assert len(ContextMode) == 5


class TestCompressionMode:
    def test_none_is_default(self) -> None:
        assert CompressionMode.NONE == "none"


class TestContextRequest:
    def test_minimal_request(self) -> None:
        req = ContextRequest(mode=ContextMode.MAP)
        assert req.mode == ContextMode.MAP
        assert req.schema_version == "rig.context_request.v1"
        assert req.budget.max_tokens == 60000

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ContextRequest.model_validate({"mode": "map", "unknown": "x"})

    def test_invalid_mode_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ContextRequest(mode="invalid")  # type: ignore[arg-type]

    def test_json_round_trip(self) -> None:
        req = ContextRequest(mode=ContextMode.MAP, scope=ContextScope(paths=["src/"]))
        data = json.loads(req.model_dump_json())
        restored = ContextRequest.model_validate(data)
        assert restored.mode == req.mode
        assert restored.scope.paths == ["src/"]


class TestRepoInfo:
    def test_minimal(self) -> None:
        info = RepoInfo(root="/repo", head="abc123", branch="main")
        assert info.root == "/repo"
        assert info.dirty_summary["modified"] == 0

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RepoInfo.model_validate({"root": "/r", "head": "h", "branch": "b", "unknown": "x"})


class TestContextPacket:
    def test_minimal_packet(self) -> None:
        packet = ContextPacket(
            mode=ContextMode.MAP,
            request_sha256="sha256:test",
            repo=RepoInfo(root="/r", head="h", branch="b"),
            summary_text="Test context",
        )
        assert packet.schema_version == "rig.context_packet.v1"
        assert packet.context_id.startswith("ctx_")

    def test_packet_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ContextPacket.model_validate({
                "mode": "map",
                "request_sha256": "s",
                "repo": {"root": "/r", "head": "h", "branch": "b"},
                "summary_text": "t",
                "unknown": "x",
            })

    def test_packet_json_serializable(self) -> None:
        packet = ContextPacket(
            mode=ContextMode.MAP,
            request_sha256="sha256:t",
            repo=RepoInfo(root="/r", head="h", branch="b"),
            summary_text="Test",
        )
        raw = packet.model_dump_json(exclude_none=True)
        data = json.loads(raw)
        assert data["schema_version"] == "rig.context_packet.v1"
        assert data["mode"] == "map"


class TestContextReceipt:
    def test_minimal_receipt(self) -> None:
        receipt = ContextReceipt(
            context_id="ctx_test",
            mode="map",
            request_sha256="s",
            packet_sha256="s",
        )
        assert receipt.kind == "rig.context.receipt.v1"

    def test_receipt_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ContextReceipt.model_validate({
                "context_id": "c",
                "mode": "map",
                "request_sha256": "s",
                "packet_sha256": "s",
                "unknown": "x",
            })


class TestSubModels:
    def test_subsystem_entry(self) -> None:
        entry = SubsystemEntry(name="core", paths=["core/main.py"])
        assert entry.name == "core"
        assert len(entry.paths) == 1

    def test_collision_warning(self) -> None:
        warn = CollisionWarning(path="file.py", claimed_by="agent-1")
        assert warn.path == "file.py"

    def test_receipt_entry(self) -> None:
        entry = ReceiptEntry(kind="receipt", path="r.json", sha256="sha256:h")
        assert entry.sha256 == "sha256:h"

    def test_symbol_entry(self) -> None:
        entry = SymbolEntry(name="MyClass", kind="class", paths=["a.py"])
        assert entry.name == "MyClass"

    def test_path_recommendation(self) -> None:
        rec = PathRecommendation(path="docs/README.md", reason="Start here")
        assert rec.path == "docs/README.md"

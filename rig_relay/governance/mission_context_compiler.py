"""Deterministic prototype compiler for mission context packets.

This compiler reads explicit allow-listed sources only. DuckDB remains an
optional future cache/index boundary, not the canonical source of truth.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from rig_relay.governance.mission_context_packet import (
    MissionContextBlocker,
    MissionContextDirtyFileState,
    MissionContextPacket,
    MissionContextPacketReceipt,
    MissionContextRequiredCheck,
    MissionContextSourceRef,
    MissionContextWarning,
    MissionEnvelopeLink,
)
from rig_relay.governance.mission_envelope import MissionEnvelope

_DEFAULT_PACKET_PREFIX = "mission_context_packet"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


class MissionContextCompileBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    message: str
    path: str | None = None


class MissionContextCompilerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet: MissionContextPacket
    receipt: MissionContextPacketReceipt
    blockers: list[MissionContextCompileBlocker]
    warnings: list[str]


def _kind_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".rst", ".txt"}:
        return "doc"
    if suffix == ".json":
        return "schema_or_json"
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".schema":
        return "schema"
    if suffix == ".py":
        return "python"
    return "file"


def _is_within_any_root(path: Path, roots: Sequence[Path]) -> bool:
    candidate = path.resolve()
    for root in roots:
        resolved = root.resolve()
        try:
            candidate.relative_to(resolved)
            return True
        except ValueError:
            continue
    return False


def _iter_allowed_files(
    paths: Iterable[Path], roots: Sequence[Path]
) -> tuple[list[Path], list[MissionContextCompileBlocker]]:
    allowed: list[Path] = []
    blockers: list[MissionContextCompileBlocker] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            blockers.append(
                MissionContextCompileBlocker(
                    kind="missing_source",
                    message=f"Missing source file: {path}",
                    path=str(path),
                )
            )
            continue
        if roots and not _is_within_any_root(path, roots):
            blockers.append(
                MissionContextCompileBlocker(
                    kind="outside_allow_list",
                    message=f"Source path is outside the explicit allow-list: {path}",
                    path=str(path),
                )
            )
            continue
        allowed.append(path)
    return allowed, blockers


def _discover_files_from_roots(roots: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix()):
            if path.is_file():
                files.append(path)
    return files


class MissionContextCompiler:
    """Deterministic prototype compiler for mission context packets."""

    def __init__(
        self,
        *,
        packet_prefix: str = _DEFAULT_PACKET_PREFIX,
        duckdb_cache_path: Path | None = None,
    ) -> None:
        self._packet_prefix = packet_prefix
        self._duckdb_cache_path = duckdb_cache_path

    def compile(
        self,
        mission_envelope: MissionEnvelope,
        *,
        source_paths: Sequence[Path] | None = None,
        source_roots: Sequence[Path] | None = None,
        dirty_file_states: Sequence[MissionContextDirtyFileState] | None = None,
        required_checks: Sequence[MissionContextRequiredCheck] | None = None,
        warnings: Sequence[MissionContextWarning] | None = None,
        blockers: Sequence[MissionContextBlocker] | None = None,
        packet_id: str | None = None,
        created_at: str,
    ) -> MissionContextCompilerResult:
        roots = list(source_roots or [])
        candidates = list(source_paths or [])
        candidates.extend(_discover_files_from_roots(roots))
        allowed_files, path_blockers = _iter_allowed_files(candidates, roots)

        unique_allowed: list[Path] = []
        seen: set[str] = set()
        for path in sorted(allowed_files, key=lambda candidate: candidate.as_posix()):
            key = path.resolve().as_posix()
            if key in seen:
                continue
            seen.add(key)
            unique_allowed.append(path)

        source_refs: list[MissionContextSourceRef] = []
        for path in unique_allowed:
            raw = path.read_bytes()
            source_refs.append(
                MissionContextSourceRef(
                    path=path.as_posix(),
                    sha256=_sha256_bytes(raw),
                    kind=_kind_for_path(path),
                    size_bytes=path.stat().st_size,
                )
            )

        packet = MissionContextPacket(
            packet_id=packet_id
            or f"{self._packet_prefix}-{mission_envelope.mission_id}",
            mission_id=mission_envelope.mission_id,
            title=mission_envelope.title,
            created_at=created_at,
            repo_root=mission_envelope.repo_root,
            branch=mission_envelope.branch,
            head=mission_envelope.head,
            mission_envelope=MissionEnvelopeLink(
                mission_id=mission_envelope.mission_id,
                fingerprint=mission_envelope.fingerprint,
            ),
            source_refs=source_refs,
            dirty_file_states=list(dirty_file_states or []),
            required_checks=list(required_checks or []),
            warnings=[
                *list(warnings or []),
                *[
                    MissionContextWarning(kind=b.kind, message=b.message)
                    for b in path_blockers
                ],
            ],
            blockers=[
                *list(blockers or []),
                *[
                    MissionContextBlocker(kind=b.kind, message=b.message)
                    for b in path_blockers
                ],
            ],
            allowed_paths=[root.as_posix() for root in roots],
            protected_paths=list(mission_envelope.protected_paths),
            instruction_paths=list(mission_envelope.instruction_paths),
            acceptance_checks=list(mission_envelope.acceptance_checks),
            handoff_required=mission_envelope.handoff_required,
        )

        receipt = MissionContextPacketReceipt(
            packet_id=packet.packet_id,
            mission_id=packet.mission_id,
            mission_envelope_sha256=mission_envelope.fingerprint,
            packet_fingerprint=packet.fingerprint,
            packet_sha256=_sha256_json(
                packet.model_dump(mode="json", exclude_none=True)
            ),
            index_backend="python",
            duckdb_cache_path=self._duckdb_cache_path.as_posix()
            if self._duckdb_cache_path
            else None,
            source_ref_count=len(packet.source_refs),
            dirty_file_count=len(packet.dirty_file_states),
            required_check_count=len(packet.required_checks),
            warning_count=len(packet.warnings),
            blocker_count=len(packet.blockers),
            created_at=created_at,
            warnings=[warning.message for warning in packet.warnings],
            blockers=[blocker.message for blocker in packet.blockers],
        )

        return MissionContextCompilerResult(
            packet=packet,
            receipt=receipt,
            blockers=path_blockers,
            warnings=[warning.message for warning in packet.warnings],
        )


__all__ = [
    "MissionContextCompileBlocker",
    "MissionContextCompiler",
    "MissionContextCompilerResult",
]

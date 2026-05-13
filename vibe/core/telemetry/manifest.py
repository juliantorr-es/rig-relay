from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from vibe.core.paths._vibe_home import resolve_evidence_root_resolution
from vibe.core.telemetry.local import dump_canonical_json

_MANIFEST_FILENAME = "manifest.json"
_MANIFEST_SCHEMA_VERSION = "rig.relay.evidence_manifest.v1"


@dataclass(frozen=True, slots=True)
class EvidenceManifestEntry:
    evidence_kind: str
    relative_path: str
    sha256: str
    size_bytes: int
    event_name: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceManifest:
    schema_version: str
    session_id: str
    created_at: str
    evidence_root_mode: str
    evidence_root_source: str
    entries: list[EvidenceManifestEntry]


def _sha256_prefix(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_path(path: Path, session_root: Path) -> str:
    return path.relative_to(session_root).as_posix()


def _make_entry(
    *, path: Path, session_root: Path, evidence_kind: str, event_name: str | None
) -> EvidenceManifestEntry:
    return EvidenceManifestEntry(
        evidence_kind=evidence_kind,
        relative_path=_relative_path(path, session_root),
        sha256=_sha256_prefix(path),
        size_bytes=path.stat().st_size,
        event_name=event_name,
    )


def build_session_manifest(session_root: Path, session_id: str) -> EvidenceManifest:
    session_root = session_root.resolve()
    resolution = resolve_evidence_root_resolution()
    entries: list[EvidenceManifestEntry] = []

    observability = session_root / "observability.jsonl"
    if observability.is_file():
        entries.append(
            _make_entry(
                path=observability,
                session_root=session_root,
                evidence_kind="observability_log",
                event_name=None,
            )
        )

    artifact_dir = session_root / "artifacts" / "tool-results"
    if artifact_dir.exists():
        for artifact in sorted(artifact_dir.glob("*.json")):
            entries.append(
                _make_entry(
                    path=artifact,
                    session_root=session_root,
                    evidence_kind="tool_output_artifact",
                    event_name="rig.relay.artifact.tool_output_written",
                )
            )

    context_dir = session_root / "context"
    if context_dir.exists():
        for report, kind, event_name in (
            (
                "assembly_*.json",
                "context_assembly_report",
                "rig.relay.context.assembly_reported",
            ),
            (
                "layout_*.json",
                "context_layout_plan",
                "rig.relay.context.layout_planned",
            ),
            (
                "shadow_request_*.json",
                "shadow_request_report",
                "rig.relay.context.shadow_request_assembled",
            ),
        ):
            for path in sorted(context_dir.glob(report)):
                entries.append(
                    _make_entry(
                        path=path,
                        session_root=session_root,
                        evidence_kind=kind,
                        event_name=event_name,
                    )
                )

    entries.sort(key=lambda entry: entry.relative_path)
    return EvidenceManifest(
        schema_version=_MANIFEST_SCHEMA_VERSION,
        session_id=session_id,
        created_at=datetime.now(UTC).isoformat(),
        evidence_root_mode=resolution.mode.value,
        evidence_root_source=resolution.source,
        entries=entries,
    )


def manifest_to_dict(manifest: EvidenceManifest) -> dict[str, Any]:
    return {
        "schema_version": manifest.schema_version,
        "session_id": manifest.session_id,
        "created_at": manifest.created_at,
        "evidence_root_mode": manifest.evidence_root_mode,
        "evidence_root_source": manifest.evidence_root_source,
        "entries": [
            {
                "evidence_kind": entry.evidence_kind,
                "relative_path": entry.relative_path,
                "sha256": entry.sha256,
                "size_bytes": entry.size_bytes,
                **({"event_name": entry.event_name} if entry.event_name else {}),
            }
            for entry in manifest.entries
        ],
    }


def build_manifest_bytes(session_root: Path, session_id: str) -> str:
    manifest = build_session_manifest(session_root, session_id)
    return dump_canonical_json(manifest_to_dict(manifest))


def write_session_manifest(session_root: Path, session_id: str) -> Path:
    session_root = session_root.resolve()
    manifest_path = session_root / _MANIFEST_FILENAME
    manifest_text = build_manifest_bytes(session_root, session_id)
    temp_path = manifest_path.with_suffix(".json.tmp")
    temp_path.write_text(manifest_text + "\n", encoding="utf-8")
    temp_path.replace(manifest_path)
    return manifest_path


def load_manifest(session_root: Path) -> dict[str, Any] | None:
    manifest_path = session_root / _MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))

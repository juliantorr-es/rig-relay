"""Context Digester — reads coordination artifacts into structured summaries.

Produces ``ContextDigestionResult`` from the coordination event ledger,
active reservations, conflicts, and release gate status.

Content-light: never includes raw file contents, secrets, private code, or prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from rig_relay.coordination._canonical_json import dump_canonical_json
from rig_relay.coordination.models import (
    CoordinationConflict,
    CoordinationStateProjection,
)
from rig_relay.coordination.store import CoordinationStore


def _git(*args: str, cwd: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], text=True, stderr=subprocess.DEVNULL, cwd=cwd
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _workspace_id(repo_root: str) -> str:
    """Deterministic workspace identity from repo root path."""
    return "sha256:" + hashlib.sha256(repo_root.encode("utf-8")).hexdigest()


@dataclass
class ContextDigestionResult:
    schema_version: str = "rig.relay.context_digestion.v1"
    generated_at: str = ""
    source_commit: str = ""
    workspace_id: str = ""
    active_lane_count: int = 0
    active_lanes: list[dict[str, Any]] = field(default_factory=list)
    owned_paths: list[str] = field(default_factory=list)
    do_not_touch_paths: list[str] = field(default_factory=list)
    recent_conflicts: list[dict[str, Any]] = field(default_factory=list)
    release_gate_status: str = "unknown"
    open_blocker_ids: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    redaction_status: str = "content_light"
    source_event_range: tuple[int, int] = (0, 0)
    digest_sha256: str = ""

    def compute_digest(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "workspace_id": self.workspace_id,
            "active_lane_count": self.active_lane_count,
            "active_lanes": self.active_lanes,
            "owned_paths": sorted(self.owned_paths),
            "do_not_touch_paths": sorted(self.do_not_touch_paths),
            "recent_conflicts": self.recent_conflicts,
            "release_gate_status": self.release_gate_status,
            "open_blocker_ids": sorted(self.open_blocker_ids),
            "evidence_paths": sorted(self.evidence_paths),
            "redaction_status": self.redaction_status,
            "source_event_range": list(self.source_event_range),
        }
        return (
            "sha256:"
            + hashlib.sha256(dump_canonical_json(payload).encode("utf-8")).hexdigest()
        )


class ContextDigester:
    def digest(
        self, store_root: str, repo_root: str, gate_path: str | None = None
    ) -> ContextDigestionResult:
        store_root_path = Path(store_root)

        source_commit = _git("rev-parse", "HEAD", cwd=repo_root) or "unknown"
        workspace = _workspace_id(repo_root)

        active_lanes, owned_paths = self._read_active_lanes(store_root_path)

        min_seq, max_seq = self._event_range(store_root_path)

        gate_status, blocker_ids = self._read_release_gate(gate_path)

        result = ContextDigestionResult(
            generated_at=datetime.now(UTC).isoformat(),
            source_commit=source_commit,
            workspace_id=workspace,
            active_lane_count=len(active_lanes),
            active_lanes=active_lanes,
            owned_paths=sorted(owned_paths),
            do_not_touch_paths=sorted(owned_paths),
            recent_conflicts=self._read_conflicts(store_root_path),
            release_gate_status=gate_status,
            open_blocker_ids=sorted(blocker_ids),
            evidence_paths=sorted(self._collect_evidence_paths(store_root_path)),
            source_event_range=(min_seq, max_seq),
        )
        result.digest_sha256 = result.compute_digest()
        return result

    def _read_active_lanes(
        self, store_root_path: Path
    ) -> tuple[list[dict[str, Any]], set[str]]:
        store = CoordinationStore(store_root_path)
        projection = store.read_state_projection()
        return self._build_lanes(projection)

    def _build_lanes(
        self, projection: CoordinationStateProjection
    ) -> tuple[list[dict[str, Any]], set[str]]:
        lanes: list[dict[str, Any]] = []
        owned: set[str] = set()

        for session_id, session in sorted(projection.active_sessions.items()):
            task_id = session.task_id or ""
            status = session.status
            last_heartbeat = session.updated_at

            reserved: list[str] = list(session.reserved_paths or [])

            for _key, reservation in sorted(
                projection.active_path_reservations.items()
            ):
                if reservation.session_id == session_id:
                    for rpath in reservation.paths:
                        if rpath not in reserved:
                            reserved.append(rpath)

            lanes.append({
                "session_id": session_id,
                "task_id": task_id,
                "status": status,
                "reserved_paths": sorted(reserved),
                "last_heartbeat": last_heartbeat,
            })
            owned.update(reserved)

        return lanes, owned

    def _event_range(self, store_root: Path) -> tuple[int, int]:
        events_path = store_root / "events.jsonl"
        if not events_path.is_file():
            return (0, 0)

        min_seq = None
        max_seq = 0
        try:
            with events_path.open("r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        event = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    seq = event.get("sequence")
                    if isinstance(seq, int):
                        if min_seq is None or seq < min_seq:
                            min_seq = seq
                        max_seq = max(max_seq, seq)
        except OSError:
            return (0, 0)

        return (min_seq or 0, max_seq)

    def _read_conflicts(self, store_root: Path) -> list[dict[str, Any]]:
        conflicts_dir = store_root / "conflicts"
        if not conflicts_dir.is_dir():
            return []

        conflict_entries: list[dict[str, Any]] = []
        for path in sorted(conflicts_dir.glob("*.json")):
            try:
                conflict = CoordinationConflict.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                conflict_entries.append({
                    "conflict_id": conflict.conflict_id,
                    "kind": conflict.kind,
                    "session_id": conflict.session_id,
                    "other_session_id": conflict.other_session_id,
                    "task_id": conflict.task_id,
                    "paths": sorted(conflict.paths),
                    "recommended_resolution": conflict.recommended_resolution,
                    "created_at": conflict.created_at,
                })
            except Exception:
                continue

        conflict_entries.sort(key=lambda c: c.get("created_at", ""), reverse=True)
        return conflict_entries[:50]

    def _read_release_gate(self, gate_path: str | None) -> tuple[str, list[str]]:
        if gate_path is None:
            return ("unknown", [])

        gate_file = Path(gate_path)
        if not gate_file.is_file():
            return ("unknown", [])

        try:
            gate = json.loads(gate_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ("unreadable", [])

        status = gate.get("status", "unknown")
        blockers: list[str] = []
        for blocker in gate.get("blockers", []):
            if isinstance(blocker, dict):
                bid = blocker.get("id", "")
                if bid:
                    blockers.append(bid)
            elif isinstance(blocker, str):
                blockers.append(blocker)

        return (status, blockers)

    def _collect_evidence_paths(self, store_root: Path) -> list[str]:
        artifacts_dir = store_root / "artifacts"
        if not artifacts_dir.is_dir():
            return []

        paths: list[str] = []
        for art_path in sorted(artifacts_dir.glob("*.json"), reverse=True):
            try:
                art = json.loads(art_path.read_text(encoding="utf-8"))
                uri = art.get("artifact_uri")
                if isinstance(uri, str):
                    paths.append(uri)
            except (json.JSONDecodeError, OSError):
                continue

        return paths[:100]


__all__ = ["ContextDigester", "ContextDigestionResult"]

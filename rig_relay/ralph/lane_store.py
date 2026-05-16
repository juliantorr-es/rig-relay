"""Ralph lane store — durable lane persistence.

Protocol, in-memory, and filesystem implementations.
Storage: .rig/ralph/lanes/lane_<lane_id>.json
No git commands, no worktree creation.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from rig_relay.ralph.lane_contracts import RalphLane


@runtime_checkable
class RalphLaneStore(Protocol):
    def save_lane(self, lane: RalphLane) -> Path: ...
    def load_lane(self, lane_id: str) -> RalphLane | None: ...
    def list_lanes(self, status: str | None = None, limit: int = 50) -> list[RalphLane]: ...
    def expire_lane(self, lane_id: str, reason: str) -> None: ...
    def seal_lane(self, lane_id: str, review_bundle_sha256: str) -> RalphLane | None: ...
    def mark_adoption_proposed(self, lane_id: str, proposal_id: str) -> RalphLane | None: ...


class InMemoryRalphLaneStore:
    def __init__(self) -> None:
        self._lanes: dict[str, RalphLane] = {}
        self._current_lane_id: str | None = None

    def save_lane(self, lane: RalphLane) -> Path:
        self._lanes[lane.lane_id] = lane
        return Path(f"/memory/lane_{lane.lane_id}")

    def load_lane(self, lane_id: str) -> RalphLane | None:
        return self._lanes.get(lane_id)

    def list_lanes(self, status: str | None = None, limit: int = 50) -> list[RalphLane]:
        lanes = list(self._lanes.values())
        if status:
            lanes = [l for l in lanes if l.status == status]
        lanes.sort(key=lambda l: l.created_at, reverse=True)
        return lanes[:limit]

    def expire_lane(self, lane_id: str, reason: str) -> None:
        lane = self._lanes.get(lane_id)
        if lane:
            lane.status = "expired"
            lane.updated_at = datetime.now(UTC).isoformat()

    def seal_lane(self, lane_id: str, review_bundle_sha256: str) -> RalphLane | None:
        lane = self._lanes.get(lane_id)
        if lane:
            lane.status = "sealed"
            lane.sealed_at = datetime.now(UTC).isoformat()
            lane.review_bundle_sha256 = review_bundle_sha256
            lane.updated_at = datetime.now(UTC).isoformat()
        return lane

    def mark_adoption_proposed(self, lane_id: str, proposal_id: str) -> RalphLane | None:
        lane = self._lanes.get(lane_id)
        if lane:
            lane.status = "adoption_proposed"
            lane.updated_at = datetime.now(UTC).isoformat()
        return lane

    def count_by_status(self, status: str) -> int:
        return sum(1 for l in self._lanes.values() if l.status == status)


class FilesystemRalphLaneStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or Path(".rig/ralph")).resolve()
        self._lanes_dir = self._root / "lanes"
        self._lanes_dir.mkdir(parents=True, exist_ok=True)

    def save_lane(self, lane: RalphLane) -> Path:
        path = self._lane_path(lane.lane_id)
        self._atomic_write(path, lane.model_dump_json(indent=2))
        return path

    def load_lane(self, lane_id: str) -> RalphLane | None:
        path = self._lane_path(lane_id)
        if not path.is_file():
            return None
        return RalphLane.model_validate_json(path.read_text(encoding="utf-8"))

    def list_lanes(self, status: str | None = None, limit: int = 50) -> list[RalphLane]:
        lanes: list[RalphLane] = []
        if not self._lanes_dir.is_dir():
            return lanes
        for p in sorted(self._lanes_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not p.is_file():
                continue
            try:
                lane = RalphLane.model_validate_json(p.read_text(encoding="utf-8"))
                if status and lane.status != status:
                    continue
                lanes.append(lane)
            except Exception:
                continue
            if len(lanes) >= limit:
                break
        return lanes

    def expire_lane(self, lane_id: str, reason: str) -> None:
        lane = self.load_lane(lane_id)
        if lane:
            lane.status = "expired"
            lane.updated_at = datetime.now(UTC).isoformat()
            self.save_lane(lane)

    def seal_lane(self, lane_id: str, review_bundle_sha256: str) -> RalphLane | None:
        lane = self.load_lane(lane_id)
        if lane:
            lane.status = "sealed"
            lane.sealed_at = datetime.now(UTC).isoformat()
            lane.review_bundle_sha256 = review_bundle_sha256
            lane.updated_at = datetime.now(UTC).isoformat()
            self.save_lane(lane)
        return lane

    def mark_adoption_proposed(self, lane_id: str, proposal_id: str) -> RalphLane | None:
        lane = self.load_lane(lane_id)
        if lane:
            lane.status = "adoption_proposed"
            lane.updated_at = datetime.now(UTC).isoformat()
            self.save_lane(lane)
        return lane

    def _lane_path(self, lane_id: str) -> Path:
        return self._lanes_dir / f"lane_{lane_id}.json"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        tmp = path.with_suffix(f".tmp.{os.getpid()}")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
        finally:
            if tmp.exists():
                tmp.unlink()


__all__ = [
    "FilesystemRalphLaneStore",
    "InMemoryRalphLaneStore",
    "RalphLaneStore",
]

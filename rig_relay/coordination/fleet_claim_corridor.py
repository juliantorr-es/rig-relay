"""Fleet Claim Corridor v0 — content-light file-claim coordination substrate.

Three components (ledger, xattr mirrors, protocol) plus helpers.
Xattrs are projections, NOT authority. The JSONL ledger is canonical.

Usage:
    from rig_relay.coordination.fleet_claim_corridor import FleetClaimProtocol
"""

from __future__ import annotations

import ctypes
import ctypes.util
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any

from pydantic import BaseModel, Field

from rig_relay.coordination._canonical_json import dump_canonical_json

# ── macOS xattr ctypes shim ─────────────────────────────────────────────────

_XATTR_CREATE = 0x0002
_XATTR_REPLACE = 0x0004
_XATTR_MAXSIZE = 65536

_libc_path = ctypes.util.find_library("c")
_libc: ctypes.CDLL | None = None
if _libc_path is not None:
    _libc = ctypes.CDLL(_libc_path, use_errno=True)
    _libc.setxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    _libc.setxattr.restype = ctypes.c_int
    _libc.getxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    _libc.getxattr.restype = ctypes.c_ssize_t
    _libc.removexattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    _libc.removexattr.restype = ctypes.c_int


def _setxattr(path: bytes, name: bytes, value: bytes, flags: int = 0) -> None:
    """Raise OSError on failure."""
    if _libc is None:
        raise OSError("libc not available for xattr operations")
    rc = _libc.setxattr(path, name, value, len(value), 0, flags)
    if rc != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), path.decode())


def _getxattr(path: bytes, name: bytes) -> bytes:
    """Return xattr value bytes, or raise OSError."""
    if _libc is None:
        raise OSError("libc not available for xattr operations")
    buf = ctypes.create_string_buffer(_XATTR_MAXSIZE)
    sz = _libc.getxattr(path, name, buf, _XATTR_MAXSIZE, 0, 0)
    if sz < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), path.decode())
    return buf.raw[:sz]


def _removexattr(path: bytes, name: bytes) -> None:
    """Remove xattr, or raise OSError."""
    if _libc is None:
        raise OSError("libc not available for xattr operations")
    rc = _libc.removexattr(path, name, 0)
    if rc != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), path.decode())


# ── Pydantic models ────────────────────────────────────────────────────────


class FleetClaimEventKind(StrEnum):
    CLAIM_REQUESTED = "claim_requested"
    CLAIM_ACQUIRED = "claim_acquired"
    CLAIM_REFUSED_CONFLICT = "claim_refused_conflict"
    CLAIM_RENEWED = "claim_renewed"
    EDIT_STARTED = "edit_started"
    TESTS_COMPLETED = "tests_completed"
    READY_FOR_INTEGRATION = "ready_for_integration"
    INTEGRATION_ACCEPTED = "integration_accepted"
    INTEGRATION_REFUSED_STALE_BASE = "integration_refused_stale_base"
    CLAIM_RELEASED = "claim_released"
    WORK_PARKED = "work_parked"


class FleetClaimEvent(BaseModel):
    schema_version: str = Field(default="rig.relay.fleet_claim_event.v1", frozen=True)
    event_id: str
    event_kind: FleetClaimEventKind
    mission_id: str
    lane_id: str
    agent_id: str
    claimed_paths: list[str]
    prior_sha256: dict[str, str] | None = None
    timestamp: str
    event_sequence: int = 0
    event_digest: str
    reason: str | None = None


class FleetClaimState(StrEnum):
    CLAIMED = "claimed"
    EDITING = "editing"
    TESTS_RUNNING = "tests_running"
    READY_FOR_INTEGRATION = "ready_for_integration"
    BLOCKED = "blocked"
    RELEASED = "released"


class FleetClaimInfo(BaseModel):
    mission_id: str
    lane_id: str
    agent_id: str
    mode: str = "exclusive_write"
    acquired_at: str
    expires_at: str
    base_sha256: dict[str, str]


class FleetClaimResult(BaseModel):
    acquired: bool
    event: FleetClaimEvent
    reason: str | None = None
    conflicting_claim: FleetClaimInfo | None = None


# ── Static helpers ─────────────────────────────────────────────────────────


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _sha256_event_payload(payload: dict[str, Any]) -> str:
    raw = dump_canonical_json(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ── FleetClaimLedger ───────────────────────────────────────────────────────


class FleetClaimLedger:
    """Append-only JSONL coordination ledger. Canonical authority.

    Location: .rig/relay/fleet/coordination_events.v1.jsonl relative to repo root.
    """

    def __init__(self, ledger_path: Path) -> None:
        self._path = ledger_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.parent / "coordination_events.v1.lock"
        self._lock_path.touch(exist_ok=True)
        self._lock_fd = open(self._lock_path, "r+b")
        self._thread_lock = threading.Lock()

    @staticmethod
    def repo_ledger_path() -> Path:
        return Path(".rig/relay/fleet/coordination_events.v1.jsonl")

    def _next_sequence(self) -> int:
        if not self._path.is_file():
            return 1
        max_seq = 0
        try:
            with self._path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                        seq = parsed.get("event_sequence", 0) or 0
                        max_seq = max(max_seq, seq)
                    except json.JSONDecodeError:
                        pass
        except OSError:
            return 1
        return max_seq + 1

    def _acquire_transition_lock(self) -> None:
        self._thread_lock.acquire()
        fcntl.flock(self._lock_fd, fcntl.LOCK_EX)

    def _release_transition_lock(self) -> None:
        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        self._thread_lock.release()

    def append(self, event: FleetClaimEvent) -> FleetClaimEvent:
        if event.event_sequence == 0:
            event.event_sequence = self._next_sequence()
        if not event.event_digest:
            payload = event.model_dump(exclude={"event_id", "event_digest"})
            event.event_digest = _sha256_event_payload(payload)
        if not event.event_id:
            event.event_id = event.event_digest
        line = dump_canonical_json(event.model_dump(exclude_none=True)) + "\n"
        with self._path.open("a", encoding="utf-8") as f:
            pos_before = f.tell()
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
            pos_after = f.tell()
            expected = len(line.encode("utf-8"))
            actual = pos_after - pos_before
            if actual != expected:
                from rig_relay.core.logger import logger

                logger.error(
                    "fleet claim append truncated: expected=%s actual=%s event_id=%s",
                    expected,
                    actual,
                    event.event_id,
                )
        return event

    def read_all(self) -> list[FleetClaimEvent]:
        events: list[FleetClaimEvent] = []
        if not self._path.is_file():
            return events
        try:
            with self._path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                        events.append(FleetClaimEvent.model_validate(parsed))
                    except (json.JSONDecodeError, ValueError):
                        pass
        except OSError:
            pass
        return events

    def find_active_claim(self, path: str) -> FleetClaimEvent | None:
        events = self.read_all()
        claimed: dict[str, FleetClaimEvent] = {}
        released: set[str] = set()
        for evt in events:
            for p in evt.claimed_paths:
                if evt.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED:
                    claimed[p] = evt
                elif evt.event_kind == FleetClaimEventKind.CLAIM_RELEASED:
                    released.add(p)
        if path in released:
            return None
        return claimed.get(path)


# ── FleetClaimXattr ────────────────────────────────────────────────────────


class FleetClaimXattr:
    """Mirror active claim state onto filesystem objects via macOS xattrs.

    Uses ctypes to call macOS xattr syscalls through libc. No dependency on
    ``os.setxattr`` (which may be missing from some Python builds on macOS).

    XATTRS ARE PROJECTIONS, NOT AUTHORITY.
    The JSONL ledger is canonical. xattrs provide local ergonomics only.
    Missing, truncated, or unreadable xattrs must never invalidate ledger state.
    """

    XATTR_CLAIM = "com.rigrelay.fleet.claim.v1"
    XATTR_STATE = "com.rigrelay.fleet.state.v1"
    XATTR_LAST_FIX = "com.rigrelay.fleet.last_fix.v1"

    @staticmethod
    def write_claim(path: Path, info: FleetClaimInfo) -> None:
        payload = dump_canonical_json(info.model_dump(exclude_none=True)).encode(
            "utf-8"
        )
        try:
            _setxattr(
                str(path).encode("utf-8"),
                FleetClaimXattr.XATTR_CLAIM.encode("utf-8"),
                payload,
            )
        except OSError:
            pass

    @staticmethod
    def read_claim(path: Path) -> FleetClaimInfo | None:
        try:
            raw = _getxattr(
                str(path).encode("utf-8"), FleetClaimXattr.XATTR_CLAIM.encode("utf-8")
            )
        except OSError:
            return None
        try:
            return FleetClaimInfo.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def write_state(path: Path, state: FleetClaimState) -> None:
        try:
            _setxattr(
                str(path).encode("utf-8"),
                FleetClaimXattr.XATTR_STATE.encode("utf-8"),
                state.value.encode("utf-8"),
            )
        except OSError:
            pass

    @staticmethod
    def read_state(path: Path) -> FleetClaimState | None:
        try:
            raw = _getxattr(
                str(path).encode("utf-8"), FleetClaimXattr.XATTR_STATE.encode("utf-8")
            )
        except OSError:
            return None
        try:
            return FleetClaimState(raw.decode("utf-8"))
        except ValueError:
            return None

    @staticmethod
    def write_last_fix(path: Path, event_id: str, invariant: str) -> None:
        payload = json.dumps(
            {"event_id": event_id, "invariant_repaired": invariant},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            _setxattr(
                str(path).encode("utf-8"),
                FleetClaimXattr.XATTR_LAST_FIX.encode("utf-8"),
                payload,
            )
        except OSError:
            pass

    @staticmethod
    def clear_claim_xattrs(path: Path) -> None:
        for attr in (FleetClaimXattr.XATTR_CLAIM, FleetClaimXattr.XATTR_STATE):
            try:
                _removexattr(str(path).encode("utf-8"), attr.encode("utf-8"))
            except OSError:
                pass

    @staticmethod
    def list_claims(root_dir: Path) -> dict[str, FleetClaimInfo]:
        result: dict[str, FleetClaimInfo] = {}
        for dirpath, dirnames, filenames in os.walk(root_dir):
            if ".git" in dirnames:
                dirnames.remove(".git")
            for fname in filenames:
                full = Path(dirpath) / fname
                info = FleetClaimXattr.read_claim(full)
                if info is not None:
                    try:
                        rel = full.relative_to(root_dir).as_posix()
                    except ValueError:
                        rel = full.as_posix()
                    result[rel] = info
        return result


# ── FleetClaimProtocol ─────────────────────────────────────────────────────


class FleetClaimProtocol:
    def __init__(self, ledger: FleetClaimLedger, repo_root: Path) -> None:
        self._ledger = ledger
        self._repo_root = repo_root.resolve()

    def _resolve(self, rel: str) -> Path:
        return (self._repo_root / rel).resolve()

    def _path_rel(self, fpath: Path) -> str:
        try:
            return fpath.relative_to(self._repo_root).as_posix()
        except ValueError:
            return fpath.as_posix()

    def acquire_claim(
        self,
        paths: list[str],
        mission_id: str,
        lane_id: str,
        agent_id: str,
        ttl_minutes: int = 120,
    ) -> FleetClaimResult:
        resolved: dict[str, Path] = {}
        base_sha256: dict[str, str] = {}
        for p in paths:
            rp = self._resolve(p)
            resolved[p] = rp
            if rp.is_file():
                base_sha256[p] = file_sha256(rp)

        self._ledger._acquire_transition_lock()
        try:
            for p in paths:
                active = self._ledger.find_active_claim(p)
                if active is not None:
                    now = _now_iso()
                    refusal = FleetClaimEvent(
                        event_id="",
                        event_kind=FleetClaimEventKind.CLAIM_REFUSED_CONFLICT,
                        mission_id=mission_id,
                        lane_id=lane_id,
                        agent_id=agent_id,
                        claimed_paths=[p],
                        prior_sha256=base_sha256,
                        timestamp=now,
                        event_digest="",
                        reason=f"Path already claimed by {active.lane_id} at {active.timestamp}",
                    )
                    refusal.event_sequence = self._ledger._next_sequence()
                    payload_refusal = refusal.model_dump(
                        exclude={"event_id", "event_digest"}
                    )
                    refusal.event_digest = _sha256_event_payload(payload_refusal)
                    refusal.event_id = refusal.event_digest
                    self._ledger.append(refusal)
                    return FleetClaimResult(
                        acquired=False, event=refusal, reason=refusal.reason
                    )

            now = _now_iso()
            expires = (
                datetime.now(tz=UTC) + timedelta(minutes=ttl_minutes)
            ).isoformat()
            event = FleetClaimEvent(
                event_id="",
                event_kind=FleetClaimEventKind.CLAIM_ACQUIRED,
                mission_id=mission_id,
                lane_id=lane_id,
                agent_id=agent_id,
                claimed_paths=list(paths),
                prior_sha256=base_sha256 if base_sha256 else None,
                timestamp=now,
                event_digest="",
            )
            event.event_sequence = self._ledger._next_sequence()
            payload = event.model_dump(exclude={"event_id", "event_digest"})
            event.event_digest = _sha256_event_payload(payload)
            event.event_id = event.event_digest
            self._ledger.append(event)

            info = FleetClaimInfo(
                mission_id=mission_id,
                lane_id=lane_id,
                agent_id=agent_id,
                acquired_at=now,
                expires_at=expires,
                base_sha256=base_sha256,
            )
            for p in paths:
                rp = resolved[p]
                if rp.is_file():
                    FleetClaimXattr.write_claim(rp, info)
                    FleetClaimXattr.write_state(rp, FleetClaimState.CLAIMED)

            return FleetClaimResult(acquired=True, event=event)
        finally:
            self._ledger._release_transition_lock()

    def release_claim(
        self,
        paths: list[str],
        mission_id: str,
        lane_id: str,
        agent_id: str,
        new_state: FleetClaimState = FleetClaimState.RELEASED,
    ) -> FleetClaimResult:
        self._ledger._acquire_transition_lock()
        try:
            release_notes = [f"Released to state={new_state.value}"]
            for p in paths:
                active = self._ledger.find_active_claim(p)
                if active is None:
                    release_notes.append(f"path={p} had no active claim at release")
                elif active.lane_id != lane_id:
                    release_notes.append(
                        f"path={p} held by lane={active.lane_id}, released by lane={lane_id}"
                    )

            now = _now_iso()
            event = FleetClaimEvent(
                event_id="",
                event_kind=FleetClaimEventKind.CLAIM_RELEASED,
                mission_id=mission_id,
                lane_id=lane_id,
                agent_id=agent_id,
                claimed_paths=list(paths),
                timestamp=now,
                event_digest="",
                reason="; ".join(release_notes),
            )
            event.event_sequence = self._ledger._next_sequence()
            payload = event.model_dump(exclude={"event_id", "event_digest"})
            event.event_digest = _sha256_event_payload(payload)
            event.event_id = event.event_digest
            self._ledger.append(event)

            for p in paths:
                rp = self._resolve(p)
                if rp.is_file():
                    FleetClaimXattr.clear_claim_xattrs(rp)

            return FleetClaimResult(acquired=False, event=event, reason=event.reason)
        finally:
            self._ledger._release_transition_lock()

    def check_stale_base(
        self, paths: list[str], mission_id: str, lane_id: str, agent_id: str
    ) -> dict[str, bool]:
        result: dict[str, bool] = {}
        for p in paths:
            active = self._ledger.find_active_claim(p)
            if active is None or active.prior_sha256 is None:
                result[p] = False
                continue
            rp = self._resolve(p)
            if not rp.is_file():
                result[p] = False
                continue
            claimed_sha = active.prior_sha256.get(p)
            if claimed_sha is None:
                result[p] = False
                continue
            current_sha = file_sha256(rp)
            result[p] = current_sha != claimed_sha
        return result

    def scan_claims(self) -> dict[str, FleetClaimInfo]:
        result: dict[str, FleetClaimInfo] = {}
        events = self._ledger.read_all()
        released: set[str] = set()
        for evt in events:
            for p in evt.claimed_paths:
                if evt.event_kind == FleetClaimEventKind.CLAIM_RELEASED:
                    released.add(p)
        for evt in reversed(events):
            if evt.event_kind != FleetClaimEventKind.CLAIM_ACQUIRED:
                continue
            for p in evt.claimed_paths:
                if p in released or p in result:
                    continue
                rp = self._resolve(p)
                info = FleetClaimXattr.read_claim(rp)
                if info is None and rp.is_file():
                    base = evt.prior_sha256 or {}
                    info = FleetClaimInfo(
                        mission_id=evt.mission_id,
                        lane_id=evt.lane_id,
                        agent_id=evt.agent_id,
                        acquired_at=evt.timestamp,
                        expires_at=_now_iso(),
                        base_sha256=base,
                    )
                if info is not None:
                    result[p] = info
        return result

    def mirror_to_xattrs(self) -> None:
        claims = self.scan_claims()
        for p, info in claims.items():
            rp = self._resolve(p)
            if rp.is_file():
                FleetClaimXattr.write_claim(rp, info)


__all__ = [
    "FleetClaimEvent",
    "FleetClaimEventKind",
    "FleetClaimInfo",
    "FleetClaimLedger",
    "FleetClaimProtocol",
    "FleetClaimResult",
    "FleetClaimState",
    "FleetClaimXattr",
    "_now_iso",
    "file_sha256",
]

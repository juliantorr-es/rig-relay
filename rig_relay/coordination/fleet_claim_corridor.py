"""Fleet Claim Corridor v0 — content-light file-claim coordination substrate.

Three components (ledger, xattr mirrors, protocol) plus helpers.
Xattrs are projections, NOT authority. The JSONL ledger is canonical.

Usage:
    from rig_relay.coordination.fleet_claim_corridor import FleetClaimProtocol
"""

from __future__ import annotations

import ctypes
import ctypes.util
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
    CLAIM_RELEASE_REFUSED = "claim_release_refused"
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
    expires_at: str | None = None
    conflicting_path: str | None = None
    conflicting_mission_id: str | None = None
    conflicting_lane_id: str | None = None
    conflicting_agent_id: str | None = None
    prior_event_digest: str | None = None


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
    expires_at: str | None = None
    base_sha256: dict[str, str]


class FleetClaimResult(BaseModel):
    acquired: bool
    event: FleetClaimEvent | None = None
    reason: str | None = None
    conflicting_claim: FleetClaimInfo | None = None


# ── Static helpers ─────────────────────────────────────────────────────────


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(tz=UTC).isoformat()


def _sha256_event_payload(payload: dict[str, Any]) -> str:
    raw = dump_canonical_json(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ── FleetClaimLedger ───────────────────────────────────────────────────────


_OWNERSHIP_CHANGING_KINDS: frozenset[FleetClaimEventKind] = frozenset({
    FleetClaimEventKind.CLAIM_ACQUIRED,
    FleetClaimEventKind.CLAIM_RELEASED,
})


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

    def _append_under_lock(self, event: FleetClaimEvent) -> FleetClaimEvent:
        """Append event under an already-held transition lock.

        Caller must hold self._thread_lock and fcntl.flock.
        Sequence allocation, digest computation, append, flush, and fsync
        are all serialized here.
        """
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

    def append(self, event: FleetClaimEvent) -> FleetClaimEvent:
        self._acquire_transition_lock()
        try:
            return self._append_under_lock(event)
        finally:
            self._release_transition_lock()

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

    def _fold_claims(self) -> dict[str, FleetClaimEvent]:
        """Canonical event-fold reducer. Returns {path: active_claim_event}.

        Processes events in event_sequence order. CLAIM_ACQUIRED sets the
        active owner. CLAIM_RELEASED removes ownership only when the release
        event's authority (mission_id, lane_id, agent_id) matches the current
        active owner — a mismatched release event is treated as an
        unauthorized observation and does NOT erase ownership.

        All other event kinds (EDIT_STARTED, TESTS_COMPLETED,
        READY_FOR_INTEGRATION, INTEGRATION_REFUSED_STALE_BASE,
        WORK_PARKED, etc.) are non-ownership-changing and are skipped
        during ownership replay.
        """
        events = self.read_all()
        events.sort(key=lambda e: e.event_sequence)
        active: dict[str, FleetClaimEvent] = {}
        for evt in events:
            if evt.event_kind not in _OWNERSHIP_CHANGING_KINDS:
                continue
            for p in evt.claimed_paths:
                if evt.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED:
                    active[p] = evt
                elif evt.event_kind == FleetClaimEventKind.CLAIM_RELEASED:
                    current = active.get(p)
                    if current is not None and (
                        current.mission_id == evt.mission_id
                        and current.lane_id == evt.lane_id
                        and current.agent_id == evt.agent_id
                    ):
                        active.pop(p, None)
        return active

    def active_claims(self) -> dict[str, FleetClaimEvent]:
        return self._fold_claims()

    def find_active_claim(self, path: str) -> FleetClaimEvent | None:
        return self._fold_claims().get(path)


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
        for xattr_name in (FleetClaimXattr.XATTR_CLAIM, FleetClaimXattr.XATTR_STATE):
            try:
                _removexattr(str(path).encode("utf-8"), xattr_name.encode("utf-8"))
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
        resolved = (self._repo_root / rel).resolve()
        repo_str = str(self._repo_root)
        resolved_str = str(resolved)
        if not (resolved_str == repo_str or resolved_str.startswith(repo_str + os.sep)):
            raise ValueError(
                f"Path {rel} resolves to {resolved_str} outside repository root {repo_str}"
            )
        return resolved

    def _path_rel(self, fpath: Path) -> str:
        try:
            return fpath.relative_to(self._repo_root).as_posix()
        except ValueError:
            return fpath.as_posix()

    def _validate_paths(self, paths: list[str]) -> str | None:
        for p in paths:
            try:
                self._resolve(p)
            except ValueError:
                return f"Path {p} resolves outside repository root"
        return None

    def _emit_locked(
        self, event: FleetClaimEvent, *, xattr_fn: Any = None
    ) -> FleetClaimEvent:
        evt = self._ledger._append_under_lock(event)
        if xattr_fn is not None:
            xattr_fn()
        return evt

    def acquire_claim(
        self,
        paths: list[str],
        mission_id: str,
        lane_id: str,
        agent_id: str,
        ttl_minutes: int = 120,
    ) -> FleetClaimResult:
        refusal = self._validate_paths(paths)
        if refusal is not None:
            return FleetClaimResult(acquired=False, reason=refusal)

        resolved: dict[str, Path] = {}
        for p in paths:
            resolved[p] = self._resolve(p)

        self._ledger._acquire_transition_lock()
        try:
            for p in paths:
                active = self._ledger.find_active_claim(p)
                if active is not None:
                    now = _now_iso()
                    refusal_event = FleetClaimEvent(
                        event_id="",
                        event_kind=FleetClaimEventKind.CLAIM_REFUSED_CONFLICT,
                        mission_id=mission_id,
                        lane_id=lane_id,
                        agent_id=agent_id,
                        claimed_paths=[p],
                        timestamp=now,
                        event_digest="",
                        reason=f"Path already claimed by {active.lane_id} at {active.timestamp}",
                    )
                    self._emit_locked(refusal_event)
                    return FleetClaimResult(
                        acquired=False, event=refusal_event, reason=refusal_event.reason
                    )

            base_sha256: dict[str, str] = {}
            for p in paths:
                rp = resolved[p]
                if rp.is_file():
                    base_sha256[p] = file_sha256(rp)

            now = _now_iso()
            from datetime import UTC, datetime, timedelta

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
                expires_at=expires,
            )

            def _xattr_acquire() -> None:
                info = FleetClaimInfo(
                    mission_id=mission_id,
                    lane_id=lane_id,
                    agent_id=agent_id,
                    acquired_at=now,
                    expires_at=expires,
                    base_sha256=base_sha256,
                )
                for p in paths:
                    rp2 = resolved[p]
                    if rp2.is_file():
                        FleetClaimXattr.write_claim(rp2, info)
                        FleetClaimXattr.write_state(rp2, FleetClaimState.CLAIMED)

            self._emit_locked(event, xattr_fn=_xattr_acquire)
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
        refusal = self._validate_paths(paths)
        if refusal is not None:
            return FleetClaimResult(acquired=False, reason=refusal)

        self._ledger._acquire_transition_lock()
        try:
            active_claims = self._ledger.active_claims()
            now = _now_iso()
            for p in paths:
                active = active_claims.get(p)
                if active is None:
                    refusal_event = FleetClaimEvent(
                        event_id="",
                        event_kind=FleetClaimEventKind.CLAIM_RELEASE_REFUSED,
                        mission_id=mission_id,
                        lane_id=lane_id,
                        agent_id=agent_id,
                        claimed_paths=[p],
                        timestamp=now,
                        event_digest="",
                        conflicting_path=p,
                        reason=f"Release refused: path={p} has no active claim",
                    )
                    self._emit_locked(refusal_event)
                    return FleetClaimResult(
                        acquired=False, event=refusal_event, reason=refusal_event.reason
                    )

                if (
                    active.mission_id != mission_id
                    or active.lane_id != lane_id
                    or active.agent_id != agent_id
                ):
                    now = _now_iso()
                    refusal_event = FleetClaimEvent(
                        event_id="",
                        event_kind=FleetClaimEventKind.CLAIM_RELEASE_REFUSED,
                        mission_id=mission_id,
                        lane_id=lane_id,
                        agent_id=agent_id,
                        claimed_paths=[p],
                        timestamp=now,
                        event_digest="",
                        conflicting_path=p,
                        conflicting_mission_id=active.mission_id,
                        conflicting_lane_id=active.lane_id,
                        conflicting_agent_id=active.agent_id,
                        reason=(
                            f"Release refused: path {p} owned by "
                            f"lane={active.lane_id} mission={active.mission_id} "
                            f"agent={active.agent_id}, not by "
                            f"lane={lane_id} mission={mission_id} agent={agent_id}"
                        ),
                    )
                    self._emit_locked(refusal_event)
                    return FleetClaimResult(
                        acquired=False, event=refusal_event, reason=refusal_event.reason
                    )

            now = _now_iso()
            release_notes = [f"Released to state={new_state.value}"]
            for p in paths:
                if active_claims.get(p) is None:
                    release_notes.append(f"path={p} had no active claim at release")

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

            def _xattr_release() -> None:
                for p in paths:
                    rp = self._resolve(p)
                    if rp.is_file():
                        FleetClaimXattr.clear_claim_xattrs(rp)

            self._emit_locked(event, xattr_fn=_xattr_release)
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
        """Return active claims derived entirely from the canonical ledger fold.

        Xattrs are not consulted for authority. Stale or missing xattrs are
        projection-only noise. mirror_to_xattrs() may repair projections.
        """
        result: dict[str, FleetClaimInfo] = {}
        active_claims = self._ledger.active_claims()
        for p, evt in active_claims.items():
            rp = self._resolve(p)
            if rp.is_file():
                base = evt.prior_sha256 or {}
                result[p] = FleetClaimInfo(
                    mission_id=evt.mission_id,
                    lane_id=evt.lane_id,
                    agent_id=evt.agent_id,
                    acquired_at=evt.timestamp,
                    expires_at=evt.expires_at,
                    base_sha256=base,
                )
        return result

    def mirror_to_xattrs(self) -> None:
        claims = self.scan_claims()
        for p, info in claims.items():
            rp = self._resolve(p)
            if rp.is_file():
                FleetClaimXattr.write_claim(rp, info)

    def record_edit_started(
        self, paths: list[str], mission_id: str, lane_id: str, agent_id: str
    ) -> FleetClaimResult:
        return self._record_lifecycle(
            paths=paths,
            mission_id=mission_id,
            lane_id=lane_id,
            agent_id=agent_id,
            event_kind=FleetClaimEventKind.EDIT_STARTED,
            new_state=FleetClaimState.EDITING,
        )

    def record_tests_completed(
        self, paths: list[str], mission_id: str, lane_id: str, agent_id: str
    ) -> FleetClaimResult:
        return self._record_lifecycle(
            paths=paths,
            mission_id=mission_id,
            lane_id=lane_id,
            agent_id=agent_id,
            event_kind=FleetClaimEventKind.TESTS_COMPLETED,
            new_state=FleetClaimState.TESTS_RUNNING,
        )

    def record_ready_for_integration(
        self, paths: list[str], mission_id: str, lane_id: str, agent_id: str
    ) -> FleetClaimResult:
        return self._record_lifecycle(
            paths=paths,
            mission_id=mission_id,
            lane_id=lane_id,
            agent_id=agent_id,
            event_kind=FleetClaimEventKind.READY_FOR_INTEGRATION,
            new_state=FleetClaimState.READY_FOR_INTEGRATION,
        )

    def record_work_parked(
        self, paths: list[str], mission_id: str, lane_id: str, agent_id: str
    ) -> FleetClaimResult:
        return self._record_lifecycle(
            paths=paths,
            mission_id=mission_id,
            lane_id=lane_id,
            agent_id=agent_id,
            event_kind=FleetClaimEventKind.WORK_PARKED,
            new_state=None,
            clear_xattrs=True,
        )

    def record_integration_refused_stale_base(
        self, paths: list[str], mission_id: str, lane_id: str, agent_id: str
    ) -> FleetClaimResult:
        refusal = self._validate_paths(paths)
        if refusal is not None:
            return FleetClaimResult(acquired=False, reason=refusal)

        self._ledger._acquire_transition_lock()
        try:
            stale_result = self.check_stale_base(
                paths=paths, mission_id=mission_id, lane_id=lane_id, agent_id=agent_id
            )
            stale_paths = [p for p, s in stale_result.items() if s]
            if not stale_paths:
                return FleetClaimResult(
                    acquired=True,
                    reason="base not stale — integration refused only when base has changed",
                )

            now = _now_iso()
            event = FleetClaimEvent(
                event_id="",
                event_kind=FleetClaimEventKind.INTEGRATION_REFUSED_STALE_BASE,
                mission_id=mission_id,
                lane_id=lane_id,
                agent_id=agent_id,
                claimed_paths=stale_paths,
                timestamp=now,
                event_digest="",
                reason="stale base detected during integration check",
            )
            self._emit_locked(event)
            return FleetClaimResult(acquired=False, event=event, reason=event.reason)
        finally:
            self._ledger._release_transition_lock()

    def _record_lifecycle(
        self,
        paths: list[str],
        mission_id: str,
        lane_id: str,
        agent_id: str,
        event_kind: FleetClaimEventKind,
        new_state: FleetClaimState | None = None,
        clear_xattrs: bool = False,
    ) -> FleetClaimResult:
        refusal = self._validate_paths(paths)
        if refusal is not None:
            return FleetClaimResult(acquired=False, reason=refusal)

        self._ledger._acquire_transition_lock()
        try:
            for p in paths:
                active = self._ledger.find_active_claim(p)
                if active is None:
                    now = _now_iso()
                    refusal_event = FleetClaimEvent(
                        event_id="",
                        event_kind=FleetClaimEventKind.CLAIM_REFUSED_CONFLICT,
                        mission_id=mission_id,
                        lane_id=lane_id,
                        agent_id=agent_id,
                        claimed_paths=[p],
                        timestamp=now,
                        event_digest="",
                        reason=f"Cannot record {event_kind.value}: path={p} has no active claim",
                    )
                    self._emit_locked(refusal_event)
                    return FleetClaimResult(
                        acquired=False, event=refusal_event, reason=refusal_event.reason
                    )
                if active.lane_id != lane_id:
                    now = _now_iso()
                    refusal_event = FleetClaimEvent(
                        event_id="",
                        event_kind=FleetClaimEventKind.CLAIM_REFUSED_CONFLICT,
                        mission_id=mission_id,
                        lane_id=lane_id,
                        agent_id=agent_id,
                        claimed_paths=[p],
                        timestamp=now,
                        event_digest="",
                        reason=f"Cannot record {event_kind.value}: path={p} owned by lane={active.lane_id}, not lane={lane_id}",
                    )
                    self._emit_locked(refusal_event)
                    return FleetClaimResult(
                        acquired=False, event=refusal_event, reason=refusal_event.reason
                    )

            now = _now_iso()
            event = FleetClaimEvent(
                event_id="",
                event_kind=event_kind,
                mission_id=mission_id,
                lane_id=lane_id,
                agent_id=agent_id,
                claimed_paths=list(paths),
                timestamp=now,
                event_digest="",
            )

            def _xattr_lifecycle() -> None:
                for p in paths:
                    rp = self._resolve(p)
                    if not rp.is_file():
                        continue
                    if clear_xattrs:
                        FleetClaimXattr.clear_claim_xattrs(rp)
                    elif new_state is not None:
                        FleetClaimXattr.write_state(rp, new_state)

            self._emit_locked(event, xattr_fn=_xattr_lifecycle)
            return FleetClaimResult(acquired=True, event=event)
        finally:
            self._ledger._release_transition_lock()


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

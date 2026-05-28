"""Canonical fleet coordination claims module.

Append-only JSONL ledger authority with typed results.
Provides claim acquisition, renewal, lifecycle transitions,
conflict detection, and active-claim projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Literal
import uuid

from jsonschema import validate as jsonschema_validate
from pydantic import BaseModel, ConfigDict, Field

from rig_relay.coordination._canonical_json import dump_canonical_json
from rig_relay.coordination.models import normalize_path
from rig_relay.core.logger import logger

# ── Enumerations ─────────────────────────────────────────────────────────────


class ClaimState(StrEnum):
    claimed = "claimed"
    editing = "editing"
    tests_running = "tests_running"
    ready_for_integration = "ready_for_integration"
    blocked = "blocked"
    released = "released"
    parked = "parked"


class ClaimMode(StrEnum):
    exclusive_write = "exclusive_write"


# ── Canonical event envelope ─────────────────────────────────────────────────


class FleetClaimEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="rig.relay.fleet_coordination_event.v1")
    event_id: str
    claim_id: str
    event_kind: Literal[
        "claim_requested",
        "claim_acquired",
        "claim_refused_conflict",
        "claim_renewed",
        "edit_started",
        "tests_completed",
        "ready_for_integration",
        "integration_accepted",
        "integration_refused_stale_base",
        "claim_released",
        "work_parked",
        "workspace_claim_acquired",
        "workspace_claim_released",
    ]
    mission_id: str
    lane_id: str
    agent_id: str
    workspace_authority_id: str
    claimed_paths: list[str] = Field(default_factory=list)
    base_sha256_by_path: dict[str, str] = Field(default_factory=dict)
    lane_output_sha256_by_path: dict[str, str] | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    event_sequence: int = 0
    prior_event_digest: str | None = None
    event_digest: str = ""
    reason_code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


# ── Projected in-memory types ────────────────────────────────────────────────


@dataclass(frozen=True)
class ActiveClaim:
    claim_id: str
    mission_id: str
    lane_id: str
    agent_id: str
    mode: ClaimMode
    claimed_paths: list[str]
    workspace_authority_id: str
    base_sha256_by_path: dict[str, str]
    lane_output_sha256_by_path: dict[str, str] | None
    acquired_at: str
    expires_at: str
    state: ClaimState
    last_event_id: str
    last_event_kind: str
    reason_code: str | None = None


@dataclass(frozen=True)
class ClaimResult:
    acquired: bool = False
    claim: ActiveClaim | None = None
    event_id: str | None = None
    event_digest: str | None = None
    refusal_reason: str | None = None
    conflict_claim_id: str | None = None
    xattr_status: str = "not_applicable"


# ── Path overlap helpers ─────────────────────────────────────────────────────


def _normalized_paths(paths: list[str]) -> list[str]:
    return [normalize_path(p) for p in paths]


def _paths_conflict(
    proposed: list[str], existing: list[str]
) -> tuple[bool, str | None]:
    for p in proposed:
        for e in existing:
            if p == e:
                return True, "conflict_exact_path"
            if p.startswith(e.rstrip("/") + "/"):
                return True, "conflict_descendant_path"
            if e.startswith(p.rstrip("/") + "/"):
                return True, "conflict_ancestor_path"
    return False, None


# ── FleetClaimStore ──────────────────────────────────────────────────────────


@dataclass
class FleetClaimStore:
    """Canonical fleet claim authority.

    FleetClaimStore is the sole authority for fleet coordination claims.
    It is event-sourced with a JSONL ledger and jsonschema validation.
    fleet_claim_corridor.py is the legacy path; FleetClaimStore supersedes it.
    """

    root: Path

    CANONICAL_AUTHORITY: bool = True
    AUTHORITY_VERSION: str = "rig.relay.fleet_claim_store.v1"

    def authority_manifest(self) -> dict[str, str]:
        return {
            "authority": "canonical",
            "version": self.AUTHORITY_VERSION,
            "root": str(self.root),
            "supersedes": "fleet_claim_corridor.py",
        }

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        lockfile = self.root / "coordination_events.v1.lock"
        lockfile.touch(exist_ok=True)
        self._lock_fd = open(str(lockfile), "r+b")
        self._thread_lock = threading.Lock()
        self._events_path = self.root / "coordination_events.v1.jsonl"
        self._schema: dict[str, Any] | None = None

    def _acquire(self) -> None:
        self._thread_lock.acquire()
        fcntl.flock(self._lock_fd, fcntl.LOCK_EX)

    def _release(self) -> None:
        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        self._thread_lock.release()

    def _load_schema(self) -> dict[str, Any]:
        if self._schema is not None:
            return self._schema
        schema_path = (
            Path(__file__).parents[2]
            / "docs"
            / "schemas"
            / "rig.relay.fleet_coordination_event.v1.schema.json"
        )
        raw = json.loads(schema_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError(
                f"Expected JSON object for schema, got {type(raw).__name__}"
            )
        self._schema = raw
        return self._schema

    def _next_sequence(self) -> int:
        if not self._events_path.is_file():
            return 1
        max_seq = 0
        try:
            with self._events_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                        seq = event.get("event_sequence", 0) or 0
                        max_seq = max(max_seq, seq)
                    except json.JSONDecodeError:
                        pass
        except OSError:
            return 1
        return max_seq + 1

    def _last_event_digest(self) -> str | None:
        if not self._events_path.is_file():
            return None
        last_line = None
        try:
            with self._events_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        last_line = line
        except OSError:
            return None
        if last_line is None:
            return None
        try:
            event = json.loads(last_line)
            return event.get("event_digest")
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _compute_event_digest(event_dict: dict[str, Any]) -> str:
        event_digest_value = event_dict.pop("event_digest", None)
        try:
            canonical = dump_canonical_json(event_dict)
            return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        finally:
            if event_digest_value is not None:
                event_dict["event_digest"] = event_digest_value

    def _append_event(self, event: FleetClaimEvent) -> FleetClaimEvent:
        event_dict = event.model_dump(exclude_none=True)

        schema = self._load_schema()
        try:
            jsonschema_validate(instance=event_dict, schema=schema)
        except Exception as exc:
            raise ValueError(f"Event validation failed: {exc}") from exc

        payload_for_id = {k: v for k, v in event_dict.items() if k != "event_digest"}
        event_id = hashlib.sha256(
            dump_canonical_json(payload_for_id).encode("utf-8")
        ).hexdigest()[:24]
        event.event_id = event_id
        event_dict["event_id"] = event_id

        event.event_sequence = self._next_sequence()
        event_dict["event_sequence"] = event.event_sequence

        prior = self._last_event_digest()
        event.prior_event_digest = prior
        event_dict["prior_event_digest"] = prior

        event_digest = self._compute_event_digest(event_dict)
        event.event_digest = event_digest
        event_dict["event_digest"] = event_digest

        line = dump_canonical_json(event_dict) + "\n"
        with self._events_path.open("a", encoding="utf-8") as f:
            pos_before = f.tell()
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
            pos_after = f.tell()
            expected = len(line.encode("utf-8"))
            actual = pos_after - pos_before
            if actual != expected:
                logger.error(
                    "fleet claims append truncated: expected=%s actual=%s event_id=%s",
                    expected,
                    actual,
                    event.event_id,
                )
                raise OSError(
                    f"Fleet claim event append truncated: expected {expected} bytes, got {actual}"
                )

        return event

    def _write_pointer_artifact(
        self, active: ActiveClaim, coordination_event_id: str
    ) -> Path:
        """Write a content-light claim pointer artifact.

        Called after successful ledger append to provide a fast lookup window
        without replaying the full event log.
        """
        claims_dir = self.root / "claims"
        claims_dir.mkdir(parents=True, exist_ok=True)
        pointer_path = claims_dir / f"{active.claim_id}.json"
        pointer_data = {
            "schema_version": "rig.relay.fleet_claim_pointer.v1",
            "claim_id": active.claim_id,
            "mission_id": active.mission_id,
            "lane_id": active.lane_id,
            "agent_id": active.agent_id,
            "state": active.state.value,
            "claimed_paths_count": len(active.claimed_paths),
            "workspace_authority_id": active.workspace_authority_id,
            "acquired_at": active.acquired_at,
            "expires_at": active.expires_at,
            "coordination_event_id": coordination_event_id,
            "base_sha256_by_path_count": len(active.base_sha256_by_path),
        }
        text = dump_canonical_json(pointer_data)
        pointer_path.write_text(text, encoding="utf-8")
        return pointer_path

    def acquire_workspace_claim(
        self,
        workspace_id: str,
        mission_id: str,
        lane_id: str,
        agent_id: str,
        claimed_paths: list[str],
        workspace_authority_id: str | None = None,
        base_sha256_by_path: dict[str, str] | None = None,
        ttl_seconds: int = 300,
    ) -> ClaimResult:
        normalized = _normalized_paths(claimed_paths)
        authority_id = workspace_authority_id or f"workspace:{workspace_id}"
        base = base_sha256_by_path or {}
        self._acquire()
        try:
            all_active = _replay_active_claims(self._events_path, None)
            for existing in all_active:
                conflicts, reason = _paths_conflict(normalized, existing.claimed_paths)
                if conflicts:
                    refusal_event = FleetClaimEvent(
                        event_id="",
                        claim_id=str(uuid.uuid4()),
                        event_kind="claim_refused_conflict",
                        mission_id=mission_id,
                        lane_id=lane_id,
                        agent_id=agent_id,
                        workspace_authority_id=authority_id,
                        claimed_paths=normalized,
                        base_sha256_by_path=base,
                        reason_code=reason,
                        details={
                            "ttl_seconds": ttl_seconds,
                            "conflict_with": existing.claim_id,
                            "conflict_workspace": existing.workspace_authority_id,
                            "workspace_id": workspace_id,
                        },
                    )
                    result = self._append_event(refusal_event)
                    return ClaimResult(
                        acquired=False,
                        event_id=result.event_id,
                        event_digest=result.event_digest,
                        refusal_reason=reason,
                        conflict_claim_id=existing.claim_id,
                    )

            claim_id = str(uuid.uuid4())
            acquire_event = FleetClaimEvent(
                event_id="",
                claim_id=claim_id,
                event_kind="workspace_claim_acquired",
                mission_id=mission_id,
                lane_id=lane_id,
                agent_id=agent_id,
                workspace_authority_id=authority_id,
                claimed_paths=normalized,
                base_sha256_by_path=base,
                details={
                    "ttl_seconds": ttl_seconds,
                    "mode": "exclusive_write",
                    "workspace_id": workspace_id,
                },
            )
            result = self._append_event(acquire_event)

            expires_at = (
                datetime.now(UTC) + timedelta(seconds=ttl_seconds)
            ).isoformat()
            active = ActiveClaim(
                claim_id=claim_id,
                mission_id=mission_id,
                lane_id=lane_id,
                agent_id=agent_id,
                mode=ClaimMode("exclusive_write"),
                claimed_paths=normalized,
                workspace_authority_id=authority_id,
                base_sha256_by_path=base,
                lane_output_sha256_by_path=None,
                acquired_at=result.timestamp,
                expires_at=expires_at,
                state=ClaimState.claimed,
                last_event_id=result.event_id,
                last_event_kind="workspace_claim_acquired",
            )

            try:
                self._write_pointer_artifact(
                    active=active, coordination_event_id=result.event_id
                )
            except OSError:
                logger.warning(
                    "Pointer artifact write failed for claim_id=%s — claim still valid",
                    claim_id,
                )

            return ClaimResult(
                acquired=True,
                claim=active,
                event_id=result.event_id,
                event_digest=result.event_digest,
            )
        finally:
            self._release()

    def release_workspace_claim(self, claim_id: str) -> ClaimResult:
        self._acquire()
        try:
            active_claims = _replay_active_claims(self._events_path, None)
            existing = next((c for c in active_claims if c.claim_id == claim_id), None)
            if existing is None:
                return ClaimResult(acquired=False, refusal_reason="claim_not_found")

            release_event = FleetClaimEvent(
                event_id="",
                claim_id=claim_id,
                event_kind="workspace_claim_released",
                mission_id=existing.mission_id,
                lane_id=existing.lane_id,
                agent_id=existing.agent_id,
                workspace_authority_id=existing.workspace_authority_id,
                claimed_paths=existing.claimed_paths,
                base_sha256_by_path=existing.base_sha256_by_path,
                lane_output_sha256_by_path=existing.lane_output_sha256_by_path,
                reason_code="explicit_release",
            )
            result = self._append_event(release_event)

            pointer_path = self.root / "claims" / f"{claim_id}.json"
            try:
                if pointer_path.exists():
                    pointer_path.unlink()
            except OSError:
                pass

            return ClaimResult(
                acquired=True,
                event_id=result.event_id,
                event_digest=result.event_digest,
            )
        finally:
            self._release()

    def get_workspace_claims(self, workspace_id: str) -> list[ActiveClaim]:
        self._acquire()
        try:
            authority_id = f"workspace:{workspace_id}"
            return _replay_active_claims(self._events_path, authority_id)
        finally:
            self._release()

    def is_workspace_boundary_claimed(
        self, workspace_id: str, boundary_name: str
    ) -> tuple[bool, str]:
        self._acquire()
        try:
            authority_id = f"workspace:{workspace_id}"
            active_claims = _replay_active_claims(self._events_path, None)
            for claim in active_claims:
                if claim.workspace_authority_id == authority_id:
                    continue
                for path in claim.claimed_paths:
                    if boundary_name in path:
                        return True, claim.claim_id
            return False, ""
        finally:
            self._release()

    def list_integration_boundary_claims(self) -> list[ActiveClaim]:
        _INTEGRATION_PATH_PREFIXES = ("docs/schemas/", "etc/", "rig_relay/desktop/")
        self._acquire()
        try:
            active_claims = _replay_active_claims(self._events_path, None)
            result: list[ActiveClaim] = []
            for claim in active_claims:
                for path in claim.claimed_paths:
                    if path.startswith(_INTEGRATION_PATH_PREFIXES):
                        result.append(claim)
                        break
            return result
        finally:
            self._release()

    def detect_integration_conflict(
        self, workspace_id: str, claimed_paths: list[str]
    ) -> tuple[bool, str, list[str]]:
        normalized = _normalized_paths(claimed_paths)
        self._acquire()
        try:
            authority_id = f"workspace:{workspace_id}"
            active_claims = _replay_active_claims(self._events_path, None)
            for claim in active_claims:
                if claim.workspace_authority_id == authority_id:
                    continue
                conflicts, _ = _paths_conflict(normalized, claim.claimed_paths)
                if conflicts:
                    return True, claim.workspace_authority_id, claim.claimed_paths
            return False, "", []
        finally:
            self._release()


# ── Active claim projection ──────────────────────────────────────────────────


def _event_to_active_claim(
    event: dict[str, Any],
    *,
    expires_at: str | None = None,
    state: ClaimState = ClaimState.claimed,
) -> ActiveClaim:
    ttl_seconds = event.get("details", {}).get("ttl_seconds", 3600)
    acquired_at = event.get("timestamp", "")
    if expires_at is None and acquired_at:
        try:
            acquired_dt = datetime.fromisoformat(acquired_at)
            expires_at = (acquired_dt + timedelta(seconds=ttl_seconds)).isoformat()
        except (ValueError, TypeError):
            expires_at = acquired_at

    return ActiveClaim(
        claim_id=event["claim_id"],
        mission_id=event["mission_id"],
        lane_id=event["lane_id"],
        agent_id=event["agent_id"],
        mode=ClaimMode(event.get("mode", "exclusive_write")),
        claimed_paths=event.get("claimed_paths", []),
        workspace_authority_id=event["workspace_authority_id"],
        base_sha256_by_path=event.get("base_sha256_by_path", {}),
        lane_output_sha256_by_path=event.get("lane_output_sha256_by_path"),
        acquired_at=acquired_at,
        expires_at=expires_at or "",
        state=state,
        last_event_id=event.get("event_id", ""),
        last_event_kind=event.get("event_kind", ""),
        reason_code=event.get("reason_code"),
    )


_TERMINAL_KINDS = frozenset([
    "claim_released",
    "work_parked",
    "workspace_claim_released",
])


def _replay_active_claims(
    events_path: Path, workspace_authority_id: str | None, now: datetime | None = None
) -> list[ActiveClaim]:
    if not events_path.is_file():
        return []

    if now is None:
        now = datetime.now(UTC)

    claims_by_id: dict[str, ActiveClaim] = {}
    terminal_ids: set[str] = set()

    try:
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                claim_id = event.get("claim_id")
                if not claim_id:
                    continue

                workspace_id = event.get("workspace_authority_id", "")
                if (
                    workspace_authority_id is not None
                    and workspace_id != workspace_authority_id
                ):
                    continue

                event_kind = event.get("event_kind")

                if event_kind in {"claim_acquired", "workspace_claim_acquired"}:
                    claims_by_id[claim_id] = _event_to_active_claim(event)
                elif event_kind == "claim_renewed":
                    if claim_id in claims_by_id:
                        ttl_seconds = event.get("details", {}).get("ttl_seconds", 3600)
                        ts = event.get("timestamp", "")
                        try:
                            ts_dt = datetime.fromisoformat(ts)
                            claims_by_id[claim_id] = ActiveClaim(
                                claim_id=claims_by_id[claim_id].claim_id,
                                mission_id=claims_by_id[claim_id].mission_id,
                                lane_id=claims_by_id[claim_id].lane_id,
                                agent_id=claims_by_id[claim_id].agent_id,
                                mode=claims_by_id[claim_id].mode,
                                claimed_paths=claims_by_id[claim_id].claimed_paths,
                                workspace_authority_id=claims_by_id[
                                    claim_id
                                ].workspace_authority_id,
                                base_sha256_by_path=claims_by_id[
                                    claim_id
                                ].base_sha256_by_path,
                                lane_output_sha256_by_path=claims_by_id[
                                    claim_id
                                ].lane_output_sha256_by_path,
                                acquired_at=claims_by_id[claim_id].acquired_at,
                                expires_at=(
                                    ts_dt + timedelta(seconds=ttl_seconds)
                                ).isoformat(),
                                state=ClaimState.claimed,
                                last_event_id=event.get("event_id", ""),
                                last_event_kind="claim_renewed",
                            )
                        except (ValueError, TypeError):
                            pass
                elif event_kind == "edit_started":
                    if claim_id in claims_by_id:
                        claims_by_id[claim_id] = ActiveClaim(
                            claim_id=claims_by_id[claim_id].claim_id,
                            mission_id=claims_by_id[claim_id].mission_id,
                            lane_id=claims_by_id[claim_id].lane_id,
                            agent_id=claims_by_id[claim_id].agent_id,
                            mode=claims_by_id[claim_id].mode,
                            claimed_paths=claims_by_id[claim_id].claimed_paths,
                            workspace_authority_id=claims_by_id[
                                claim_id
                            ].workspace_authority_id,
                            base_sha256_by_path=claims_by_id[
                                claim_id
                            ].base_sha256_by_path,
                            lane_output_sha256_by_path=claims_by_id[
                                claim_id
                            ].lane_output_sha256_by_path,
                            acquired_at=claims_by_id[claim_id].acquired_at,
                            expires_at=claims_by_id[claim_id].expires_at,
                            state=ClaimState.editing,
                            last_event_id=event.get("event_id", ""),
                            last_event_kind="edit_started",
                        )
                elif event_kind == "tests_completed":
                    if claim_id in claims_by_id:
                        claims_by_id[claim_id] = ActiveClaim(
                            claim_id=claims_by_id[claim_id].claim_id,
                            mission_id=claims_by_id[claim_id].mission_id,
                            lane_id=claims_by_id[claim_id].lane_id,
                            agent_id=claims_by_id[claim_id].agent_id,
                            mode=claims_by_id[claim_id].mode,
                            claimed_paths=claims_by_id[claim_id].claimed_paths,
                            workspace_authority_id=claims_by_id[
                                claim_id
                            ].workspace_authority_id,
                            base_sha256_by_path=claims_by_id[
                                claim_id
                            ].base_sha256_by_path,
                            lane_output_sha256_by_path=claims_by_id[
                                claim_id
                            ].lane_output_sha256_by_path,
                            acquired_at=claims_by_id[claim_id].acquired_at,
                            expires_at=claims_by_id[claim_id].expires_at,
                            state=ClaimState.tests_running,
                            last_event_id=event.get("event_id", ""),
                            last_event_kind="tests_completed",
                        )
                elif event_kind == "ready_for_integration":
                    if claim_id in claims_by_id:
                        lane_output = event.get("lane_output_sha256_by_path")
                        claims_by_id[claim_id] = ActiveClaim(
                            claim_id=claims_by_id[claim_id].claim_id,
                            mission_id=claims_by_id[claim_id].mission_id,
                            lane_id=claims_by_id[claim_id].lane_id,
                            agent_id=claims_by_id[claim_id].agent_id,
                            mode=claims_by_id[claim_id].mode,
                            claimed_paths=claims_by_id[claim_id].claimed_paths,
                            workspace_authority_id=claims_by_id[
                                claim_id
                            ].workspace_authority_id,
                            base_sha256_by_path=claims_by_id[
                                claim_id
                            ].base_sha256_by_path,
                            lane_output_sha256_by_path=lane_output
                            or claims_by_id[claim_id].lane_output_sha256_by_path,
                            acquired_at=claims_by_id[claim_id].acquired_at,
                            expires_at=claims_by_id[claim_id].expires_at,
                            state=ClaimState.ready_for_integration,
                            last_event_id=event.get("event_id", ""),
                            last_event_kind="ready_for_integration",
                        )
                elif event_kind == "integration_accepted":
                    terminal_ids.add(claim_id)
                    claims_by_id.pop(claim_id, None)
                elif event_kind == "integration_refused_stale_base":
                    if claim_id in claims_by_id:
                        claims_by_id[claim_id] = ActiveClaim(
                            claim_id=claims_by_id[claim_id].claim_id,
                            mission_id=claims_by_id[claim_id].mission_id,
                            lane_id=claims_by_id[claim_id].lane_id,
                            agent_id=claims_by_id[claim_id].agent_id,
                            mode=claims_by_id[claim_id].mode,
                            claimed_paths=claims_by_id[claim_id].claimed_paths,
                            workspace_authority_id=claims_by_id[
                                claim_id
                            ].workspace_authority_id,
                            base_sha256_by_path=claims_by_id[
                                claim_id
                            ].base_sha256_by_path,
                            lane_output_sha256_by_path=claims_by_id[
                                claim_id
                            ].lane_output_sha256_by_path,
                            acquired_at=claims_by_id[claim_id].acquired_at,
                            expires_at=claims_by_id[claim_id].expires_at,
                            state=ClaimState.blocked,
                            last_event_id=event.get("event_id", ""),
                            last_event_kind="integration_refused_stale_base",
                            reason_code=event.get("reason_code"),
                        )
                elif event_kind in _TERMINAL_KINDS:
                    terminal_ids.add(claim_id)
                    claims_by_id.pop(claim_id, None)
                elif event_kind == "claim_refused_conflict":
                    terminal_ids.add(claim_id)
                    claims_by_id.pop(claim_id, None)
    except OSError:
        pass

    active = []
    for claim in claims_by_id.values():
        try:
            expires_dt = datetime.fromisoformat(claim.expires_at)
            if expires_dt <= now:
                continue
        except (ValueError, TypeError):
            continue
        active.append(claim)

    return active


# ── Public API ───────────────────────────────────────────────────────────────


def acquire_claim(
    store: FleetClaimStore,
    *,
    mission_id: str,
    lane_id: str,
    agent_id: str,
    mode: Literal["exclusive_write"],
    claimed_paths: list[str],
    base_sha256_by_path: dict[str, str],
    workspace_authority_id: str,
    ttl_seconds: int = 3600,
) -> ClaimResult:
    normalized = _normalized_paths(claimed_paths)
    store._acquire()
    try:
        active_claims = _replay_active_claims(
            store._events_path, workspace_authority_id
        )
        for existing in active_claims:
            if existing.workspace_authority_id != workspace_authority_id:
                continue
            conflicts, reason = _paths_conflict(normalized, existing.claimed_paths)
            if conflicts:
                refusal_event = FleetClaimEvent(
                    event_id="",
                    claim_id=str(uuid.uuid4()),
                    event_kind="claim_refused_conflict",
                    mission_id=mission_id,
                    lane_id=lane_id,
                    agent_id=agent_id,
                    workspace_authority_id=workspace_authority_id,
                    claimed_paths=normalized,
                    base_sha256_by_path=base_sha256_by_path,
                    reason_code=reason,
                    details={
                        "ttl_seconds": ttl_seconds,
                        "conflict_with": existing.claim_id,
                    },
                )
                result = store._append_event(refusal_event)
                return ClaimResult(
                    acquired=False,
                    event_id=result.event_id,
                    event_digest=result.event_digest,
                    refusal_reason=reason,
                    conflict_claim_id=existing.claim_id,
                )

        claim_id = str(uuid.uuid4())
        acquire_event = FleetClaimEvent(
            event_id="",
            claim_id=claim_id,
            event_kind="claim_acquired",
            mission_id=mission_id,
            lane_id=lane_id,
            agent_id=agent_id,
            workspace_authority_id=workspace_authority_id,
            claimed_paths=normalized,
            base_sha256_by_path=base_sha256_by_path,
            details={"ttl_seconds": ttl_seconds, "mode": mode},
        )
        result = store._append_event(acquire_event)

        expires_at = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()
        active = ActiveClaim(
            claim_id=claim_id,
            mission_id=mission_id,
            lane_id=lane_id,
            agent_id=agent_id,
            mode=ClaimMode(mode),
            claimed_paths=normalized,
            workspace_authority_id=workspace_authority_id,
            base_sha256_by_path=base_sha256_by_path,
            lane_output_sha256_by_path=None,
            acquired_at=result.timestamp,
            expires_at=expires_at,
            state=ClaimState.claimed,
            last_event_id=result.event_id,
            last_event_kind="claim_acquired",
        )

        # Write pointer artifact (content-light claim window)
        try:
            store._write_pointer_artifact(
                active=active, coordination_event_id=result.event_id
            )
        except OSError:
            logger.warning(
                "Pointer artifact write failed for claim_id=%s — claim still valid",
                claim_id,
            )

        return ClaimResult(
            acquired=True,
            claim=active,
            event_id=result.event_id,
            event_digest=result.event_digest,
        )
    finally:
        store._release()


def renew_claim(
    store: FleetClaimStore, *, claim_id: str, ttl_seconds: int = 3600
) -> ClaimResult:
    store._acquire()
    try:
        active_claims = _replay_active_claims(store._events_path, None)
        existing = next((c for c in active_claims if c.claim_id == claim_id), None)
        if existing is None:
            return ClaimResult(acquired=False, refusal_reason="claim_not_found")

        renew_event = FleetClaimEvent(
            event_id="",
            claim_id=claim_id,
            event_kind="claim_renewed",
            mission_id=existing.mission_id,
            lane_id=existing.lane_id,
            agent_id=existing.agent_id,
            workspace_authority_id=existing.workspace_authority_id,
            claimed_paths=existing.claimed_paths,
            base_sha256_by_path=existing.base_sha256_by_path,
            details={"ttl_seconds": ttl_seconds},
        )
        result = store._append_event(renew_event)

        expires_at = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()
        active = ActiveClaim(
            claim_id=existing.claim_id,
            mission_id=existing.mission_id,
            lane_id=existing.lane_id,
            agent_id=existing.agent_id,
            mode=existing.mode,
            claimed_paths=existing.claimed_paths,
            workspace_authority_id=existing.workspace_authority_id,
            base_sha256_by_path=existing.base_sha256_by_path,
            lane_output_sha256_by_path=existing.lane_output_sha256_by_path,
            acquired_at=existing.acquired_at,
            expires_at=expires_at,
            state=ClaimState.claimed,
            last_event_id=result.event_id,
            last_event_kind="claim_renewed",
        )
        return ClaimResult(
            acquired=True,
            claim=active,
            event_id=result.event_id,
            event_digest=result.event_digest,
        )
    finally:
        store._release()


def start_editing(store: FleetClaimStore, *, claim_id: str) -> ClaimResult:
    store._acquire()
    try:
        active_claims = _replay_active_claims(store._events_path, None)
        existing = next((c for c in active_claims if c.claim_id == claim_id), None)
        if existing is None:
            return ClaimResult(acquired=False, refusal_reason="claim_not_found")
        if existing.state != ClaimState.claimed:
            return ClaimResult(
                acquired=False,
                refusal_reason=f"invalid_state: expected claimed, got {existing.state.value}",
            )

        edit_event = FleetClaimEvent(
            event_id="",
            claim_id=claim_id,
            event_kind="edit_started",
            mission_id=existing.mission_id,
            lane_id=existing.lane_id,
            agent_id=existing.agent_id,
            workspace_authority_id=existing.workspace_authority_id,
            claimed_paths=existing.claimed_paths,
            base_sha256_by_path=existing.base_sha256_by_path,
        )
        result = store._append_event(edit_event)

        active = ActiveClaim(
            claim_id=existing.claim_id,
            mission_id=existing.mission_id,
            lane_id=existing.lane_id,
            agent_id=existing.agent_id,
            mode=existing.mode,
            claimed_paths=existing.claimed_paths,
            workspace_authority_id=existing.workspace_authority_id,
            base_sha256_by_path=existing.base_sha256_by_path,
            lane_output_sha256_by_path=existing.lane_output_sha256_by_path,
            acquired_at=existing.acquired_at,
            expires_at=existing.expires_at,
            state=ClaimState.editing,
            last_event_id=result.event_id,
            last_event_kind="edit_started",
        )
        return ClaimResult(
            acquired=True,
            claim=active,
            event_id=result.event_id,
            event_digest=result.event_digest,
        )
    finally:
        store._release()


def record_tests_completed(store: FleetClaimStore, *, claim_id: str) -> ClaimResult:
    store._acquire()
    try:
        active_claims = _replay_active_claims(store._events_path, None)
        existing = next((c for c in active_claims if c.claim_id == claim_id), None)
        if existing is None:
            return ClaimResult(acquired=False, refusal_reason="claim_not_found")

        tests_event = FleetClaimEvent(
            event_id="",
            claim_id=claim_id,
            event_kind="tests_completed",
            mission_id=existing.mission_id,
            lane_id=existing.lane_id,
            agent_id=existing.agent_id,
            workspace_authority_id=existing.workspace_authority_id,
            claimed_paths=existing.claimed_paths,
            base_sha256_by_path=existing.base_sha256_by_path,
        )
        result = store._append_event(tests_event)

        active = ActiveClaim(
            claim_id=existing.claim_id,
            mission_id=existing.mission_id,
            lane_id=existing.lane_id,
            agent_id=existing.agent_id,
            mode=existing.mode,
            claimed_paths=existing.claimed_paths,
            workspace_authority_id=existing.workspace_authority_id,
            base_sha256_by_path=existing.base_sha256_by_path,
            lane_output_sha256_by_path=existing.lane_output_sha256_by_path,
            acquired_at=existing.acquired_at,
            expires_at=existing.expires_at,
            state=ClaimState.tests_running,
            last_event_id=result.event_id,
            last_event_kind="tests_completed",
        )
        return ClaimResult(
            acquired=True,
            claim=active,
            event_id=result.event_id,
            event_digest=result.event_digest,
        )
    finally:
        store._release()


def mark_ready_for_integration(
    store: FleetClaimStore, *, claim_id: str, lane_output_sha256_by_path: dict[str, str]
) -> ClaimResult:
    store._acquire()
    try:
        active_claims = _replay_active_claims(store._events_path, None)
        existing = next((c for c in active_claims if c.claim_id == claim_id), None)
        if existing is None:
            return ClaimResult(acquired=False, refusal_reason="claim_not_found")

        ready_event = FleetClaimEvent(
            event_id="",
            claim_id=claim_id,
            event_kind="ready_for_integration",
            mission_id=existing.mission_id,
            lane_id=existing.lane_id,
            agent_id=existing.agent_id,
            workspace_authority_id=existing.workspace_authority_id,
            claimed_paths=existing.claimed_paths,
            base_sha256_by_path=existing.base_sha256_by_path,
            lane_output_sha256_by_path=lane_output_sha256_by_path,
        )
        result = store._append_event(ready_event)

        active = ActiveClaim(
            claim_id=existing.claim_id,
            mission_id=existing.mission_id,
            lane_id=existing.lane_id,
            agent_id=existing.agent_id,
            mode=existing.mode,
            claimed_paths=existing.claimed_paths,
            workspace_authority_id=existing.workspace_authority_id,
            base_sha256_by_path=existing.base_sha256_by_path,
            lane_output_sha256_by_path=lane_output_sha256_by_path,
            acquired_at=existing.acquired_at,
            expires_at=existing.expires_at,
            state=ClaimState.ready_for_integration,
            last_event_id=result.event_id,
            last_event_kind="ready_for_integration",
        )
        return ClaimResult(
            acquired=True,
            claim=active,
            event_id=result.event_id,
            event_digest=result.event_digest,
        )
    finally:
        store._release()


def accept_integration(
    store: FleetClaimStore,
    *,
    claim_id: str,
    current_base_sha256_by_path: dict[str, str],
) -> ClaimResult:
    store._acquire()
    try:
        active_claims = _replay_active_claims(store._events_path, None)
        existing = next((c for c in active_claims if c.claim_id == claim_id), None)
        if existing is None:
            return ClaimResult(acquired=False, refusal_reason="claim_not_found")

        for path, acq_hash in existing.base_sha256_by_path.items():
            current_hash = current_base_sha256_by_path.get(path)
            if current_hash != acq_hash:
                stale_event = FleetClaimEvent(
                    event_id="",
                    claim_id=claim_id,
                    event_kind="integration_refused_stale_base",
                    mission_id=existing.mission_id,
                    lane_id=existing.lane_id,
                    agent_id=existing.agent_id,
                    workspace_authority_id=existing.workspace_authority_id,
                    claimed_paths=existing.claimed_paths,
                    base_sha256_by_path=existing.base_sha256_by_path,
                    lane_output_sha256_by_path=existing.lane_output_sha256_by_path,
                    reason_code="stale_base",
                    details={
                        "stale_path": path,
                        "expected": acq_hash,
                        "actual": current_hash,
                    },
                )
                result = store._append_event(stale_event)
                return ClaimResult(
                    acquired=False,
                    event_id=result.event_id,
                    event_digest=result.event_digest,
                    refusal_reason="stale_base",
                )

        accept_event = FleetClaimEvent(
            event_id="",
            claim_id=claim_id,
            event_kind="integration_accepted",
            mission_id=existing.mission_id,
            lane_id=existing.lane_id,
            agent_id=existing.agent_id,
            workspace_authority_id=existing.workspace_authority_id,
            claimed_paths=existing.claimed_paths,
            base_sha256_by_path=existing.base_sha256_by_path,
            lane_output_sha256_by_path=existing.lane_output_sha256_by_path,
        )
        result = store._append_event(accept_event)
        return ClaimResult(
            acquired=True, event_id=result.event_id, event_digest=result.event_digest
        )
    finally:
        store._release()


def release_claim(store: FleetClaimStore, *, claim_id: str) -> ClaimResult:
    store._acquire()
    try:
        active_claims = _replay_active_claims(store._events_path, None)
        existing = next((c for c in active_claims if c.claim_id == claim_id), None)
        if existing is None:
            return ClaimResult(acquired=False, refusal_reason="claim_not_found")

        release_event = FleetClaimEvent(
            event_id="",
            claim_id=claim_id,
            event_kind="claim_released",
            mission_id=existing.mission_id,
            lane_id=existing.lane_id,
            agent_id=existing.agent_id,
            workspace_authority_id=existing.workspace_authority_id,
            claimed_paths=existing.claimed_paths,
            base_sha256_by_path=existing.base_sha256_by_path,
            lane_output_sha256_by_path=existing.lane_output_sha256_by_path,
            reason_code="explicit_release",
        )
        result = store._append_event(release_event)

        # Remove pointer artifact
        pointer_path = store.root / "claims" / f"{claim_id}.json"
        try:
            if pointer_path.exists():
                pointer_path.unlink()
        except OSError:
            pass

        return ClaimResult(
            acquired=True, event_id=result.event_id, event_digest=result.event_digest
        )
    finally:
        store._release()


def park_work(store: FleetClaimStore, *, claim_id: str, reason: str) -> ClaimResult:
    store._acquire()
    try:
        active_claims = _replay_active_claims(store._events_path, None)
        existing = next((c for c in active_claims if c.claim_id == claim_id), None)
        if existing is None:
            return ClaimResult(acquired=False, refusal_reason="claim_not_found")

        park_event = FleetClaimEvent(
            event_id="",
            claim_id=claim_id,
            event_kind="work_parked",
            mission_id=existing.mission_id,
            lane_id=existing.lane_id,
            agent_id=existing.agent_id,
            workspace_authority_id=existing.workspace_authority_id,
            claimed_paths=existing.claimed_paths,
            base_sha256_by_path=existing.base_sha256_by_path,
            lane_output_sha256_by_path=existing.lane_output_sha256_by_path,
            reason_code="work_parked",
            details={"reason": reason},
        )
        result = store._append_event(park_event)

        # Remove pointer artifact
        pointer_path = store.root / "claims" / f"{claim_id}.json"
        try:
            if pointer_path.exists():
                pointer_path.unlink()
        except OSError:
            pass

        return ClaimResult(
            acquired=True, event_id=result.event_id, event_digest=result.event_digest
        )
    finally:
        store._release()


def get_active_claims(
    store: FleetClaimStore, workspace_authority_id: str | None = None
) -> list[ActiveClaim]:
    store._acquire()
    try:
        return _replay_active_claims(store._events_path, workspace_authority_id)
    finally:
        store._release()


def get_claim_conflicts(
    store: FleetClaimStore, *, claimed_paths: list[str], workspace_authority_id: str
) -> list[ActiveClaim]:
    normalized = _normalized_paths(claimed_paths)
    store._acquire()
    try:
        active_claims = _replay_active_claims(
            store._events_path, workspace_authority_id
        )
        conflicting: list[ActiveClaim] = []
        for existing in active_claims:
            conflicts, _ = _paths_conflict(normalized, existing.claimed_paths)
            if conflicts:
                conflicting.append(existing)
        return conflicting
    finally:
        store._release()


# ── Exports ──────────────────────────────────────────────────────────────────

__all__ = [
    "ActiveClaim",
    "ClaimMode",
    "ClaimResult",
    "ClaimState",
    "FleetClaimEvent",
    "FleetClaimStore",
    "accept_integration",
    "acquire_claim",
    "get_active_claims",
    "get_claim_conflicts",
    "mark_ready_for_integration",
    "park_work",
    "record_tests_completed",
    "release_claim",
    "renew_claim",
    "start_editing",
]

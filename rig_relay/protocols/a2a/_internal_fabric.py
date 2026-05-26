"""Internal A2A task coordination fabric.

Provides a durable file-backed store for A2A tasks, events, messages,
and artifact references. Uses the same append-only JSONL + atomic
replacement patterns proven in the coordination store.

Distinguishes coordination from execution: this fabric manages task
state; it does not spawn agents, mutate files, or execute tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import fcntl
import json
from pathlib import Path
import threading
import uuid

from rig_relay.protocols.a2a._artifacts import A2AArtifactRef
from rig_relay.protocols.a2a._governance_bindings import A2AGovernanceBinding
from rig_relay.protocols.a2a._models import A2ATaskLifecycleEvent, A2ATaskStatus
from rig_relay.protocols.a2a._trust import (
    CapabilityClass,
    TrustTier,
    capability_admitted,
)

_CONTENT_LIGHT_FORBIDDEN = {
    "raw_prompt",
    "raw_output",
    "raw_source",
    "api_key",
    "token",
    "secret",
    "password",
    "credential",
    "private_key",
    "diff_body",
    "stdout_body",
    "stderr_body",
    "raw_file_content",
}

_DEFAULT_ROOT = Path(".build/rig-relay/a2a")


@dataclass
class InternalA2ATaskState:
    """In-memory + persisted state for an internal A2A task."""

    task_id: str
    agent_id: str
    trust_tier: TrustTier = TrustTier.INTERNAL_GOVERNED_AGENT
    status: A2ATaskStatus = A2ATaskStatus.CREATED
    description: str = ""
    trace_id: str = ""
    messages: list[str] = field(default_factory=list)
    events: list[A2ATaskLifecycleEvent] = field(default_factory=list)
    artifact_refs: list[A2AArtifactRef] = field(default_factory=list)
    governance_binding: A2AGovernanceBinding | None = None
    coordination_task_claim_id: str = ""
    coordination_path_reservation_ids: list[str] = field(default_factory=list)
    seq: int = 0


def _generate_task_id(prefix: str = "a2a") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _content_light_scan(obj: object) -> list[str]:
    """Scan a serializable object for forbidden content markers.

    Returns a list of forbidden field names found. Empty list = clean.
    """
    serialized = json.dumps(obj, default=str).lower()
    found: list[str] = []
    for forbidden in _CONTENT_LIGHT_FORBIDDEN:
        if forbidden in serialized:
            found.append(forbidden)
    return found


class A2AInternalFabric:
    """Durable internal A2A task coordination store.

    File-backed under ``.build/rig-relay/a2a/``. Thread-safe via
    fcntl advisory locks. All durable state is content-light.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "tasks").mkdir(exist_ok=True)
        (self.root / "events").mkdir(exist_ok=True)
        (self.root / "messages").mkdir(exist_ok=True)
        lockfile = self.root / ".fabric.lock"
        lockfile.touch(exist_ok=True)
        self._lock_fd = open(lockfile, "r+b")
        self._thread_lock = threading.Lock()
        self._tasks: dict[str, InternalA2ATaskState] = {}
        self._reload_all()

    def _acquire_lock(self) -> None:
        self._thread_lock.acquire()
        fcntl.flock(self._lock_fd, fcntl.LOCK_EX)

    def _release_lock(self) -> None:
        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        self._thread_lock.release()

    def _task_path(self, task_id: str) -> Path:
        return self.root / "tasks" / f"{task_id}.json"

    def _events_path(self, task_id: str) -> Path:
        return self.root / "events" / f"{task_id}.jsonl"

    def _messages_path(self, task_id: str) -> Path:
        return self.root / "messages" / f"{task_id}.jsonl"

    def _persist_task(self, state: InternalA2ATaskState) -> None:
        """Atomically write task state to disk."""
        data = {
            "task_id": state.task_id,
            "agent_id": state.agent_id,
            "trust_tier": state.trust_tier.value,
            "status": state.status.value,
            "description": state.description,
            "trace_id": state.trace_id,
            "seq": state.seq,
            "coordination_task_claim_id": state.coordination_task_claim_id,
            "coordination_path_reservation_ids": state.coordination_path_reservation_ids.copy(),
            "artifact_refs": [r.to_dict() for r in state.artifact_refs],
            "governance_binding": (
                state.governance_binding.model_dump(exclude_none=True)
                if state.governance_binding is not None
                else None
            ),
        }
        tmp = self._task_path(state.task_id).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, sort_keys=True, indent=2), encoding="utf-8")
        tmp.replace(self._task_path(state.task_id))

    def _append_event(
        self, state: InternalA2ATaskState, event: A2ATaskLifecycleEvent
    ) -> None:
        """Append a lifecycle event to the task's event log."""
        event_data = {
            "event_type": event.event_type.value,
            "timestamp": event.timestamp,
            "metadata_hash": event.metadata_hash,
            "task_id": event.task_id,
            "trace_id": event.trace_id,
            "seq": event.seq,
            "content_light": event.content_light,
        }
        line = json.dumps(event_data, sort_keys=True) + "\n"
        with open(self._events_path(state.task_id), "a") as f:
            f.write(line)
            f.flush()

    def _append_message(self, task_id: str, message: str) -> None:
        """Append a message to the task's message log."""
        entry = {"timestamp": datetime.now(UTC).isoformat(), "message": message}
        line = json.dumps(entry, sort_keys=True) + "\n"
        with open(self._messages_path(task_id), "a") as f:
            f.write(line)
            f.flush()

    def _reload_all(self) -> None:
        """Load all tasks from durable storage.

        Scans both the tasks/ snapshots and events/ directories.
        A task with events but no snapshot is still loadable — the
        snapshot is a non-authoritative projection; events are canonical.
        """
        self._tasks.clear()
        tasks_dir = self.root / "tasks"
        events_dir = self.root / "events"

        task_ids: set[str] = set()

        if tasks_dir.exists():
            for task_file in tasks_dir.glob("*.json"):
                task_ids.add(task_file.stem)

        if events_dir.exists():
            for event_file in events_dir.glob("*.jsonl"):
                task_ids.add(event_file.stem)

        for task_id in sorted(task_ids):
            try:
                self._load_one_task(task_id)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

    def _load_one_task(self, task_id: str) -> None:
        """Load a single task from durable storage.

        Base metadata (agent_id, description, etc.) comes from the
        snapshot if available. Status and seq are derived exclusively
        from event replay — the events.jsonl is canonical authority.
        """
        task_path = self._task_path(task_id)
        events_path = self._events_path(task_id)

        if task_path.exists():
            try:
                data = json.loads(task_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, FileNotFoundError):
                data = {}
        else:
            data = {}

        state = InternalA2ATaskState(
            task_id=task_id,
            agent_id=data.get("agent_id", ""),
            trust_tier=TrustTier(data.get("trust_tier", "internal_governed_agent")),
            status=A2ATaskStatus.CREATED,
            description=data.get("description", ""),
            trace_id=data.get("trace_id", ""),
            seq=0,
            coordination_task_claim_id=data.get("coordination_task_claim_id", ""),
            coordination_path_reservation_ids=data.get(
                "coordination_path_reservation_ids", []
            ),
        )

        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                evt = json.loads(line)
                event_type = A2ATaskStatus(evt["event_type"])
                state.events.append(
                    A2ATaskLifecycleEvent(
                        event_type=event_type,
                        timestamp=evt.get("timestamp", ""),
                        metadata_hash=evt.get("metadata_hash", ""),
                        task_id=evt.get("task_id", task_id),
                        trace_id=evt.get("trace_id", ""),
                        seq=evt.get("seq", len(state.events) + 1),
                    )
                )
                state.status = event_type
                state.seq = evt.get("seq", state.seq)

        for ref_data in data.get("artifact_refs", []):
            state.artifact_refs.append(
                A2AArtifactRef(
                    artifact_id=ref_data["artifact_id"],
                    artifact_kind=ref_data["artifact_kind"],
                    content_hash=ref_data.get("content_hash", ""),
                    description=ref_data.get("description", ""),
                    generated_at=ref_data.get("generated_at", ""),
                )
            )

        gb_data = data.get("governance_binding")
        if gb_data is not None:
            state.governance_binding = A2AGovernanceBinding.model_validate(gb_data)

        msgs_path = self._messages_path(task_id)
        if msgs_path.exists():
            for line in msgs_path.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                msg = json.loads(line)
                state.messages.append(msg.get("message", ""))

        self._tasks[task_id] = state

    def create_task(
        self,
        agent_id: str,
        description: str = "",
        trace_id: str = "",
        trust_tier: TrustTier = TrustTier.INTERNAL_GOVERNED_AGENT,
        governance_binding: A2AGovernanceBinding | None = None,
        task_id: str | None = None,
    ) -> InternalA2ATaskState:
        """Create a new internal A2A task.

        The task starts in CREATED status and must be explicitly
        submitted before any consumer acts on it.
        """
        tid = task_id or _generate_task_id()
        now = datetime.now(UTC).isoformat()

        if trace_id:
            tid = f"{tid}_{trace_id[:8]}"

        state = InternalA2ATaskState(
            task_id=tid,
            agent_id=agent_id,
            trust_tier=trust_tier,
            description=description,
            trace_id=trace_id,
            governance_binding=governance_binding,
            seq=1,
        )

        create_event = A2ATaskLifecycleEvent(
            event_type=A2ATaskStatus.CREATED,
            timestamp=now,
            task_id=tid,
            trace_id=trace_id,
            seq=1,
        )
        state.events.append(create_event)

        self._acquire_lock()
        try:
            if tid in self._tasks:
                raise ValueError(f"Task {tid} already exists")
            # Content-light scan
            forbidden = _content_light_scan({
                "description": description,
                "governance_binding": (
                    governance_binding.model_dump() if governance_binding else None
                ),
            })
            if forbidden:
                raise ValueError(
                    f"Task contains forbidden content markers: {forbidden}"
                )
            self._tasks[tid] = state
            self._persist_task(state)
            self._append_event(state, create_event)
        finally:
            self._release_lock()

        return state

    def get_task(self, task_id: str) -> InternalA2ATaskState | None:
        """Return a task by ID, or None if not found."""
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        agent_id: str | None = None,
        status: A2ATaskStatus | None = None,
        trust_tier: TrustTier | None = None,
    ) -> list[InternalA2ATaskState]:
        """List tasks matching optional filters."""
        results = list(self._tasks.values())
        if agent_id is not None:
            results = [t for t in results if t.agent_id == agent_id]
        if status is not None:
            results = [t for t in results if t.status == status]
        if trust_tier is not None:
            results = [t for t in results if t.trust_tier == trust_tier]
        return results

    def submit_task(self, task_id: str, trace_id: str = "") -> InternalA2ATaskState:
        """Submit a created task for execution consideration."""
        return self._transition(task_id, A2ATaskStatus.SUBMITTED, trace_id)

    def start_task(self, task_id: str, trace_id: str = "") -> InternalA2ATaskState:
        """Mark a task as running."""
        return self._transition(task_id, A2ATaskStatus.RUNNING, trace_id)

    def complete_task(
        self, task_id: str, output_hash: str = "", trace_id: str = ""
    ) -> InternalA2ATaskState:
        """Mark a task as completed."""
        return self._transition(task_id, A2ATaskStatus.COMPLETED, trace_id)

    def fail_task(
        self, task_id: str, reason: str = "", trace_id: str = ""
    ) -> InternalA2ATaskState:
        """Mark a task as failed with an optional reason."""
        state = self._transition(task_id, A2ATaskStatus.FAILED, trace_id)
        if reason:
            self.send_message(task_id, f"[FAILED] {reason}")
        return state

    def cancel_task(
        self, task_id: str, reason: str = "", trace_id: str = ""
    ) -> InternalA2ATaskState:
        """Cancel a task if not already terminal."""
        self._acquire_lock()
        try:
            state = self._tasks.get(task_id)
            if state is None:
                raise ValueError(f"Task {task_id} not found")
            if state.status in {
                A2ATaskStatus.COMPLETED,
                A2ATaskStatus.FAILED,
                A2ATaskStatus.CANCELLED,
            }:
                return state
        finally:
            self._release_lock()

        result = self._transition(task_id, A2ATaskStatus.CANCELLED, trace_id)
        if reason:
            self.send_message(task_id, f"[CANCELLED] {reason}")
        return result

    def set_input_required(
        self, task_id: str, trace_id: str = ""
    ) -> InternalA2ATaskState:
        """Mark a task as waiting for input."""
        return self._transition(task_id, A2ATaskStatus.INPUT_REQUIRED, trace_id)

    def send_message(self, task_id: str, message: str, trace_id: str = "") -> None:
        """Append a message to the task's message log."""
        self._acquire_lock()
        try:
            state = self._tasks.get(task_id)
            if state is None:
                raise ValueError(f"Task {task_id} not found")
            state.messages.append(message)
            self._append_message(task_id, message)
        finally:
            self._release_lock()

    def attach_artifact(self, task_id: str, artifact_ref: A2AArtifactRef) -> None:
        """Attach an artifact reference to a task."""
        self._acquire_lock()
        try:
            state = self._tasks.get(task_id)
            if state is None:
                raise ValueError(f"Task {task_id} not found")
            # Idempotent: skip if same artifact_id already attached
            existing_ids = {r.artifact_id for r in state.artifact_refs}
            if artifact_ref.artifact_id in existing_ids:
                return
            state.artifact_refs.append(artifact_ref)
            self._persist_task(state)
        finally:
            self._release_lock()

    def link_coordination_claim(self, task_id: str, claim_id: str) -> None:
        """Link a coordination task claim to this A2A task."""
        self._acquire_lock()
        try:
            state = self._tasks.get(task_id)
            if state is None:
                raise ValueError(f"Task {task_id} not found")
            state.coordination_task_claim_id = claim_id
            self._persist_task(state)
        finally:
            self._release_lock()

    def _transition(
        self, task_id: str, new_status: A2ATaskStatus, trace_id: str = ""
    ) -> InternalA2ATaskState:
        """Execute a state transition under lock and persist.

        The append-only events.jsonl is the canonical state authority.
        The task snapshot JSON is a non-authoritative projection derived
        from events — it can be rebuilt from the event log at any time.
        Events are written first; the snapshot follows.
        """
        _VALID = {
            A2ATaskStatus.CREATED: {A2ATaskStatus.SUBMITTED},
            A2ATaskStatus.SUBMITTED: {A2ATaskStatus.RUNNING, A2ATaskStatus.CANCELLED},
            A2ATaskStatus.RUNNING: {
                A2ATaskStatus.INPUT_REQUIRED,
                A2ATaskStatus.COMPLETED,
                A2ATaskStatus.FAILED,
                A2ATaskStatus.CANCELLED,
            },
            A2ATaskStatus.INPUT_REQUIRED: {
                A2ATaskStatus.RUNNING,
                A2ATaskStatus.CANCELLED,
            },
            A2ATaskStatus.COMPLETED: set(),
            A2ATaskStatus.FAILED: set(),
            A2ATaskStatus.CANCELLED: set(),
        }

        now = datetime.now(UTC).isoformat()
        self._acquire_lock()
        try:
            state = self._tasks.get(task_id)
            if state is None:
                raise ValueError(f"Task {task_id} not found")

            allowed = _VALID.get(state.status, set())
            if new_status not in allowed:
                raise ValueError(
                    f"Invalid A2A transition: {state.status.value} -> {new_status.value}"
                )

            state.status = new_status
            state.seq += 1
            event = A2ATaskLifecycleEvent(
                event_type=new_status,
                timestamp=now,
                task_id=task_id,
                trace_id=trace_id,
                seq=state.seq,
            )
            state.events.append(event)

            # Write event first — canonical authority
            self._append_event(state, event)
            # Snapshot is a non-authoritative projection derived from events
            self._persist_task(state)
        finally:
            self._release_lock()
        return state

    def replay_task_state(self, task_id: str) -> InternalA2ATaskState | None:
        """Reconstruct task state from durable events only.

        The events.jsonl is the sole canonical state authority.
        Returns None if the task does not exist or has no events.
        """
        self._acquire_lock()
        try:
            return self._reconstruct_from_events(task_id)
        finally:
            self._release_lock()

    def _reconstruct_from_events(self, task_id: str) -> InternalA2ATaskState | None:
        """Rebuild task state purely from the event log.

        The event log is the canonical state authority. This
        reconstruction uses only the events.jsonl and the snapshot
        for non-state metadata (agent_id, description, artifact refs,
        governance binding). Status and seq are derived exclusively
        from event replay.

        If the snapshot JSON is corrupted or missing, base metadata
        defaults to empty values — the event replay still produces
        correct status and seq.
        """
        task_path = self._task_path(task_id)
        events_path = self._events_path(task_id)

        if not events_path.exists():
            return None

        try:
            base_data = json.loads(task_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            base_data = {}

        state = InternalA2ATaskState(
            task_id=task_id,
            agent_id=base_data.get("agent_id", ""),
            trust_tier=TrustTier(
                base_data.get("trust_tier", "internal_governed_agent")
            ),
            status=A2ATaskStatus.CREATED,
            description=base_data.get("description", ""),
            trace_id=base_data.get("trace_id", ""),
            seq=0,
        )

        for line in events_path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            evt = json.loads(line)
            event_type = A2ATaskStatus(evt["event_type"])
            state.events.append(
                A2ATaskLifecycleEvent(
                    event_type=event_type,
                    timestamp=evt.get("timestamp", ""),
                    metadata_hash=evt.get("metadata_hash", ""),
                    task_id=evt.get("task_id", task_id),
                    trace_id=evt.get("trace_id", ""),
                    seq=evt.get("seq", len(state.events) + 1),
                )
            )
            state.status = event_type
            state.seq = evt.get("seq", state.seq)

        for ref_data in base_data.get("artifact_refs", []):
            state.artifact_refs.append(
                A2AArtifactRef(
                    artifact_id=ref_data["artifact_id"],
                    artifact_kind=ref_data["artifact_kind"],
                    content_hash=ref_data.get("content_hash", ""),
                    description=ref_data.get("description", ""),
                    generated_at=ref_data.get("generated_at", ""),
                )
            )

        return state

    def check_integrity(self, task_id: str) -> tuple[bool, str]:
        """Verify that task snapshot agrees with canonical event log.

        Replays events to derive expected state, then compares with
        the snapshot. Returns (consistent: bool, detail: str).
        """
        snapshot_path = self._task_path(task_id)
        events_path = self._events_path(task_id)

        if not events_path.exists():
            return False, f"No event log for task {task_id}"

        reconstructed = self._reconstruct_from_events(task_id)
        if reconstructed is None:
            return False, f"Failed to reconstruct {task_id} from events"

        result = self._verify_snapshot_matches_events(
            task_id, snapshot_path, reconstructed
        )
        return result

    def _verify_snapshot_matches_events(
        self, task_id: str, snapshot_path: Path, reconstructed: InternalA2ATaskState
    ) -> tuple[bool, str]:
        """Compare snapshot state against events-reconstructed state."""
        if not snapshot_path.exists():
            return True, (
                f"Task {task_id}: snapshot missing, "
                f"reconstructed status={reconstructed.status.value} seq={reconstructed.seq}"
            )

        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return False, f"Task {task_id}: snapshot corrupted, cannot verify"

        snap_status = snapshot.get("status", "")
        snap_seq = snapshot.get("seq", -1)

        if snap_status != reconstructed.status.value:
            return False, (
                f"Task {task_id}: status mismatch — "
                f"snapshot={snap_status}, events={reconstructed.status.value}"
            )

        if snap_seq != reconstructed.seq:
            return False, (
                f"Task {task_id}: seq mismatch — "
                f"snapshot={snap_seq}, events={reconstructed.seq}"
            )

        return True, (
            f"Task {task_id}: integrity verified — "
            f"status={reconstructed.status.value} seq={reconstructed.seq}"
        )

    def get_events(self, task_id: str) -> list[A2ATaskLifecycleEvent]:
        """Return all lifecycle events for a task."""
        state = self._tasks.get(task_id)
        if state is None:
            return []
        return list(state.events)

    def get_messages(self, task_id: str) -> list[str]:
        """Return all messages for a task."""
        state = self._tasks.get(task_id)
        if state is None:
            return []
        return list(state.messages)

    def task_count(self) -> int:
        """Return the number of tasks in the fabric."""
        return len(self._tasks)


def capability_check_for_task(
    task: InternalA2ATaskState, required_capability: CapabilityClass
) -> tuple[bool, str]:
    """Check whether a task's trust tier admits a capability.

    Returns (admitted: bool, reason: str). Used by future consumers
    (AgentLoop, Ralph, fleet) to gate execution without executing.
    """
    return capability_admitted(task.trust_tier, required_capability)


__all__ = ["A2AInternalFabric", "InternalA2ATaskState", "capability_check_for_task"]

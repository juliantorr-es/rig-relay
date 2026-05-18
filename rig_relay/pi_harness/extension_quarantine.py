from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import traceback
from typing import Any


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _redact_message(message: str) -> str:
    if not message:
        return ""
    tokens = []
    for token in message.split():
        if (
            "key" in token.lower()
            or "secret" in token.lower()
            or "token" in token.lower()
        ):
            tokens.append("[redacted]")
        else:
            tokens.append(token)
    return " ".join(tokens)[:240]


@dataclass(frozen=True, slots=True)
class ExtensionIdentity:
    extension_id: str
    name: str
    path: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class ExtensionCrashRecord:
    extension_id: str
    lifecycle_phase: str
    exception_type: str
    redacted_message: str
    traceback_hash: str
    timestamp: str
    session_id: str | None
    crash_count: int


@dataclass(frozen=True, slots=True)
class QuarantineDecision:
    quarantined: bool
    reason: str | None = None
    until: str | None = None


@dataclass(slots=True)
class ExtensionHealthPolicy:
    crash_threshold: int = 3
    crash_window_minutes: int = 30
    recent_sessions_threshold: int = 5
    safe_mode: bool = False


@dataclass(slots=True)
class ExtensionHealthState:
    extension: ExtensionIdentity
    crashes: list[ExtensionCrashRecord] = field(default_factory=list)
    quarantined: bool = False
    quarantine_reason: str | None = None
    quarantine_until: str | None = None
    healthy: bool = True


class ExtensionHealthStore:
    def __init__(
        self, root: Path | None = None, policy: ExtensionHealthPolicy | None = None
    ) -> None:
        self.root = root or (Path.cwd() / ".rig" / "pi-harness")
        self.policy = policy or ExtensionHealthPolicy()
        self.state_path = self.root / "extension-health.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, ExtensionHealthState] = self._load()

    def _load(self) -> dict[str, ExtensionHealthState]:
        if not self.state_path.exists():
            return {}
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        state: dict[str, ExtensionHealthState] = {}
        for entry in raw.get("extensions", []):
            identity = ExtensionIdentity(**entry["extension"])
            crashes = [
                ExtensionCrashRecord(**item) for item in entry.get("crashes", [])
            ]
            state[identity.extension_id] = ExtensionHealthState(
                extension=identity,
                crashes=crashes,
                quarantined=entry.get("quarantined", False),
                quarantine_reason=entry.get("quarantine_reason"),
                quarantine_until=entry.get("quarantine_until"),
                healthy=entry.get("healthy", True),
            )
        return state

    def _save(self) -> None:
        payload = {
            "schema_version": "rig.pi_harness.extension_health.v1",
            "generated_at": _now().isoformat(),
            "extensions": [
                {
                    "extension": {
                        "extension_id": state.extension.extension_id,
                        "name": state.extension.name,
                        "path": state.extension.path,
                        "content_hash": state.extension.content_hash,
                    },
                    "crashes": [asdict(record) for record in state.crashes],
                    "quarantined": state.quarantined,
                    "quarantine_reason": state.quarantine_reason,
                    "quarantine_until": state.quarantine_until,
                    "healthy": state.healthy,
                }
                for state in sorted(
                    self._state.values(), key=lambda item: item.extension.extension_id
                )
            ],
        }
        self.state_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    def register_extension(self, extension: ExtensionIdentity) -> ExtensionHealthState:
        state = self._state.setdefault(
            extension.extension_id, ExtensionHealthState(extension=extension)
        )
        state.extension = extension
        self._save()
        return state

    def record_success(self, extension: ExtensionIdentity) -> ExtensionHealthState:
        state = self.register_extension(extension)
        state.healthy = True
        self._save()
        return state

    def record_crash(
        self,
        extension: ExtensionIdentity,
        lifecycle_phase: str,
        exc: BaseException,
        session_id: str | None = None,
    ) -> tuple[ExtensionHealthState, ExtensionCrashRecord, QuarantineDecision]:
        state = self.register_extension(extension)
        tb_hash = _sha256_text(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        )
        record = ExtensionCrashRecord(
            extension_id=extension.extension_id,
            lifecycle_phase=lifecycle_phase,
            exception_type=type(exc).__name__,
            redacted_message=_redact_message(str(exc)),
            traceback_hash=tb_hash,
            timestamp=_now().isoformat(),
            session_id=session_id,
            crash_count=len(state.crashes) + 1,
        )
        state.crashes.append(record)
        state.healthy = False
        decision = self._apply_quarantine_policy(state)
        self._save()
        return state, record, decision

    def _apply_quarantine_policy(
        self, state: ExtensionHealthState
    ) -> QuarantineDecision:
        now = _now()
        window_start = now - timedelta(minutes=self.policy.crash_window_minutes)
        recent = [
            item
            for item in state.crashes
            if datetime.fromisoformat(item.timestamp) >= window_start
        ]
        if len(recent) >= self.policy.crash_threshold:
            state.quarantined = True
            state.quarantine_reason = (
                f"{len(recent)} crashes in {self.policy.crash_window_minutes} minutes"
            )
            state.quarantine_until = (
                now + timedelta(minutes=self.policy.crash_window_minutes)
            ).isoformat()
            return QuarantineDecision(
                True, state.quarantine_reason, state.quarantine_until
            )
        if self.policy.safe_mode:
            state.quarantined = False
            state.quarantine_reason = None
            state.quarantine_until = None
        return QuarantineDecision(False)

    def clear_quarantine(self, extension_id: str) -> ExtensionHealthState:
        state = self._state[extension_id]
        state.quarantined = False
        state.quarantine_reason = None
        state.quarantine_until = None
        self._save()
        return state

    def get_status(self) -> list[ExtensionHealthState]:
        return sorted(
            self._state.values(), key=lambda item: item.extension.extension_id
        )

    def should_start(self, extension: ExtensionIdentity) -> bool:
        state = self._state.get(extension.extension_id)
        return not (state and state.quarantined and not self.policy.safe_mode)


def extension_content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_extension_with_containment(
    extension: ExtensionIdentity,
    *,
    lifecycle_phase: str,
    session_id: str | None,
    store: ExtensionHealthStore,
    callback: Any,
    callback_args: tuple[Any, ...] = (),
    **kwargs: Any,
) -> Any:
    if not store.should_start(extension):
        return {
            "status": "skipped",
            "extension_id": extension.extension_id,
            "quarantined": True,
        }
    try:
        result = callback(*callback_args, **kwargs)
        store.record_success(extension)
        return {
            "status": "ok",
            "extension_id": extension.extension_id,
            "result": result,
        }
    except Exception as exc:
        state, record, decision = store.record_crash(
            extension, lifecycle_phase, exc, session_id=session_id
        )
        return {
            "status": "crashed",
            "extension_id": extension.extension_id,
            "crash": asdict(record),
            "quarantine": {
                "quarantined": decision.quarantined,
                "reason": decision.reason,
                "until": decision.until,
            },
            "healthy": state.healthy,
        }

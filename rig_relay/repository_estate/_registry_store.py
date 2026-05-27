"""Append-only JSONL evidence store for repository estate.

Events are written to lane-owned paths under ``.build/rig-relay/repository_estate/``.
Each event is a single JSONL line: schema-validated, content-light, deterministic.

No raw file contents, raw paths beyond root_path_digest, or secrets are stored.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import uuid

from rig_relay.coordination._canonical_json import dump_canonical_json
from rig_relay.repository_estate._digest_utils import digest_text
from rig_relay.repository_estate._models import (
    RegisteredRepository,
    RepositoryObservation,
)


class RepositoryEstateRegistryStore:
    """Append-only evidence store for registration and observation events.

    Writes to two JSONL files::
        <root>/registrations.jsonl
        <root>/observations.jsonl

    Each line is a compact canonical JSON object with an event envelope.
    Flush + fsync on every append for durability.
    """

    def __init__(self, store_root: Path | None = None) -> None:
        self._store_root = store_root or _default_store_root()
        self._store_root.mkdir(parents=True, exist_ok=True)

    @property
    def registrations_path(self) -> Path:
        return self._store_root / "registrations.jsonl"

    @property
    def observations_path(self) -> Path:
        return self._store_root / "observations.jsonl"

    # ── Registration evidence ────────────────────────────────────────

    def append_registration(self, registration: RegisteredRepository) -> str:
        """Append a registration event and return its event ID."""
        event = _make_event_envelope("repository_estate.registration", registration)
        _append_jsonl(self.registrations_path, event)
        return event["event_id"]

    def read_all_registrations(self) -> list[dict]:
        """Read all registration events from the JSONL file."""
        return _read_jsonl(self.registrations_path)

    # ── Observation evidence ─────────────────────────────────────────

    def append_observation(self, observation: RepositoryObservation) -> str:
        """Append an observation event and return its event ID."""
        event = _make_event_envelope("repository_estate.observation", observation)
        _append_jsonl(self.observations_path, event)
        return event["event_id"]

    def read_all_observations(self) -> list[dict]:
        """Read all observation events from the JSONL file."""
        return _read_jsonl(self.observations_path)

    def read_observations_for(self, repository_hash: str) -> list[dict]:
        """Read all observation events for a specific repository."""
        all_obs = self.read_all_observations()
        return [
            o
            for o in all_obs
            if o.get("payload", {}).get("repository_hash") == repository_hash
        ]

    def latest_observation_for(self, repository_hash: str) -> dict | None:
        """Return the most recent observation event for a repository."""
        obs = self.read_observations_for(repository_hash)
        return obs[-1] if obs else None


# ── Envelope helpers ─────────────────────────────────────────────


class _EntryEncoder:
    """Converts a pydantic model to a plain dict for evidence envelope."""

    @staticmethod
    def encode(model: RegisteredRepository | RepositoryObservation) -> dict:
        return model.model_dump(mode="json")


def _make_event_envelope(
    event_kind: str, payload_model: RegisteredRepository | RepositoryObservation
) -> dict:
    """Create a content-light event envelope for JSONL storage."""
    now = datetime.now(UTC).isoformat()
    payload = _EntryEncoder.encode(payload_model)
    payload_canonical = dump_canonical_json(payload)
    event = {
        "schema_version": "rig.relay.repository_estate_event_envelope.v1",
        "event_id": str(uuid.uuid4()),
        "event_kind": event_kind,
        "created_at": now,
        "payload": payload,
        "payload_sha256": digest_text(payload_canonical),
    }
    event["event_sha256"] = digest_text(
        dump_canonical_json({k: v for k, v in event.items() if k != "event_sha256"})
    )
    return event


# ── JSONL I/O ────────────────────────────────────────────────────


def _append_jsonl(path: Path, event: dict) -> None:
    """Append a single event as a JSONL line with flush+fsync."""
    line = dump_canonical_json(event) + "\n"
    with open(path, "ab") as f:
        f.write(line.encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())


def _read_jsonl(path: Path) -> list[dict]:
    """Read all lines from a JSONL file. Returns empty list if file missing.

    Corrupt (non-JSON) lines are captured as ``{"_corrupt": true, "_raw": ...}``
    so the projection builder can detect and report them as corruption events
    rather than crashing the reader.
    """
    import json

    if not path.is_file():
        return []
    results: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                results.append(json.loads(stripped))
            except json.JSONDecodeError:
                results.append({
                    "_corrupt": True,
                    "_raw": stripped[:200],
                    "event_id": "",
                    "payload": {},
                })
    return results


def _default_store_root() -> Path:
    """Default evidence store root under the project build directory."""
    return Path(".build/rig-relay/repository_estate")


__all__ = ["RepositoryEstateRegistryStore"]

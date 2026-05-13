"""Consent store for telemetry consent records.

Separate from OAuth token storage. Consent records are stored locally.
OAuth tokens remain in the token store — never in consent records.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.identity.state_paths import consent_state_root
from rig_relay.identity.telemetry_consent import (
    TelemetryConsentRecord,
    TelemetryConsentStatus,
    build_initial_consent,
)


class ConsentStore:
    """Local file-backed consent store.

    Stores one consent record as JSON. Separate from OAuth token store.
    No raw OAuth tokens in consent records.
    """

    CONSENT_FILE_NAME = "telemetry_consent.json"

    def __init__(self, store_root: Path | None = None) -> None:
        if store_root is None:
            store_root = consent_state_root()
        self._store_root = store_root
        self._store_root.mkdir(parents=True, exist_ok=True)

    def _path(self) -> Path:
        return self._store_root / self.CONSENT_FILE_NAME

    def get(self) -> TelemetryConsentRecord:
        """Read the current consent record, or return initial if none."""
        path = self._path()
        if not path.is_file():
            return build_initial_consent()
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return TelemetryConsentRecord(**data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return build_initial_consent()

    def save(self, record: TelemetryConsentRecord) -> None:
        """Save a consent record to disk."""
        path = self._path()
        path.write_text(
            json.dumps(record.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )

    def status(self) -> TelemetryConsentStatus:
        """Return the current consent status."""
        return self.get().status

    def summary(self) -> dict[str, Any]:
        """Return a content-light consent summary for UI/audit.

        No raw tokens, no raw email, no raw prompts, no raw code, no raw output.
        """
        record = self.get()
        return {
            "schema_version": record.schema_version,
            "consent_id": record.consent_id,
            "subject_hash": record.subject_hash,
            "provider": record.provider,
            "status": record.status.value,
            "scopes": [s.value for s in record.scopes],
            "granted_at": record.granted_at,
            "revoked_at": record.revoked_at,
            "local_only": record.local_only,
            "warnings": record.warnings,
        }

    def delete(self) -> bool:
        """Delete the consent record file. Returns True if existed."""
        path = self._path()
        if path.is_file():
            path.unlink()
            return True
        return False

    def clear(self) -> None:
        """Reset consent to initial state."""
        self.save(build_initial_consent())

"""ReceiptStore protocol and filesystem-backed implementation.

Provides append/get/list operations on ReceiptEnvelope objects, stored as
canonical JSON files in a structured directory hierarchy.

Manifest enrichment (v2): manifest.jsonl rows now include governance
correlation fields for discoverability without reading every shard.
Backward-compatible: old rows without new fields remain readable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from rig_relay.evidence.receipt_envelope import ReceiptEnvelope


@runtime_checkable
class ReceiptStore(Protocol):
    """Protocol for persisting and querying receipt envelopes.

    Implementations store ReceiptEnvelope objects and provide
    append/get/list operations.
    """

    def append(self, envelope: ReceiptEnvelope) -> Path:
        """Persist a receipt envelope and return its file path."""
        ...

    def get(self, envelope_id: str) -> ReceiptEnvelope | None:
        """Retrieve a receipt envelope by ID, or None if not found."""
        ...

    def list(self, limit: int = 100, offset: int = 0) -> list[ReceiptEnvelope]:
        """List receipt envelopes ordered by creation time (newest first)."""
        ...

    def list_by_session(
        self, session_id: str, limit: int = 100, offset: int = 0
    ) -> list[ReceiptEnvelope]:
        """List receipt envelopes for a given session ID."""
        ...

    def count(self) -> int:
        """Return the total number of stored receipt envelopes."""
        ...


class ManifestDiagnostic:
    """A diagnostic record for manifest integrity issues.

    Content-light: no raw payloads or file contents.
    """

    def __init__(
        self,
        kind: str,
        envelope_id: str | None = None,
        manifest_line: int | None = None,
        reason: str = "",
    ) -> None:
        self.kind = kind
        self.envelope_id = envelope_id
        self.manifest_line = manifest_line
        self.reason = reason

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "envelope_id": self.envelope_id,
            "manifest_line": self.manifest_line,
            "reason": self.reason,
        }


class FilesystemReceiptStore:
    """Filesystem-backed receipt store.

    Stores envelopes as canonical JSON files under ``root/envelopes/``,
    sharded by first two hex characters of the envelope ID for
    directory performance.

    A manifest at ``root/manifest.jsonl`` maintains an append-only
    ordered index for efficient list/query without directory walks.

    Manifest v2 enrichment (backward-compatible): each row includes
    governance correlation fields when available.
    Old rows without new fields are silently tolerated.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._envelopes_dir = self._root / "envelopes"
        self._manifest_path = self._root / "manifest.jsonl"
        self._envelopes_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ──────────────────────────────────────────────────

    def append(self, envelope: ReceiptEnvelope) -> Path:
        path = self._envelope_path(envelope.envelope_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = envelope.model_dump(mode="json")
        path.write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        manifest_line = json.dumps(
            self._build_manifest_row(envelope, path), sort_keys=True
        )
        with self._manifest_path.open("a", encoding="utf-8") as f:
            f.write(manifest_line + "\n")

        return path

    def get(self, envelope_id: str) -> ReceiptEnvelope | None:
        path = self._envelope_path(envelope_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ReceiptEnvelope.model_validate(data)
        except (json.JSONDecodeError, ValueError, KeyError):
            return None

    def list(self, limit: int = 100, offset: int = 0) -> list[ReceiptEnvelope]:
        return self._list_from_manifest(limit=limit, offset=offset)

    def list_by_session(
        self, session_id: str, limit: int = 100, offset: int = 0
    ) -> list[ReceiptEnvelope]:
        return self._list_from_manifest(
            session_id=session_id, limit=limit, offset=offset
        )

    def count(self) -> int:
        return self._manifest_line_count()

    # ── Lookup helpers ────────────────────────────────────────────

    def find_by_decision_id(self, decision_id: str) -> list[ReceiptEnvelope]:
        results: list[ReceiptEnvelope] = []
        for row in self.iter_manifest_rows():
            gd_id = row.get("governance_decision_id")
            if gd_id is not None and gd_id == decision_id:
                env = self.get(str(row["envelope_id"]))
                if env is not None:
                    results.append(env)
        return results

    def find_by_surface(self, surface: str) -> list[ReceiptEnvelope]:
        results: list[ReceiptEnvelope] = []
        for row in self.iter_manifest_rows():
            if row.get("surface") == surface:
                env = self.get(str(row["envelope_id"]))
                if env is not None:
                    results.append(env)
        return results

    def find_by_capability_id(self, capability_id: str) -> list[ReceiptEnvelope]:
        results: list[ReceiptEnvelope] = []
        for row in self.iter_manifest_rows():
            if row.get("capability_id") == capability_id:
                env = self.get(str(row["envelope_id"]))
                if env is not None:
                    results.append(env)
        return results

    def find_by_authority_tier(self, authority_tier: str) -> list[ReceiptEnvelope]:
        results: list[ReceiptEnvelope] = []
        for row in self.iter_manifest_rows():
            if row.get("authority_tier") == authority_tier:
                env = self.get(str(row["envelope_id"]))
                if env is not None:
                    results.append(env)
        return results

    def iter_manifest_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        if not self._manifest_path.is_file():
            return rows
        with self._manifest_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    # ── Diagnostics ──────────────────────────────────────────────

    def diagnose(self) -> list[ManifestDiagnostic]:
        diagnostics: list[ManifestDiagnostic] = []

        envelope_ids_on_disk: set[str] = set()
        for shard_dir in self._envelopes_dir.iterdir():
            if not shard_dir.is_dir():
                continue
            for envelope_file in shard_dir.iterdir():
                if envelope_file.suffix == ".json":
                    eid = envelope_file.stem
                    envelope_ids_on_disk.add(eid)
                    try:
                        json.loads(envelope_file.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        diagnostics.append(
                            ManifestDiagnostic(
                                kind="corrupted_shard",
                                envelope_id=eid,
                                reason="JSON decode failure",
                            )
                        )

        manifest_ids: set[str] = set()
        if self._manifest_path.is_file():
            with self._manifest_path.open("r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        diagnostics.append(
                            ManifestDiagnostic(
                                kind="corrupted_manifest_line",
                                manifest_line=line_num,
                                reason="JSON decode failure",
                            )
                        )
                        continue
                    eid = row.get("envelope_id", "")
                    if isinstance(eid, str) and eid:
                        manifest_ids.add(eid)
                        if eid not in envelope_ids_on_disk:
                            diagnostics.append(
                                ManifestDiagnostic(
                                    kind="missing_shard",
                                    envelope_id=eid,
                                    manifest_line=line_num,
                                    reason="Manifest row references envelope file not on disk",
                                )
                            )

        for eid in envelope_ids_on_disk - manifest_ids:
            diagnostics.append(
                ManifestDiagnostic(
                    kind="orphaned_shard",
                    envelope_id=eid,
                    reason="Envelope file on disk with no manifest row",
                )
            )

        return diagnostics

    # ── Internal helpers ────────────────────────────────────────────

    def _build_manifest_row(
        self, envelope: ReceiptEnvelope, path: Path
    ) -> dict[str, object]:
        row: dict[str, object] = {
            "envelope_id": envelope.envelope_id,
            "receipt_kind": envelope.receipt_kind,
            "session_id": envelope.subject.session_id,
            "created_at": envelope.created_at,
            "schema_version": envelope.schema_version,
        }

        if envelope.decision is not None:
            row["governance_decision_id"] = envelope.decision.governance_decision_id
            row["decision_status"] = envelope.decision.decision
            row["surface"] = envelope.decision.surface
            row["authority_tier"] = envelope.decision.authority_tier
            row["capability_id"] = envelope.decision.capability_id
            row["content_light_classification"] = (
                envelope.decision.content_light_classification
            )

        return row

    def _envelope_path(self, envelope_id: str) -> Path:
        return self._envelopes_dir / envelope_id[:2] / f"{envelope_id}.json"

    def _manifest_line_count(self) -> int:
        if not self._manifest_path.is_file():
            return 0
        count = 0
        with self._manifest_path.open("r", encoding="utf-8") as f:
            for _ in f:
                count += 1
        return count

    def _list_from_manifest(
        self, session_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[ReceiptEnvelope]:
        if not self._manifest_path.is_file():
            return []

        entries: list[dict[str, str]] = []
        with self._manifest_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if session_id and entry.get("session_id") != session_id:
                    continue
                entries.append(entry)

        entries.reverse()
        sliced = entries[offset : offset + limit]

        result: list[ReceiptEnvelope] = []
        for entry in sliced:
            env = self.get(entry["envelope_id"])
            if env is not None:
                result.append(env)
        return result


__all__ = ["FilesystemReceiptStore", "ManifestDiagnostic", "ReceiptStore"]

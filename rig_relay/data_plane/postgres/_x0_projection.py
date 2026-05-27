"""X0 public projection boundary for PostgreSQL data plane.

Typed public application-service projection surface consumed by X0
(Gridline Interface / desktop cockpit). X0 must consume this boundary,
not query PostgreSQL domain tables, materialized views, or private
X1 implementation modules directly (per the X0 admission contract at
``docs/json/contracts/x0_postgres_consumer_admission.v1.json``).

All methods are read-only and content-light: SHA256 digests, counts,
status labels, timestamps. Never raw file contents, paths, or secrets.
"""

from __future__ import annotations

from datetime import datetime
import json as _json
from pathlib import Path
from typing import Any

from psycopg import sql as psql
from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.logger import logger
from rig_relay.data_plane.postgres._materialization_input import (
    compute_multi_table_digest,
    compute_projection_digest,
)
from rig_relay.data_plane.postgres._store import PostgresOperationalProjectionStore

X0_ADMISSION_CONTRACT_PATH = (
    "docs/json/contracts/x0_postgres_consumer_admission.v1.json"
)

_PROJECTION_NAME_MAP: dict[str, str] = {
    "repository_estate": "repository_estate",
    "investigation_timeline": "timeline",
    "publication_history": "publication",
}

_DOMAIN_TABLE_MAP: dict[str, str] = {
    "repository_estate": "repository_estate_builds",
    "investigation_timeline": "timeline_builds",
    "publication_history": "publication_builds",
}

_VALID_AVAILABILITY = frozenset({
    "unavailable",
    "refused",
    "corrupt_source",
    "degraded",
    "derived",
    "rebuilt",
})


def _determine_availability(
    build_row: dict[str, Any] | None,
    *,
    has_corrupt: bool,
    rows_materialized: int = 0,
    has_rebuild: bool = False,
) -> str:
    """Map build receipt state to an availability label.

    Content-light: returns a status label only — never raw row data.
    """
    if build_row is None:
        return "unavailable"
    if rows_materialized == 0 and not has_corrupt:
        return "refused"
    if has_corrupt:
        return "corrupt_source"
    deterministic = build_row.get("deterministic")
    if deterministic is True:
        if has_rebuild:
            return "rebuilt"
        return "derived"
    return "degraded"


class ProjectionDomainStatus(BaseModel):
    """Projection status for a single domain as visible to X0."""

    model_config = ConfigDict(extra="forbid")

    domain: str = Field(
        description="Domain identity: repository_estate, investigation_timeline, or publication_history"
    )
    availability: str = Field(
        description="Projection availability: unavailable, refused, corrupt_source, degraded, derived, rebuilt"
    )
    latest_build_receipt_id: str | None = Field(
        default=None, description="Receipt ID of the latest materialization build"
    )
    latest_build_at: str | None = Field(
        default=None, description="ISO 8601 timestamp of the latest build"
    )
    rows_materialized: int = Field(
        default=0, ge=0, description="Total rows materialized in the latest build"
    )
    corrupt_rows: int = Field(
        default=0, ge=0, description="Corrupt evidence rows in the latest build"
    )
    source_evidence_digest: str = Field(
        default="",
        description="SHA256 digest of the source evidence consumed by the latest build",
    )
    deterministic: bool = Field(
        default=False, description="Whether the latest build was deterministic"
    )
    authority_state: str = Field(
        default="unknown",
        description="Authority state: derived, derived_degraded, corrupt, unknown",
    )
    provenance_class: str = Field(
        default="unknown",
        description="Provenance classification: derived_deterministic, derived_degraded, corrupt_untrusted, unknown",
    )
    content_light_guarantee: bool = Field(
        default=True,
        description="Always true: this status carries no raw content, paths, or secrets",
    )


def _derive_authority_state(deterministic: bool, has_corrupt: bool) -> str:
    if has_corrupt:
        return "corrupt"
    if deterministic:
        return "derived"
    return "derived_degraded"


def _derive_provenance_class(deterministic: bool, has_corrupt: bool) -> str:
    if has_corrupt:
        return "corrupt_untrusted"
    if deterministic:
        return "derived_deterministic"
    return "derived_degraded"


class X0ProjectionSurface:
    """Typed public projection surface consumed by X0 (desktop cockpit).

    Wraps ``PostgresOperationalProjectionStore`` and exposes read-only,
    content-light projection methods for repository estate, investigation
    timeline, and publication history domains.

    X0 MUST consume this boundary — not query PostgreSQL domain tables,
    materialized views, or private X1 implementation modules directly.

    Usage::

        from rig_relay.data_plane.postgres import (
            X0ProjectionSurface,
            PostgresOperationalProjectionStore,
            PostgresConnectionConfig,
        )

        store = PostgresOperationalProjectionStore(config)
        surface = X0ProjectionSurface(store)
        status = surface.get_projection_status()
    """

    ADMISSION_CONTRACT_PATH: str = X0_ADMISSION_CONTRACT_PATH

    def __init__(self, store: PostgresOperationalProjectionStore) -> None:
        self._store = store

    # ── Admission contract ────────────────────────────────────────────

    def verify_admission_contract(self) -> bool:
        """Load and validate the X0 admission contract.

        Returns True if the contract exists and carries the correct
        schema version; False otherwise.
        """
        repo_root = _resolve_repo_root()
        contract_path = repo_root / self.ADMISSION_CONTRACT_PATH
        try:
            raw = contract_path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            logger.warning("X0 admission contract not found at %s", contract_path)
            return False

        try:
            body = _json.loads(raw)
        except _json.JSONDecodeError:
            logger.warning("X0 admission contract is not valid JSON")
            return False

        schema_version = body.get("schema_version", "")
        if schema_version != "rig.relay.x0_postgres_consumer_admission.v1":
            logger.warning(
                "X0 admission contract has unexpected schema_version %s", schema_version
            )
            return False

        content_light = body.get("content_light_guarantee", False)
        if not content_light:
            logger.warning("X0 admission contract lacks content_light_guarantee")
            return False

        return True

    # ── Domain status ─────────────────────────────────────────────────

    def get_projection_status(self) -> dict[str, ProjectionDomainStatus]:
        """Return projection status for all three domains.

        Queries build receipt tables only — never domain tables
        or materialized views. Each domain is mapped through
        ``_build_status_for_domain``.
        """
        result: dict[str, ProjectionDomainStatus] = {}
        for domain in (
            "repository_estate",
            "investigation_timeline",
            "publication_history",
        ):
            try:
                result[domain] = self._build_status_for_domain(domain)
            except Exception as exc:
                logger.error("Failed to get status for domain %s: %s", domain, exc)
                result[domain] = ProjectionDomainStatus(
                    domain=domain,
                    availability="unavailable",
                    authority_state="unknown",
                    provenance_class="unknown",
                )
        return result

    def _build_status_for_domain(self, domain: str) -> ProjectionDomainStatus:
        """Query the domain build receipt table for the latest build row."""
        table = _DOMAIN_TABLE_MAP[domain]
        schema = self._store.config.schema_name

        query = psql.SQL(
            "SELECT receipt_id, built_at, evidence_source_sha256, deterministic "
            "FROM {}.{} ORDER BY built_at DESC LIMIT 1"
        ).format(psql.Identifier(schema), psql.Identifier(table))

        with self._store.conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()

        if row is None:
            return ProjectionDomainStatus(
                domain=domain,
                availability="unavailable",
                authority_state="unknown",
                provenance_class="unknown",
            )

        receipt_id: str = row[0] or ""
        built_at: datetime | None = row[1]
        evidence_digest: str = row[2] or ""
        deterministic: bool = bool(row[3]) if row[3] is not None else False

        # Count materialized rows and corrupt rows from the build receipt
        rows_mat, corrupt = self._count_build_rows(domain, receipt_id)

        has_corrupt = corrupt > 0
        availability = _determine_availability(
            {"receipt_id": receipt_id, "deterministic": deterministic},
            has_corrupt=has_corrupt,
            rows_materialized=rows_mat,
            has_rebuild=self._has_rebuild_records(
                _PROJECTION_NAME_MAP.get(domain, domain)
            ),
        )

        authority_state = _derive_authority_state(deterministic, has_corrupt)
        provenance_class = _derive_provenance_class(deterministic, has_corrupt)

        return ProjectionDomainStatus(
            domain=domain,
            availability=availability,
            latest_build_receipt_id=receipt_id,
            latest_build_at=built_at.isoformat() if built_at else None,
            rows_materialized=rows_mat,
            corrupt_rows=corrupt,
            source_evidence_digest=evidence_digest,
            deterministic=deterministic,
            authority_state=authority_state,
            provenance_class=provenance_class,
        )

    def _count_build_rows(self, domain: str, receipt_id: str) -> tuple[int, int]:
        """Return (rows_materialized, corrupt_rows) for a build receipt."""
        table = _DOMAIN_TABLE_MAP[domain]
        schema = self._store.config.schema_name

        if domain == "repository_estate":
            query = psql.SQL(
                "SELECT repositories_built + observations_built + "
                "workspace_instances_built + changes_built, "
                "corrupt_registration_count + corrupt_observation_count "
                "FROM {}.{} WHERE receipt_id = %s"
            ).format(psql.Identifier(schema), psql.Identifier(table))
        elif domain == "investigation_timeline":
            query = psql.SQL(
                "SELECT events_built, corrupt_count FROM {}.{} WHERE receipt_id = %s"
            ).format(psql.Identifier(schema), psql.Identifier(table))
        elif domain == "publication_history":
            query = psql.SQL(
                "SELECT receipts_built, corrupt_receipt_count "
                "FROM {}.{} WHERE receipt_id = %s"
            ).format(psql.Identifier(schema), psql.Identifier(table))
        else:
            return 0, 0

        with self._store.conn.cursor() as cur:
            cur.execute(query, (receipt_id,))
            row = cur.fetchone()
            if row:
                return int(row[0] or 0), int(row[1] or 0)
        return 0, 0

    def _has_rebuild_records(self, projection_name: str) -> bool:
        """Return True if rebuild_receipts has at least one rebuild for the projection."""
        schema = self._store.config.schema_name
        try:
            with self._store.conn.cursor() as cur:
                cur.execute(
                    psql.SQL(
                        "SELECT COUNT(*) FROM {}.{} "
                        "WHERE projection_name = %s AND rows_before > 0"
                    ).format(
                        psql.Identifier(schema), psql.Identifier("rebuild_receipts")
                    ),
                    (projection_name,),
                )
                row = cur.fetchone()
                return bool(row and row[0] and int(row[0]) > 0)
        except Exception:
            return False

    # ── Rebuild history ───────────────────────────────────────────────

    def get_rebuild_history(self, domain: str, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent rebuild receipts for a domain.

        Maps domain to projection_name and queries ``rebuild_receipts``.
        Returns content-light rows: receipt_id, rows_before, rows_after,
        rebuilt_at ISO string, deterministic flag.
        """
        projection_name = _PROJECTION_NAME_MAP.get(domain, domain)
        schema = self._store.config.schema_name

        query = psql.SQL(
            "SELECT receipt_id, rows_before, rows_after, rebuilt_at, deterministic "
            "FROM {}.{} WHERE projection_name = %s "
            "ORDER BY rebuilt_at DESC LIMIT %s"
        ).format(psql.Identifier(schema), psql.Identifier("rebuild_receipts"))

        try:
            with self._store.conn.cursor() as cur:
                cur.execute(query, (projection_name, limit))
                results: list[dict[str, Any]] = []
                for row in cur:
                    rebuilt_at: datetime | None = row[3]
                    results.append({
                        "receipt_id": row[0],
                        "rows_before": int(row[1] or 0),
                        "rows_after": int(row[2] or 0),
                        "rebuilt_at": rebuilt_at.isoformat() if rebuilt_at else None,
                        "deterministic": bool(row[4]) if row[4] is not None else False,
                    })
                return results
        except Exception as exc:
            logger.error("Failed to get rebuild history for domain %s: %s", domain, exc)
            return []

    # ── Domain summaries ──────────────────────────────────────────────

    def get_estate_summary(self) -> dict[str, Any]:
        """Content-light aggregate summary of repository estate projection.

        Returns counts from the latest build receipt plus a
        degradation summary with corrupt counts.
        """
        schema = self._store.config.schema_name
        table = "repository_estate_builds"

        try:
            with self._store.conn.cursor() as cur:
                cur.execute(
                    psql.SQL(
                        "SELECT receipt_id, built_at, "
                        "repositories_built, observations_built, "
                        "workspace_instances_built, changes_built, "
                        "corrupt_registration_count, corrupt_observation_count, "
                        "deterministic, evidence_source_sha256 "
                        "FROM {}.{} ORDER BY built_at DESC LIMIT 1"
                    ).format(psql.Identifier(schema), psql.Identifier(table))
                )
                row = cur.fetchone()

            if row is None:
                return {
                    "registered_repositories": 0,
                    "observations": 0,
                    "workspace_instances": 0,
                    "changes": 0,
                    "corrupt_registrations": 0,
                    "corrupt_observations": 0,
                    "deterministic": False,
                    "source_evidence_digest": "",
                    "latest_build_at": None,
                    "degradation_summary": {
                        "total_corrupt": 0,
                        "authority_state": "unknown",
                    },
                }

            total_corrupt = int(row[6] or 0) + int(row[7] or 0)
            built_at: datetime | None = row[1]
            deterministic = bool(row[8]) if row[8] is not None else False

            return {
                "registered_repositories": int(row[2] or 0),
                "observations": int(row[3] or 0),
                "workspace_instances": int(row[4] or 0),
                "changes": int(row[5] or 0),
                "corrupt_registrations": int(row[6] or 0),
                "corrupt_observations": int(row[7] or 0),
                "deterministic": deterministic,
                "source_evidence_digest": row[9] or "",
                "latest_build_at": built_at.isoformat() if built_at else None,
                "degradation_summary": {
                    "total_corrupt": total_corrupt,
                    "authority_state": _derive_authority_state(
                        deterministic, total_corrupt > 0
                    ),
                },
            }
        except Exception as exc:
            logger.error("Failed to get estate summary: %s", exc)
            return {
                "registered_repositories": 0,
                "observations": 0,
                "workspace_instances": 0,
                "changes": 0,
                "corrupt_registrations": 0,
                "corrupt_observations": 0,
                "deterministic": False,
                "source_evidence_digest": "",
                "latest_build_at": None,
                "degradation_summary": {
                    "total_corrupt": 0,
                    "authority_state": "unknown",
                },
                "error": str(exc),
            }

    def get_timeline_summary(self) -> dict[str, Any]:
        """Content-light aggregate summary of investigation timeline projection.

        Returns event counts and degradation classification from the
        latest build receipt.
        """
        schema = self._store.config.schema_name
        table = "timeline_builds"

        try:
            with self._store.conn.cursor() as cur:
                cur.execute(
                    psql.SQL(
                        "SELECT receipt_id, built_at, source_event_count, "
                        "events_built, verified_canonical_count, "
                        "canonical_degraded_count, corrupt_count, "
                        "unsupported_count, missing_count, "
                        "contradictory_count, stale_count, "
                        "deterministic, evidence_source_sha256 "
                        "FROM {}.{} ORDER BY built_at DESC LIMIT 1"
                    ).format(psql.Identifier(schema), psql.Identifier(table))
                )
                row = cur.fetchone()

            if row is None:
                return {
                    "total_events": 0,
                    "verified_canonical": 0,
                    "canonical_degraded": 0,
                    "corrupt": 0,
                    "unsupported": 0,
                    "missing": 0,
                    "contradictory": 0,
                    "stale": 0,
                    "deterministic": False,
                    "source_evidence_digest": "",
                    "latest_build_at": None,
                    "degradation_summary": {
                        "total_degraded": 0,
                        "total_corrupt": 0,
                        "authority_state": "unknown",
                    },
                }

            built_at: datetime | None = row[1]
            deterministic = bool(row[11]) if row[11] is not None else False
            corrupt_count = int(row[6] or 0)
            degraded_count = (
                int(row[5] or 0)
                + int(row[7] or 0)
                + int(row[8] or 0)
                + int(row[9] or 0)
                + int(row[10] or 0)
            )

            return {
                "total_events": int(row[3] or 0),
                "verified_canonical": int(row[4] or 0),
                "canonical_degraded": int(row[5] or 0),
                "corrupt": corrupt_count,
                "unsupported": int(row[7] or 0),
                "missing": int(row[8] or 0),
                "contradictory": int(row[9] or 0),
                "stale": int(row[10] or 0),
                "deterministic": deterministic,
                "source_evidence_digest": row[12] or "",
                "latest_build_at": built_at.isoformat() if built_at else None,
                "degradation_summary": {
                    "total_degraded": degraded_count,
                    "total_corrupt": corrupt_count,
                    "authority_state": _derive_authority_state(
                        deterministic, corrupt_count > 0
                    ),
                },
            }
        except Exception as exc:
            logger.error("Failed to get timeline summary: %s", exc)
            return {
                "total_events": 0,
                "verified_canonical": 0,
                "canonical_degraded": 0,
                "corrupt": 0,
                "unsupported": 0,
                "missing": 0,
                "contradictory": 0,
                "stale": 0,
                "deterministic": False,
                "source_evidence_digest": "",
                "latest_build_at": None,
                "degradation_summary": {
                    "total_degraded": 0,
                    "total_corrupt": 0,
                    "authority_state": "unknown",
                },
                "error": str(exc),
            }

    def get_publication_summary(self) -> dict[str, Any]:
        """Content-light aggregate summary of publication history projection.

        Returns receipt counts, success/refusal/safety/corruption breakdown,
        and reconstruction health from the latest build receipt.
        """
        schema = self._store.config.schema_name
        table = "publication_builds"

        try:
            with self._store.conn.cursor() as cur:
                cur.execute(
                    psql.SQL(
                        "SELECT receipt_id, built_at, source_receipt_count, "
                        "receipts_built, successful_count, refused_count, "
                        "safety_failed_count, corrupt_receipt_count, "
                        "reconstruction_healthy, deterministic, "
                        "evidence_source_sha256 "
                        "FROM {}.{} ORDER BY built_at DESC LIMIT 1"
                    ).format(psql.Identifier(schema), psql.Identifier(table))
                )
                row = cur.fetchone()

            if row is None:
                return {
                    "total_receipts": 0,
                    "successful": 0,
                    "refused": 0,
                    "safety_failed": 0,
                    "corrupt": 0,
                    "reconstruction_healthy": False,
                    "deterministic": False,
                    "source_evidence_digest": "",
                    "latest_build_at": None,
                    "degradation_summary": {
                        "total_corrupt": 0,
                        "authority_state": "unknown",
                    },
                }

            built_at: datetime | None = row[1]
            deterministic = bool(row[9]) if row[9] is not None else False
            corrupt_count = int(row[7] or 0)

            return {
                "total_receipts": int(row[3] or 0),
                "successful": int(row[4] or 0),
                "refused": int(row[5] or 0),
                "safety_failed": int(row[6] or 0),
                "corrupt": corrupt_count,
                "reconstruction_healthy": bool(row[8]) if row[8] is not None else False,
                "deterministic": deterministic,
                "source_evidence_digest": row[10] or "",
                "latest_build_at": built_at.isoformat() if built_at else None,
                "degradation_summary": {
                    "total_corrupt": corrupt_count,
                    "authority_state": _derive_authority_state(
                        deterministic, corrupt_count > 0
                    ),
                },
            }
        except Exception as exc:
            logger.error("Failed to get publication summary: %s", exc)
            return {
                "total_receipts": 0,
                "successful": 0,
                "refused": 0,
                "safety_failed": 0,
                "corrupt": 0,
                "reconstruction_healthy": False,
                "deterministic": False,
                "source_evidence_digest": "",
                "latest_build_at": None,
                "degradation_summary": {
                    "total_corrupt": 0,
                    "authority_state": "unknown",
                },
                "error": str(exc),
            }

    # ── Projection digest ─────────────────────────────────────────────

    def compute_projection_digest(self, domain: str) -> str:
        """Compute a SHA256 digest of the current projection state.

        Delegates to ``compute_projection_digest`` for single-table
        domains (timeline) and ``compute_multi_table_digest`` for
        multi-table domains (repository estate, publication).

        Returns an empty string on error — callers should treat an
        empty digest as unavailable.
        """
        schema = self._store.config.schema_name
        exclude = ["materialized_at", "built_at", "receipt_id"]

        try:
            if domain == "investigation_timeline":
                return compute_projection_digest(
                    self._store.conn,
                    schema,
                    "timeline_events",
                    exclude_columns=["materialized_at"],
                    domain_name="investigation_timeline",
                )
            if domain == "repository_estate":
                return compute_multi_table_digest(
                    self._store.conn,
                    schema,
                    [
                        ("repository_observations", ["observation_id"]),
                        ("repository_workspace_instances", ["instance_id"]),
                        ("repository_observation_changes", ["change_id"]),
                    ],
                    exclude_columns=exclude,
                    domain_name="repository_estate",
                )
            if domain == "publication_history":
                return compute_multi_table_digest(
                    self._store.conn,
                    schema,
                    [
                        ("publication_preview_receipts", ["receipt_id"]),
                        ("publication_reconstruction", ["ledger_path_hash"]),
                        ("publication_builds", ["receipt_id"]),
                    ],
                    exclude_columns=exclude,
                    domain_name="publication_history",
                )
            return ""
        except Exception as exc:
            logger.error(
                "Failed to compute projection digest for domain %s: %s", domain, exc
            )
            return ""


def _resolve_repo_root() -> Path:
    """Resolve the repository root relative to this module's location."""
    return Path(__file__).resolve().parents[3]

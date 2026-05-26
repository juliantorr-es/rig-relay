"""Disposable Operational Analytics Plane — DuckDB read-side projections.

Provides typed read-only projection services that build disposable DuckDB
views from canonical evidence artifacts. DuckDB is strictly a rebuildable
lens over canonical evidence — NOT a mutation authority.

Admitted source corpora:
    - GitHub truth observations  (GitHubTruthStore)
    - Coordination events        (CoordinationStore)
    - Fleet queue state          (FleetQueue)
    - Storage lifecycle audit    (audit_storage)
    - Governance decisions       (ReceiptStore → DuckDB)

All projections are rebuildable from canonical artifacts.
All queries are content-light (counts, statuses, hashes, timestamps).
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"
RECEIPT_STORE_ROOT = Path.home() / ".rig" / "relay" / "receipts"

HAS_DUCKDB = False
_duckdb = None
try:
    import duckdb as _duckdb_actual

    _duckdb = _duckdb_actual
    HAS_DUCKDB = True
except ImportError:
    pass


def _get_con() -> Any:
    """Return a new disposable DuckDB connection. Raises if unavailable."""
    if _duckdb is None:
        raise RuntimeError("DuckDB is not available")
    return _duckdb.connect(":memory:")


CONTENT_LIGHT_FORBIDDEN = frozenset({
    "access_token",
    "api_key",
    "Bearer",
    "credential",
    "password",
    "private_key",
    "raw_prompt",
    "raw_source",
    "secret",
    "token",
})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode('utf-8')).hexdigest()}"


def _content_light_assert(data: dict[str, Any], label: str = "") -> None:
    serialized = json.dumps(data, sort_keys=True, default=str).lower()
    found = [f for f in CONTENT_LIGHT_FORBIDDEN if f.lower() in serialized]
    if found:
        raise ValueError(
            f"Analytics output contains forbidden fields: {found}"
            + (f" (source: {label})" if label else "")
        )


def _duckdb_rows(con: Any, sql: str) -> list[dict[str, Any]]:
    try:
        result = con.execute(sql)
    except Exception:
        return []
    if result is None:
        return []
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]


class OperationalAnalytics:
    """Disposable DuckDB analytics plane over Lane B canonical evidence.

    Usage:
        analytics = OperationalAnalytics()
        analytics.load_github_truth()
        analytics.load_coordination()
        analytics.load_fleet_queue()
        results = analytics.query_github_truth_summary()
    """

    def __init__(self, build_root: Path | None = None) -> None:
        if _duckdb is None:
            raise RuntimeError("DuckDB is not available")
        self._con: Any = _duckdb.connect(":memory:")
        self._build_root = build_root or DEFAULT_BUILD_ROOT
        self._loaded: set[str] = set()

    @property
    def con(self) -> Any:
        return self._con

    # ── Source loading ────────────────────────────────────────────────

    def load_github_truth(self, store_root: Path | None = None) -> int:
        from rig_relay.evidence.github_truth_store import GitHubTruthStore

        store = GitHubTruthStore(root=store_root) if store_root else GitHubTruthStore()
        observations = store.list_observations()
        if not observations:
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS github_truth_observations "
                "(observation_digest VARCHAR, operation_kind VARCHAR, "
                "repository_hash VARCHAR, status VARCHAR, "
                "verification_status VARCHAR, ci_state VARCHAR, "
                "overall_state VARCHAR, expected_sha VARCHAR, "
                "remote_head_sha VARCHAR, ref VARCHAR, "
                "observed_at VARCHAR, error_kind VARCHAR, "
                "follow_on_commits_count BIGINT, accepted_head_present BOOLEAN, "
                "passed_count BIGINT, failed_count BIGINT, pending_count BIGINT)"
            )
            self._loaded.add("github_truth")
            return 0
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            for obs in observations:
                f.write(json.dumps(obs) + "\n")
            tmp = f.name
        try:
            self._con.execute(
                f"CREATE OR REPLACE TABLE github_truth_observations AS "
                f"SELECT * FROM read_json_auto('{tmp}')"
            )
        finally:
            os.unlink(tmp)
        count = len(observations)
        self._loaded.add("github_truth")
        return count

    def load_coordination(self) -> int:
        events_path = self._build_root / "coordination" / "events.jsonl"
        if not events_path.is_file():
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS coordination_events "
                "(event_id VARCHAR, event_name VARCHAR, session_id VARCHAR, "
                "payload VARCHAR)"
            )
            self._loaded.add("coordination")
            return 0
        self._con.execute(
            f"CREATE OR REPLACE TABLE coordination_events AS "
            f"SELECT * FROM read_json_auto('{events_path}')"
        )
        count = self._con.execute(
            "SELECT COUNT(*) FROM coordination_events"
        ).fetchone()[0]
        self._loaded.add("coordination")
        return count

    def load_fleet_queue(self) -> int:
        events_path = self._build_root / "coordination" / "queue" / "events.jsonl"
        if not events_path.is_file():
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS fleet_queue_events "
                "(event_id VARCHAR, queue_item_id VARCHAR, "
                "event_kind VARCHAR, payload VARCHAR)"
            )
            self._loaded.add("fleet_queue")
            return 0
        self._con.execute(
            f"CREATE OR REPLACE TABLE fleet_queue_events AS "
            f"SELECT * FROM read_json_auto('{events_path}')"
        )
        count = self._con.execute("SELECT COUNT(*) FROM fleet_queue_events").fetchone()[
            0
        ]
        self._loaded.add("fleet_queue")
        return count

    def load_storage(self) -> None:
        from rig_relay.evidence._storage_audit import audit_storage

        result = audit_storage(root=self._build_root)
        self._con.execute(
            "CREATE OR REPLACE TABLE storage_audit AS "
            "SELECT * FROM (SELECT ? AS schema_version, ? AS budget_status, "
            "? AS total_size_mb, ? AS stale_lease_count, "
            "? AS rollup_candidate_count, ? AS prune_candidate_count)",
            parameters=[
                result.get("schema_version", ""),
                result.get("budget", {}).get("status", "unknown"),
                result.get("total_size_mb", 0.0),
                result.get("stale_lease_count", 0),
                len(result.get("rollup_candidates", [])),
                result.get("prune_candidates_count", 0),
            ],
        )
        self._loaded.add("storage")

    def load_governance_decisions(self) -> int:
        from rig_relay.analytics.governance_decisions_projection import (
            build_governance_decisions_projection,
        )

        proj = build_governance_decisions_projection(RECEIPT_STORE_ROOT)
        records = proj.get("records", [])
        if not records:
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS governance_decisions "
                "(decision_id VARCHAR, decision_kind VARCHAR, severity VARCHAR, "
                "status VARCHAR, created_at VARCHAR, session_id VARCHAR, "
                "tool_name VARCHAR, path_hashes VARCHAR)"
            )
            self._loaded.add("governance_decisions")
            return 0
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
            tmp = f.name
        try:
            self._con.execute(
                f"CREATE OR REPLACE TABLE governance_decisions AS "
                f"SELECT * FROM read_json_auto('{tmp}')"
            )
        finally:
            os.unlink(tmp)
        count = len(records)
        self._loaded.add("governance_decisions")
        return count

    def load_all(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        try:
            counts["github_truth"] = self.load_github_truth()
        except Exception:
            counts["github_truth"] = -1
        try:
            counts["coordination"] = self.load_coordination()
        except Exception:
            counts["coordination"] = -1
        try:
            counts["fleet_queue"] = self.load_fleet_queue()
        except Exception:
            counts["fleet_queue"] = -1
        try:
            self.load_storage()
            counts["storage"] = 1
        except Exception:
            counts["storage"] = -1
        try:
            counts["governance_decisions"] = self.load_governance_decisions()
        except Exception:
            counts["governance_decisions"] = -1
        return counts

    def is_loaded(self, source: str) -> bool:
        return source in self._loaded

    # ── Typed queries ──────────────────────────────────────────────────

    def query_github_truth_summary(self) -> dict[str, Any]:
        if not self.is_loaded("github_truth"):
            return {"available": False, "reason": "github_truth_not_loaded"}
        result: dict[str, Any] = {
            "available": True,
            "total_observations": 0,
            "latest_observed_at": None,
            "by_operation_kind": {},
            "by_verification_status": {},
            "by_ci_state": {},
        }
        try:
            result["total_observations"] = self._con.execute(
                "SELECT COUNT(*) FROM github_truth_observations"
            ).fetchone()[0]
            latest = _duckdb_rows(
                self._con,
                "SELECT MAX(observed_at) AS latest FROM github_truth_observations",
            )
            if latest:
                result["latest_observed_at"] = latest[0].get("latest")
            ops = _duckdb_rows(
                self._con,
                "SELECT operation_kind, COUNT(*) AS cnt "
                "FROM github_truth_observations "
                "GROUP BY operation_kind",
            )
            result["by_operation_kind"] = {
                r["operation_kind"]: r["cnt"] for r in ops if r.get("operation_kind")
            }
            vs = _duckdb_rows(
                self._con,
                "SELECT verification_status, COUNT(*) AS cnt "
                "FROM github_truth_observations "
                "WHERE verification_status IS NOT NULL "
                "GROUP BY verification_status",
            )
            result["by_verification_status"] = {
                r["verification_status"]: r["cnt"]
                for r in vs
                if r.get("verification_status")
            }
            ci = _duckdb_rows(
                self._con,
                "SELECT ci_state, COUNT(*) AS cnt "
                "FROM github_truth_observations "
                "WHERE ci_state IS NOT NULL "
                "GROUP BY ci_state",
            )
            result["by_ci_state"] = {
                r["ci_state"]: r["cnt"] for r in ci if r.get("ci_state")
            }
        except Exception:
            pass
        _content_light_assert(result, label="github_truth_summary")
        return result

    def query_coordination_summary(self) -> dict[str, Any]:
        if not self.is_loaded("coordination"):
            return {"available": False, "reason": "coordination_not_loaded"}
        result: dict[str, Any] = {
            "available": True,
            "total_events": 0,
            "by_event_name": {},
        }
        try:
            result["total_events"] = self._con.execute(
                "SELECT COUNT(*) FROM coordination_events"
            ).fetchone()[0]
            by_name = _duckdb_rows(
                self._con,
                "SELECT event_name, COUNT(*) AS cnt "
                "FROM coordination_events "
                "GROUP BY event_name",
            )
            result["by_event_name"] = {
                r["event_name"]: r["cnt"] for r in by_name if r.get("event_name")
            }
        except Exception:
            pass
        _content_light_assert(result, label="coordination_summary")
        return result

    def query_fleet_summary(self) -> dict[str, Any]:
        if not self.is_loaded("fleet_queue"):
            return {"available": False, "reason": "fleet_queue_not_loaded"}
        result: dict[str, Any] = {"available": True, "total_events": 0}
        try:
            result["total_events"] = self._con.execute(
                "SELECT COUNT(*) FROM fleet_queue_events"
            ).fetchone()[0]
        except Exception:
            pass
        _content_light_assert(result, label="fleet_summary")
        return result

    def query_storage_summary(self) -> dict[str, Any]:
        if not self.is_loaded("storage"):
            return {"available": False, "reason": "storage_not_loaded"}
        row = _duckdb_rows(self._con, "SELECT * FROM storage_audit LIMIT 1")
        result = row[0] if row else {"available": False}
        result["available"] = True
        _content_light_assert(result, label="storage_summary")
        return result

    def query_governance_summary(self) -> dict[str, Any]:
        if not self.is_loaded("governance_decisions"):
            return {"available": False, "reason": "governance_decisions_not_loaded"}
        result: dict[str, Any] = {
            "available": True,
            "total_decisions": 0,
            "by_decision_kind": {},
            "by_severity": {},
        }
        try:
            result["total_decisions"] = self._con.execute(
                "SELECT COUNT(*) FROM governance_decisions"
            ).fetchone()[0]
            dk = _duckdb_rows(
                self._con,
                "SELECT decision_kind, COUNT(*) AS cnt "
                "FROM governance_decisions "
                "WHERE decision_kind IS NOT NULL "
                "GROUP BY decision_kind",
            )
            result["by_decision_kind"] = {
                r["decision_kind"]: r["cnt"] for r in dk if r.get("decision_kind")
            }
            sv = _duckdb_rows(
                self._con,
                "SELECT severity, COUNT(*) AS cnt "
                "FROM governance_decisions "
                "WHERE severity IS NOT NULL "
                "GROUP BY severity",
            )
            result["by_severity"] = {
                r["severity"]: r["cnt"] for r in sv if r.get("severity")
            }
        except Exception:
            pass
        _content_light_assert(result, label="governance_summary")
        return result

    def query_source_health(self) -> dict[str, Any]:
        """Aggregate source availability and freshness across all loaded corpora."""
        health: dict[str, Any] = {}
        for source in sorted(self._loaded):
            health[source] = {"loaded": True, "freshness": _now_iso()}
            if source == "github_truth":
                summary = self.query_github_truth_summary()
                health[source].update({
                    "total": summary.get("total_observations", 0),
                    "latest_at": summary.get("latest_observed_at"),
                })
            elif source == "coordination":
                summary = self.query_coordination_summary()
                health[source].update({"total": summary.get("total_events", 0)})
            elif source == "fleet_queue":
                summary = self.query_fleet_summary()
                health[source].update({"total": summary.get("total_events", 0)})
            elif source == "storage":
                health[source]["total"] = 1
            elif source == "governance_decisions":
                summary = self.query_governance_summary()
                health[source].update({"total": summary.get("total_decisions", 0)})
        result: dict[str, Any] = {
            "available": len(health) > 0,
            "loaded_sources": len(health),
            "source_detail": health,
        }
        _content_light_assert(result, label="source_health")
        return result

    def query_refinement_candidates(self) -> list[dict[str, Any]]:
        """Derive refinement candidates from loaded operational evidence.

        Produces content-light recommendations based on real evidence
        patterns. Never invokes models, mutates evidence, or executes tools.
        """
        candidates: list[dict[str, Any]] = []
        now = _now_iso()

        if self.is_loaded("coordination"):
            events = self.query_coordination_summary()
            by_name = events.get("by_event_name", {})
            if by_name.get("coord.conflict.reported", 0) > 0:
                candidates.append({
                    "candidate_id": _sha256("coordination_conflicts_v1"),
                    "source": "coordination",
                    "kind": "repeated_conflicts",
                    "severity": "P2",
                    "evidence_count": by_name["coord.conflict.reported"],
                    "reason": f"Coordination conflicts detected ({by_name['coord.conflict.reported']} events).",
                    "suggested_action": "inspect_coordination_logs",
                    "generated_at": now,
                })

        if self.is_loaded("github_truth"):
            gt = self.query_github_truth_summary()
            vs = gt.get("by_verification_status", {})
            if vs.get("ABSENT", 0) > 0 or vs.get("REMOTE_UNAVAILABLE", 0) > 0:
                candidates.append({
                    "candidate_id": _sha256("github_publication_gap_v1"),
                    "source": "github_truth",
                    "kind": "publication_gap",
                    "severity": "P1",
                    "evidence_count": vs.get("ABSENT", 0)
                    + vs.get("REMOTE_UNAVAILABLE", 0),
                    "reason": "Publication verification gaps detected.",
                    "suggested_action": "verify_github_publication_status",
                    "generated_at": now,
                })

        if self.is_loaded("storage"):
            storage = self.query_storage_summary()
            status = storage.get("budget_status", "unknown")
            if status in {"over_budget", "fleet_blocked"}:
                candidates.append({
                    "candidate_id": _sha256("storage_pressure_v1"),
                    "source": "storage",
                    "kind": "storage_pressure",
                    "severity": "P1",
                    "evidence_count": 1,
                    "reason": f"Storage budget status is {status}.",
                    "suggested_action": "run_storage_gc",
                    "generated_at": now,
                })

        if self.is_loaded("governance_decisions"):
            gov = self.query_governance_summary()
            dk = gov.get("by_decision_kind", {})
            refused = dk.get("refused", 0) + dk.get("blocked", 0)
            if refused > 5:
                candidates.append({
                    "candidate_id": _sha256("governance_refusal_rate_v1"),
                    "source": "governance_decisions",
                    "kind": "high_refusal_rate",
                    "severity": "P2",
                    "evidence_count": refused,
                    "reason": f"High governance refusal count ({refused}).",
                    "suggested_action": "review_governance_policy",
                    "generated_at": now,
                })

        return candidates


__all__ = ["HAS_DUCKDB", "OperationalAnalytics"]

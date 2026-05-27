from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rig_relay.investigation_timeline._content_light import enforce_content_light_dict
from rig_relay.investigation_timeline._models import (
    DuckDBDatasetDescriptor,
    DuckDBViewDefinition,
    InvestigationTimeline,
    TimelineDuckDBExport,
)


def build_duckdb_export(
    timeline: InvestigationTimeline, output_dir: str | Path
) -> TimelineDuckDBExport:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    export = TimelineDuckDBExport(timeline_id=timeline.timeline_id)

    timeline_dataset_name = "investigation_timeline_events.jsonl"
    timeline_dataset_path = output_path / timeline_dataset_name

    rows = _events_to_dict_rows(timeline)

    violations = enforce_content_light_dict(rows)
    if violations:
        raise ValueError(
            f"content-light violations in exported rows: {'; '.join(violations[:10])}"
        )

    with timeline_dataset_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    timeline_sha256 = _file_sha256(timeline_dataset_path)

    export.datasets.append(
        DuckDBDatasetDescriptor(
            dataset_name="investigation_timeline_events",
            relative_path=timeline_dataset_name,
            row_count=len(rows),
            dataset_sha256=timeline_sha256,
            schema_version="rig.relay.investigation_timeline_event.v1",
            description=(
                "Normalized investigation timeline events from all available"
                " canonical evidence domains."
            ),
        )
    )
    export.row_counts["investigation_timeline_events"] = len(rows)

    summary_dataset_name = "investigation_timeline_summary.jsonl"
    summary_dataset_path = output_path / summary_dataset_name
    summary_rows = _build_summary_rows(timeline)
    with summary_dataset_path.open("w", encoding="utf-8") as f:
        for row in summary_rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    summary_sha256 = _file_sha256(summary_dataset_path)

    export.datasets.append(
        DuckDBDatasetDescriptor(
            dataset_name="investigation_timeline_aggregates",
            relative_path=summary_dataset_name,
            row_count=len(summary_rows),
            dataset_sha256=summary_sha256,
            schema_version="rig.relay.investigation_timeline_aggregate.v1",
            description="Pre-computed aggregates: event-kind counts, domain coverage, degradation summary.",
        )
    )
    export.row_counts["investigation_timeline_aggregates"] = len(summary_rows)

    export.view_definitions = _build_view_definitions()

    return export


def _events_to_dict_rows(timeline: InvestigationTimeline) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for event in timeline.events:
        row: dict[str, object] = {
            "event_id": event.event_id,
            "timeline_sequence": event.timeline_sequence,
            "observed_at": event.observed_at,
            "event_kind": event.event_kind.value,
            "source_domain": event.source_domain.value,
            "source_event_id": event.source_event_id,
            "source_digest": event.source_digest,
            "source_sequence": event.source_sequence,
            "authority_classification": event.authority_classification.value,
            "degradation_detail": event.degradation_detail,
            "session_id": event.session_id,
            "investigation_id": event.investigation_id,
            "project_id": event.project_id,
            "parent_session_id": event.parent_session_id,
            "task_id": event.task_id,
            "outcome": event.outcome,
            "status": event.status,
            "latency_ms": event.latency_ms,
            "path_count": event.path_count,
            "artifact_kind": event.artifact_kind,
            "artifact_sha256": event.artifact_sha256,
            "commit_sha": event.commit_sha,
            "refusal_code": event.refusal_code,
            "producer_digest": event.producer_digest,
            "producer_digest_verified": event.producer_digest_verified,
            "verification_class": event.verification_class.value,
        }
        rows.append(row)
    return rows


def _build_summary_rows(timeline: InvestigationTimeline) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    rows.append({
        "summary_kind": "timeline_metadata",
        "timeline_id": timeline.timeline_id,
        "investigation_id": timeline.investigation_id,
        "session_id": timeline.session_id,
        "event_count": timeline.event_count,
        "domain_count": len(timeline.domain_coverage),
        "assembled_at": timeline.assembled_at,
        "projection_digest": timeline.projection_digest,
    })

    for domain, count in timeline.domain_coverage.items():
        rows.append({
            "summary_kind": "domain_coverage",
            "timeline_id": timeline.timeline_id,
            "source_domain": domain,
            "event_count": count,
        })

    ds = timeline.degradation_summary
    rows.append({
        "summary_kind": "degradation_summary",
        "timeline_id": timeline.timeline_id,
        "total_events": ds.total_events,
        "canonical_live_count": ds.canonical_live_count,
        "canonical_degraded_count": ds.canonical_degraded_count,
        "missing_count": ds.missing_count,
        "contradictory_count": ds.contradictory_count,
        "corrupt_count": ds.corrupt_count,
        "stale_count": ds.stale_count,
    })

    for domain in timeline.unsupported_domains:
        rows.append({
            "summary_kind": "unsupported_domain",
            "timeline_id": timeline.timeline_id,
            "source_domain": domain,
        })

    event_kind_counts: dict[str, int] = {}
    for event in timeline.events:
        kind = event.event_kind.value
        event_kind_counts[kind] = event_kind_counts.get(kind, 0) + 1

    for kind, count in event_kind_counts.items():
        rows.append({
            "summary_kind": "event_kind_count",
            "timeline_id": timeline.timeline_id,
            "event_kind": kind,
            "count": count,
        })

    outcome_counts: dict[str, int] = {}
    for event in timeline.events:
        if event.outcome:
            outcome_counts[event.outcome] = outcome_counts.get(event.outcome, 0) + 1

    for outcome, count in outcome_counts.items():
        rows.append({
            "summary_kind": "outcome_count",
            "timeline_id": timeline.timeline_id,
            "outcome": outcome,
            "count": count,
        })

    return rows


def _build_view_definitions() -> list[DuckDBViewDefinition]:
    return [
        DuckDBViewDefinition(
            view_name="v_timeline_chronological",
            sql=(
                "CREATE OR REPLACE VIEW v_timeline_chronological AS "
                "SELECT * FROM investigation_timeline_events "
                "ORDER BY timeline_sequence ASC"
            ),
            purpose="Full chronological timeline.",
            query_example="SELECT * FROM v_timeline_chronological WHERE session_id = 's-1';",
        ),
        DuckDBViewDefinition(
            view_name="v_timeline_refusals",
            sql=(
                "CREATE OR REPLACE VIEW v_timeline_refusals AS "
                "SELECT * FROM investigation_timeline_events "
                "WHERE outcome = 'refused' ORDER BY timeline_sequence ASC"
            ),
            purpose="All refusals across all evidence domains.",
            query_example="SELECT event_kind, source_domain, COUNT(*) FROM v_timeline_refusals GROUP BY event_kind, source_domain ORDER BY COUNT(*) DESC;",
        ),
        DuckDBViewDefinition(
            view_name="v_timeline_degradation",
            sql=(
                "CREATE OR REPLACE VIEW v_timeline_degradation AS "
                "SELECT * FROM investigation_timeline_events "
                "WHERE authority_classification != 'CANONICAL_LIVE' "
                "ORDER BY timeline_sequence ASC"
            ),
            purpose="All degraded/missing/contradictory evidence events.",
            query_example="SELECT authority_classification, COUNT(*) FROM v_timeline_degradation GROUP BY authority_classification;",
        ),
        DuckDBViewDefinition(
            view_name="v_timeline_tool_outcomes",
            sql=(
                "CREATE OR REPLACE VIEW v_timeline_tool_outcomes AS "
                "SELECT * FROM investigation_timeline_events "
                "WHERE event_kind IN ('TOOL_CALL_COMPLETED', 'TOOL_CALL_REFUSED', 'TOOL_CALL_FAILED') "
                "ORDER BY timeline_sequence ASC"
            ),
            purpose="Tool-call outcome distribution.",
            query_example="SELECT event_kind, COUNT(*) FROM v_timeline_tool_outcomes GROUP BY event_kind;",
        ),
        DuckDBViewDefinition(
            view_name="v_timeline_checkpoints",
            sql=(
                "CREATE OR REPLACE VIEW v_timeline_checkpoints AS "
                "SELECT * FROM investigation_timeline_events "
                "WHERE event_kind IN ('CHECKPOINT_COMMITTED', 'CHECKPOINT_REFUSED') "
                "ORDER BY timeline_sequence ASC"
            ),
            purpose="Checkpoint commits and refusals.",
            query_example="SELECT event_kind, commit_sha, COUNT(*) FROM v_timeline_checkpoints GROUP BY event_kind, commit_sha;",
        ),
        DuckDBViewDefinition(
            view_name="v_timeline_coordination_conflicts",
            sql=(
                "CREATE OR REPLACE VIEW v_timeline_coordination_conflicts AS "
                "SELECT * FROM investigation_timeline_events "
                "WHERE event_kind IN ('COORDINATION_CONFLICT_REPORTED', 'COORDINATION_RESERVATION_REFUSED') "
                "ORDER BY timeline_sequence ASC"
            ),
            purpose="Coordination conflicts and refusals.",
            query_example="SELECT event_kind, COUNT(*) FROM v_timeline_coordination_conflicts GROUP BY event_kind;",
        ),
        DuckDBViewDefinition(
            view_name="v_timeline_disclosure_transitions",
            sql=(
                "CREATE OR REPLACE VIEW v_timeline_disclosure_transitions AS "
                "SELECT * FROM investigation_timeline_events "
                "WHERE event_kind LIKE 'DISCLOSURE_%' "
                "ORDER BY timeline_sequence ASC"
            ),
            purpose="Disclosure transition lifecycle.",
            query_example="SELECT status, COUNT(*) FROM v_timeline_disclosure_transitions GROUP BY status;",
        ),
        DuckDBViewDefinition(
            view_name="v_timeline_event_kind_distribution",
            sql=(
                "CREATE OR REPLACE VIEW v_timeline_event_kind_distribution AS "
                "SELECT summary_kind, event_kind, count "
                "FROM investigation_timeline_aggregates "
                "WHERE summary_kind = 'event_kind_count'"
            ),
            purpose="Event-kind distribution from pre-computed aggregates.",
            query_example="SELECT * FROM v_timeline_event_kind_distribution ORDER BY count DESC;",
        ),
        DuckDBViewDefinition(
            view_name="v_timeline_verified_canonical",
            sql=(
                "CREATE OR REPLACE VIEW v_timeline_verified_canonical AS "
                "SELECT * FROM investigation_timeline_events "
                "WHERE verification_class = 'VERIFIED_CANONICAL'"
            ),
            purpose="Only events with verified canonical producer digests.",
            query_example="SELECT * FROM v_timeline_verified_canonical ORDER BY timeline_sequence ASC;",
        ),
    ]


def _file_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            sha.update(chunk)
    return f"sha256:{sha.hexdigest()}"

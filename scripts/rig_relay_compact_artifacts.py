#!/usr/bin/env python3
"""Rig Relay Artifact Compaction.

Reads derived JSONL datasets, writes Parquet rollups using DuckDB.
Never compacts raw logs. Never destructive.

Compaction pipeline:
    derived/*.dataset.jsonl ──→ DuckDB SELECT/filter/count ──→ derived/*.parquet
                                   └─→ derived/rollup_manifest.json

Usage:
    uv run python scripts/rig_relay_compact_artifacts.py
    uv run python scripts/rig_relay_compact_artifacts.py --root .build/rig-relay --confirm
    uv run python scripts/rig_relay_compact_artifacts.py --root .build/rig-relay --confirm --dataset cross_session_coordination
    uv run python scripts/rig_relay_compact_artifacts.py --dry-run

Content-light: never reads source code, secrets, or user data.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import duckdb

from rig_relay.core.paths import (
    filter_exportable_artifact_paths,
    refuse_confidential_input,
)
from rig_relay.cli.governance_guard import (
    emit_structured_result,
    require_governed_execution_with_evidence,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"

# ── Raw prefixes that compaction MUST NOT touch ─────────────────────────

RAW_PREFIXES = ("raw", "observability", "events", "tool_artifacts")

# ── Dataset-specific compaction queries ─────────────────────────────────

DATASET_QUERIES: dict[str, str] = {
    "cross_session_coordination_dataset": """
        SELECT
            event_name,
            session_id,
            parent_session_id,
            task_id,
            claim_kind,
            status,
            created_at,
            schema_version
        FROM read_json_auto('{source}')
    """,
    "coordination_conflict_dataset": """
        SELECT
            conflict_id,
            session_id,
            other_session_id,
            task_id,
            status,
            conflict_type,
            created_at,
            recommended_resolution,
            schema_version
        FROM read_json_auto('{source}')
    """,
    "artifact_reuse_dataset": """
        SELECT
            session_id,
            artifact_kind,
            artifact_uri,
            artifact_sha256,
            schema_id,
            reuse_count,
            created_at,
            schema_version
        FROM read_json_auto('{source}')
    """,
    "checkpoint_eval_dataset": """
        SELECT
            session_id,
            task_id,
            commit_sha,
            files_committed,
            pre_commit_head,
            post_commit_head,
            branch,
            created_at,
            schema_version
        FROM read_json_auto('{source}')
    """,
    "findings_dataset": """
        SELECT
            finding_id,
            session_id,
            subsystem,
            severity,
            status,
            created_at,
            schema_version
        FROM read_json_auto('{source}')
    """,
    "semantic_change_snippets": """
        SELECT
            session_id,
            language,
            tool_name,
            snippet_hash,
            change_category,
            estimated_tokens,
            remote_sharing_safe,
            created_at,
            schema_version
        FROM read_json_auto('{source}')
    """,
    "provider_task_performance_dataset": """
        SELECT
            provider,
            model,
            agent_profile,
            task_id,
            session_id,
            status,
            latency_ms,
            total_tokens,
            thinking_enabled,
            created_at,
            schema_version
        FROM read_json_auto('{source}')
    """,
    "tool_failure_patterns_dataset": """
        SELECT
            tool_name,
            status,
            determinism_class,
            model,
            session_id,
            failure_type,
            created_at,
            schema_version
        FROM read_json_auto('{source}')
    """,
}

# ── Rollup SQL: aggregate counts per dataset ────────────────────────────

ROLLUP_QUERIES: dict[str, str] = {
    "cross_session_coordination_dataset": """
        SELECT event_name, status, COUNT(*) AS row_count
        FROM read_parquet('{parquet}')
        GROUP BY event_name, status
        ORDER BY row_count DESC
    """,
    "coordination_conflict_dataset": """
        SELECT conflict_type, status, COUNT(*) AS row_count
        FROM read_parquet('{parquet}')
        GROUP BY conflict_type, status
        ORDER BY row_count DESC
    """,
    "artifact_reuse_dataset": """
        SELECT artifact_kind, COUNT(*) AS row_count, COUNT(DISTINCT session_id) AS unique_sessions
        FROM read_parquet('{parquet}')
        GROUP BY artifact_kind
        ORDER BY row_count DESC
    """,
    "checkpoint_eval_dataset": """
        SELECT branch, COUNT(*) AS row_count, COUNT(DISTINCT session_id) AS unique_sessions
        FROM read_parquet('{parquet}')
        GROUP BY branch
        ORDER BY row_count DESC
    """,
    "findings_dataset": """
        SELECT subsystem, severity, status, COUNT(*) AS row_count
        FROM read_parquet('{parquet}')
        GROUP BY subsystem, severity, status
        ORDER BY row_count DESC
    """,
    "semantic_change_snippets": """
        SELECT language, change_category, COUNT(*) AS row_count
        FROM read_parquet('{parquet}')
        GROUP BY language, change_category
        ORDER BY row_count DESC
    """,
    "provider_task_performance_dataset": """
        SELECT provider, model, status,
               COUNT(*) AS row_count,
               AVG(latency_ms) AS avg_latency_ms,
               AVG(total_tokens) AS avg_tokens
        FROM read_parquet('{parquet}')
        GROUP BY provider, model, status
        ORDER BY row_count DESC
    """,
    "tool_failure_patterns_dataset": """
        SELECT tool_name, determinism_class, failure_type,
               COUNT(*) AS row_count,
               COUNT(DISTINCT session_id) AS unique_sessions
        FROM read_parquet('{parquet}')
        GROUP BY tool_name, determinism_class, failure_type
        ORDER BY row_count DESC
    """,
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _count_jsonl_rows(path: Path) -> int:
    count = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
    except OSError:
        pass
    return count


def _is_raw_dataset(name: str) -> bool:
    """Return True if the dataset name indicates raw data that should not be compacted."""
    return any(name.startswith(p) for p in RAW_PREFIXES)


def _find_compactable_datasets(derived_dir: Path) -> list[dict[str, Any]]:
    """Find JSONL datasets in derived/ that are compactable (not raw, have a query)."""
    if not derived_dir.is_dir():
        return []
    allowed, _reason = refuse_confidential_input(
        derived_dir, "artifact_compaction_derived_dir", REPO_ROOT
    )
    if not allowed:
        return []
    datasets: list[dict[str, Any]] = []
    for f in filter_exportable_artifact_paths(sorted(derived_dir.iterdir()), REPO_ROOT):
        if f.suffix != ".jsonl":
            continue
        stem = f.stem
        if _is_raw_dataset(stem):
            continue
        if stem not in DATASET_QUERIES:
            continue
        parquet_path = f.with_suffix(".parquet")
        datasets.append({
            "name": stem,
            "source": f,
            "parquet_path": parquet_path,
            "parquet_exists": parquet_path.is_file(),
            "size_mb": round(f.stat().st_size / 1_048_576.0, 3),
            "rows": _count_jsonl_rows(f),
        })
    return datasets


def compact_dataset(
    source: Path,
    parquet_path: Path,
    query_template: str,
    rollup_query_template: str | None = None,
) -> dict[str, Any]:
    """Compact one JSONL dataset to Parquet using DuckDB.

    Args:
        source: Path to JSONL file.
        parquet_path: Output Parquet path.
        query_template: DuckDB SQL with {source} placeholder.
        rollup_query_template: Optional rollup SQL with {parquet} placeholder.

    Returns:
        Dict with source_hash, row_count, output_hash, and optional rollup.
    """
    source_hash = _sha256_file(source)
    source_str = str(source)

    # Build DuckDB compaction query
    query = query_template.format(source=source_str)

    con = duckdb.connect()
    try:
        # Create a view and write to parquet
        con.execute(f"CREATE OR REPLACE TEMP VIEW dataset_view AS {query}")
        con.execute(
            f"COPY (SELECT * FROM dataset_view) TO '{parquet_path}' (FORMAT PARQUET)"
        )
        count_row = con.execute("SELECT COUNT(*) FROM dataset_view").fetchone()
        assert count_row is not None, "COUNT(*) returned None"
        row_count = count_row[0]
    finally:
        con.close()

    output_hash = _sha256_file(parquet_path)

    result: dict[str, Any] = {
        "source": source.name,
        "source_sha256": source_hash,
        "source_rows": row_count,
        "output_path": str(parquet_path),
        "output_sha256": output_hash,
        "output_size_bytes": parquet_path.stat().st_size,
        "output_size_mb": round(parquet_path.stat().st_size / 1_048_576.0, 3),
    }

    # Run rollup if template exists
    if rollup_query_template:
        try:
            con2 = duckdb.connect()
            try:
                rollup_sql = rollup_query_template.format(parquet=str(parquet_path))
                rollup_rows = con2.execute(rollup_sql).fetchdf()
                result["rollup"] = json.loads(rollup_rows.to_json(orient="records"))
            finally:
                con2.close()
        except Exception as e:
            result["rollup_error"] = str(e)

    return result


def compact_all(
    root: Path = DEFAULT_BUILD_ROOT,
    dataset_filter: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Compact all eligible datasets.

    Args:
        root: Build root directory.
        dataset_filter: Optional dataset name filter (substring match).
        confirm: If True, actually write Parquet files. If False, dry-run.

    Returns:
        Manifest dict with results.
    """
    derived_dir = root / "derived"
    datasets = _find_compactable_datasets(derived_dir)

    if dataset_filter:
        datasets = [d for d in datasets if dataset_filter in d["name"]]

    if not datasets:
        return {
            "schema_version": "rig.relay.compaction_manifest.v1",
            "build_root": str(root),
            "created_at": datetime.now(UTC).isoformat(),
            "datasets": [],
            "summary": {
                "total_datasets": 0,
                "compacted": 0,
                "skipped": 0,
                "dry_run": not confirm,
            },
            "warnings": ["No compactable datasets found."],
        }

    results: list[dict[str, Any]] = []
    compacted_count = 0
    skipped_count = 0
    warnings: list[str] = []

    for ds in datasets:
        if not confirm:
            # Dry-run: report what would be done
            action = "overwrite" if ds["parquet_exists"] else "create"
            results.append({
                "name": ds["name"],
                "source": str(ds["source"]),
                "size_mb": ds["size_mb"],
                "rows": ds["rows"],
                "parquet_exists": ds["parquet_exists"],
                "action": f"would {action}",
            })
            skipped_count += 1
            continue

        # Actually compact
        try:
            query_template = DATASET_QUERIES[ds["name"]]
            rollup_template = ROLLUP_QUERIES.get(ds["name"])
            result = compact_dataset(
                source=ds["source"],
                parquet_path=ds["parquet_path"],
                query_template=query_template,
                rollup_query_template=rollup_template,
            )
            result["parquet_exists"] = True
            result["action"] = "compacted"
            results.append(result)
            compacted_count += 1
        except Exception as e:
            warnings.append(f"Failed to compact {ds['name']}: {e}")
            results.append({
                "name": ds["name"],
                "source": str(ds["source"]),
                "error": str(e),
                "action": "failed",
            })
            skipped_count += 1

    manifest: dict[str, Any] = {
        "schema_version": "rig.relay.compaction_manifest.v1",
        "build_root": str(root),
        "created_at": datetime.now(UTC).isoformat(),
        "datasets": results,
        "summary": {
            "total_datasets": len(datasets),
            "compacted": compacted_count,
            "skipped": skipped_count,
            "dry_run": not confirm,
        },
        "warnings": warnings,
    }

    # Write rollup_manifest.json
    if confirm and compacted_count > 0:
        manifest_path = derived_dir / "rollup_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8"
        )

    return manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compact derived JSONL datasets to Parquet using DuckDB. "
        "Dry-run by default. Use --execute to write."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_BUILD_ROOT,
        help=f"Build root directory (default: {DEFAULT_BUILD_ROOT})",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="Only compact datasets matching this name (substring match)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report what would be done without writing (default).",
    )
    parser.add_argument(
        "--confirm",
        action="store_false",
        dest="dry_run",
        help="Actually write Parquet files.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Execute artifact compaction. Default is dry-run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit structured JSON output.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    root = args.root
    if not root.is_dir():
        print(f"ERROR: Build root not found: {root}", file=sys.stderr)
        return 1

    confirm = not args.dry_run
    execute = args.execute or confirm

    governed = require_governed_execution_with_evidence(
        script_name="rig_relay_compact_artifacts",
        authority_tier="local_mutation",
        capability_id="artifact_compaction",
        execute_requested=execute,
    )

    if not args.execute and not confirm:
        manifest = compact_all(root=root, dataset_filter=args.dataset, confirm=False)
        print("=== DRY RUN — No files written ===")
        print(
            f"Datasets: {manifest['summary']['total_datasets']} total, "
            f"{manifest['summary']['compacted']} compacted, "
            f"{manifest['summary']['skipped']} skipped"
        )
        for ds in manifest["datasets"]:
            action = ds.get("action", "?")
            name = ds["name"]
            size = ds.get("size_mb", 0)
            rows = ds.get("rows", 0)
            parquet = " (parquet exists)" if ds.get("parquet_exists") else ""
            print(f"  [{action:12s}] {name:45s} {size:.2f} MB ({rows} rows){parquet}")
        for w in manifest["warnings"]:
            print(f"WARNING: {w}")
        if manifest["summary"]["total_datasets"] > 0:
            print()
            print("Run with --execute to write Parquet files.")
        print()
        print("Nothing was written.")
        if args.json:
            r = emit_structured_result(
                script_name="rig_relay_compact_artifacts",
                authority_tier="local_mutation",
                capability_id="artifact_compaction",
                dry_run=True,
                execute_requested=False,
                decision=governed.decision,
                status="dry_run",
            )
            print(json.dumps(r, indent=2))
        return 0

    if not governed.can_execute:
        r = emit_structured_result(
            script_name="rig_relay_compact_artifacts",
            authority_tier="local_mutation",
            capability_id="artifact_compaction",
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="blocked_by_governance",
            can_execute=False,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
        )
        if args.json:
            print(json.dumps(r, indent=2))
        else:
            print(f"BLOCKED: {governed.decision.decision.value}")
            if governed.evidence_status == "persistence_failed":
                print(
                    "  EVIDENCE: persistence failed — compaction blocked (fail-closed)"
                )
        return 1

    manifest = compact_all(root=root, dataset_filter=args.dataset, confirm=True)

    print("=== Compaction Complete ===")
    print(
        f"Datasets: {manifest['summary']['total_datasets']} total, "
        f"{manifest['summary']['compacted']} compacted, "
        f"{manifest['summary']['skipped']} skipped"
    )

    for ds in manifest["datasets"]:
        action = ds.get("action", "?")
        name = ds["name"]
        size = ds.get("size_mb", 0)
        rows = ds.get("rows", 0)
        output_size = ds.get("output_size_mb")
        if output_size is not None:
            print(
                f"  [{action:12s}] {name:45s} {size:.2f} MB → {output_size:.3f} MB ({rows} rows)"
            )
        else:
            parquet = " (parquet exists)" if ds.get("parquet_exists") else ""
            print(f"  [{action:12s}] {name:45s} {size:.2f} MB ({rows} rows){parquet}")

    for w in manifest["warnings"]:
        print(f"WARNING: {w}")

    if args.json:
        r = emit_structured_result(
            script_name="rig_relay_compact_artifacts",
            authority_tier="local_mutation",
            capability_id="artifact_compaction",
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="executed",
            can_execute=True,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
            artifacts=manifest.get("summary"),
        )
        print(json.dumps(r, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

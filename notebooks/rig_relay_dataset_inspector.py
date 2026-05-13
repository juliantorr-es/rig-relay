# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo>=0.10.0",
#     "pandas>=2.0.0",
#     "altair>=5.5.0",
# ]
# ///
# Copyright 2026 Julian Torres. All rights reserved.
# Licensed under Apache-2.0.

"""Rig Relay Dataset Inspector — marimo notebook.

Reads derived datasets from .build/rig-relay/derived/ and provides
interactive filters, tables, and charts for inspecting Rig Relay usage data.

Usage:
    uv run --with-editable . --with marimo --with altair marimo run notebooks/rig_relay_dataset_inspector.py
    uv sync --extra workbench && uv run marimo run notebooks/rig_relay_dataset_inspector.py
"""

from __future__ import annotations

import marimo

__generated_with = "0.10.9"
app = marimo.App(width="full")


# ── Imports ──────────────────────────────────────────────────────────────

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.rig_relay_dataset_inspector_lib as lib  # noqa: E402


# ── Reactive state ───────────────────────────────────────────────────────


@app.cell
def init_state():
    datasets = lib.load_all()
    summary = lib.compute_summary(datasets)
    return datasets, summary


# ── Sidebar: overview ────────────────────────────────────────────────────


@app.cell
def overview(summary):
    import marimo as mo

    items = [
        mo.stat("Sessions", value=str(summary.total_sessions)),
        mo.stat("Coordination", value=str(summary.total_coordination_rows)),
        mo.stat("Conflicts", value=str(summary.total_conflict_rows)),
        mo.stat("Artifact Reuse", value=str(summary.total_artifact_reuse_rows)),
        mo.stat("Checkpoints", value=str(summary.total_checkpoint_rows)),
        mo.stat("Tool Failures", value=str(summary.total_tool_failure_rows)),
        mo.stat("Provider Perf", value=str(summary.total_provider_perf_rows)),
        mo.stat("Findings", value=str(summary.total_finding_rows)),
    ]
    mo.hstack(items, justify="space-around")
    return (items,)


@app.cell
def export_info(summary):
    import marimo as mo

    if summary.export_timestamp:
        mo.md(f"**Export timestamp:** `{summary.export_timestamp}`").callout()
    if summary.export_warnings:
        mo.md(
            "**Manifest warnings:**\n"
            + "\n".join(f"- {w}" for w in summary.export_warnings)
        ).callout(kind="warn")
    if summary.missing_files:
        mo.md(
            "**Missing files:**\n"
            + "\n".join(f"- `{f}`" for f in summary.missing_files)
        ).callout(kind="warn")
    if summary.empty_datasets:
        mo.md(
            "**Empty datasets:**\n"
            + "\n".join(f"- `{d}`" for d in summary.empty_datasets)
        ).callout(kind="neutral")
    if summary.schema_validation_results:
        lines = []
        for name, res in summary.schema_validation_results.items():
            if res.get("errors"):
                lines.append(
                    f"- {name}: {res['valid']}/{res['total']} valid ({len(res['errors'])} errors)"
                )
            else:
                lines.append(f"- {name}: {res['valid']}/{res['total']} valid")
        if lines:
            mo.md("**Schema validation:**\n" + "\n".join(lines)).callout(kind="success")


# ── Filters ──────────────────────────────────────────────────────────────


@app.cell
def filters(datasets):
    import marimo as mo

    coord_sessions = lib.unique_values(datasets.coordination, "session_id")
    coord_event_names = lib.unique_values(datasets.coordination, "event_name")
    tool_names = lib.unique_values(datasets.tool_failures, "tool_name")
    provider_models = lib.unique_values(datasets.provider_perf, "model")
    finding_kinds = lib.unique_values(datasets.findings, "finding_kind")
    finding_severities = lib.unique_values(datasets.findings, "severity")
    checkpoint_statuses = lib.unique_values(datasets.checkpoints, "status")
    artifact_kinds = lib.unique_values(datasets.artifact_reuse, "artifact_kind")

    session_filter = mo.ui.dropdown(
        options=[""] + coord_sessions, value="", label="Session ID"
    )
    event_filter = mo.ui.dropdown(
        options=[""] + coord_event_names, value="", label="Event Name"
    )
    tool_filter = mo.ui.dropdown(options=[""] + tool_names, value="", label="Tool Name")
    model_filter = mo.ui.dropdown(
        options=[""] + provider_models, value="", label="Model"
    )
    severity_filter = mo.ui.dropdown(
        options=[""] + finding_severities, value="", label="Finding Severity"
    )
    kind_filter = mo.ui.dropdown(
        options=[""] + finding_kinds, value="", label="Finding Kind"
    )
    cp_status_filter = mo.ui.dropdown(
        options=[""] + checkpoint_statuses, value="", label="Checkpoint Status"
    )
    artifact_filter = mo.ui.dropdown(
        options=[""] + artifact_kinds, value="", label="Artifact Kind"
    )

    mo.hstack(
        [
            session_filter,
            event_filter,
            tool_filter,
            model_filter,
            severity_filter,
            kind_filter,
            cp_status_filter,
            artifact_filter,
        ],
        justify="space-around",
        wrap=True,
    )
    return (
        artifact_filter,
        artifact_kinds,
        checkpoint_statuses,
        coord_event_names,
        coord_sessions,
        cp_status_filter,
        event_filter,
        finding_kinds,
        finding_severities,
        kind_filter,
        model_filter,
        provider_models,
        session_filter,
        severity_filter,
        tool_filter,
        tool_names,
    )


# ── Coordination Events ──────────────────────────────────────────────────


@app.cell
def coordination_view(datasets, session_filter, event_filter):
    import marimo as mo

    rows = datasets.coordination
    if session_filter.value:
        rows = lib.filter_by_session_id(rows, session_filter.value)
    if event_filter.value:
        rows = lib.filter_by_event_name(rows, event_filter.value)

    mo.md("## Coordination Events")
    if not rows:
        mo.md("*No coordination events.*").callout(kind="neutral")
        return

    counts = lib.count_by_field(rows, "event_name")
    if counts:
        mo.md("### Event Counts")
        mo.ui.table([{"Event Name": k, "Count": v} for k, v in counts], selection=None)
    else:
        mo.md("*No event_name field.*")

    session_counts = lib.count_by_field(rows, "session_id")
    if session_counts:
        mo.md("### Sessions")
        mo.ui.table(
            [{"Session ID": k, "Events": v} for k, v in session_counts[:20]],
            selection=None,
        )

    status_counts = lib.count_by_field(rows, "status")
    if status_counts:
        mo.md("### Status Distribution")
        mo.ui.table(
            [{"Status": k, "Count": v} for k, v in status_counts], selection=None
        )


# ── Coordination Conflicts ───────────────────────────────────────────────


@app.cell
def conflicts_view(datasets):
    import marimo as mo

    mo.md("## Coordination Conflicts")
    if not datasets.conflicts:
        mo.md("*No conflicts reported.*").callout(kind="neutral")
        return

    mo.ui.table(datasets.conflicts, selection=None)


# ── Artifact Reuse ───────────────────────────────────────────────────────


@app.cell
def artifact_view(datasets, artifact_filter):
    import marimo as mo

    rows = datasets.artifact_reuse
    if artifact_filter.value:
        rows = [
            r for r in rows if str(r.get("artifact_kind", "")) == artifact_filter.value
        ]

    mo.md("## Artifact Reuse")
    if not rows:
        mo.md("*No artifact reuse events.*").callout(kind="neutral")
        return

    counts = lib.count_by_field(rows, "artifact_kind")
    if counts:
        mo.md("### By Artifact Kind")
        mo.ui.table(
            [{"Artifact Kind": k, "Count": v} for k, v in counts], selection=None
        )

    mo.md("### Completeness Gaps")
    null_producer = sum(1 for r in rows if r.get("producer_session_id") is None)
    null_consumer = sum(1 for r in rows if r.get("consumer_session_id") is None)
    null_reuse = sum(1 for r in rows if r.get("reuse_kind") is None)
    null_outcome = sum(1 for r in rows if r.get("outcome") is None)
    mo.md(
        f"- Rows missing `producer_session_id`: {null_producer}\n"
        f"- Rows missing `consumer_session_id`: {null_consumer}\n"
        f"- Rows missing `reuse_kind`: {null_reuse}\n"
        f"- Rows missing `outcome`: {null_outcome}\n"
    )

    mo.ui.table(rows[:20], selection=None)


# ── Tool Failures ────────────────────────────────────────────────────────


@app.cell
def tool_failure_view(datasets, tool_filter):
    import marimo as mo

    rows = datasets.tool_failures
    if tool_filter.value:
        rows = lib.filter_by_tool_name(rows, tool_filter.value)

    mo.md("## Tool Failures")
    if not rows:
        mo.md("*No tool failures.*").callout(kind="neutral")
        return

    failure_counts = lib.count_by_field_pair(rows, "tool_name", "status")
    if failure_counts:
        mo.md("### Failures by Tool and Status")
        mo.ui.table(
            [{"Tool": t, "Status": s, "Count": c} for t, s, c in failure_counts],
            selection=None,
        )

    rows_with_warnings = [r for r in rows if r.get("warnings")]
    if rows_with_warnings:
        mo.md("### Warnings")
        mo.ui.table(
            [
                {
                    "Tool": r.get("tool_name", ""),
                    "Status": r.get("status", ""),
                    "Warnings": r.get("warnings", []),
                }
                for r in rows_with_warnings[:20]
            ],
            selection=None,
        )


# ── Provider / Task Performance ──────────────────────────────────────────


@app.cell
def provider_view(datasets, model_filter):
    import marimo as mo

    rows = datasets.provider_perf
    if model_filter.value:
        rows = lib.filter_by_model(rows, model_filter.value)

    mo.md("## Provider / Task Performance")
    if not rows:
        mo.md("*No provider performance data.*").callout(kind="neutral")
        return

    model_counts = lib.count_by_field(rows, "model")
    if model_counts:
        mo.md("### By Model")
        mo.ui.table(
            [{"Model": k, "Requests": v} for k, v in model_counts], selection=None
        )

    if rows and rows[0].get("estimated_tokens") is not None:
        mo.md("### Token Estimates")
        tokens = [
            r["estimated_tokens"] for r in rows if r.get("estimated_tokens") is not None
        ]
        if tokens:
            mo.md(
                f"- Min: {min(tokens):,}\n"
                f"- Max: {max(tokens):,}\n"
                f"- Avg: {sum(tokens) / len(tokens):,.0f}\n"
            )


# ── Checkpoints ──────────────────────────────────────────────────────────


@app.cell
def checkpoint_view(datasets, cp_status_filter):
    import marimo as mo

    rows = datasets.checkpoints
    if cp_status_filter.value:
        rows = [r for r in rows if str(r.get("status", "")) == cp_status_filter.value]

    mo.md("## Checkpoints")
    if not rows:
        mo.md("*No checkpoint events.*").callout(kind="neutral")
        return

    status_counts = lib.count_by_field(rows, "status")
    if status_counts:
        mo.md("### By Status")
        mo.ui.table(
            [{"Status": k, "Count": v} for k, v in status_counts], selection=None
        )

    refused = [r for r in rows if r.get("status") == "refused"]
    if refused:
        refusal_reasons = lib.count_by_field(refused, "refusal_code")
        mo.md("### Refusal Codes")
        mo.ui.table(
            [{"Refusal Code": k, "Count": v} for k, v in refusal_reasons],
            selection=None,
        )

    committed = [r for r in rows if r.get("status") == "committed"]
    if committed:
        files_counts = [
            r.get("files_committed_count")
            for r in committed
            if r.get("files_committed_count") is not None
        ]
        if files_counts:
            mo.md("### Files Committed")
            mo.md(
                f"- Min: {min(files_counts)}\n"
                f"- Max: {max(files_counts)}\n"
                f"- Total: {sum(files_counts)}\n"
            )


# ── Findings ─────────────────────────────────────────────────────────────


@app.cell
def findings_view(datasets, severity_filter, kind_filter):
    import marimo as mo

    rows = datasets.findings
    if severity_filter.value:
        rows = [r for r in rows if str(r.get("severity", "")) == severity_filter.value]
    if kind_filter.value:
        rows = [r for r in rows if str(r.get("finding_kind", "")) == kind_filter.value]

    mo.md("## Findings")
    if not rows:
        mo.md("*No findings.*").callout(kind="neutral")
        return

    sev_counts = lib.count_by_field(rows, "severity")
    if sev_counts:
        mo.md("### By Severity")
        mo.ui.table(
            [{"Severity": k, "Count": v} for k, v in sev_counts], selection=None
        )

    kind_counts = lib.count_by_field(rows, "finding_kind")
    if kind_counts:
        mo.md("### By Kind")
        mo.ui.table([{"Kind": k, "Count": v} for k, v in kind_counts], selection=None)

    area_counts = lib.count_by_field(rows, "repo_area")
    if area_counts:
        mo.md("### By Repo Area")
        mo.ui.table(
            [{"Repo Area": k, "Count": v} for k, v in area_counts], selection=None
        )

    if any(r.get("suggested_slice") for r in rows):
        mo.md("### Suggested Slices")
        mo.ui.table(
            [
                {
                    "Finding ID": r.get("finding_id", ""),
                    "Slice": r.get("suggested_slice", ""),
                }
                for r in rows
                if r.get("suggested_slice")
            ],
            selection=None,
        )


# ── Completeness ─────────────────────────────────────────────────────────


@app.cell
def completeness_view(summary, datasets):
    import marimo as mo

    mo.md("## Dataset Completeness")

    file_status = []
    all_files = [
        "cross_session_coordination_dataset.jsonl",
        "coordination_conflict_dataset.jsonl",
        "artifact_reuse_dataset.jsonl",
        "checkpoint_eval_dataset.jsonl",
        "tool_failure_patterns_dataset.jsonl",
        "provider_task_performance_dataset.jsonl",
        "findings_dataset.jsonl",
        "export_manifest.json",
    ]
    for f in all_files:
        if f in summary.missing_files:
            file_status.append({"File": f, "Status": "❌ Missing"})
        else:
            file_status.append({"File": f, "Status": "✓ Present"})
    mo.ui.table(file_status, selection=None)

    if summary.schema_validation_results:
        mo.md("### Schema Validation Results")
        rows = []
        for name, res in summary.schema_validation_results.items():
            n_errors = len(res.get("errors", []))
            rows.append({
                "Dataset": name,
                "Total": res.get("total", 0),
                "Valid": res.get("valid", 0),
                "Errors": n_errors,
            })
        mo.ui.table(rows, selection=None)


# ── App metadata ─────────────────────────────────────────────────────────


@app.cell
def about():
    import marimo as mo

    mo.md(
        "---\n"
        "**Rig Relay Dataset Inspector** — consumes content-light derived "
        "datasets only. See [Usage Data Doctrine](../docs/governance/usage-data-doctrine.md).\n"
        f"*marimo v{mo.__version__}*"
    )


# ── Coordination Event Chart ─────────────────────────────────────────────


@app.cell
def coordination_chart(datasets):
    import marimo as mo

    data = lib.event_counts_for_chart(datasets)
    if not data:
        mo.md("*No coordination events to chart.*").callout(kind="neutral")
        return

    import altair as alt
    import pandas as pd

    df = pd.DataFrame(data)
    chart = (
        alt
        .Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("event_name:N", sort="-y", title="Event Name"),
            y=alt.Y("count:Q", title="Count"),
        )
        .properties(width=600, height=300, title="Coordination Events by Name")
    )
    mo.ui.altair_chart(chart)


# ── Tool Failures Chart ──────────────────────────────────────────────────


@app.cell
def tool_failure_chart(datasets):
    import marimo as mo

    data = lib.tool_status_counts_for_chart(datasets)
    if not data:
        mo.md("*No tool failure data to chart.*").callout(kind="neutral")
        return

    import altair as alt
    import pandas as pd

    df = pd.DataFrame(data)
    chart = (
        alt
        .Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("tool_name:N", sort="-y", title="Tool"),
            y=alt.Y("count:Q", title="Count"),
            color=alt.Color("status:N", title="Status"),
        )
        .properties(width=600, height=300, title="Tool Failures by Tool and Status")
    )
    mo.ui.altair_chart(chart)


# ── Model Counts Chart ───────────────────────────────────────────────────


@app.cell
def model_chart(datasets):
    import marimo as mo

    data = lib.model_counts_for_chart(datasets)
    if not data:
        mo.md("*No provider performance data to chart.*").callout(kind="neutral")
        return

    import altair as alt
    import pandas as pd

    df = pd.DataFrame(data)
    chart = (
        alt
        .Chart(df)
        .mark_bar(color="steelblue")
        .encode(
            x=alt.X("model:N", sort="-y", title="Model"),
            y=alt.Y("requests:Q", title="Requests"),
        )
        .properties(width=600, height=300, title="Model Request Counts")
    )
    mo.ui.altair_chart(chart)


# ── Findings Severity Chart ──────────────────────────────────────────────


@app.cell
def findings_chart(datasets):
    import marimo as mo

    data = lib.findings_severity_counts_for_chart(datasets)
    if not data:
        mo.md("*No findings data to chart.*").callout(kind="neutral")
        return

    import altair as alt
    import pandas as pd

    df = pd.DataFrame(data)
    chart = (
        alt
        .Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("severity:N", sort="-y", title="Severity"),
            y=alt.Y("count:Q", title="Count"),
            color=alt.Color("severity:N", title="Severity"),
        )
        .properties(width=400, height=250, title="Findings by Severity")
    )
    mo.ui.altair_chart(chart)


# ── Artifact Kind Chart ──────────────────────────────────────────────────


@app.cell
def artifact_chart(datasets):
    import marimo as mo

    data = lib.artifact_kind_counts_for_chart(datasets)
    if not data:
        mo.md("*No artifact reuse data to chart.*").callout(kind="neutral")
        return

    import altair as alt
    import pandas as pd

    df = pd.DataFrame(data)
    chart = (
        alt
        .Chart(df)
        .mark_bar(color="teal")
        .encode(
            x=alt.X("artifact_kind:N", sort="-y", title="Artifact Kind"),
            y=alt.Y("count:Q", title="Count"),
        )
        .properties(width=500, height=250, title="Artifact Reuse by Kind")
    )
    mo.ui.altair_chart(chart)


# ── Checkpoint Status Chart ──────────────────────────────────────────────


@app.cell
def checkpoint_chart(datasets):
    import marimo as mo

    data = lib.checkpoint_status_counts_for_chart(datasets)
    if not data:
        mo.md("*No checkpoint data to chart.*").callout(kind="neutral")
        return

    import altair as alt
    import pandas as pd

    df = pd.DataFrame(data)
    chart = (
        alt
        .Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("status:N", sort="-y", title="Status"),
            y=alt.Y("count:Q", title="Count"),
            color=alt.Color("status:N", title="Status"),
        )
        .properties(width=400, height=250, title="Checkpoint Outcomes")
    )
    mo.ui.altair_chart(chart)


# ── SQL Workbench ────────────────────────────────────────────────────────


@app.cell
def sql_workbench(datasets):
    import marimo as mo

    mo.md("## SQL Workbench")

    if not lib.HAS_DUCKDB:
        mo.md(
            "*DuckDB not available. Install with `uv sync --extra workbench`.*"
        ).callout(kind="warn")
        return

    con, views = lib.create_derived_connection()
    if con is None:
        mo.md(
            "*No derived datasets found. Run `uv run python scripts/rig_relay_dataset_export.py` first.*"
        ).callout(kind="warn")
        return

    mo.md(f"**Available views:** {', '.join(sorted(views))}").callout()

    mo.md("### Canned Queries")
    query_names = list(lib.CANNED_QUERIES.keys())
    _qs = mo.ui.dropdown(options=[""] + query_names, value="", label="Select Query")
    mo.hstack([_qs], justify="start")

    if _qs.value:
        result = lib.run_canned_query(con, _qs.value)
        if result is None:
            mo.md(f"*Query failed or returned no results: {_qs.value}*").callout(
                kind="warn"
            )
        elif not result:
            mo.md("*Query returned 0 rows.*").callout(kind="neutral")
        else:
            mo.md(f"**Results:** {len(result)} rows")
            mo.ui.table(result, selection=None)

    con.close()
    return


if __name__ == "__main__":
    app.run()

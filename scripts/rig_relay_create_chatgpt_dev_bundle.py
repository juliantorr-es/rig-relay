#!/usr/bin/env python3
# ruff: noqa: PLR0912, PLR0914, PLR0915
"""Rig Relay ChatGPT-Friendly Dev Bundle Generator.

Curates a token-budgeted, content-light analysis bundle from available Rig Relay
artifacts. Designed for upload to ChatGPT for analysis.

Usage:
    uv run python scripts/rig_relay_create_chatgpt_dev_bundle.py --profile lite
    uv run python scripts/rig_relay_create_chatgpt_dev_bundle.py --profile analysis --dry-run
    uv run python scripts/rig_relay_create_chatgpt_dev_bundle.py --profile full-dev --strict

Content-light: never includes raw prompts, model outputs, source code,
stdout/stderr bodies, diffs, secrets, or raw private paths.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import uuid
import zipfile

import duckdb
import jsonschema
import tiktoken

from rig_relay.evidence.redaction import (
    assert_remote_safe,
    classify_shareable_field,
    redact_for_remote,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"
DEFAULT_DOCS_ROOT = REPO_ROOT / "docs"
DEFAULT_OUTPUT_DIR = DEFAULT_BUILD_ROOT / "chatgpt-bundles"
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
MANIFEST_SCHEMA_PATH = (
    SCHEMAS_DIR / "rig.relay.chatgpt_dev_bundle_manifest.v1.schema.json"
)

HARD_FILE_LIMIT_MB = 512
MAX_TOKENS_PER_TEXT_FILE = 2_000_000
DEFAULT_MAX_TOKENS = 1_800_000
DEFAULT_TARGET_MB = 100

# ── Forbidden content patterns ──────────────────────────────────────────

FORBIDDEN_TEXT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?i)(-----BEGIN\s+(?:RSA\s+PRIVATE|EC\s+PRIVATE|OPENSSH\s+PRIVATE|PRIVATE)\s+KEY-----)"
    ),
    re.compile(r"(?i)(sk-[A-Za-z0-9_-]{20,})"),
    re.compile(r"(?i)(ghp_[A-Za-z0-9]{36,})"),
    re.compile(r"(?i)(gho_[A-Za-z0-9]{36,})"),
    re.compile(r"(?i)(ghu_[A-Za-z0-9]{36,})"),
    re.compile(r"(?i)(ghs_[A-Za-z0-9]{36,})"),
    re.compile(r"(?i)(ghr_[A-Za-z0-9]{36,})"),
    re.compile(r"(?i)(bearer\s+[A-Za-z0-9\-_.]{20,})"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*['\"][^'\"]+['\"])"),
    re.compile(r"(?i)(api[_-]?token\s*[:=]\s*['\"][^'\"]+['\"])"),
    re.compile(r"(?i)(secret[_-]?key\s*[:=]\s*['\"][^'\"]+['\"])"),
    re.compile(r"(?i)(<\|im_start\|>|<\|user\|>|<\|assistant\|>)"),
    re.compile(
        r"(?i)(model_output_text|raw_prompt_text|raw_file_contents|stdout_bodies|stderr_bodies)"
    ),
    re.compile(r"^diff --git a/", re.MULTILINE),
    re.compile(r"```\s*(stdout|stderr)\s*\n"),
]

# ── Token estimation ──────────────────────────────────────────────


def _estimate_tokens(text: str) -> int:
    """Estimate token count using tiktoken cl100k_base encoding.

    Falls back to approximate heuristic (4 chars per token) if tiktoken
    unexpectedly fails, though tiktoken is a core dependency.
    """
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # Heuristic fallback: ~4 chars per token for English text
        return len(text) // 4


# ── Helpers ──────────────────────────────────────────────────────


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_jsonl(path: Path, max_rows: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        rows.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
                if max_rows > 0 and len(rows) >= max_rows:
                    break
    except OSError:
        pass
    return rows


def _count_jsonl(path: Path) -> int:
    try:
        count = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
    except OSError:
        return 0


def _duckdb_query(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    """Run a DuckDB query and return rows as dicts."""
    try:
        result = con.execute(sql)
        if result is None:
            return []
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]
    except Exception:
        return []


# ── Content-light scanning ───────────────────────────────────────


def _has_forbidden_content(text: str) -> bool:
    """Check text for any forbidden pattern."""
    for pattern in FORBIDDEN_TEXT_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _has_forbidden_field_keys(data: dict[str, Any]) -> bool:
    """Check parsed JSON dict for forbidden field keys at any level."""
    for key in data:
        if classify_shareable_field(str(key), data[key]) == "forbid":
            return True
        if isinstance(data[key], dict):
            if _has_forbidden_field_keys(data[key]):
                return True
    return False


def _check_content_light(data: dict[str, Any]) -> list[str]:
    """Check a dict and its string-serialized form for forbidden content."""
    redacted = redact_for_remote(data)
    issues: list[str] = list(redacted.warnings)
    serialized = json.dumps(redacted.payload, sort_keys=True)
    if _has_forbidden_content(serialized):
        issues.append("forbidden text pattern detected")
    if _has_forbidden_field_keys(data):
        issues.append("forbidden field key detected")
    return issues


# ── DuckDB dataset queries ───────────────────────────────────────


def _query_coordination_summary(build_root: Path) -> dict[str, Any]:
    """Query aggregate summaries from derived coordination dataset."""
    dataset_path = build_root / "derived" / "cross_session_coordination_dataset.jsonl"
    if not dataset_path.is_file():
        return {"available": False}

    con = duckdb.connect()
    try:
        con.execute(
            f"CREATE TABLE coord AS SELECT * FROM read_json_auto('{dataset_path}')"
        )
        _row = con.execute("SELECT COUNT(*) FROM coord").fetchone()
        total = _row[0] if _row else 0
        # Try to get some sample stats
        try:
            _row = con.execute(
                "SELECT COUNT(DISTINCT session_id) FROM coord WHERE session_id IS NOT NULL"
            ).fetchone()
            session_count = _row[0] if _row else 0
        except Exception:
            session_count = 0
        try:
            _row = con.execute(
                "SELECT COUNT(*) FROM coord WHERE event_name LIKE '%conflict%'"
            ).fetchone()
            conflict_count = _row[0] if _row else 0
        except Exception:
            conflict_count = 0
        try:
            _row = con.execute(
                "SELECT COUNT(*) FROM coord WHERE event_name LIKE '%claim%'"
            ).fetchone()
            claim_count = _row[0] if _row else 0
        except Exception:
            claim_count = 0
        con.close()
        return {
            "available": True,
            "total_rows": total,
            "unique_sessions": session_count,
            "conflict_events": conflict_count,
            "claim_events": claim_count,
        }
    except Exception:
        con.close()
        return {"available": False}


def _query_tool_failure_summary(build_root: Path) -> dict[str, Any]:
    """Query tool failure patterns summary."""
    dataset_path = build_root / "derived" / "tool_failure_patterns_dataset.jsonl"
    if not dataset_path.is_file():
        return {"available": False}

    con = duckdb.connect()
    try:
        con.execute(
            f"CREATE TABLE failures AS SELECT * FROM read_json_auto('{dataset_path}')"
        )
        _row = con.execute("SELECT COUNT(*) FROM failures").fetchone()
        total = _row[0] if _row else 0
        try:
            top_tools = [
                dict(r)
                for r in con.execute(
                    "SELECT tool_name, COUNT(*) as count FROM failures "
                    "GROUP BY tool_name ORDER BY count DESC LIMIT 10"
                ).fetchall()
            ]
        except Exception:
            top_tools = []
        con.close()
        return {"available": True, "total_rows": total, "top_failing_tools": top_tools}
    except Exception:
        con.close()
        return {"available": False}


def _query_performance_summary(build_root: Path) -> dict[str, Any]:
    """Query provider/task performance rollup."""
    dataset_path = build_root / "derived" / "provider_task_performance_dataset.jsonl"
    if not dataset_path.is_file():
        return {"available": False}

    con = duckdb.connect()
    try:
        con.execute(
            f"CREATE TABLE perf AS SELECT * FROM read_json_auto('{dataset_path}')"
        )
        _row = con.execute("SELECT COUNT(*) FROM perf").fetchone()
        total = _row[0] if _row else 0
        try:
            _row = con.execute(
                "SELECT AVG(latency_ms) FROM perf WHERE latency_ms IS NOT NULL"
            ).fetchone()
            avg_latency = round(_row[0], 1) if _row and _row[0] is not None else None
        except Exception:
            avg_latency = None
        con.close()
        return {
            "available": True,
            "total_rows": total,
            "avg_latency_ms": round(avg_latency, 1) if avg_latency else None,
        }
    except Exception:
        con.close()
        return {"available": False}


def _query_findings_summary(build_root: Path) -> dict[str, Any]:
    """Query findings summary."""
    dataset_path = build_root / "derived" / "findings_dataset.jsonl"
    if not dataset_path.is_file():
        return {"available": False}
    rows = _load_jsonl(dataset_path, max_rows=0)
    return {"available": True, "total_findings": len(rows)}


def _query_snippets_summary(build_root: Path) -> dict[str, Any]:
    """Query semantic change snippets manifest."""
    manifest_path = build_root / "derived" / "semantic_change_snippets_manifest.json"
    data = _load_json(manifest_path)
    if not data:
        return {"available": False}
    safe = data.get("remote_sharing_safe", False)
    return {
        "available": True,
        "snippet_count": data.get("snippet_count", 0),
        "skipped_count": data.get("skipped_count", 0),
        "forbidden_count": data.get("forbidden_count", 0),
        "remote_sharing_safe": safe,
        "strict_mode": data.get("strict_mode", False),
    }


# ── Bundle structure ─────────────────────────────────────────────


def _build_bundle(
    build_root: Path,
    docs_root: Path,
    profile: str,
    target_mb: int,
    max_text_file_tokens: int,
    strict: bool,
    dry_run: bool,
) -> dict[str, Any]:
    """Build the bundle contents and return manifest data."""
    bundle_id = f"chatgpt-dev-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC)

    # ── Collect data ─────────────────────────────────────────────

    warnings: list[str] = []
    files_to_include: list[dict[str, Any]] = []
    row_counts: dict[str, int] = {}

    current_state = _load_json(build_root / "current_state.json")
    projection = _load_json(build_root / "desktop" / "projection.json")
    export_manifest = _load_json(build_root / "derived" / "export_manifest.json")
    # ready_plan available via source-map.json

    # Saved row counts from export manifest
    if export_manifest:
        row_counts = export_manifest.get("row_counts", {})

    # DuckDB summaries
    coord_summary = _query_coordination_summary(build_root)
    failure_summary = _query_tool_failure_summary(build_root)
    perf_summary = _query_performance_summary(build_root)
    findings_summary = _query_findings_summary(build_root)
    snippets_summary = _query_snippets_summary(build_root)

    # ── Generate README ──────────────────────────────────────────

    readme_text = _generate_readme(bundle_id, profile, now, target_mb)
    readme_bytes = readme_text.encode("utf-8")
    readme_tokens = _estimate_tokens(readme_text)

    if readme_tokens > max_text_file_tokens:
        warnings.append(
            f"README.md exceeds token budget ({readme_tokens} > {max_text_file_tokens})"
        )

    files_to_include.append({
        "path": "README.md",
        "kind": "readme",
        "estimated_tokens": readme_tokens,
        "size_bytes": len(readme_bytes),
        "source": "generated",
        "reason_included": "Bundle overview and inspection guide",
        "sha256": _sha256_bytes(readme_bytes),
    })

    # ── Generate executive summary ───────────────────────────────

    exec_summary = _generate_executive_summary(
        current_state,
        projection,
        coord_summary,
        failure_summary,
        perf_summary,
        findings_summary,
        snippets_summary,
        row_counts,
    )
    exec_text = json.dumps(exec_summary, indent=2, sort_keys=True)
    exec_bytes = exec_text.encode("utf-8")
    exec_tokens = _estimate_tokens(exec_text)

    if exec_tokens > max_text_file_tokens:
        warnings.append(
            f"executive-summary.md exceeds token budget ({exec_tokens} > {max_text_file_tokens})"
        )

    files_to_include.append({
        "path": "executive-summary.json",
        "kind": "json",
        "estimated_tokens": exec_tokens,
        "size_bytes": len(exec_bytes),
        "source": "generated",
        "reason_included": "Key metrics and state at a glance",
        "sha256": _sha256_bytes(exec_bytes),
    })

    # ── Dataset counts ───────────────────────────────────────────

    counts_doc = {
        "row_counts": row_counts,
        "coordination_summary": coord_summary,
        "tool_failure_summary": failure_summary,
        "performance_summary": perf_summary,
        "findings_summary": findings_summary,
        "snippets_summary": snippets_summary,
    }
    counts_text = json.dumps(counts_doc, indent=2, sort_keys=True)
    counts_bytes = counts_text.encode("utf-8")
    counts_tokens = _estimate_tokens(counts_text)

    files_to_include.append({
        "path": "dataset-counts.json",
        "kind": "json",
        "estimated_tokens": counts_tokens,
        "size_bytes": len(counts_bytes),
        "source": "generated",
        "reason_included": "Derived dataset row counts and summaries",
        "sha256": _sha256_bytes(counts_bytes),
    })

    # ── Current state snapshot ───────────────────────────────────

    if current_state:
        cs_text = json.dumps(current_state, indent=2, sort_keys=True)
        cs_bytes = cs_text.encode("utf-8")
        cs_tokens = _estimate_tokens(cs_text)
        files_to_include.append({
            "path": "current-state.json",
            "kind": "json",
            "estimated_tokens": cs_tokens,
            "size_bytes": len(cs_bytes),
            "source": str(build_root / "current_state.json"),
            "reason_included": "Current coordination state snapshot",
            "sha256": _sha256_bytes(cs_bytes),
        })
    else:
        warnings.append("current_state.json not available")

    # ── Schema index ─────────────────────────────────────────────

    schema_index = _build_schema_index(docs_root)
    si_text = schema_index + "\n"
    si_bytes = si_text.encode("utf-8")
    si_tokens = _estimate_tokens(si_text)
    files_to_include.append({
        "path": "schema-index.md",
        "kind": "md",
        "estimated_tokens": si_tokens,
        "size_bytes": len(si_bytes),
        "source": "generated",
        "reason_included": "Reference for schema IDs and counts",
        "sha256": _sha256_bytes(si_bytes),
    })

    # ── Source map ───────────────────────────────────────────────

    source_map = _build_source_map(build_root)
    sm_text = json.dumps(source_map, indent=2, sort_keys=True)
    sm_bytes = sm_text.encode("utf-8")
    sm_tokens = _estimate_tokens(sm_text)
    files_to_include.append({
        "path": "source-map.json",
        "kind": "json",
        "estimated_tokens": sm_tokens,
        "size_bytes": len(sm_bytes),
        "source": "generated",
        "reason_included": "Map of available artifacts and their status",
        "sha256": _sha256_bytes(sm_bytes),
    })

    # ── Profile-specific data ────────────────────────────────────

    if profile in {"analysis", "full-dev"}:
        # Latest findings (capped)
        findings_path = build_root / "derived" / "findings_dataset.jsonl"
        if findings_path.is_file():
            max_findings = 200 if profile == "analysis" else 1000
            findings_rows = _load_jsonl(findings_path, max_rows=max_findings)
            findings_text = "\n".join(
                json.dumps(r, sort_keys=True) for r in findings_rows
            )
            if findings_text:
                findings_text += "\n"
            findings_bytes = findings_text.encode("utf-8")
            findings_tokens = _estimate_tokens(findings_text)
            if findings_tokens <= max_text_file_tokens:
                files_to_include.append({
                    "path": "latest-findings.jsonl",
                    "kind": "jsonl",
                    "estimated_tokens": findings_tokens,
                    "size_bytes": len(findings_bytes),
                    "source": str(findings_path),
                    "reason_included": f"Latest {len(findings_rows)} findings rows (capped)",
                    "sha256": _sha256_bytes(findings_bytes),
                })

        # Latest coordination rows (capped)
        coord_path = build_root / "derived" / "cross_session_coordination_dataset.jsonl"
        if coord_path.is_file():
            max_coord = 1000 if profile == "analysis" else 5000
            coord_rows = _load_jsonl(coord_path, max_rows=max_coord)
            coord_text = "\n".join(json.dumps(r, sort_keys=True) for r in coord_rows)
            if coord_text:
                coord_text += "\n"
            coord_bytes = coord_text.encode("utf-8")
            coord_tokens = _estimate_tokens(coord_text)
            if coord_tokens <= max_text_file_tokens:
                files_to_include.append({
                    "path": "latest-coordination-rows.jsonl",
                    "kind": "jsonl",
                    "estimated_tokens": coord_tokens,
                    "size_bytes": len(coord_bytes),
                    "source": str(coord_path),
                    "reason_included": f"Latest {len(coord_rows)} coordination rows (capped)",
                    "sha256": _sha256_bytes(coord_bytes),
                })

        # Semantic change snippets sample
        snippets_safe = snippets_summary.get("remote_sharing_safe", False)
        snippets_path = build_root / "derived" / "semantic_change_snippets.jsonl"
        if snippets_path.is_file() and snippets_safe:
            max_snippets = 50 if profile == "analysis" else 200
            snippet_rows = _load_jsonl(snippets_path, max_rows=max_snippets)
            snippet_text = "\n".join(
                json.dumps(r, sort_keys=True) for r in snippet_rows
            )
            if snippet_text:
                snippet_text += "\n"
            snippet_bytes = snippet_text.encode("utf-8")
            snippet_tokens = _estimate_tokens(snippet_text)
            if snippet_tokens <= max_text_file_tokens:
                files_to_include.append({
                    "path": "latest-semantic-change-snippets.jsonl",
                    "kind": "jsonl",
                    "estimated_tokens": snippet_tokens,
                    "size_bytes": len(snippet_bytes),
                    "source": str(snippets_path),
                    "reason_included": f"Latest {len(snippet_rows)} snippets (capped, safe={snippets_safe})",
                    "sha256": _sha256_bytes(snippet_bytes),
                })
        elif snippets_path.is_file() and not snippets_safe:
            warnings.append(
                "Semantic snippets available but remote_sharing_safe=false; excluded"
            )

        # Tool failure rows (capped)
        failure_path = build_root / "derived" / "tool_failure_patterns_dataset.jsonl"
        if failure_path.is_file():
            max_fail = 200 if profile == "analysis" else 1000
            fail_rows = _load_jsonl(failure_path, max_rows=max_fail)
            fail_text = "\n".join(json.dumps(r, sort_keys=True) for r in fail_rows)
            if fail_text:
                fail_text += "\n"
            fail_bytes = fail_text.encode("utf-8")
            fail_tokens = _estimate_tokens(fail_text)
            if fail_tokens <= max_text_file_tokens:
                files_to_include.append({
                    "path": "latest-tool-failure-rows.jsonl",
                    "kind": "jsonl",
                    "estimated_tokens": fail_tokens,
                    "size_bytes": len(fail_bytes),
                    "source": str(failure_path),
                    "reason_included": f"Latest {len(fail_rows)} tool failure rows (capped)",
                    "sha256": _sha256_bytes(fail_bytes),
                })

    # ── Content-light scan ───────────────────────────────────────

    # ── Token budget check ───────────────────────────────────────
    total_tokens = sum(f["estimated_tokens"] for f in files_to_include)
    total_text_bytes = sum(f["size_bytes"] for f in files_to_include)

    # Check if any single file exceeds max_tokens
    for f in files_to_include:
        if f["estimated_tokens"] > max_text_file_tokens:
            warnings.append(
                f"{f['path']}: {f['estimated_tokens']} tokens exceeds limit "
                f"({max_text_file_tokens})"
            )

    # Check if total would exceed hard zip limit (rough estimate)
    # Zip ratio is ~3:1 for JSON, use 2:1 as conservative estimate
    estimated_zip_bytes = total_text_bytes // 2
    chatgpt_safe = (
        all(f["estimated_tokens"] <= MAX_TOKENS_PER_TEXT_FILE for f in files_to_include)
        and estimated_zip_bytes <= HARD_FILE_LIMIT_MB * 1_000_000
    )

    if estimated_zip_bytes > HARD_FILE_LIMIT_MB * 1_000_000:
        warnings.append(
            f"Estimated zip size ({estimated_zip_bytes // 1_000_000} MB) "
            f"exceeds hard limit ({HARD_FILE_LIMIT_MB} MB)"
        )

    if not chatgpt_safe:
        warnings.append("Bundle exceeds ChatGPT upload constraints")

    # ── Assemble manifest ────────────────────────────────────────
    excluded_patterns = [
        "raw/logs/*",
        "raw/artifacts/*",
        "raw/observability/*",
        "*.diff",
        "*.patch",
        "raw_prompt*",
        "model_output*",
        "secrets/*",
        "stdout*",
        "stderr*",
        "private_keys*",
        "source_code/*",
        ".git/*",
        "node_modules/*",
        "__pycache__/*",
    ]

    manifest: dict[str, Any] = {
        "schema_version": "rig.relay.chatgpt_dev_bundle_manifest.v1",
        "bundle_id": bundle_id,
        "created_at": now.isoformat(),
        "profile": profile,
        "source_root": str(build_root.resolve()),
        "output_zip": "",
        "estimated_total_tokens": total_tokens,
        "estimated_total_text_bytes": total_text_bytes,
        "zip_size_bytes": 0,
        "chatgpt_upload_safe": chatgpt_safe,
        "hard_file_limit_mb": HARD_FILE_LIMIT_MB,
        "target_bundle_mb": target_mb,
        "max_tokens_per_text_file": max_text_file_tokens,
        "included_files": files_to_include,
        "excluded_files": excluded_patterns,
        "row_counts": row_counts,
        "warnings": warnings,
        "content_light_guarantee": True,
    }
    assert_remote_safe(manifest)

    return manifest


# ── ZIP writer ──────────────────────────────────────────────────


def _write_zip(manifest: dict[str, Any], output_dir: Path, dry_run: bool) -> Path:
    """Write the bundle files to a zip archive."""
    bundle_id = manifest["bundle_id"]
    profile = manifest["profile"]
    now_str = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    zip_name = f"rig-relay-dev-bundle-{profile}-{now_str}-{bundle_id[:8]}.zip"
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / zip_name

    if dry_run:
        return zip_path

    # Re-generate content for each included file
    readme_text = _generate_readme(
        bundle_id, profile, datetime.now(UTC), manifest["target_bundle_mb"]
    )

    exec_summary_data: dict[str, Any] = {}
    counts_data: dict[str, Any] = {}
    current_state_data: dict[str, Any] = {}
    schema_index_text = ""
    source_map_data: dict[str, Any] = {}
    findings_rows: list[dict[str, Any]] = []
    coord_rows: list[dict[str, Any]] = []
    snippet_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []

    # Pre-collect generated content for the zip
    for f in manifest["included_files"]:
        if f["path"] == "README.md":
            readme_text = _generate_readme(
                bundle_id, profile, datetime.now(UTC), manifest["target_bundle_mb"]
            )
        elif f["path"] == "executive-summary.json":
            # Parse from manifest? Actually we need to reference the data again
            pass

    # Re-generate all content for zip
    build_root = Path(manifest["source_root"])

    current_state = _load_json(build_root / "current_state.json")
    projection = _load_json(build_root / "desktop" / "projection.json")
    export_manifest = _load_json(build_root / "derived" / "export_manifest.json")
    row_counts = export_manifest.get("row_counts", {}) if export_manifest else {}

    coord_summary = _query_coordination_summary(build_root)
    failure_summary = _query_tool_failure_summary(build_root)
    perf_summary = _query_performance_summary(build_root)
    findings_summary = _query_findings_summary(build_root)
    snippets_summary = _query_snippets_summary(build_root)

    exec_summary_data = _generate_executive_summary(
        current_state,
        projection,
        coord_summary,
        failure_summary,
        perf_summary,
        findings_summary,
        snippets_summary,
        row_counts,
    )

    counts_data = {
        "row_counts": row_counts,
        "coordination_summary": coord_summary,
        "tool_failure_summary": failure_summary,
        "performance_summary": perf_summary,
        "findings_summary": findings_summary,
        "snippets_summary": snippets_summary,
    }

    if current_state:
        current_state_data = current_state

    schema_index_text = _build_schema_index(Path(REPO_ROOT / "docs"))
    source_map_data = _build_source_map(build_root)

    if manifest["profile"] in {"analysis", "full-dev"}:
        cap_findings = 200 if manifest["profile"] == "analysis" else 1000
        findings_rows = (
            _load_jsonl(
                build_root / "derived" / "findings_dataset.jsonl", max_rows=cap_findings
            )
            if (build_root / "derived" / "findings_dataset.jsonl").is_file()
            else []
        )

        cap_coord = 1000 if manifest["profile"] == "analysis" else 5000
        coord_rows = (
            _load_jsonl(
                build_root / "derived" / "cross_session_coordination_dataset.jsonl",
                max_rows=cap_coord,
            )
            if (
                build_root / "derived" / "cross_session_coordination_dataset.jsonl"
            ).is_file()
            else []
        )

        snippets_safe = snippets_summary.get("remote_sharing_safe", False)
        cap_snippets = 50 if manifest["profile"] == "analysis" else 200
        snippet_rows = (
            _load_jsonl(
                build_root / "derived" / "semantic_change_snippets.jsonl",
                max_rows=cap_snippets,
            )
            if (build_root / "derived" / "semantic_change_snippets.jsonl").is_file()
            and snippets_safe
            else []
        )

        cap_fail = 200 if manifest["profile"] == "analysis" else 1000
        failure_rows = (
            _load_jsonl(
                build_root / "derived" / "tool_failure_patterns_dataset.jsonl",
                max_rows=cap_fail,
            )
            if (
                build_root / "derived" / "tool_failure_patterns_dataset.jsonl"
            ).is_file()
            else []
        )

    # Write zip
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # README
        readme_bytes = readme_text.encode("utf-8")
        zf.writestr("README.md", readme_bytes)
        # Manifest
        manifest_copy = dict(manifest)
        manifest_copy["output_zip"] = str(zip_path.resolve())
        manifest_copy = assert_remote_safe(manifest_copy)
        zf.writestr(
            "manifest.json",
            json.dumps(manifest_copy, indent=2, sort_keys=True, ensure_ascii=False),
        )
        # Executive summary
        zf.writestr(
            "executive-summary.json",
            json.dumps(exec_summary_data, indent=2, sort_keys=True, ensure_ascii=False),
        )
        # Dataset counts
        zf.writestr(
            "dataset-counts.json",
            json.dumps(counts_data, indent=2, sort_keys=True, ensure_ascii=False),
        )
        # Current state
        if current_state_data:
            zf.writestr(
                "current-state.json",
                json.dumps(
                    current_state_data, indent=2, sort_keys=True, ensure_ascii=False
                ),
            )
        # Schema index
        zf.writestr("schema-index.md", schema_index_text)
        # Source map
        zf.writestr(
            "source-map.json",
            json.dumps(source_map_data, indent=2, sort_keys=True, ensure_ascii=False),
        )
        # Profile-specific JSONL
        if findings_rows:
            findings_text = (
                "\n".join(json.dumps(r, sort_keys=True) for r in findings_rows) + "\n"
            )
            zf.writestr("latest-findings.jsonl", findings_text.encode("utf-8"))
        if coord_rows:
            coord_text = (
                "\n".join(json.dumps(r, sort_keys=True) for r in coord_rows) + "\n"
            )
            zf.writestr("latest-coordination-rows.jsonl", coord_text.encode("utf-8"))
        if snippet_rows:
            snippet_text = (
                "\n".join(json.dumps(r, sort_keys=True) for r in snippet_rows) + "\n"
            )
            zf.writestr(
                "latest-semantic-change-snippets.jsonl", snippet_text.encode("utf-8")
            )
        if failure_rows:
            fail_text = (
                "\n".join(json.dumps(r, sort_keys=True) for r in failure_rows) + "\n"
            )
            zf.writestr("latest-tool-failure-rows.jsonl", fail_text.encode("utf-8"))

    # Update manifest with actual zip size
    actual_zip_bytes = zip_path.stat().st_size
    manifest["zip_size_bytes"] = actual_zip_bytes
    manifest["chatgpt_upload_safe"] = (
        all(
            f["estimated_tokens"] <= MAX_TOKENS_PER_TEXT_FILE
            for f in manifest["included_files"]
        )
        and actual_zip_bytes <= HARD_FILE_LIMIT_MB * 1_000_000
    )
    if not manifest["chatgpt_upload_safe"]:
        if "Bundle exceeds ChatGPT upload constraints" not in manifest["warnings"]:
            manifest["warnings"].append("Bundle exceeds ChatGPT upload constraints")

    return zip_path


# ── Content generators ──────────────────────────────────────────


def _generate_readme(
    bundle_id: str, profile: str, now: datetime, target_mb: int
) -> str:
    """Generate GPT-friendly README.md."""
    profile_desc = {
        "lite": (
            "Lightweight overview with key metrics, dataset counts, schema index, "
            "and executive summary. Under 25 MB."
        ),
        "analysis": (
            "Analysis-grade bundle with sampled derived data, findings, coordination "
            "rows, and tool failure patterns. Under 100 MB."
        ),
        "full-dev": (
            "Comprehensive dev bundle with all available content-light derived datasets "
            "that fit the budget. Under 250 MB."
        ),
    }.get(profile, "Custom bundle profile.")

    return f"""# Rig Relay Dev Bundle — {profile} profile

**Bundle ID:** {bundle_id}
**Generated:** {now.isoformat()}
**Profile:** {profile}
**Target size:** {target_mb} MB

## What this is

This is a curated, token-budgeted, content-light analysis bundle of Rig Relay
structured data. It is designed for upload to ChatGPT for analysis.

{profile_desc}

## What to inspect first

1. **`executive-summary.json`** — Key metrics and state overview
2. **`dataset-counts.json`** — Row counts and derived dataset summaries
3. **`manifest.json`** — Full manifest with token estimates, included files, and warnings
4. **`current-state.json`** — Current coordination state snapshot
5. **`source-map.json`** — Map of available artifacts and their status

## What is intentionally excluded

- **Raw prompts**: No user or assistant prompts
- **Raw model outputs**: No model-generated text
- **Raw source code**: No source code files
- **stdout/stderr bodies**: No command output
- **Diffs and patches**: No file diffs or patch files
- **Secrets and keys**: No API keys, tokens, or private keys
- **Raw observability logs**: No raw `observability.jsonl` files
- **Full coordination event stream**: Only sampled/capped derived rows
- **Schema files**: Only schema index (schema JSON files excluded)
- **Governance docs**: Excluded to keep bundle focused (reference the repo)

## Content-light guarantee

This bundle contains NO raw prompts, NO raw model outputs, NO source code,
NO stdout/stderr bodies, NO diffs, and NO secrets. All data is content-light:
counts, hashes, statuses, schema IDs, event names, and structured summaries.

## File structure

```
chatgpt-bundle/
  README.md              — This file
  manifest.json          — Full manifest with token estimates and warnings
  executive-summary.json — Key metrics and state at a glance
  dataset-counts.json    — Row counts and derived dataset summaries
  current-state.json     — Current coordination state snapshot
  schema-index.md        — Reference of all available schemas
  source-map.json        — Map of artifacts and their status
  latest-findings.jsonl  — (profile+) Latest findings rows
  latest-coordination-rows.jsonl  — (profile+) Latest coordination rows
  latest-semantic-change-snippets.jsonl  — (profile+) Latest snippets
  latest-tool-failure-rows.jsonl  — (profile+) Latest tool failure rows
```

## See also

- [Rig Relay repository](https://github.com/juliantorr-es/rig-relay)
- [docs/governance/usage-data-doctrine.md](https://github.com/juliantorr-es/rig-relay/blob/main/docs/governance/usage-data-doctrine.md)
"""


def _generate_executive_summary(
    current_state: dict[str, Any] | None,
    projection: dict[str, Any] | None,
    coord_summary: dict[str, Any],
    failure_summary: dict[str, Any],
    perf_summary: dict[str, Any],
    findings_summary: dict[str, Any],
    snippets_summary: dict[str, Any],
    row_counts: dict[str, Any],
) -> dict[str, Any]:
    """Generate structured executive summary."""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "coordination_state": {
            "active_children": (
                current_state.get("summary", {}).get("active_children", 0)
                if current_state
                else 0
            ),
            "conflicts": (
                current_state.get("summary", {}).get("conflicts", 0)
                if current_state
                else 0
            ),
            "stale_leases": (
                current_state.get("summary", {}).get("stale_leases", 0)
                if current_state
                else 0
            ),
            "checkpoint_commits": (
                current_state.get("summary", {}).get("checkpoint_commits", 0)
                if current_state
                else 0
            ),
            "checkpoint_refusals": (
                current_state.get("summary", {}).get("checkpoint_refusals", 0)
                if current_state
                else 0
            ),
        },
        "coordination_dataset": coord_summary,
        "tool_failures": failure_summary,
        "provider_performance": perf_summary,
        "findings": findings_summary,
        "semantic_snippets": snippets_summary,
        "derived_dataset_row_counts": {k: v for k, v in sorted(row_counts.items())},
        "projection_source_availability": (
            {k: v for k, v in projection.get("source_status", {}).items()}
            if projection
            else {}
        ),
    }


def _build_schema_index(docs_root: Path) -> str:
    """Build a Markdown index of available schemas."""
    schemas_dir = docs_root / "schemas"
    if not schemas_dir.is_dir():
        return "No schemas directory found.\n"

    schemas = sorted(schemas_dir.glob("*.json"))
    lines = ["# Schema Index", "", f"Total schemas: {len(schemas)}", ""]
    for s in schemas:
        lines.append(f"- `{s.name}`")
    lines.append("")
    return "\n".join(lines)


def _build_source_map(build_root: Path) -> dict[str, Any]:
    """Build a map of available artifacts and their status."""
    sources: dict[str, Any] = {}

    checks = [
        (
            "current_state.json",
            build_root / "current_state.json",
            "Coordination state snapshot",
        ),
        (
            "desktop/projection.json",
            build_root / "desktop" / "projection.json",
            "Desktop projection",
        ),
        (
            "queue/ready_plan.json",
            build_root / "queue" / "ready_plan.json",
            "Queue ready plan",
        ),
        (
            "derived/export_manifest.json",
            build_root / "derived" / "export_manifest.json",
            "Export manifest",
        ),
        (
            "derived/cross_session_coordination_dataset.jsonl",
            build_root / "derived" / "cross_session_coordination_dataset.jsonl",
            "Coordination dataset",
        ),
        (
            "derived/tool_failure_patterns_dataset.jsonl",
            build_root / "derived" / "tool_failure_patterns_dataset.jsonl",
            "Tool failure patterns",
        ),
        (
            "derived/provider_task_performance_dataset.jsonl",
            build_root / "derived" / "provider_task_performance_dataset.jsonl",
            "Provider performance",
        ),
        (
            "derived/findings_dataset.jsonl",
            build_root / "derived" / "findings_dataset.jsonl",
            "Findings dataset",
        ),
        (
            "derived/artifact_reuse_dataset.jsonl",
            build_root / "derived" / "artifact_reuse_dataset.jsonl",
            "Artifact reuse dataset",
        ),
        (
            "derived/checkpoint_eval_dataset.jsonl",
            build_root / "derived" / "checkpoint_eval_dataset.jsonl",
            "Checkpoint eval dataset",
        ),
        (
            "derived/semantic_change_snippets.jsonl",
            build_root / "derived" / "semantic_change_snippets.jsonl",
            "Semantic change snippets",
        ),
        (
            "derived/semantic_change_snippets_manifest.json",
            build_root / "derived" / "semantic_change_snippets_manifest.json",
            "Snippet manifest",
        ),
        (
            "reports/dataset-summary.md",
            build_root / "reports" / "dataset-summary.md",
            "Dataset summary report",
        ),
    ]

    for name, path, description in checks:
        sources[name] = {
            "available": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else 0,
            "description": description,
        }

    return {
        "build_root": str(build_root.resolve()),
        "sources": sources,
        "checked_at": datetime.now(UTC).isoformat(),
    }


# ── CLI ─────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rig Relay ChatGPT-Friendly Dev Bundle Generator"
    )
    parser.add_argument(
        "--build-root",
        type=Path,
        default=DEFAULT_BUILD_ROOT,
        help="Path to .build/rig-relay directory",
    )
    parser.add_argument(
        "--docs-root",
        type=Path,
        default=DEFAULT_DOCS_ROOT,
        help="Path to docs/ directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for generated bundles",
    )
    parser.add_argument(
        "--profile",
        choices=["lite", "analysis", "full-dev"],
        default="lite",
        help="Bundle profile (default: lite)",
    )
    parser.add_argument(
        "--target-mb",
        type=int,
        default=DEFAULT_TARGET_MB,
        help=f"Target bundle size in MB (default: {DEFAULT_TARGET_MB})",
    )
    parser.add_argument(
        "--max-text-file-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Max tokens per text file (default: {DEFAULT_MAX_TOKENS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned contents without writing zip",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on forbidden content or budget violations",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    manifest = _build_bundle(
        build_root=args.build_root,
        docs_root=args.docs_root,
        profile=args.profile,
        target_mb=args.target_mb,
        max_text_file_tokens=args.max_text_file_tokens,
        strict=args.strict,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        _print_summary(manifest)
        return 0 if not args.strict else _check_strict(manifest)

    zip_path = _write_zip(manifest, args.output_dir, dry_run=False)

    # Validate manifest against schema
    schema = _load_json(MANIFEST_SCHEMA_PATH)
    if schema:
        try:
            jsonschema.validate(manifest, schema)
        except jsonschema.ValidationError as e:
            print(f"WARNING: Manifest schema validation failed: {e}")

    print(f"Bundle written to {zip_path}")
    print(f"  Profile: {args.profile}")
    print(f"  Files: {len(manifest['included_files'])}")
    print(f"  Estimated tokens: {manifest['estimated_total_tokens']:,}")
    print(
        f"  Zip size: {manifest['zip_size_bytes']:,} bytes "
        f"({manifest['zip_size_bytes'] / 1_000_000:.1f} MB)"
    )
    print(f"  ChatGPT safe: {manifest['chatgpt_upload_safe']}")
    print(f"  Warnings: {len(manifest['warnings'])}")
    for w in manifest["warnings"]:
        print(f"    ! {w}")

    if args.strict:
        return _check_strict(manifest)

    return 0


def _print_summary(manifest: dict[str, Any]) -> None:
    """Print dry-run summary."""
    print(f"Bundle: {manifest['bundle_id']}")
    print(f"  Profile: {manifest['profile']}")
    print(f"  Generated at: {manifest['created_at']}")
    print(f"  Estimated total tokens: {manifest['estimated_total_tokens']:,}")
    print(f"  Estimated text bytes: {manifest['estimated_total_text_bytes']:,}")
    print(f"  ChatGPT upload safe: {manifest['chatgpt_upload_safe']}")
    print(f"  Target bundle: {manifest['target_bundle_mb']} MB")
    print()
    print("Included files:")
    for f in manifest["included_files"]:
        print(
            f"  [{f['kind']:8s}] {f['path']:45s} "
            f"{f['estimated_tokens']:>8,} tokens  {f['size_bytes']:>8,} bytes"
        )
    print()
    print("Row counts:")
    for name, count in sorted(manifest["row_counts"].items()):
        print(f"  {name}: {count}")
    print()
    if manifest["warnings"]:
        print("Warnings:")
        for w in manifest["warnings"]:
            print(f"  ! {w}")
    print()
    print("Excluded patterns:")
    for p in manifest["excluded_files"]:
        print(f"  - {p}")


def _check_strict(manifest: dict[str, Any]) -> int:
    """Return non-zero if strict mode detects issues."""
    issues = 0
    if not manifest["content_light_guarantee"]:
        print("ERROR (strict): content_light_guarantee is false")
        issues += 1
    for w in manifest["warnings"]:
        print(f"ERROR (strict): {w}")
        issues += 1
    return 1 if issues > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())

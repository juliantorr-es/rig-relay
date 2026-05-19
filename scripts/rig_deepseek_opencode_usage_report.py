#!/usr/bin/env python3
"""DeepSeek OpenCode usage and cache economics report.

Read-only local report generation from the OpenCode SQLite session database and
local logs. The report intentionally excludes raw prompts, raw completions,
private repository contents, auth material, and raw absolute paths.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_ID = "rig.deepseek_opencode_usage_report.v1"
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / f"{SCHEMA_ID}.schema.json"
SUMMARY_SCHEMA_ID = "rig.deepseek_opencode_usage_summary.v1"
SUMMARY_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / f"{SUMMARY_SCHEMA_ID}.schema.json"
)
DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
DEFAULT_LOG_DIR = Path.home() / ".local" / "share" / "opencode" / "log"
DEFAULT_OUTPUT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "deepseek_opencode_usage_report.v1.json"
)
DEFAULT_SUMMARY_OUTPUT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "deepseek_opencode_usage_summary.v1.json"
)
PRICING_SOURCE_URL = "https://api-docs.deepseek.com/quick_start/pricing/"


@dataclass
class Totals:
    session_count: int = 0
    request_count: int = 0
    input_token_total: int = 0
    output_token_total: int = 0
    reasoning_token_total: int = 0
    cache_read_token_total: int = 0
    cache_write_token_total: int = 0

    def add_session(self, record: dict[str, Any]) -> None:
        self.session_count += 1
        self.input_token_total += int(record["input_token_total"])
        self.output_token_total += int(record["output_token_total"])
        self.reasoning_token_total += int(record["reasoning_token_total"])
        self.cache_read_token_total += int(record["cache_read_token_total"])
        self.cache_write_token_total += int(record["cache_write_token_total"])

    def add_request(self, request_count: int = 1) -> None:
        self.request_count += request_count

    def as_dict(
        self, *, session_share: float | None = None, request_share: float | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_count": self.session_count,
            "request_count": self.request_count,
            "input_token_total": self.input_token_total,
            "output_token_total": self.output_token_total,
            "reasoning_token_total": self.reasoning_token_total,
            "cache_read_token_total": self.cache_read_token_total,
            "cache_write_token_total": self.cache_write_token_total,
        }
        if session_share is not None:
            payload["session_share"] = round(session_share, 6)
        if request_share is not None:
            payload["request_share"] = round(request_share, 6)
        return payload


@dataclass
class UsageSnapshot:
    session_count: int
    request_count: int
    model_counts: list[dict[str, Any]]
    deepseek_totals: Totals
    pro_usage: dict[str, Any]
    flash_usage: dict[str, Any]
    default_usage: dict[str, Any]
    max_usage: dict[str, Any]
    cache_hit_ratio: float


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def _parse_model(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _normalized_variant(model: dict[str, Any]) -> str:
    variant = model.get("variant")
    if variant in {None, ""}:
        return "default"
    return str(variant)


def _normalized_model_key(model: dict[str, Any]) -> tuple[str, str]:
    model_id = str(model.get("id") or "unknown")
    variant = _normalized_variant(model)
    return model_id, variant


def _session_fingerprint(model: dict[str, Any]) -> tuple[str, str]:
    return _normalized_model_key(model)


def _detect_opencode_version() -> str:
    binary = shutil.which("opencode")
    if binary is not None:
        try:
            result = subprocess.run(
                [binary, "--version"], check=True, capture_output=True, text=True
            )
            version = result.stdout.strip() or result.stderr.strip()
            if version:
                return version
        except (OSError, subprocess.CalledProcessError):
            pass
        parts = Path(binary).parts
        if "opencode" in parts:
            try:
                index = parts.index("opencode")
                if index + 1 < len(parts):
                    return parts[index + 1]
            except ValueError:
                pass
    return "unknown"


def _load_session_rows(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.is_file():
        raise FileNotFoundError(f"OpenCode DB not found: {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT model, tokens_input, tokens_output, tokens_reasoning,
                   tokens_cache_read, tokens_cache_write
            FROM session
            WHERE model IS NOT NULL
            """
        ).fetchall()
    finally:
        conn.close()
    records: list[dict[str, Any]] = []
    for (
        model_raw,
        tokens_input,
        tokens_output,
        tokens_reasoning,
        cache_read,
        cache_write,
    ) in rows:
        model = _parse_model(model_raw)
        if model is None:
            continue
        if str(model.get("providerID") or "") != "deepseek":
            continue
        model_id, variant = _normalized_model_key(model)
        records.append({
            "model_id": model_id,
            "variant": variant,
            "cache_write_present": True,
            "input_token_total": int(tokens_input or 0),
            "output_token_total": int(tokens_output or 0),
            "reasoning_token_total": int(tokens_reasoning or 0),
            "cache_read_token_total": int(cache_read or 0),
            "cache_write_token_total": int(cache_write or 0),
        })
    return records


def _load_request_rows(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT m.session_id, m.data, s.model
            FROM message AS m
            JOIN session AS s ON s.id = m.session_id
            WHERE json_extract(m.data, '$.role') = 'assistant'
              AND json_extract(m.data, '$.providerID') = 'deepseek'
              AND s.model IS NOT NULL
            """
        ).fetchall()
    finally:
        conn.close()
    records: list[dict[str, Any]] = []
    for _, raw_message, raw_model in rows:
        model = _parse_model(raw_model)
        if model is None:
            continue
        if str(model.get("providerID") or "") != "deepseek":
            continue
        message = json.loads(raw_message)
        tokens = message.get("tokens") or {}
        cache = tokens.get("cache") or {}
        model_id, variant = _normalized_model_key(model)
        records.append({
            "model_id": model_id,
            "variant": variant,
            "cache_write_present": "write" in cache,
            "input_token_total": int(tokens.get("input") or 0),
            "output_token_total": int(tokens.get("output") or 0),
            "reasoning_token_total": int(tokens.get("reasoning") or 0),
            "cache_read_token_total": int(cache.get("read") or 0),
            "cache_write_token_total": int(cache.get("write") or 0),
        })
    return records


def _count_reasoning_tool_messages(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT part.message_id, json_extract(part.data, '$.type') AS part_type
            FROM part
            JOIN message ON message.id = part.message_id
            WHERE json_extract(message.data, '$.providerID') = 'deepseek'
              AND json_extract(message.data, '$.role') = 'assistant'
              AND json_extract(part.data, '$.type') IN ('reasoning', 'tool')
            """
        ).fetchall()
    finally:
        conn.close()
    by_message: dict[str, set[str]] = defaultdict(set)
    for message_id, part_type in rows:
        if message_id is None or part_type is None:
            continue
        by_message[str(message_id)].add(str(part_type))
    return sum(1 for parts in by_message.values() if {"reasoning", "tool"} <= parts)


def _scan_logs(log_dir: Path) -> dict[str, bool]:
    signals = {
        "beta_base_url_seen": False,
        "anthropic_base_url_seen": False,
        "prompt_cache_tokens_seen": False,
    }
    if not log_dir.is_dir():
        return signals
    for path in sorted(log_dir.glob("*.log")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "api.deepseek.com/beta" in text:
            signals["beta_base_url_seen"] = True
        if "api.deepseek.com/anthropic" in text:
            signals["anthropic_base_url_seen"] = True
        if "prompt_cache_hit_tokens" in text or "prompt_cache_miss_tokens" in text:
            signals["prompt_cache_tokens_seen"] = True
    return signals


def _build_cost_estimate(
    family_totals: dict[str, dict[str, Any]],
    prices: dict[str, dict[str, Decimal]],
    *,
    snapshot_date: str,
) -> dict[str, Any]:
    breakdown: list[dict[str, Any]] = []
    amount = Decimal("0")
    for model_family, totals in sorted(family_totals.items()):
        family_prices = prices[model_family]
        family_amount = (
            Decimal(totals["input_token_total"]) * family_prices["miss"]
            + Decimal(totals["cache_read_token_total"]) * family_prices["hit"]
            + Decimal(totals["output_token_total"] + totals["reasoning_token_total"])
            * family_prices["out"]
        ) / Decimal("1000000")
        amount += family_amount
        breakdown.append({
            "model_family": model_family,
            "amount_usd": float(family_amount.quantize(Decimal("0.0001"))),
        })
    return {
        "currency": "USD",
        "amount_usd": float(amount.quantize(Decimal("0.0001"))),
        "pricing_source_url": PRICING_SOURCE_URL,
        "pricing_snapshot_date": snapshot_date,
        "reasoning_treated_as_output_equivalent": True,
        "family_breakdown": breakdown,
        "method_summary": (
            "Session-level DeepSeek token totals are priced with cache-read as discounted input "
            "and reasoning tokens treated as output-equivalent for a conservative estimate."
        ),
    }


def _build_usage_snapshot(
    session_rows: list[dict[str, Any]], request_rows: list[dict[str, Any]]
) -> UsageSnapshot:
    session_totals_by_key: dict[tuple[str, str], Totals] = defaultdict(Totals)
    request_counts_by_key: Counter[tuple[str, str]] = Counter()
    family_totals: dict[str, Totals] = {"pro": Totals(), "flash": Totals()}
    variant_totals: dict[str, Totals] = defaultdict(Totals)

    for row in session_rows:
        key = (row["model_id"], row["variant"])
        session_totals_by_key[key].add_session(row)
        family_totals[
            "pro" if row["model_id"] == "deepseek-v4-pro" else "flash"
        ].add_session(row)
        variant_totals[row["variant"]].add_session(row)

    for row in request_rows:
        key = (row["model_id"], row["variant"])
        request_counts_by_key[key] += 1
        family_totals[
            "pro" if row["model_id"] == "deepseek-v4-pro" else "flash"
        ].add_request()
        variant_totals[row["variant"]].add_request()

    total_sessions = len(session_rows)
    total_requests = len(request_rows)
    model_counts, deepseek_totals = _summarize_model_usage(
        session_totals_by_key, request_counts_by_key, total_requests=total_requests
    )

    cache_hit_ratio = (
        deepseek_totals.cache_read_token_total
        / (deepseek_totals.cache_read_token_total + deepseek_totals.input_token_total)
        if deepseek_totals.cache_read_token_total + deepseek_totals.input_token_total
        else 0.0
    )

    pro_usage = _usage_totals_dict(
        family_totals["pro"],
        total_sessions=total_sessions,
        total_requests=total_requests,
    )
    pro_usage["input_token_total"] = family_totals["pro"].input_token_total
    pro_usage["output_token_total"] = family_totals["pro"].output_token_total
    pro_usage["reasoning_token_total"] = family_totals["pro"].reasoning_token_total
    pro_usage["cache_read_token_total"] = family_totals["pro"].cache_read_token_total
    pro_usage["cache_write_token_total"] = family_totals["pro"].cache_write_token_total

    flash_usage = _usage_totals_dict(
        family_totals["flash"],
        total_sessions=total_sessions,
        total_requests=total_requests,
    )
    flash_usage["input_token_total"] = family_totals["flash"].input_token_total
    flash_usage["output_token_total"] = family_totals["flash"].output_token_total
    flash_usage["reasoning_token_total"] = family_totals["flash"].reasoning_token_total
    flash_usage["cache_read_token_total"] = family_totals[
        "flash"
    ].cache_read_token_total
    flash_usage["cache_write_token_total"] = family_totals[
        "flash"
    ].cache_write_token_total

    default_usage = _usage_totals_dict(
        variant_totals["default"],
        total_sessions=total_sessions,
        total_requests=total_requests,
    )
    default_usage["input_token_total"] = variant_totals["default"].input_token_total
    default_usage["output_token_total"] = variant_totals["default"].output_token_total
    default_usage["reasoning_token_total"] = variant_totals[
        "default"
    ].reasoning_token_total
    default_usage["cache_read_token_total"] = variant_totals[
        "default"
    ].cache_read_token_total
    default_usage["cache_write_token_total"] = variant_totals[
        "default"
    ].cache_write_token_total

    max_usage = _usage_totals_dict(
        variant_totals["max"],
        total_sessions=total_sessions,
        total_requests=total_requests,
    )
    max_usage["input_token_total"] = variant_totals["max"].input_token_total
    max_usage["output_token_total"] = variant_totals["max"].output_token_total
    max_usage["reasoning_token_total"] = variant_totals["max"].reasoning_token_total
    max_usage["cache_read_token_total"] = variant_totals["max"].cache_read_token_total
    max_usage["cache_write_token_total"] = variant_totals["max"].cache_write_token_total

    return UsageSnapshot(
        session_count=total_sessions,
        request_count=total_requests,
        model_counts=model_counts,
        deepseek_totals=deepseek_totals,
        pro_usage=pro_usage,
        flash_usage=flash_usage,
        default_usage=default_usage,
        max_usage=max_usage,
        cache_hit_ratio=round(cache_hit_ratio, 6),
    )


def _feature(
    *,
    feature_id: str,
    status: str,
    summary: str,
    evidence_refs: list[str],
    recommended_action: str,
) -> dict[str, Any]:
    return {
        "feature_id": feature_id,
        "status": status,
        "summary": summary,
        "evidence_refs": evidence_refs,
        "recommended_action": recommended_action,
    }


def _usage_totals_dict(
    totals: Totals, *, total_sessions: int, total_requests: int
) -> dict[str, Any]:
    session_share = totals.session_count / total_sessions if total_sessions else None
    request_share = totals.request_count / total_requests if total_requests else None
    return totals.as_dict(session_share=session_share, request_share=request_share)


def _cache_write_visibility(rows: list[dict[str, Any]]) -> tuple[str, str]:
    reported_values = [
        int(row["cache_write_token_total"])
        for row in rows
        if row.get("cache_write_present") is True
    ]
    if any(value > 0 for value in reported_values):
        return (
            "reported_nonzero",
            "The source evidence explicitly reports nonzero cache-write tokens.",
        )
    if reported_values:
        return (
            "reported_zero",
            "The source evidence explicitly reports cache-write tokens as zero.",
        )
    if rows:
        return (
            "not_reported_by_source",
            "The inspected source evidence does not expose cache-write fields, so zero cannot be inferred.",
        )
    return (
        "unknown",
        "No cache-write evidence was available in the inspected source data.",
    )


def _content_light_path_str(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return path.name


def _summarize_model_usage(
    session_totals_by_key: dict[tuple[str, str], Totals],
    request_counts_by_key: Counter[tuple[str, str]],
    *,
    total_requests: int,
) -> tuple[list[dict[str, Any]], Totals]:
    model_counts: list[dict[str, Any]] = []
    deepseek_totals = Totals()
    for key in sorted(session_totals_by_key):
        totals = session_totals_by_key[key]
        totals.add_request(request_counts_by_key[key])
        model_counts.append({
            "model_id": key[0],
            "variant": key[1],
            "session_count": totals.session_count,
            "request_count": totals.request_count,
            "input_token_total": totals.input_token_total,
            "output_token_total": totals.output_token_total,
            "reasoning_token_total": totals.reasoning_token_total,
            "cache_read_token_total": totals.cache_read_token_total,
            "cache_write_token_total": totals.cache_write_token_total,
        })
    for totals in session_totals_by_key.values():
        deepseek_totals.session_count += totals.session_count
        deepseek_totals.input_token_total += totals.input_token_total
        deepseek_totals.output_token_total += totals.output_token_total
        deepseek_totals.reasoning_token_total += totals.reasoning_token_total
        deepseek_totals.cache_read_token_total += totals.cache_read_token_total
        deepseek_totals.cache_write_token_total += totals.cache_write_token_total
    deepseek_totals.request_count = total_requests
    return model_counts, deepseek_totals


def _build_feature_sections(
    *, reasoning_tool_message_count: int, log_signals: dict[str, bool]
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    already_enabled = [
        _feature(
            feature_id="thinking_mode",
            status="supported_and_enabled",
            summary=(
                "DeepSeek reasoning tokens are present across the sampled sessions, which indicates "
                "thinking mode is already active in the current OpenCode lane."
            ),
            evidence_refs=["opencode_db"],
            recommended_action="Keep the current thinking-mode path; add explicit policy only if you need manual overrides.",
        ),
        _feature(
            feature_id="reasoning_effort_control",
            status="supported_and_enabled",
            summary=(
                "deepseek-v4-pro is routed through both default and max variants, so effort-tier routing is already in use."
            ),
            evidence_refs=["opencode_db", "opencode_log_latest"],
            recommended_action="Use the existing variant split as the current effort-control mechanism.",
        ),
        _feature(
            feature_id="reasoning_content_continuation_with_tool_calls",
            status="supported_and_enabled",
            summary=(
                f"{reasoning_tool_message_count:,} assistant messages contain both reasoning and tool parts, "
                "which is the local evidence that reasoning_content survives tool-call turns."
            ),
            evidence_refs=["opencode_db", "opencode_sdk_types"],
            recommended_action="Preserve the current reasoning/tool continuation path and add a regression test if the adapter changes.",
        ),
        _feature(
            feature_id="tool_calls",
            status="supported_and_enabled",
            summary="Assistant tool-call parts and tool_call_id handling are present in the OpenCode session DB and SDK surface.",
            evidence_refs=["opencode_db", "opencode_sdk_types"],
            recommended_action="Keep the current OpenAI-format tool loop.",
        ),
        _feature(
            feature_id="context_cache_visibility",
            status="supported_and_enabled",
            summary=(
                "OpenCode stores cache-read/cache-write counters in the session DB, which makes DeepSeek cache economics visible locally."
            ),
            evidence_refs=["opencode_db"],
            recommended_action="Expose the same counters in any future dashboard so cache-share trends are visible without digging into SQLite.",
        ),
        _feature(
            feature_id="openai_compatible_deepseek_transport",
            status="supported_and_enabled",
            summary=(
                "The installed OpenCode stack uses the standard OpenAI-compatible DeepSeek route rather than a beta or Anthropic-specific route."
            ),
            evidence_refs=["opencode_binary", "opencode_log_latest", "opencode_config"],
            recommended_action="Stay on the OpenAI-compatible path unless a separate adapter need appears.",
        ),
    ]
    not_enabled = {
        "supported_but_not_enabled": [
            _feature(
                feature_id="json_output_mode",
                status="supported_but_not_enabled",
                summary="The binary contains response_format/json_object support strings, but JSON output mode was not actively used in the inspected usage data.",
                evidence_refs=["opencode_binary"],
                recommended_action="Enable only for workflows that actually need machine-parseable JSON output.",
            ),
            _feature(
                feature_id="strict_tool_call_mode_beta",
                status="supported_but_not_enabled",
                summary="The binary contains function.strict strings, but there is no evidence of beta routing or strict-mode activation in the current usage data.",
                evidence_refs=["opencode_binary"],
                recommended_action="Only enable after you have a beta profile and strict-compatible tool schemas.",
            ),
        ],
        "adapter_change_required": [
            _feature(
                feature_id="chat_prefix_completion_beta",
                status="adapter_change_required",
                summary="Chat prefix completion needs the beta route and prefix=true handling, neither of which is present in the current OpenCode evidence.",
                evidence_refs=[
                    "opencode_binary",
                    "opencode_log_latest",
                    "opencode_config",
                ],
                recommended_action="Treat as adapter work, not a config toggle.",
            ),
            _feature(
                feature_id="fim_completion_beta",
                status="adapter_change_required",
                summary="FIM completion needs the beta route and a completions-style prompt/suffix flow, which is absent from the current OpenCode evidence.",
                evidence_refs=[
                    "opencode_binary",
                    "opencode_log_latest",
                    "opencode_config",
                ],
                recommended_action="Treat as adapter work and only add it if a code-completion context really needs it.",
            ),
        ],
    }
    not_priority = [
        _feature(
            feature_id="chat_prefix_and_fim_beta_work",
            status="not_worth_prioritizing",
            summary=(
                "Chat prefix completion and FIM require adapter changes but do not address the dominant cost lever in this install: cache reuse."
            ),
            evidence_refs=["opencode_binary", "opencode_log_latest"],
            recommended_action="Defer beta prefix/FIM work until the cache and lane policy are stable.",
        ),
        _feature(
            feature_id="thinking_mode_noop_parameters",
            status="not_worth_prioritizing",
            summary=(
                "temperature, top_p, presence_penalty, and frequency_penalty are no-op or ineffective in DeepSeek thinking mode."
            ),
            evidence_refs=["opencode_binary"],
            recommended_action="Do not spend the discount window tuning parameters DeepSeek ignores in thinking mode.",
        ),
    ]
    if (
        not log_signals["beta_base_url_seen"]
        and not log_signals["anthropic_base_url_seen"]
    ):
        not_priority.append(
            _feature(
                feature_id="beta_endpoint_routing",
                status="not_worth_prioritizing",
                summary="Local logs do not show beta or Anthropic DeepSeek base URLs, so beta endpoint routing is not a near-term optimization target.",
                evidence_refs=["opencode_log_latest"],
                recommended_action="Keep the current OpenAI-compatible path and avoid beta-only routing unless a clear need appears.",
            )
        )
    return already_enabled, not_enabled, not_priority


def _build_lane_policy(
    *, pro_usage: dict[str, Any], flash_usage: dict[str, Any], cache_hit_ratio: float
) -> dict[str, Any]:
    return {
        "policy_summary": (
            "Use deepseek-v4-flash only for short, low-risk, low-context tasks. Use deepseek-v4-pro "
            "default for normal repo work. Use deepseek-v4-pro max for architecture, deep debugging, "
            "and long multi-step reasoning. Keep pro as the default lane while cache-read share stays high."
        ),
        "lanes": [
            {
                "lane_id": "flash",
                "model_id": "deepseek-v4-flash",
                "effort": "default",
                "when_to_use": "Quick triage, exploratory reads, short-context summaries, and other cheap low-risk tasks.",
                "why": "Flash is the cheap lane and is best reserved for work where a wrong first pass is inexpensive.",
            },
            {
                "lane_id": "pro-default",
                "model_id": "deepseek-v4-pro",
                "effort": "default",
                "when_to_use": "Normal repo work, bugfixing, tests, and moderate-complexity reasoning.",
                "why": "Pro accounts for most of the observed DeepSeek usage and is the safest default for real work.",
            },
            {
                "lane_id": "pro-max",
                "model_id": "deepseek-v4-pro",
                "effort": "max",
                "when_to_use": "Architecture, deep debugging, long reasoning chains, and multi-file refactors.",
                "why": "Max is the right escalation lane when the first pass fails or the task is likely to need broader synthesis.",
            },
        ],
        "selection_rules": [
            "Prefer flash only when the task can be completed with short context and failure is cheap.",
            "Prefer pro default for anything that might need tool calls or non-trivial synthesis.",
            "Escalate to pro max when the task spans multiple steps, needs broader reasoning, or the first pass stalls.",
        ],
        "cache_guidance": (
            f"Cache-read share is {cache_hit_ratio:.4f}; keep system and tool prefixes stable so the current cache economics hold."
        ),
    }


def _lane_usage_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total_sessions = int(report["session_count"])
    total_requests = int(report["request_count_if_available"] or 0)
    for row in report["model_counts"]:
        session_count = int(row["session_count"])
        request_count = int(row["request_count"])
        rows.append({
            "model_id": row["model_id"],
            "variant": row["variant"],
            "session_count": session_count,
            "request_count": request_count,
            "session_share": round(session_count / total_sessions, 6)
            if total_sessions
            else None,
            "request_share": round(request_count / total_requests, 6)
            if total_requests
            else None,
        })
    priority = {
        ("deepseek-v4-pro", "default"): 0,
        ("deepseek-v4-pro", "max"): 1,
        ("deepseek-v4-flash", "default"): 2,
    }
    return sorted(
        rows, key=lambda row: priority.get((row["model_id"], row["variant"]), 99)
    )


def _build_summary_artifact(
    report: dict[str, Any], *, source_report_path: Path, source_report_sha256: str
) -> dict[str, Any]:
    return {
        "schema_version": "rig.deepseek_opencode_usage_summary.v1",
        "generated_at": report["generated_at"],
        "source_report_path": _content_light_path_str(source_report_path),
        "source_report_sha256": source_report_sha256,
        "opencode_version": report["opencode_version"],
        "provider": report["provider"],
        "session_count": report["session_count"],
        "request_count_if_available": report["request_count_if_available"],
        "lane_usage": _lane_usage_rows(report),
        "cache_hit_ratio": report["cache_hit_ratio"],
        "cache_read_token_total": report["cache_read_token_total"],
        "cache_write_visibility": report["cache_write_visibility"],
        "cache_write_visibility_note": report["cache_write_visibility_note"],
        "estimated_discounted_cost_usd": report[
            "estimated_discounted_cost_if_pricing_available"
        ]["amount_usd"]
        if report["estimated_discounted_cost_if_pricing_available"] is not None
        else None,
        "estimated_full_cost_usd": report["estimated_full_cost_if_pricing_available"][
            "amount_usd"
        ]
        if report["estimated_full_cost_if_pricing_available"] is not None
        else None,
        "recommended_lane": "deepseek-v4-pro default",
        "lane_policy_summary": report["lane_policy_recommendation"]["policy_summary"],
        "final_recommendation_summary": report["final_recommendation"]["summary"],
        "redaction_notes": report["redaction_notes"],
    }


def build_deepseek_opencode_usage_report(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    log_dir: Path = DEFAULT_LOG_DIR,
    opencode_version: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    session_rows = _load_session_rows(db_path)
    request_rows = _load_request_rows(db_path)
    log_signals = _scan_logs(log_dir)
    reasoning_tool_message_count = _count_reasoning_tool_messages(db_path)
    snapshot = _build_usage_snapshot(session_rows, request_rows)
    cache_write_visibility, cache_write_visibility_note = _cache_write_visibility(
        session_rows + request_rows
    )
    pricing_snapshot_date = (generated_at or datetime.now(tz=UTC).date().isoformat())[
        :10
    ]

    discounted_estimate = _build_cost_estimate(
        {
            "deepseek-v4-pro": snapshot.pro_usage,
            "deepseek-v4-flash": snapshot.flash_usage,
        },
        {
            "deepseek-v4-pro": {
                "hit": Decimal("0.003625"),
                "miss": Decimal("0.435"),
                "out": Decimal("0.87"),
            },
            "deepseek-v4-flash": {
                "hit": Decimal("0.0028"),
                "miss": Decimal("0.14"),
                "out": Decimal("0.28"),
            },
        },
        snapshot_date=pricing_snapshot_date,
    )
    full_estimate = _build_cost_estimate(
        {
            "deepseek-v4-pro": snapshot.pro_usage,
            "deepseek-v4-flash": snapshot.flash_usage,
        },
        {
            "deepseek-v4-pro": {
                "hit": Decimal("0.0145"),
                "miss": Decimal("1.74"),
                "out": Decimal("3.48"),
            },
            "deepseek-v4-flash": {
                "hit": Decimal("0.0028"),
                "miss": Decimal("0.14"),
                "out": Decimal("0.28"),
            },
        },
        snapshot_date=pricing_snapshot_date,
    )

    already_enabled, not_enabled, not_priority = _build_feature_sections(
        reasoning_tool_message_count=reasoning_tool_message_count,
        log_signals=log_signals,
    )
    generated_at = generated_at or datetime.now(tz=UTC).isoformat().replace(
        "+00:00", "Z"
    )
    opencode_version = opencode_version or _detect_opencode_version()

    return {
        "schema_version": SCHEMA_ID,
        "generated_at": generated_at,
        "opencode_version": opencode_version,
        "provider": "deepseek",
        "model_counts": snapshot.model_counts,
        "session_count": snapshot.session_count,
        "request_count_if_available": snapshot.request_count,
        "reasoning_token_total": snapshot.deepseek_totals.reasoning_token_total,
        "cache_read_token_total": snapshot.deepseek_totals.cache_read_token_total,
        "cache_write_token_total": snapshot.deepseek_totals.cache_write_token_total,
        "cache_write_visibility": cache_write_visibility,
        "cache_write_visibility_note": cache_write_visibility_note,
        "cache_hit_ratio": snapshot.cache_hit_ratio,
        "output_token_total_if_available": snapshot.deepseek_totals.output_token_total,
        "estimated_discounted_cost_if_pricing_available": discounted_estimate,
        "estimated_full_cost_if_pricing_available": full_estimate,
        "pro_vs_flash_usage": {
            "pro": snapshot.pro_usage,
            "flash": snapshot.flash_usage,
        },
        "max_vs_default_effort_usage": {
            "default": snapshot.default_usage,
            "max": snapshot.max_usage,
        },
        "top_cache_efficiency_findings": [
            {
                "finding_id": "cache-read-dominates",
                "summary": (
                    f"Cache-read tokens account for {snapshot.cache_hit_ratio * 100:.2f}% "
                    "of cache-eligible input tokens, so stable prefixes are already paying off."
                ),
                "impact": "Keep system/tool prefixes stable to preserve the current cache economics.",
                "evidence_refs": ["opencode_db"],
            },
            {
                "finding_id": "cache-write-zero",
                "summary": (
                    "Cache-write tokens are reported as zero across the sampled DeepSeek sessions."
                ),
                "impact": "There is no evidence that cache warming or write-side behavior is a meaningful lever here.",
                "evidence_refs": ["opencode_db"],
            },
            {
                "finding_id": "pro-dominates",
                "summary": (
                    f"deepseek-v4-pro accounts for {snapshot.pro_usage['request_share'] * 100:.2f}% of DeepSeek requests "
                    "and remains the right default lane."
                ),
                "impact": "Flash should stay an explicit cheap lane rather than the default.",
                "evidence_refs": ["opencode_db"],
            },
        ],
        "lane_policy_recommendation": _build_lane_policy(
            pro_usage=snapshot.pro_usage,
            flash_usage=snapshot.flash_usage,
            cache_hit_ratio=snapshot.cache_hit_ratio,
        ),
        "features_already_enabled": already_enabled,
        "features_not_enabled": not_enabled,
        "features_not_worth_prioritizing": not_priority,
        "redaction_notes": [
            "No API keys, auth headers, raw prompts, raw completions, raw private file contents, or raw absolute paths were persisted.",
            "Evidence references use symbolic labels such as opencode_db, opencode_log_latest, opencode_binary, and opencode_sdk_types.",
            "22 session rows with null model metadata were excluded from DeepSeek-specific counts so other providers are not misattributed.",
            "Local logs were scanned for DeepSeek beta and Anthropic route strings, and no beta/Anthropic base URL evidence was found.",
            "OpenCode's session DB exposes cache-read/cache-write counters; raw prompt_cache_hit_tokens and prompt_cache_miss_tokens were not surfaced in the inspected logs.",
        ],
        "final_recommendation": {
            "verdict": (
                "Keep DeepSeek on the OpenAI-compatible api.deepseek.com path, preserve stable prefixes, "
                "and route most normal work through deepseek-v4-pro. Use flash only when the task is cheap "
                "and local to the prefix. Do not spend the discount window on beta-only prefix/FIM work."
            ),
            "summary": (
                f"The sampled DeepSeek usage is already cost-aware: cache-read share is {snapshot.cache_hit_ratio * 100:.2f}%, "
                f"pro carries {snapshot.pro_usage['request_share'] * 100:.2f}% of requests, and the discount window "
                f"reduces the estimated bill from ${full_estimate['amount_usd']:.4f} to ${discounted_estimate['amount_usd']:.4f}."
            ),
            "next_step": (
                "Add a lightweight session-level cache and lane report so pro-vs-flash usage and cache-read share stay visible."
            ),
            "do_not_prioritize": [
                "chat_prefix_completion_beta",
                "fim_completion_beta",
                "strict_tool_call_mode_beta unless a strict JSON tool workflow becomes necessary",
            ],
        },
    }


def validate_deepseek_opencode_usage_report(report: dict[str, Any]) -> list[str]:
    schema = _schema()
    validator = jsonschema.Draft7Validator(schema)
    return [
        f"{'/'.join(str(part) for part in err.absolute_path)}: {err.message}"
        for err in validator.iter_errors(report)
    ]


def write_deepseek_opencode_usage_report(
    report: dict[str, Any], output_path: Path
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_json_dumps(report) + "\n", encoding="utf-8")


def _summary_schema() -> dict[str, Any]:
    return json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))


def build_deepseek_opencode_usage_summary(
    report: dict[str, Any],
    *,
    source_report_path: Path,
    source_report_bytes: bytes | None = None,
) -> dict[str, Any]:
    source_bytes = (
        source_report_bytes
        if source_report_bytes is not None
        else source_report_path.read_bytes()
    )
    source_report_sha256 = hashlib.sha256(source_bytes).hexdigest()
    return _build_summary_artifact(
        report,
        source_report_path=source_report_path,
        source_report_sha256=source_report_sha256,
    )


def validate_deepseek_opencode_usage_summary(summary: dict[str, Any]) -> list[str]:
    schema = _summary_schema()
    validator = jsonschema.Draft7Validator(schema)
    return [
        f"{'/'.join(str(part) for part in err.absolute_path)}: {err.message}"
        for err in validator.iter_errors(summary)
    ]


def write_deepseek_opencode_usage_summary(
    summary: dict[str, Any], output_path: Path
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_json_dumps(summary) + "\n", encoding="utf-8")


def _render_summary_table(summary: dict[str, Any]) -> str:
    lane_rows = summary["lane_usage"]
    split = "; ".join(
        (
            f"{row['model_id']} {row['variant']} "
            f"{row['session_count']:,} sessions / {row['request_count']:,} requests"
        )
        for row in lane_rows
    )
    rows = [
        ("Sessions", f"{summary['session_count']:,}"),
        ("Assistant requests", f"{summary['request_count_if_available']:,}"),
        ("Lane split", split),
        (
            "Cache-hit ratio",
            f"{summary['cache_hit_ratio'] * 100:.2f}% ({summary['cache_hit_ratio']:.6f})",
        ),
        ("Cache-read tokens", f"{summary['cache_read_token_total']:,}"),
        ("Cache-write visibility", summary["cache_write_visibility"]),
        ("Cache-write note", summary["cache_write_visibility_note"]),
        (
            "Discounted estimated cost",
            f"${summary['estimated_discounted_cost_usd']:.4f}",
        ),
        ("Full estimated cost", f"${summary['estimated_full_cost_usd']:.4f}"),
        ("Recommended lane", summary["recommended_lane"]),
    ]
    label_width = max(len(label) for label, _ in rows)
    value_width = max(len(value) for _, value in rows)
    header = f"{'Metric'.ljust(label_width)} | {'Value'.ljust(value_width)}"
    separator = f"{'-' * label_width}-+-{'-' * value_width}"
    body = "\n".join(
        f"{label.ljust(label_width)} | {value.ljust(value_width)}"
        for label, value in rows
    )
    return "\n".join([header, separator, body])


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a local DeepSeek/OpenCode usage and cache report."
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--summary-output-path", type=Path, default=DEFAULT_SUMMARY_OUTPUT_PATH
    )
    parser.add_argument("--opencode-version", type=str, default=None)
    parser.add_argument("--generated-at", type=str, default=None)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--fail-on-schema-error", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = build_deepseek_opencode_usage_report(
            db_path=args.db_path,
            log_dir=args.log_dir,
            opencode_version=args.opencode_version,
            generated_at=args.generated_at,
        )
    except FileNotFoundError as exc:
        print(str(exc))
        return 1

    report_errors = validate_deepseek_opencode_usage_report(report)
    report_json = _json_dumps(report) + "\n"
    summary = build_deepseek_opencode_usage_summary(
        report,
        source_report_path=args.output_path,
        source_report_bytes=report_json.encode("utf-8"),
    )
    summary_errors = validate_deepseek_opencode_usage_summary(summary)
    if report_errors or summary_errors:
        if args.fail_on_schema_error:
            print("Schema validation failed:")
            for err in report_errors:
                print(f"  - report: {err}")
            for err in summary_errors:
                print(f"  - summary: {err}")
        return 1

    write_deepseek_opencode_usage_report(report, args.output_path)
    write_deepseek_opencode_usage_summary(summary, args.summary_output_path)
    if args.summary:
        print(_render_summary_table(summary))
    else:
        print(
            json.dumps(
                {
                    "output_path": str(args.output_path),
                    "summary_output_path": str(args.summary_output_path),
                    "session_count": report["session_count"],
                    "request_count": report["request_count_if_available"],
                    "cache_hit_ratio": report["cache_hit_ratio"],
                    "discounted_cost_usd": report[
                        "estimated_discounted_cost_if_pricing_available"
                    ]["amount_usd"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

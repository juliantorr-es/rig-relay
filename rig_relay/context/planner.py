"""ContextPlanner — deterministic context candidate discovery, scoring, and budget enforcement.

plan_context() is the public entry point. Accepts a ContextRequest and
optional pre-built repo/subsystem/work/index data. Returns a
ContextAssemblyPlan with selections, omissions, warnings, and hashes.

Lane A models: assembly_plan.py
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Any

from rig_relay.context.assembly_plan import (
    CacheTier,
    CandidateKind,
    CandidateRelation,
    CandidateSource,
    ContextAssemblyPlan,
    ContextAssemblyWarning,
    ContextBudgetLedger,
    ContextCandidate,
    ContextOmission,
    ContextSelection,
    IncludeMode,
    OmissionReason,
    RiskFlag,
    TrustTier,
)
from rig_relay.context.models import ContextRequest, SubsystemEntry
from rig_relay.context.token_estimator import estimate_tokens


def plan_context(  # noqa: PLR0912, PLR0915, PLR0914
    request: ContextRequest,
    *,
    workspace_root: Path | None = None,
    subsystems: list[SubsystemEntry] | None = None,
    active_work: dict[str, Any] | None = None,
    repo_index: Any | None = None,
) -> ContextAssemblyPlan:
    _ = (workspace_root or Path.cwd()).resolve()  # reserved for future use
    warnings: list[ContextAssemblyWarning] = []
    candidates: list[ContextCandidate] = []
    candidate_ids: set[str] = set()

    req_json = request.model_dump_json(exclude_none=True)
    request_sha256 = hashlib.sha256(req_json.encode("utf-8")).hexdigest()

    # ── 1. Discover from requested paths ────────────────────────
    for path in request.scope.paths:
        path_str = str(path)
        cand = ContextCandidate(
            path=path_str,
            kind=CandidateKind.source,
            source=CandidateSource.requested_path,
            relation=CandidateRelation.direct,
            estimated_tokens=estimate_tokens(path_str),
            priority=1000,
            reason=f"Directly requested: {path_str}",
            trust_tier=TrustTier.repo_content,
            cache_tier=CacheTier.semi_stable,
        )
        if cand.candidate_id in candidate_ids:
            continue
        candidate_ids.add(cand.candidate_id)
        candidates.append(cand)

    # ── 2. Discover from subsystem map ──────────────────────────
    if subsystems:
        for sub in subsystems:
            for cfg in sub.config_files:
                cand = ContextCandidate(
                    path=cfg,
                    kind=CandidateKind.config,
                    source=CandidateSource.repo_map,
                    relation=CandidateRelation.config,
                    estimated_tokens=estimate_tokens(cfg),
                    priority=500,
                    reason=f"Config for {sub.name}",
                    trust_tier=TrustTier.repo_content,
                    cache_tier=CacheTier.semi_stable,
                )
                if cand.candidate_id in candidate_ids:
                    continue
                candidate_ids.add(cand.candidate_id)
                candidates.append(cand)

            for doc in sub.docs:
                cand = ContextCandidate(
                    path=doc,
                    kind=CandidateKind.doc,
                    source=CandidateSource.repo_map,
                    relation=CandidateRelation.doc,
                    estimated_tokens=estimate_tokens(doc),
                    priority=300,
                    reason=f"Doc for {sub.name}",
                    trust_tier=TrustTier.repo_content,
                    cache_tier=CacheTier.stable,
                )
                if cand.candidate_id in candidate_ids:
                    continue
                candidate_ids.add(cand.candidate_id)
                candidates.append(cand)

            for test in sub.tests:
                cand = ContextCandidate(
                    path=test,
                    kind=CandidateKind.test,
                    source=CandidateSource.repo_map,
                    relation=CandidateRelation.test,
                    estimated_tokens=estimate_tokens(test),
                    priority=350,
                    reason=f"Test for {sub.name}",
                    trust_tier=TrustTier.repo_content,
                    cache_tier=CacheTier.dynamic,
                )
                if cand.candidate_id in candidate_ids:
                    continue
                candidate_ids.add(cand.candidate_id)
                candidates.append(cand)

            for schema in sub.schemas:
                cand = ContextCandidate(
                    path=schema,
                    kind=CandidateKind.schema,
                    source=CandidateSource.repo_map,
                    relation=CandidateRelation.schema,
                    estimated_tokens=estimate_tokens(schema),
                    priority=450,
                    reason=f"Schema for {sub.name}",
                    trust_tier=TrustTier.repo_content,
                    cache_tier=CacheTier.stable,
                )
                if cand.candidate_id in candidate_ids:
                    continue
                candidate_ids.add(cand.candidate_id)
                candidates.append(cand)

            for ep in sub.entry_points:
                cand = ContextCandidate(
                    path=ep,
                    kind=CandidateKind.source,
                    source=CandidateSource.repo_map,
                    relation=CandidateRelation.direct,
                    estimated_tokens=estimate_tokens(ep),
                    priority=200,
                    reason=f"Entry point for {sub.name}",
                    trust_tier=TrustTier.repo_content,
                    cache_tier=CacheTier.semi_stable,
                )
                if cand.candidate_id in candidate_ids:
                    continue
                candidate_ids.add(cand.candidate_id)
                candidates.append(cand)

    # ── 3. Expand RepoIndex relations ──────────────────────────
    if request.scope.paths and repo_index is not None:
        requested_paths = [str(p) for p in request.scope.paths]

        if request.scope.include_tests:
            related, test_err = _safe_find(repo_index, "find_tests", requested_paths)
            if test_err:
                warnings.append(
                    ContextAssemblyWarning(
                        code="repo_index_query_failed", detail=f"find_tests: {test_err}"
                    )
                )
            for related_path in related:
                cand = ContextCandidate(
                    path=related_path,
                    kind=CandidateKind.test,
                    source=CandidateSource.repo_index,
                    relation=CandidateRelation.test,
                    estimated_tokens=estimate_tokens(related_path),
                    priority=350,
                    reason="Related test from RepoIndex",
                    trust_tier=TrustTier.repo_content,
                    cache_tier=CacheTier.dynamic,
                )
                if cand.candidate_id in candidate_ids:
                    continue
                candidate_ids.add(cand.candidate_id)
                candidates.append(cand)

        if request.scope.include_docs:
            related, doc_err = _safe_find(repo_index, "find_docs", requested_paths)
            if doc_err:
                warnings.append(
                    ContextAssemblyWarning(
                        code="repo_index_query_failed", detail=f"find_docs: {doc_err}"
                    )
                )
            for related_path in related:
                cand = ContextCandidate(
                    path=related_path,
                    kind=CandidateKind.doc,
                    source=CandidateSource.repo_index,
                    relation=CandidateRelation.doc,
                    estimated_tokens=estimate_tokens(related_path),
                    priority=300,
                    reason="Related doc from RepoIndex",
                    trust_tier=TrustTier.repo_content,
                    cache_tier=CacheTier.stable,
                )
                if cand.candidate_id in candidate_ids:
                    continue
                candidate_ids.add(cand.candidate_id)
                candidates.append(cand)

        related, schema_err = _safe_find(repo_index, "find_schemas", requested_paths)
        if schema_err:
            warnings.append(
                ContextAssemblyWarning(
                    code="repo_index_query_failed", detail=f"find_schemas: {schema_err}"
                )
            )
        for related_path in related:
            cand = ContextCandidate(
                path=related_path,
                kind=CandidateKind.schema,
                source=CandidateSource.repo_index,
                relation=CandidateRelation.schema,
                estimated_tokens=estimate_tokens(related_path),
                priority=450,
                reason="Related schema from RepoIndex",
                trust_tier=TrustTier.repo_content,
                cache_tier=CacheTier.stable,
            )
            if cand.candidate_id in candidate_ids:
                continue
            candidate_ids.add(cand.candidate_id)
            candidates.append(cand)

        related_map, rel_err = _safe_find_dict(
            repo_index, "find_related", requested_paths
        )
        if rel_err:
            warnings.append(
                ContextAssemblyWarning(
                    code="repo_index_query_failed", detail=f"find_related: {rel_err}"
                )
            )
        for rel_type, paths in related_map.items():
            for path in paths:
                relation = _map_relation(rel_type)
                cand = ContextCandidate(
                    path=path,
                    kind=CandidateKind.source,
                    source=CandidateSource.repo_index,
                    relation=relation,
                    estimated_tokens=estimate_tokens(path),
                    priority=150,
                    reason=f"Related {rel_type} from RepoIndex",
                    trust_tier=TrustTier.repo_content,
                    cache_tier=CacheTier.semi_stable,
                )
                if cand.candidate_id in candidate_ids:
                    continue
                candidate_ids.add(cand.candidate_id)
                candidates.append(cand)

    elif request.scope.paths and repo_index is None:
        warnings.append(
            ContextAssemblyWarning(
                code="repo_index_unavailable",
                detail="RepoIndex not available; relations not expanded",
            )
        )

    # ── 4. Active work and collisions ──────────────────────────
    if active_work:
        collisions = active_work.get("collision_warnings", [])
        for col in collisions:
            col_path = col.get("path", "")
            if not col_path:
                continue
            cand = ContextCandidate(
                path=col_path,
                kind=CandidateKind.work,
                source=CandidateSource.work_map,
                relation=CandidateRelation.collision,
                risk_flags=[RiskFlag.collision],
                priority=0,
                reason=f"Collision: {col.get('reason', '')[:120]}",
                trust_tier=TrustTier.repo_content,
                cache_tier=CacheTier.dynamic,
            )
            if cand.candidate_id in candidate_ids:
                continue
            candidate_ids.add(cand.candidate_id)
            candidates.append(cand)

    # ── 5. Sort by priority descending ─────────────────────────
    candidates.sort(key=lambda c: (-c.priority, c.path))

    # ── 6. Apply scope + budget ────────────────────────────────
    selections: list[ContextSelection] = []
    omissions: list[ContextOmission] = []
    used_tokens = 0
    max_tokens = max(0, request.budget.max_tokens)
    sel_idx = 0

    for cand in candidates:
        if RiskFlag.collision in cand.risk_flags:
            omissions.append(
                ContextOmission(
                    candidate_id=cand.candidate_id,
                    omission_reason=OmissionReason.risk_policy,
                    estimated_tokens=cand.estimated_tokens,
                    detail=f"Collision: {cand.reason[:100]}",
                )
            )
            continue

        if not request.scope.include_tests and cand.kind == CandidateKind.test:
            omissions.append(
                ContextOmission(
                    candidate_id=cand.candidate_id,
                    omission_reason=OmissionReason.disabled_by_scope,
                    estimated_tokens=cand.estimated_tokens,
                    detail="Tests disabled by scope",
                )
            )
            continue

        if not request.scope.include_docs and cand.kind == CandidateKind.doc:
            omissions.append(
                ContextOmission(
                    candidate_id=cand.candidate_id,
                    omission_reason=OmissionReason.disabled_by_scope,
                    estimated_tokens=cand.estimated_tokens,
                    detail="Docs disabled by scope",
                )
            )
            continue

        if used_tokens + cand.estimated_tokens > max_tokens > 0:
            omissions.append(
                ContextOmission(
                    candidate_id=cand.candidate_id,
                    omission_reason=OmissionReason.budget_exceeded,
                    estimated_tokens=cand.estimated_tokens,
                    detail=f"Budget: {used_tokens}/{max_tokens} used",
                )
            )
            continue

        used_tokens += cand.estimated_tokens
        selections.append(
            ContextSelection(
                candidate_id=cand.candidate_id,
                selected_tokens=cand.estimated_tokens,
                include_mode=IncludeMode.full,
                selection_reason=cand.reason,
                cache_tier=cand.cache_tier,
            )
        )
        sel_idx += 1

    # ── 7. Build plan ──────────────────────────────────────────
    if not candidates and not warnings:
        warnings.append(
            ContextAssemblyWarning(
                code="no_candidates_discovered",
                detail="No candidates discovered from any source",
            )
        )

    remaining = max(0, max_tokens - used_tokens) if max_tokens > 0 else 0

    plan = ContextAssemblyPlan(
        request_sha256=request_sha256,
        candidates=candidates,
        selections=selections,
        omissions=omissions,
        budget=ContextBudgetLedger(
            requested_tokens=max_tokens,
            used_tokens=used_tokens,
            remaining_tokens=remaining,
        ),
        warnings=warnings,
        deterministic_inputs={
            "request_sha256": request_sha256,
            "scope_paths": [str(p) for p in request.scope.paths],
            "subsystem_count": len(subsystems) if subsystems else 0,
            "max_tokens": max_tokens,
            "include_tests": request.scope.include_tests,
            "include_docs": request.scope.include_docs,
        },
        generated_at=datetime.now(UTC).isoformat(),
    )

    return plan


# ── Helpers ─────────────────────────────────────────────────────


def _safe_find(obj: Any, method: str, paths: list[str]) -> tuple[list[str], str | None]:
    """Call method on obj, return (results, error_string).

    Never raises. Returns empty list + error string on failure.
    """
    try:
        fn = getattr(obj, method, None)
        if fn is None:
            return [], f"method '{method}' not found"
        return list(fn(paths)), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"[:200]


def _safe_find_dict(
    obj: Any, method: str, paths: list[str]
) -> tuple[dict[str, list[str]], str | None]:
    """Call method on obj, return (results_dict, error_string).

    Never raises. Returns empty dict + error string on failure.
    """
    try:
        fn = getattr(obj, method, None)
        if fn is None:
            return {}, f"method '{method}' not found"
        result = fn(paths)
        if isinstance(result, dict):
            return {str(k): list(v) for k, v in result.items()}, None
        return {}, f"method '{method}' returned non-dict: {type(result).__name__}"
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"[:200]


def _map_relation(rel_type: str) -> CandidateRelation:
    try:
        return CandidateRelation(rel_type)
    except ValueError:
        return CandidateRelation.derived

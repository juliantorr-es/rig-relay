from __future__ import annotations

import ast
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
)
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolPermission,
)
from rig_relay.core.types import ToolStreamEvent

if TYPE_CHECKING:
    pass


class InspectStructureArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspection: str = Field(
        description=(
            "Named inspection to run. Available: tool_contract_completeness, "
            "deterministic_failure_surface_coverage, "
            "git_operator_picture_coverage, "
            "tool_runtime_request_classification, "
            "agent_outcome_projection_propagation."
        )
    )
    paths: list[str] = Field(
        default_factory=list,
        description=(
            "Repository-relative files or directories to inspect. "
            "Empty = default scope per inspection."
        ),
    )
    max_findings: int = Field(
        default=50, description="Maximum findings returned. Capped."
    )
    max_indeterminate: int = Field(
        default=20, description="Maximum indeterminate items returned. Capped."
    )


class StructuralFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_kind: str
    severity: str  # info, warning, blocker
    certainty: str  # definite, indeterminate, advisory
    evidence_basis: list[str] = Field(default_factory=list)
    file: str
    line: int
    subject: str
    detail: str  # Agent-visible; excluded from telemetry


class StructuralInspectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspection_id: str
    inspection_version: str
    language_scope: str
    verdict: str  # pass, findings, indeterminate, truncated
    summary: str
    counts: dict[str, int] = Field(default_factory=dict)
    findings: list[StructuralFinding] = Field(default_factory=list)
    indeterminate_items: list[StructuralFinding] = Field(default_factory=list)
    evidence_truncated: bool = False
    parser_failures: int = 0
    suggested_next_action: str | None = None


_DAILY_USE_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "grep",
    "get_context",
    "git_status",
    "git_diff",
    "git_log",
    "git_show",
    "git_ls_files",
    "search_replace",
    "write_file",
    "validate",
    "validation_suite",
    "checkpoint",
})

_GIT_DETAIL_FIELDS: frozenset[str] = frozenset({
    "branch",
    "staged_files",
    "unstaged_files",
    "tracked_files",
    "untracked_files",
    "deleted_files",
    "dirty_files",
    "checkpoint_eligible_paths",
    "in_scope_paths",
    "out_of_scope_paths",
})

_GIT_BARE_FIELDS: frozenset[str] = frozenset({
    "stdout",
    "stderr",
    "returncode",
    "argv",
    "operation",
    "truncated_stdout",
    "truncated_stderr",
})

_MIN_DESC_LENGTH: int = 20

_FAILURE_SURFACE_FIELDS: frozenset[str] = frozenset({
    "error_kind",
    "status",
    "refusal_reason",
    "suggested_next_action",
})

_REQUEST_CLASS_NAMES: frozenset[str] = frozenset({"ToolRuntimeRequest"})


def _is_daily_use_tool(name: str) -> bool:
    return name in _DAILY_USE_TOOLS


def _resolve_call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _classify_surface(file_path: str) -> str:
    rel = str(file_path)
    if "/tests/" in rel or rel.startswith("tests/"):
        return "test"
    if "rig_relay/core/agent_loop.py" in rel:
        return "native_agentloop"
    if "rig_relay/core/tool_executor/" in rel:
        return "native_tool_executor"
    if "rig_relay/runtime/" in rel:
        return "runtime_adapter"
    return "unknown"


def _resolve_python_files(paths: list[str]) -> list[str]:
    result: list[str] = []
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            continue
        if p.is_file() and p.suffix == ".py":
            result.append(str(p))
        elif p.is_dir():
            for py_file in sorted(p.rglob("*.py")):
                result.append(str(py_file))
    return result


def _discover_tools_from_paths(
    paths: list[str],
) -> dict[str, type[BaseTool[Any, Any, Any, Any]]]:
    import inspect as _inspect

    from rig_relay.core.config._settings import VibeConfig
    from rig_relay.core.tools.manager import ToolManager

    config = VibeConfig()
    manager = ToolManager(lambda: config)
    available = manager.available_tools

    if not paths:
        return available

    tool_source_files: dict[str, str] = {}
    for cls in available.values():
        try:
            tool_source_files[cls.get_name()] = _inspect.getfile(cls)
        except (TypeError, OSError):
            continue

    path_prefixes = tuple(paths)
    return {
        name: cls
        for name, cls in available.items()
        if name in tool_source_files
        and any(tool_source_files[name].startswith(p) for p in path_prefixes)
    }


def _run_tool_contract_completeness(
    paths: list[str], max_findings: int, max_indeterminate: int
) -> StructuralInspectionResult:
    findings: list[StructuralFinding] = []
    indeterminate: list[StructuralFinding] = []

    try:
        available = _discover_tools_from_paths(paths)
    except Exception:
        return StructuralInspectionResult(
            inspection_id="tool_contract_completeness",
            inspection_version="1.0",
            language_scope="native_registry",
            verdict="indeterminate",
            summary="Tool registry unavailable — cannot inspect.",
            suggested_next_action="Ensure the AgentLoop tool manager is accessible.",
        )

    detected = 0
    missing_desc = 0
    trivial_desc = 0
    missing_arg_desc = 0

    for tool_name, tool_cls in sorted(available.items()):
        if not _is_daily_use_tool(tool_name):
            continue
        detected += 1

        desc = getattr(tool_cls, "description", "") or ""
        source_file = ""
        try:
            import inspect as _inspect

            source_file = _inspect.getfile(tool_cls)
        except (TypeError, OSError):
            source_file = ""

        if not desc:
            missing_desc += 1
            findings.append(
                StructuralFinding(
                    finding_kind="missing_description",
                    severity="blocker",
                    certainty="definite",
                    evidence_basis=["runtime_tool_schema"],
                    file=source_file,
                    line=0,
                    subject=tool_name,
                    detail=f"Tool '{tool_name}' has no description visible to the agent.",
                )
            )
        elif len(desc) < _MIN_DESC_LENGTH:
            trivial_desc += 1
            findings.append(
                StructuralFinding(
                    finding_kind="trivial_description",
                    severity="warning",
                    certainty="definite",
                    evidence_basis=["runtime_tool_schema"],
                    file=source_file,
                    line=0,
                    subject=tool_name,
                    detail=f"Tool '{tool_name}' description is too short ({len(desc)} chars).",
                )
            )

        try:
            args_model, _ = tool_cls._get_tool_args_results()
        except Exception:
            args_model = None

        if args_model is not None:
            for field_name, field_info in args_model.model_fields.items():
                field_desc = field_info.description or ""
                if not field_desc:
                    missing_arg_desc += 1
                    findings.append(
                        StructuralFinding(
                            finding_kind="missing_arg_field_description",
                            severity="blocker",
                            certainty="definite",
                            evidence_basis=["runtime_tool_schema"],
                            file=source_file,
                            line=0,
                            subject=f"{tool_name}.{field_name}",
                            detail=(
                                f"Tool '{tool_name}' argument '{field_name}' "
                                "has no Field(description=...)."
                            ),
                        )
                    )

        examples_exist = (
            "example" in desc.lower()
            or "usage" in desc.lower()
            or "e.g." in desc.lower()
        )
        if not examples_exist:
            indeterminate.append(
                StructuralFinding(
                    finding_kind="usage_example_not_declared",
                    severity="info",
                    certainty="advisory",
                    evidence_basis=["runtime_tool_schema"],
                    file=source_file,
                    line=0,
                    subject=tool_name,
                    detail=(
                        f"Tool '{tool_name}' has no visible usage example. "
                        "Add examples in description."
                    ),
                )
            )

    counts = {
        "tools_detected": detected,
        "missing_description": missing_desc,
        "trivial_description": trivial_desc,
        "missing_arg_field_description": missing_arg_desc,
        "usage_example_not_declared": len(indeterminate),
    }

    if missing_desc or missing_arg_desc:
        verdict = "findings"
    elif trivial_desc or indeterminate:
        verdict = "findings"
    else:
        verdict = "pass"

    findings = findings[:max_findings]
    indeterminate = indeterminate[:max_indeterminate]

    return StructuralInspectionResult(
        inspection_id="tool_contract_completeness",
        inspection_version="1.0",
        language_scope="native_registry",
        verdict=verdict,
        summary=(
            f"{detected} daily-use tools detected. "
            f"{missing_desc} missing descriptions, "
            f"{trivial_desc} trivial descriptions, "
            f"{missing_arg_desc} missing arg descriptions, "
            f"{len(indeterminate)} tool(s) missing usage examples."
        ),
        counts=counts,
        findings=findings,
        indeterminate_items=indeterminate,
        suggested_next_action=(
            "Add Field(description=...) to argument models and meaningful "
            "class descriptions for tools listed in findings."
        )
        if findings
        else None,
    )


def _run_deterministic_failure_surface_coverage(
    paths: list[str], max_findings: int, max_indeterminate: int
) -> StructuralInspectionResult:
    findings: list[StructuralFinding] = []
    indeterminate: list[StructuralFinding] = []

    try:
        available = _discover_tools_from_paths(paths)
    except Exception:
        return StructuralInspectionResult(
            inspection_id="deterministic_failure_surface_coverage",
            inspection_version="1.0",
            language_scope="native_registry",
            verdict="indeterminate",
            summary="Tool registry unavailable.",
        )

    generic_only = 0
    structured = 0
    needs_proof = 0

    for tool_name, tool_cls in sorted(available.items()):
        if not _is_daily_use_tool(tool_name):
            continue

        source_file = ""
        try:
            import inspect as _inspect

            source_file = _inspect.getfile(tool_cls)
        except (TypeError, OSError):
            source_file = ""

        has_error_kind = False
        try:
            _, result_model = tool_cls._get_tool_args_results()
            if result_model is not None:
                for fn in result_model.model_fields:
                    if fn in _FAILURE_SURFACE_FIELDS:
                        has_error_kind = True
        except Exception:
            pass

        uses_generic_exceptions = False
        try:
            if source_file and Path(source_file).exists():
                src = Path(source_file).read_text(encoding="utf-8")
                if "ToolError" in src and "error_kind" not in src:
                    uses_generic_exceptions = True
        except Exception:
            pass

        if has_error_kind:
            structured += 1
        elif uses_generic_exceptions:
            generic_only += 1
            findings.append(
                StructuralFinding(
                    finding_kind="generic_failure_path_detected",
                    severity="warning",
                    certainty="definite",
                    evidence_basis=["source_static_scan"],
                    file=source_file,
                    line=0,
                    subject=tool_name,
                    detail=(
                        f"Tool '{tool_name}' uses ToolError but does not expose "
                        "error_kind in its result model."
                    ),
                )
            )
        else:
            needs_proof += 1
            indeterminate.append(
                StructuralFinding(
                    finding_kind="agent_visible_proof_missing",
                    severity="info",
                    certainty="indeterminate",
                    evidence_basis=["source_static_scan"],
                    file=source_file,
                    line=0,
                    subject=tool_name,
                    detail=(
                        f"Tool '{tool_name}' has no detectable structured failure "
                        "surface. Verify manually."
                    ),
                )
            )

    counts = {
        "tools_detected": generic_only + structured + needs_proof,
        "structured_failure_surface_declared": structured,
        "generic_failure_path_detected": generic_only,
        "agent_visible_proof_missing": needs_proof,
    }

    verdict = "pass" if generic_only == 0 else "findings"

    findings = findings[:max_findings]
    indeterminate = indeterminate[:max_indeterminate]

    return StructuralInspectionResult(
        inspection_id="deterministic_failure_surface_coverage",
        inspection_version="1.0",
        language_scope="native_registry",
        verdict=verdict,
        summary=(
            f"{structured} tool(s) with structured failures, "
            f"{generic_only} with generic-only failures, "
            f"{needs_proof} unproven."
        ),
        counts=counts,
        findings=findings,
        indeterminate_items=indeterminate,
        suggested_next_action=(
            "Add error_kind and suggested_next_action to result models for tools "
            "using generic ToolError."
        )
        if generic_only
        else None,
    )


def _run_git_operator_picture_coverage(
    paths: list[str], max_findings: int, max_indeterminate: int
) -> StructuralInspectionResult:
    findings: list[StructuralFinding] = []
    indeterminate: list[StructuralFinding] = []

    try:
        available = _discover_tools_from_paths(paths)
    except Exception:
        return StructuralInspectionResult(
            inspection_id="git_operator_picture_coverage",
            inspection_version="1.0",
            language_scope="native_registry",
            verdict="indeterminate",
            summary="Tool registry unavailable.",
        )

    raw_output = 0
    structured_count = 0

    git_tools = {n: c for n, c in available.items() if n.startswith("git_")}

    for tool_name, tool_cls in sorted(git_tools.items()):
        source_file = ""
        try:
            import inspect as _inspect

            source_file = _inspect.getfile(tool_cls)
        except (TypeError, OSError):
            source_file = ""

        has_detail = False
        try:
            _, result_model = tool_cls._get_tool_args_results()
            if result_model is not None:
                result_fields = set(result_model.model_fields.keys())
                if result_fields & _GIT_DETAIL_FIELDS:
                    has_detail = True
                if result_fields <= _GIT_BARE_FIELDS:
                    has_detail = False
        except Exception:
            pass

        if has_detail:
            structured_count += 1
        else:
            raw_output += 1
            findings.append(
                StructuralFinding(
                    finding_kind="raw_git_output_requires_agent_parsing",
                    severity="warning",
                    certainty="definite",
                    evidence_basis=["native_result_model"],
                    file=source_file,
                    line=0,
                    subject=tool_name,
                    detail=(
                        f"Tool '{tool_name}' returns raw Git stdout. "
                        "Agent must parse porcelain output manually."
                    ),
                )
            )

    counts = {
        "git_tools_detected": len(git_tools),
        "raw_output_requires_agent_parsing": raw_output,
        "structured_fields_present": structured_count,
    }

    verdict = "pass" if raw_output == 0 and structured_count > 0 else "findings"

    findings = findings[:max_findings]
    indeterminate = indeterminate[:max_indeterminate]

    return StructuralInspectionResult(
        inspection_id="git_operator_picture_coverage",
        inspection_version="1.0",
        language_scope="native_registry",
        verdict=verdict,
        summary=(
            f"{structured_count} git tool(s) with structured fields, "
            f"{raw_output} raw-only."
        ),
        counts=counts,
        findings=findings,
        indeterminate_items=indeterminate,
        suggested_next_action=(
            "Add structured result fields to Git read tools to eliminate agent parsing."
        )
        if raw_output
        else None,
    )


def _run_request_classification(
    paths: list[str], max_findings: int, max_indeterminate: int
) -> StructuralInspectionResult:
    findings: list[StructuralFinding] = []
    indeterminate: list[StructuralFinding] = []

    resolved = _resolve_python_files(paths)

    present = 0
    missing = 0
    indeterminate_count = 0

    for file_path in resolved:
        try:
            tree = ast.parse(Path(file_path).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = _resolve_call_name(node)
            if func_name not in _REQUEST_CLASS_NAMES:
                continue

            has_mutation = False
            has_kwargs = False
            for kw in node.keywords:
                if kw.arg == "mutation_class":
                    has_mutation = True
                elif kw.arg is None:
                    has_kwargs = True

            surface = _classify_surface(file_path)

            if has_mutation:
                present += 1
            elif has_kwargs and not has_mutation:
                indeterminate_count += 1
                indeterminate.append(
                    StructuralFinding(
                        finding_kind="indeterminate_dynamic_construction",
                        severity="warning",
                        certainty="indeterminate",
                        evidence_basis=["python_ast"],
                        file=file_path,
                        line=node.lineno,
                        subject=f"ToolRuntimeRequest(**kwargs, surface={surface})",
                        detail=(
                            "ToolRuntimeRequest uses **kwargs — cannot statically "
                            "determine mutation_class."
                        ),
                    )
                )
            else:
                missing += 1
                findings.append(
                    StructuralFinding(
                        finding_kind="missing_required_keyword",
                        severity="blocker",
                        certainty="definite",
                        evidence_basis=["python_ast"],
                        file=file_path,
                        line=node.lineno,
                        subject=f"ToolRuntimeRequest(surface={surface})",
                        detail=(
                            "ToolRuntimeRequest constructed without mutation_class "
                            "keyword."
                        ),
                    )
                )

    counts = {
        "constructions_detected": present + missing + indeterminate_count,
        "mutation_class_present": present,
        "mutation_class_missing": missing,
        "indeterminate_dynamic_construction": indeterminate_count,
    }

    verdict = "pass" if missing == 0 else "findings"

    findings = findings[:max_findings]
    indeterminate = indeterminate[:max_indeterminate]

    return StructuralInspectionResult(
        inspection_id="tool_runtime_request_classification",
        inspection_version="1.0",
        language_scope="python",
        verdict=verdict,
        summary=(
            f"{present} construction(s) with mutation_class, "
            f"{missing} missing, "
            f"{indeterminate_count} indeterminate (**kwargs)."
        ),
        counts=counts,
        findings=findings,
        indeterminate_items=indeterminate,
        suggested_next_action=(
            "Add mutation_class=... to ToolRuntimeRequest calls listed in findings."
        )
        if missing
        else None,
    )


_INSPECTIONS: dict[str, dict[str, Any]] = {
    "tool_contract_completeness": {
        "version": "1.0",
        "description": (
            "Check native built-in tools for present, non-trivial descriptions "
            "and argument Field(description=...) coverage, using the runtime-exposed "
            "tool registry. Source-location mapping for repairs is best-effort via AST."
        ),
        "language_scope": "native_registry",
        "default_paths": ["rig_relay/core/tools/builtins"],
        "determinism_basis": "tool_registry_snapshot",
        "privacy_classification": "content_light_metadata",
        "result_finding_kinds": [
            "missing_description",
            "trivial_description",
            "missing_arg_field_description",
            "usage_example_not_declared",
        ],
    },
    "deterministic_failure_surface_coverage": {
        "version": "1.0",
        "description": (
            "Report which daily-use built-in tools expose predictable operator "
            "failures as structured domain outcomes vs. raw text or generic ToolError. "
            "Combines runtime schema inspection, source-level error-site detection, "
            "and existing contract test evidence where available."
        ),
        "language_scope": "native_registry",
        "default_paths": ["rig_relay/core/tools/builtins"],
        "determinism_basis": "tool_registry_snapshot",
        "privacy_classification": "content_light_metadata",
        "result_finding_kinds": [
            "structured_failure_surface_declared",
            "generic_failure_path_detected",
            "agent_visible_proof_present",
            "agent_visible_proof_missing",
        ],
    },
    "git_operator_picture_coverage": {
        "version": "1.0",
        "description": (
            "Whether native Git read tools expose structured workspace facts "
            "or return raw stdout requiring agent parsing."
        ),
        "language_scope": "native_registry",
        "default_paths": ["rig_relay/core/tools/builtins"],
        "determinism_basis": "tool_registry_snapshot",
        "privacy_classification": "content_light_metadata",
        "result_finding_kinds": [
            "raw_git_output_requires_agent_parsing",
            "structured_field_missing",
        ],
    },
    "tool_runtime_request_classification": {
        "version": "1.0",
        "description": (
            "Classify ToolRuntimeRequest(...) construction sites by mutation_class "
            "keyword presence. Distinguishes native AgentLoop, subagent, and test "
            "surfaces."
        ),
        "language_scope": "python",
        "default_paths": ["rig_relay"],
        "determinism_basis": "repository_snapshot",
        "privacy_classification": "content_light_metadata",
        "result_finding_kinds": [
            "missing_required_keyword",
            "indeterminate_dynamic_construction",
        ],
    },
    "agent_outcome_projection_propagation": {
        "version": "1.0",
        "description": (
            "Inspect native AgentLoop projection sinks (derive_agent_outcome, "
            "format_agent_outcome, ToolResultRuntime, telemetry evidence) to verify "
            "canonical AgentToolOutcome fields survive through the model-visible path. "
            "Checks for exclude_none serialization risks, missing fields in sinks, "
            "and intentional telemetry exclusions. Native sinks only — no bridge inspection."
        ),
        "language_scope": "python",
        "default_paths": [
            "rig_relay/core/tools/_agent_outcome.py",
            "rig_relay/core/tool_result_runtime",
            "rig_relay/core/telemetry_evidence_service.py",
        ],
        "determinism_basis": "repository_snapshot",
        "privacy_classification": "content_light_metadata",
        "result_finding_kinds": [
            "exclude_none_drops_conditional_field",
            "formatter_filters_canonical_field",
            "telemetry_missing_canonical_field",
            "injection_path_alters_outcome",
        ],
    },
}


_PROJECTION_CANONICAL_ALWAYS: frozenset[str] = frozenset({
    "schema_version",
    "tool_name",
    "tool_call_id",
    "status",
    "retryable",
    "retryability_basis",
    "mutation_disposition",
    "authority_decision",
    "authority_source",
    "degraded_capabilities",
    "cache_hit",
})

_PROJECTION_CANONICAL_CONDITIONAL: frozenset[str] = frozenset({
    "error_kind",
    "refusal_code",
    "recoverable",
    "suggested_next_action",
    "suggested_next_action_source",
    "mission_identity",
    "matched_rule_kind",
})

_PROJECTION_TELEMETRY_INTENTIONAL_OMIT: frozenset[str] = frozenset({
    "suggested_next_action",  # safety: only _source in telemetry
    "warnings",  # safety: only warning_count in telemetry
})

_MODEL_DUMP_ATTRS: frozenset[str] = frozenset({"model_dump", "model_dump_json"})
_FILTER_KWARGS: frozenset[str] = frozenset({"exclude", "include"})


def _projection_scan_exclude_none(
    file_path: str, tree: ast.AST, findings: list[StructuralFinding]
) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "format_agent_outcome":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            for kw in child.keywords:
                if not _is_exclude_none_true(kw):
                    continue
                for field in sorted(_PROJECTION_CANONICAL_CONDITIONAL):
                    findings.append(
                        _make_exclude_none_finding(file_path, child.lineno, field)
                    )
        return


def _is_exclude_none_true(kw: ast.keyword) -> bool:
    return (
        kw.arg == "exclude_none"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value is True
    )


def _make_exclude_none_finding(
    file_path: str, line: int, field: str
) -> StructuralFinding:
    return StructuralFinding(
        finding_kind="exclude_none_drops_conditional_field",
        severity="warning",
        certainty="advisory",
        evidence_basis=["python_ast"],
        file=file_path,
        line=line,
        subject=f"AgentToolOutcome.{field}",
        detail=(
            f"Field '{field}' can be None and is dropped "
            f"by exclude_none=True in format_agent_outcome(). "
            f"When absent, the model cannot distinguish "
            f"'not applicable' from serialization loss."
        ),
    )


def _projection_scan_telemetry(
    file_path: str, tree: ast.AST, findings: list[StructuralFinding]
) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "emit_agent_outcome_projection":
            continue
        telemetry_fields = _collect_telemetry_dict_keys(node)
        missing_always = _PROJECTION_CANONICAL_ALWAYS - telemetry_fields
        for field in sorted(missing_always):
            if field in _PROJECTION_TELEMETRY_INTENTIONAL_OMIT:
                findings.append(
                    StructuralFinding(
                        finding_kind="telemetry_missing_canonical_field",
                        severity="info",
                        certainty="advisory",
                        evidence_basis=["python_ast"],
                        file=file_path,
                        line=node.lineno,
                        subject=f"telemetry.{field}",
                        detail=f"Field '{field}' intentionally excluded from telemetry (privacy/safety).",
                    )
                )
            else:
                findings.append(
                    StructuralFinding(
                        finding_kind="telemetry_missing_canonical_field",
                        severity="warning",
                        certainty="definite",
                        evidence_basis=["python_ast"],
                        file=file_path,
                        line=node.lineno,
                        subject=f"telemetry.{field}",
                        detail=f"Canonical field '{field}' not found in telemetry properties dict.",
                    )
                )
        return


def _collect_telemetry_dict_keys(func_node: ast.AST) -> set[str]:
    keys: set[str] = set()
    for child in ast.walk(func_node):
        if isinstance(child, ast.Dict):
            for key_node in child.keys:
                if isinstance(key_node, ast.Constant) and isinstance(
                    key_node.value, str
                ):
                    keys.add(key_node.value)
    return keys


def _projection_scan_result_runtime(
    file_path: str,
    tree: ast.AST,
    findings: list[StructuralFinding],
    indeterminate: list[StructuralFinding],
) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "handle_tool_response":
            continue
        has_filter = False
        for child in ast.walk(node):
            if isinstance(child, ast.DictComp):
                continue
            if not isinstance(child, ast.Call):
                continue
            if not isinstance(child.func, ast.Attribute):
                continue
            if child.func.attr not in _MODEL_DUMP_ATTRS:
                continue
            for kw in child.keywords:
                if kw.arg not in _FILTER_KWARGS:
                    continue
                has_filter = True
                findings.append(
                    StructuralFinding(
                        finding_kind="injection_path_alters_outcome",
                        severity="blocker",
                        certainty="definite",
                        evidence_basis=["python_ast"],
                        file=file_path,
                        line=child.lineno,
                        subject="AgentToolOutcome projection",
                        detail=(
                            f"handle_tool_response applies {kw.arg} filter "
                            f"to AgentToolOutcome serialization. "
                            f"Canonical fields may be dropped before the model sees them."
                        ),
                    )
                )
        if not has_filter:
            indeterminate.append(
                StructuralFinding(
                    finding_kind="injection_path_alters_outcome",
                    severity="info",
                    certainty="advisory",
                    evidence_basis=["python_ast"],
                    file=file_path,
                    line=node.lineno,
                    subject="AgentToolOutcome projection",
                    detail=(
                        "No allowlist/filter detected in handle_tool_response. "
                        "Full outcome appears to reach the model message. "
                        "Verify with a real integration test."
                    ),
                )
            )
        return


def _run_projection_inspection(
    paths: list[str], max_findings: int, max_indeterminate: int
) -> StructuralInspectionResult:
    findings: list[StructuralFinding] = []
    indeterminate: list[StructuralFinding] = []

    resolved = _resolve_python_files(paths)

    for file_path in resolved:
        try:
            tree = ast.parse(Path(file_path).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue

        if "_agent_outcome.py" in file_path:
            _projection_scan_exclude_none(file_path, tree, findings)
        if "telemetry_evidence_service.py" in file_path:
            _projection_scan_telemetry(file_path, tree, findings)
        if "tool_result_runtime" in file_path:
            _projection_scan_result_runtime(file_path, tree, findings, indeterminate)

    counts = {
        "sinks_inspected": len(resolved),
        "exclude_none_conditional_risks": sum(
            1
            for f in findings
            if f.finding_kind == "exclude_none_drops_conditional_field"
        ),
        "telemetry_safety_exclusions": sum(1 for f in findings if f.severity == "info"),
        "definite_blockers": sum(1 for f in findings if f.certainty == "definite"),
    }

    verdict = "findings" if any(f.certainty == "definite" for f in findings) else "pass"

    return StructuralInspectionResult(
        inspection_id="agent_outcome_projection_propagation",
        inspection_version="1.0",
        language_scope="python",
        verdict=verdict,
        summary=(
            f"{len(resolved)} sink(s) inspected. "
            f"{counts['exclude_none_conditional_risks']} exclude_none risks, "
            f"{counts['definite_blockers']} definite blockers."
        ),
        counts=counts,
        findings=findings[:max_findings],
        indeterminate_items=indeterminate[:max_indeterminate],
        suggested_next_action=(
            "Address definite blockers by adding missing canonical fields to telemetry. "
            "Consider replacing exclude_none with explicit field selection in format_agent_outcome."
            if counts["definite_blockers"]
            else None
        ),
    )


_tool_contract_recipe = _INSPECTIONS["tool_contract_completeness"]
_tool_contract_recipe["impl"] = _run_tool_contract_completeness

_failure_recipe = _INSPECTIONS["deterministic_failure_surface_coverage"]
_failure_recipe["impl"] = _run_deterministic_failure_surface_coverage

_git_recipe = _INSPECTIONS["git_operator_picture_coverage"]
_git_recipe["impl"] = _run_git_operator_picture_coverage

_classification_recipe = _INSPECTIONS["tool_runtime_request_classification"]
_classification_recipe["impl"] = _run_request_classification

_projection_recipe = _INSPECTIONS["agent_outcome_projection_propagation"]
_projection_recipe["impl"] = _run_projection_inspection


class InspectStructureConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class InspectStructure(
    BaseTool[
        InspectStructureArgs,
        StructuralInspectionResult,
        InspectStructureConfig,
        BaseToolState,
    ]
):
    description: ClassVar[str] = (
        "Run a named deterministic code inspection against the repository. "
        "Returns normalized findings and a verdict — the agent receives "
        "classified results rather than raw syntax hits. "
        "Available inspections: tool_contract_completeness, "
        "deterministic_failure_surface_coverage, git_operator_picture_coverage, "
        "tool_runtime_request_classification, "
        "agent_outcome_projection_propagation. "
        "Each inspection has its own deterministic rule, result contract, and "
        "bounded output."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY

    def __init__(self, config_getter: Any = None, state: Any = None) -> None:
        super().__init__(config_getter=config_getter, state=state)

    async def run(
        self, args: InspectStructureArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | StructuralInspectionResult, None]:
        inspection_id = args.inspection
        recipe = _INSPECTIONS.get(inspection_id)
        if recipe is None:
            yield StructuralInspectionResult(
                inspection_id=inspection_id,
                inspection_version="unknown",
                language_scope="none",
                verdict="indeterminate",
                summary=f"Unknown inspection: {inspection_id}",
                suggested_next_action=(
                    "Available inspections: " + ", ".join(sorted(_INSPECTIONS.keys()))
                ),
            )
            return

        impl = recipe.get("impl")
        if impl is None:
            yield StructuralInspectionResult(
                inspection_id=inspection_id,
                inspection_version=recipe["version"],
                language_scope=recipe["language_scope"],
                verdict="indeterminate",
                summary=f"Inspection not implemented: {inspection_id}",
                suggested_next_action=(
                    "This inspection is registered but has no implementation."
                ),
            )
            return

        paths: list[str] = args.paths if args.paths else recipe["default_paths"]
        result = impl(paths, args.max_findings, args.max_indeterminate)
        result.inspection_id = inspection_id
        result.inspection_version = recipe["version"]
        result.language_scope = recipe["language_scope"]
        yield result


__all__ = [
    "_INSPECTIONS",
    "InspectStructure",
    "InspectStructureArgs",
    "StructuralFinding",
    "StructuralInspectionResult",
]

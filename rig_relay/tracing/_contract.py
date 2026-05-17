"""Trace Contract Enforcement — reusable validation helpers.

Loads the canonical correlation vocabulary and correlated visibility
matrix, then validates emitted trace events against them.

Architecture:
    TraceContractRegistry  — loads vocabulary + matrix into normalized lookup
    EventEmissionScanner   — scans codebase for trace event emission sites
    TraceContractValidator — validates emissions against registry
    TraceContractReport    — structured violation report

All helpers are content-light: no raw paths, no secrets, no payload.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, ClassVar

# ── Models ────────────────────────────────────────────────────────────


@dataclass
class RegisteredEvent:
    """A trace event known to the contract registry."""

    event_name: str
    domain: str
    owner_component: str = ""
    required: bool = False
    safety_class: str = "safe"
    propagation_rules: str = ""
    path_ids: list[str] = field(default_factory=list)
    status: str = "active"

    def is_future(self) -> bool:
        return self.status in {"planned", "future", "reserved", "deprecated"}

    def is_emittable(self) -> bool:
        return self.status not in {"deprecated"}


@dataclass
class EmittedEvent:
    """A trace event discovered in the codebase."""

    event_name: str
    source_file: str
    line: int | None = None
    snippet: str = ""


@dataclass
class ContractViolation:
    """A single contract violation."""

    violation_id: str
    kind: str
    severity: str
    event_name: str = ""
    source_file: str = ""
    line: int | None = None
    description: str = ""
    recommendation: str = ""


# ── Registry ──────────────────────────────────────────────────────────


class TraceContractRegistry:
    """Loads vocabulary + matrix into normalized lookup tables."""

    def __init__(
        self, vocab_path: Path | None = None, matrix_path: Path | None = None
    ) -> None:
        self._vocab_path = vocab_path
        self._matrix_path = matrix_path
        self._events: dict[str, RegisteredEvent] = {}
        self._correlation_fields: dict[str, dict[str, Any]] = {}
        self._paths: dict[str, dict[str, Any]] = {}
        self._loaded = False

    @property
    def events(self) -> dict[str, RegisteredEvent]:
        self._ensure_loaded()
        return self._events

    @property
    def correlation_fields(self) -> dict[str, dict[str, Any]]:
        self._ensure_loaded()
        return self._correlation_fields

    @property
    def paths(self) -> dict[str, dict[str, Any]]:
        self._ensure_loaded()
        return self._paths

    def _default_vocab_path(self) -> Path:
        return (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "json"
            / "tracing"
            / "correlation_vocabulary.v1.json"
        )

    def _default_matrix_path(self) -> Path:
        return (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "json"
            / "tracing"
            / "correlated_visibility_matrix.v1.json"
        )

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._load_vocabulary()
        self._load_matrix()
        self._index_events_from_paths()
        self._loaded = True

    def _load_vocabulary(self) -> None:
        path = self._vocab_path or self._default_vocab_path()
        if not path.is_file():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        for fentry in data.get("fields", []):
            name = fentry.get("field_name", "")
            if name:
                self._correlation_fields[name] = {
                    "owner_component": fentry.get("owner_component", ""),
                    "required_optional": fentry.get("required_optional", "optional"),
                    "safe_to_log": fentry.get("safe_to_log_classification", "safe"),
                    "propagation_rules": fentry.get("propagation_rules", ""),
                    "status": fentry.get("current_implementation_status", "missing"),
                }

    def _load_matrix(self) -> None:
        path = self._matrix_path or self._default_matrix_path()
        if not path.is_file():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        for cp in data.get("critical_paths", []):
            path_id = cp.get("path_id", "")
            if path_id:
                self._paths[path_id] = {
                    "visibility_status": cp.get("visibility_status", "unknown"),
                    "release_blocker": cp.get("release_blocker", False),
                    "owner_area": cp.get("owner_area", ""),
                    "required_correlation_fields": cp.get(
                        "required_correlation_fields", []
                    ),
                    "current_events_found": cp.get("current_events_found", []),
                    "missing_events": cp.get("missing_events", []),
                    "required_start_event": cp.get("required_start_event", ""),
                    "required_success_event": cp.get("required_success_event", ""),
                    "required_failure_events": cp.get("required_failure_events", []),
                    "required_refusal_events": cp.get("required_refusal_events", []),
                }

    def _index_events_from_paths(self) -> None:
        """Derive RegisteredEvent entries from visibility matrix paths."""
        for path_id, path_data in self._paths.items():
            events_found = path_data.get("current_events_found", [])
            owner = path_data.get("owner_area", "")
            for raw_event in events_found:
                name = self._normalize_event_name(raw_event)
                if not name:
                    continue
                if name not in self._events:
                    self._events[name] = RegisteredEvent(
                        event_name=name,
                        domain=self._infer_domain(name),
                        owner_component=owner,
                        path_ids=[path_id],
                    )
                elif path_id not in self._events[name].path_ids:
                    self._events[name].path_ids.append(path_id)

            # Also process required events that might not be in current_events_found
            for key in ("required_start_event", "required_success_event"):
                ev = path_data.get(key, "")
                if ev and ev not in self._events:
                    self._events[ev] = RegisteredEvent(
                        event_name=ev,
                        domain=self._infer_domain(ev),
                        owner_component=owner,
                        path_ids=[path_id],
                        status="planned",
                    )

    @staticmethod
    def _canonicalize(name: str) -> str:
        """Normalize event names: dots→underscores for consistent matching."""
        return name.replace(".", "_").strip()

    @staticmethod
    def _normalize_event_name(raw: str) -> str:
        """Strip reason annotations like '(reason: invalid_json)'. Canonicalize."""
        raw = raw.strip()
        idx = raw.find(" (reason:")
        if idx > 0:
            raw = raw[:idx].strip()
        idx = raw.find(" (OpenTelemetry)")
        if idx > 0:
            raw = raw[:idx].strip()
        idx = raw.find(" (local)")
        if idx > 0:
            raw = raw[:idx].strip()
        return TraceContractRegistry._canonicalize(raw)

    @staticmethod
    def _infer_domain(name: str) -> str:
        domain = TraceContractRegistry._canonicalize(name)
        if "_" in domain:
            return domain.split("_", 1)[0]
        return "unknown"

    def get_event(self, name: str) -> RegisteredEvent | None:
        self._ensure_loaded()
        canonical = self._canonicalize(name)
        if canonical in self._events:
            return self._events[canonical]
        return self._events.get(name)

    def get_correlation_field(self, name: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        return self._correlation_fields.get(name)

    def get_path(self, path_id: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        return self._paths.get(path_id)


# ── Scanner ───────────────────────────────────────────────────────────

# Matches emitted trace event names: string literals that look like domain.event_name
_EVENT_EMISSION_REGEX = re.compile(
    r"""["']((?:desktop\.|frontend[_.]|agent\.|tool[_.]|context\.|"""
    r"""worktree\.|docs\.|session\.|security\.|coordination\.|"""
    r"""runtime\.|subagent\.|validate\.)[a-z_.]{3,80})["']"""
)

# Prefix fragments for quick pre-filter (skip files with no event prefixes)
_SCAN_PREFIXES = (
    "desktop.",
    "frontend_",
    "frontend.",
    "agent.",
    "tool.",
    "tool_",
    "context.",
    "worktree.",
    "docs.",
    "session.",
    "security.",
    "coordination.",
    "runtime.",
    "subagent.",
    "validate.",
)

# Frontend event names use underscores or dots
_FRONTEND_EVENT_REGEX = re.compile(r"""['"](frontend[_.][a-z_]{3,60})['"]""")

_EXCLUDED_DIRS = {
    "__pycache__",
    ".git",
    ".build",
    "node_modules",
    ".rig",
    "generated",
    ".venv",
    "venv",
    "site-packages",
    "pages",
    "collections",
    "assets",
}

_EXCLUDED_FILES = {
    ".html",
    ".svg",
    ".png",
    ".jpg",
    ".json",
    ".lock",
    ".toml",
    ".yml",
    ".yaml",
}
_EXCLUDED_SCRIPTS = {
    "scripts/rig_relay_trace_visibility_audit.py",
    "scripts/rig_relay_trace_golden_path.py",
    "scripts/rig_relay_trace_handshake.py",
}


# Correlation field names that should not be treated as event names
_CORRELATION_FIELD_EXCLUSIONS: frozenset[str] = frozenset({
    "frontend_session_id",
    "frontend_sequence",
    "backend_sequence",
    "event_sequence",
    "performance_now_ms",
    "monotonic_ns",
    "handshake_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "connection_id",
    "session_id",
    "job_id",
    "tool_batch_id",
    "tool_call_id",
    "agent_id",
    "lane_id",
    "worktree_id",
    "request_id",
    "schema_id",
    "document_id",
    "commit_sha",
    "repo_head",
    "wall_time",
})


class EventEmissionScanner:
    """Scans Python and JavaScript source files for trace event emissions."""

    _scan_cache: ClassVar[dict[Path, list[EmittedEvent]]] = {}

    def __init__(self, repo_root: Path | None = None) -> None:
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]

    def scan(self) -> list[EmittedEvent]:
        if self._repo_root in self._scan_cache:
            return list(self._scan_cache[self._repo_root])
        events: list[EmittedEvent] = []
        for py_file in self._repo_root.rglob("*.py"):
            if self._is_excluded(py_file):
                continue
            events.extend(self._scan_python(py_file))
        for js_file in (self._repo_root / "frontend" / "desktop" / "js").rglob("*.js"):
            if self._is_excluded(js_file):
                continue
            events.extend(self._scan_javascript(js_file))
        self._scan_cache[self._repo_root] = events
        return list(events)

    def _is_excluded(self, path: Path) -> bool:
        parts = set(path.parts)
        if parts & _EXCLUDED_DIRS:
            return True
        if path.name.startswith(".") or path.name.endswith(".pyc"):
            return True
        if any(path.name.endswith(ext) for ext in _EXCLUDED_FILES):
            return True
        repo_rel = (
            str(path.relative_to(self._repo_root))
            if hasattr(self, "_repo_root")
            else str(path)
        )
        if repo_rel in _EXCLUDED_SCRIPTS:
            return True
        return False

    def _repo_rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self._repo_root))
        except ValueError:
            return str(path)

    def _is_correlation_field(self, name: str) -> bool:
        """Filter out names that are correlation fields, not trace events."""
        canonical = name.replace(".", "_").strip()
        return canonical in _CORRELATION_FIELD_EXCLUSIONS

    def _scan_python(self, path: Path) -> list[EmittedEvent]:
        events: list[EmittedEvent] = []
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return events

        if not any(p in content for p in _SCAN_PREFIXES):
            return events

        try:
            tree = ast.parse(content, filename=str(path))
        except SyntaxError:
            return events

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for match in _EVENT_EMISSION_REGEX.finditer(node.value):
                    name = match.group(1)
                    if self._is_correlation_field(name):
                        continue
                    events.append(
                        EmittedEvent(
                            event_name=name,
                            source_file=self._repo_rel(path),
                            line=node.lineno,
                            snippet=node.value[:100],
                        )
                    )

        # Also scan raw text for f-strings and dynamic constructions
        for match in _EVENT_EMISSION_REGEX.finditer(content):
            name = match.group(1)
            if self._is_correlation_field(name):
                continue
            events.append(
                EmittedEvent(event_name=name, source_file=self._repo_rel(path))
            )

        return events

    def _scan_javascript(self, path: Path) -> list[EmittedEvent]:
        events: list[EmittedEvent] = []
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return events

        for i, line in enumerate(content.splitlines(), start=1):
            for match in _FRONTEND_EVENT_REGEX.finditer(line):
                name = match.group(1)
                events.append(
                    EmittedEvent(
                        event_name=name,
                        source_file=self._repo_rel(path),
                        line=i,
                        snippet=line.strip()[:100],
                    )
                )

            for match in _EVENT_EMISSION_REGEX.finditer(line):
                name = match.group(1)
                events.append(
                    EmittedEvent(
                        event_name=name,
                        source_file=self._repo_rel(path),
                        line=i,
                        snippet=line.strip()[:100],
                    )
                )

        return events


# ── Validator ─────────────────────────────────────────────────────────


class TraceContractValidator:
    """Validates emitted events against the contract registry."""

    def __init__(self, registry: TraceContractRegistry | None = None) -> None:
        self._registry = registry or TraceContractRegistry()
        self._violations: list[ContractViolation] = []
        self._vid = 0

    @property
    def registry(self) -> TraceContractRegistry:
        return self._registry

    @property
    def violations(self) -> list[ContractViolation]:
        return self._violations

    def _add(
        self,
        kind: str,
        severity: str,
        *,
        event_name: str = "",
        source_file: str = "",
        line: int | None = None,
        description: str = "",
        recommendation: str = "",
    ) -> None:
        self._vid += 1
        self._violations.append(
            ContractViolation(
                violation_id=f"TC-{self._vid:04d}",
                kind=kind,
                severity=severity,
                event_name=event_name,
                source_file=source_file,
                line=line,
                description=description,
                recommendation=recommendation,
            )
        )

    def validate_all(self, emitted: list[EmittedEvent]) -> list[ContractViolation]:
        self._violations = []
        self._vid = 0

        self._check_emitted_registered(emitted)
        self._check_registered_emitted(emitted)
        self._check_vocabulary_integrity()
        self._check_matrix_integrity()
        self._check_duplicates(emitted)

        return self._violations

    def _check_emitted_registered(self, emitted: list[EmittedEvent]) -> None:
        seen: set[str] = set()
        for ev in emitted:
            name = ev.event_name
            if name in seen:
                continue
            seen.add(name)
            if "test" in ev.source_file.lower() or ev.source_file.startswith("tests/"):
                continue
            registered = self._registry.get_event(name)
            if registered is None:
                self._add(
                    "unregistered_event",
                    "high",
                    event_name=name,
                    source_file=ev.source_file,
                    line=ev.line,
                    description=f"Emitted event '{name}' is not registered in vocabulary or visibility matrix.",
                    recommendation=f"Add '{name}' to correlation vocabulary or visibility matrix, or remove the emission.",
                )

    def _check_registered_emitted(self, emitted: list[EmittedEvent]) -> None:
        emitted_canonical = {
            self._registry._canonicalize(ev.event_name) for ev in emitted
        }
        for name, reg in self._registry.events.items():
            if reg.is_future():
                continue
            if self._registry._canonicalize(name) not in emitted_canonical:
                self._add(
                    "registered_never_emitted",
                    "medium",
                    event_name=name,
                    description=f"Registered event '{name}' (paths: {', '.join(reg.path_ids)}) is never emitted in codebase.",
                    recommendation=f"Either emit '{name}' in source code or mark it as planned/deprecated in the vocabulary.",
                )

    def _check_vocabulary_integrity(self) -> None:
        for name, fdef in self._registry.correlation_fields.items():
            if not fdef.get("owner_component"):
                self._add(
                    "missing_owner",
                    "high",
                    event_name=name,
                    description=f"Correlation field '{name}' is missing owner_component.",
                    recommendation="Add owner_component to the field definition.",
                )
            if not fdef.get("safe_to_log"):
                self._add(
                    "missing_safety",
                    "high",
                    event_name=name,
                    description=f"Correlation field '{name}' is missing safe_to_log_classification.",
                    recommendation="Add safe_to_log_classification to the field definition.",
                )
            if not fdef.get("propagation_rules"):
                self._add(
                    "missing_propagation",
                    "medium",
                    event_name=name,
                    description=f"Correlation field '{name}' is missing propagation_rules.",
                    recommendation="Add propagation_rules to the field definition.",
                )
            required = fdef.get("required_optional", "")
            if required not in {"required", "optional", "conditional"}:
                self._add(
                    "malformed_required",
                    "high",
                    event_name=name,
                    description=f"Correlation field '{name}' has invalid required_optional value: '{required}'.",
                    recommendation="Set required_optional to 'required', 'optional', or 'conditional'.",
                )

    def _check_matrix_integrity(self) -> None:
        for path_id, path_data in self._registry.paths.items():
            events = path_data.get("current_events_found", [])
            for raw_event in events:
                name = TraceContractRegistry._normalize_event_name(raw_event)
                if not name:
                    continue
                if self._registry.get_event(name) is None:
                    self._add(
                        "matrix_orphan_event",
                        "high",
                        event_name=name,
                        description=f"Visibility path '{path_id}' references event '{name}' not indexed in registry.",
                        recommendation="Ensure event is in vocabulary or remove from path.",
                    )

            # Verify required fields exist
            for field_name in path_data.get("required_correlation_fields", []):
                if field_name not in self._registry.correlation_fields:
                    self._add(
                        "matrix_unknown_field",
                        "medium",
                        event_name=field_name,
                        description=f"Visibility path '{path_id}' requires correlation field '{field_name}' not in vocabulary.",
                        recommendation="Add field to vocabulary or remove from path requirements.",
                    )

    def _check_duplicates(self, emitted: list[EmittedEvent]) -> None:
        names: dict[str, list[EmittedEvent]] = {}
        for ev in emitted:
            names.setdefault(ev.event_name, []).append(ev)
        # Duplicate is fine (multiple emission sites). Check for near-duplicate
        # event names that might indicate naming inconsistency.
        normalized: dict[str, str] = {}
        for name in names:
            key = name.replace("_", ".").lower()
            if key in normalized:
                existing = normalized[key]
                if existing != name:
                    self._add(
                        "naming_inconsistency",
                        "low",
                        event_name=name,
                        description=f"Event '{name}' and '{existing}' have the same normalized form. "
                        "Consider consistent naming (dots vs underscores).",
                        recommendation="Standardize event naming to use dots (domain.event) consistently.",
                    )
            else:
                normalized[key] = name

    def is_clean(self) -> bool:
        return len(self._violations) == 0

    def has_blockers(self) -> bool:
        return any(v.severity == "high" for v in self._violations)


# ── Report ────────────────────────────────────────────────────────────


def build_contract_report(
    emitted: list[EmittedEvent],
    violations: list[ContractViolation],
    registry: TraceContractRegistry,
) -> dict[str, Any]:
    """Build a structured contract enforcement report."""
    from datetime import UTC, datetime

    return {
        "schema_version": "rig.trace_contract_report.v1",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "total_emitted": len(set(ev.event_name for ev in emitted)),
            "total_registered": len(registry.events),
            "total_violations": len(violations),
            "high_severity": sum(1 for v in violations if v.severity == "high"),
            "medium_severity": sum(1 for v in violations if v.severity == "medium"),
            "low_severity": sum(1 for v in violations if v.severity == "low"),
            "clean": len(violations) == 0,
        },
        "violations": [
            {
                "violation_id": v.violation_id,
                "kind": v.kind,
                "severity": v.severity,
                "event_name": v.event_name,
                "source_file": v.source_file,
                "line": v.line,
                "description": v.description,
                "recommendation": v.recommendation,
            }
            for v in violations
        ],
        "emitted_events": sorted(set(ev.event_name for ev in emitted)),
        "registered_events": sorted(registry.events.keys()),
        "paths": {
            pid: {
                "visibility_status": pd["visibility_status"],
                "events_found": len(pd.get("current_events_found", [])),
                "events_missing": len(pd.get("missing_events", [])),
            }
            for pid, pd in registry.paths.items()
        },
    }

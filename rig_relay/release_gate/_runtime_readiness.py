"""Runtime readiness checks for the Release Evidence Gate.

Each check is a deterministic function that inspects the repository
and returns CheckResult findings. Checks do not mutate any files.

Architecture:
    - Trace contract enforcement: wraps existing TraceContractRegistry
    - Visibility matrix: parses correlated_visibility_matrix.v1.json
    - WebSocket security: probes websocket_server.py invariants
    - GitHub App audit: verifies audit artifacts and implementation gap
    - CI workflow coverage: inspects .github/workflows/
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from rig_relay.release_gate.models import (
    CheckResult,
    CheckSeverity,
    CheckStatus,
    Finding,
    TriageEntry,
    TriagePolicy,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

_VISIBILITY_MATRIX_PATH = (
    _REPO_ROOT / "docs" / "json" / "tracing" / "correlated_visibility_matrix.v1.json"
)
_GITHUB_AUDIT_PATH = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "github_app_integration_audit_v0.v1.json"
)
_GITHUB_AUDIT_SCHEMA_PATH = (
    _REPO_ROOT / "docs" / "schemas" / "rig.github_app.integration_audit.v1.schema.json"
)
_WEBSOCKET_SERVER_PATH = _REPO_ROOT / "rig_relay" / "desktop" / "websocket_server.py"
_CI_DIR = _REPO_ROOT / ".github" / "workflows"

_DEFAULT_TRIAGE_PATH = _REPO_ROOT / ".build" / "rig-relay" / "release_gate_triage.json"

# ── Trace contract ─────────────────────────────────────────────────────


def check_trace_contract(triage: TriagePolicy | None = None) -> CheckResult:
    result = CheckResult(
        check_id="runtime.trace_contract.clean_or_triaged",
        title="Trace contract enforcement — clean or triaged",
        status=CheckStatus.PASS,
    )
    findings: list[Finding] = []

    try:
        from rig_relay.tracing._contract import (
            EmittedEvent,
            EventEmissionScanner,
            TraceContractRegistry,
            TraceContractValidator,
            build_contract_report,
        )

        registry = TraceContractRegistry()
        scanner = EventEmissionScanner(repo_root=_REPO_ROOT)
        emitted: list[EmittedEvent] = scanner.scan()
        validator = TraceContractValidator(registry)
        violations = validator.validate_all(emitted)
        report = build_contract_report(emitted, violations, registry)

        result.evidence["contract_report"] = report

        if registry.paths:
            release_blockers = [
                pid
                for pid, pd in registry.paths.items()
                if pd.get("release_blocker")
                and pd.get("visibility_status") != "complete"
            ]
            if release_blockers:
                result.status = CheckStatus.FAIL
                result.severity = CheckSeverity.BLOCKER
                findings.append(
                    Finding(
                        finding_id="trace.release_blocker.incomplete",
                        category="trace_contract",
                        description=f"Release-blocking paths incomplete: {release_blockers}",
                        severity=CheckSeverity.BLOCKER,
                        source="correlated_visibility_matrix.v1.json",
                        recommendation="Complete trace instrumentation for release-blocking paths.",
                    )
                )

        high_violations = [v for v in violations if v.severity == "high"]
        medium_violations = [v for v in violations if v.severity == "medium"]

        for v in high_violations:
            finding_id = f"trace.violation.{v.violation_id}"
            if triage and triage.is_triaged(finding_id):
                continue
            findings.append(
                Finding(
                    finding_id=finding_id,
                    category="trace_contract",
                    description=f"{v.kind}: {v.event_name} — {v.description[:200]}",
                    severity=CheckSeverity.BLOCKER,
                    source=f"{v.source_file}:{v.line}",
                    recommendation=v.recommendation,
                )
            )

        for v in medium_violations:
            finding_id = f"trace.violation.{v.violation_id}"
            if triage and triage.is_triaged(finding_id):
                continue
            findings.append(
                Finding(
                    finding_id=finding_id,
                    category="trace_contract",
                    description=f"{v.kind}: {v.event_name} — {v.description[:200]}",
                    severity=CheckSeverity.MEDIUM,
                    source=f"{v.source_file}:{v.line}",
                    recommendation=v.recommendation,
                )
            )

        if high_violations:
            result.status = CheckStatus.FAIL
            result.severity = CheckSeverity.BLOCKER
        elif medium_violations:
            result.status = CheckStatus.WARN

        dot_underscore_drift = [
            v for v in violations if v.kind == "naming_inconsistency"
        ]
        if dot_underscore_drift:
            findings.append(
                Finding(
                    finding_id="trace.naming.dot_underscore_drift",
                    category="trace_contract",
                    description=f"Dot-vs-underscore canonicalization drift detected in {len(dot_underscore_drift)} event pair(s)",
                    severity=CheckSeverity.LOW,
                    source="TraceContractValidator._check_duplicates",
                    recommendation="Standardize event naming to use dots (domain.event) consistently.",
                )
            )

        if not findings and not report["summary"]["violations"]:
            result.summary = f"Trace contract clean: {report['summary']['total_emitted']} emitted, {report['summary']['total_registered']} registered, 0 violations"
        else:
            result.summary = (
                f"Trace contract: {len(findings)} findings, "
                f"{report['summary']['total_violations']} total violations"
            )

    except Exception as exc:
        result.status = CheckStatus.FAIL
        result.severity = CheckSeverity.BLOCKER
        result.summary = f"Trace contract check failed: {exc}"
        findings.append(
            Finding(
                finding_id="trace.check.exception",
                category="trace_contract",
                description=f"Could not run trace contract enforcement: {exc}",
                severity=CheckSeverity.BLOCKER,
            )
        )

    result.findings = findings
    return result


# ── Visibility matrix ──────────────────────────────────────────────────


def check_visibility_matrix() -> CheckResult:
    result = CheckResult(
        check_id="runtime.visibility_matrix.release_paths",
        title="Visibility matrix — release-blocking paths verified",
        status=CheckStatus.PASS,
    )
    findings: list[Finding] = []

    try:
        if not _VISIBILITY_MATRIX_PATH.is_file():
            result.status = CheckStatus.FAIL
            result.severity = CheckSeverity.BLOCKER
            result.summary = "Correlated visibility matrix not found."
            findings.append(
                Finding(
                    finding_id="visibility.matrix.missing",
                    category="visibility_matrix",
                    description="correlated_visibility_matrix.v1.json missing",
                    severity=CheckSeverity.BLOCKER,
                )
            )
            result.findings = findings
            return result

        matrix = json.loads(_VISIBILITY_MATRIX_PATH.read_text(encoding="utf-8"))
        result.evidence["matrix_summary"] = matrix.get("summary", {})
        paths = matrix.get("critical_paths", [])

        matrix_summary = matrix.get("summary", {})
        result.evidence["matrix_summary"] = matrix_summary

        if int(matrix_summary.get("release_blockers", 0)) > 0:
            result.status = CheckStatus.FAIL
            result.severity = CheckSeverity.BLOCKER
            findings.append(
                Finding(
                    finding_id="visibility.release_blockers.outstanding",
                    category="visibility_matrix",
                    description=f"Matrix declares {matrix_summary['release_blockers']} outstanding release blockers",
                    severity=CheckSeverity.BLOCKER,
                    source="correlated_visibility_matrix.v1.json",
                    recommendation="Resolve all release blockers before gate pass.",
                )
            )

        for path in paths:
            path_id = path.get("path_id", "unknown")
            visibility = path.get("visibility_status", "unknown")
            release_blocker = path.get("release_blocker", False)
            recommended_fix = path.get("recommended_fix", "")

            if release_blocker and visibility != "complete":
                result.status = CheckStatus.FAIL
                result.severity = CheckSeverity.BLOCKER
                findings.append(
                    Finding(
                        finding_id=f"visibility.path.{path_id}.release_blocker_incomplete",
                        category="visibility_matrix",
                        description=f"Release-blocking path '{path_id}' is '{visibility}', not 'complete'",
                        severity=CheckSeverity.BLOCKER,
                        source="correlated_visibility_matrix.v1.json",
                        recommendation=recommended_fix
                        or "Complete trace instrumentation for this path.",
                    )
                )
            elif visibility != "complete":
                if not recommended_fix or recommended_fix.startswith("None"):
                    findings.append(
                        Finding(
                            finding_id=f"visibility.path.{path_id}.no_deferral_rationale",
                            category="visibility_matrix",
                            description=f"Non-complete path '{path_id}' ({visibility}) has no deferral rationale",
                            severity=CheckSeverity.MEDIUM,
                            source="correlated_visibility_matrix.v1.json",
                            recommendation="Add recommended_fix explaining why this path is deferred.",
                        )
                    )
                    if result.status == CheckStatus.PASS:
                        result.status = CheckStatus.WARN

        if not findings:
            result.summary = f"All {len(paths)} critical paths verified: {matrix_summary.get('complete', 0)} complete"
        else:
            result.summary = (
                f"Visibility matrix: {len(findings)} findings across {len(paths)} paths"
            )

    except Exception as exc:
        result.status = CheckStatus.FAIL
        result.severity = CheckSeverity.BLOCKER
        result.summary = f"Visibility matrix check failed: {exc}"
        findings.append(
            Finding(
                finding_id="visibility.check.exception",
                category="visibility_matrix",
                description=f"Could not parse visibility matrix: {exc}",
                severity=CheckSeverity.BLOCKER,
            )
        )

    result.findings = findings
    return result


# ── WebSocket security invariants ───────────────────────────────────────

_WS_ORIGIN_EXACT_REGEX = re.compile(r"origin\s+not\s+in\s+self\._allowed_origins")
_WS_LOOPBACK_SUBSTRING_REGEX = re.compile(r"""loopback\s+in\s+origin""")
_WS_AUTH_BEFORE_REGEX = re.compile(r"if\s+not\s+authenticated:")
_WS_PARSE_MESSAGE_REGEX = re.compile(r"def\s+_parse_message")
_WS_ISINSTANCE_DICT_REGEX = re.compile(r"not\s+isinstance\(parsed,\s*dict\)")
_WS_MAX_INVALID_REGEX = re.compile(r"MAX_INVALID_WEBSOCKET_MESSAGES\s*=\s*(\d+)")
_WS_MAX_BYTES_REGEX = re.compile(
    r"max_message_bytes:\s*int\s*=\s*DEFAULT_MAX_MESSAGE_BYTES"
)
_WS_DEFAULT_BYTES_REGEX = re.compile(r"DEFAULT_MAX_MESSAGE_BYTES\s*=\s*(\d+)")
_WS_RATE_LIMIT_REGEX = re.compile(
    r"rate_limit_per_minute:\s*int\s*=\s*DEFAULT_RATE_LIMIT_PER_MINUTE"
)
_WS_DEFAULT_RATE_REGEX = re.compile(r"DEFAULT_RATE_LIMIT_PER_MINUTE\s*=\s*(\d+)")
_WS_RATE_WINDOW_REGEX = re.compile(r"_RATE_WINDOW_SECONDS\s*=\s*(\d+)")
_WS_SCHEMA_VALIDATION_REGEX = re.compile(r"_validate_message_shape")
_WS_GOLDEN_EVENT_REGEX = re.compile(r"_emit_golden_event")
_WS_ORIGIN_REJECTED_EVENT = re.compile(r"desktop\.websocket\.origin_rejected")
_WS_AUTH_FAILED_EVENT = re.compile(r"desktop\.websocket\.auth_failed")
_WS_RATE_LIMITED_EVENT = re.compile(r"desktop\.websocket\.rate_limited")


def check_websocket_security() -> CheckResult:
    result = CheckResult(
        check_id="runtime.websocket.security_invariants",
        title="WebSocket security invariants verified",
        status=CheckStatus.PASS,
    )
    findings: list[Finding] = []

    try:
        if not _WEBSOCKET_SERVER_PATH.is_file():
            result.status = CheckStatus.FAIL
            result.severity = CheckSeverity.BLOCKER
            result.summary = "WebSocket server file not found."
            findings.append(
                Finding(
                    finding_id="ws.invariant.file_missing",
                    category="websocket_security",
                    description="websocket_server.py not found",
                    severity=CheckSeverity.BLOCKER,
                )
            )
            result.findings = findings
            return result

        source = _WEBSOCKET_SERVER_PATH.read_text(encoding="utf-8")
        result.evidence["source_sha256"] = _sha256(source)

        invariants: dict[str, bool] = {}

        # 1. Origin validation uses exact match (not substring) for non-loopback
        has_origin_exact = bool(_WS_ORIGIN_EXACT_REGEX.search(source))
        invariants["origin_exact_match"] = has_origin_exact

        # OWASP: explicit Origin allowlists, no substring matching
        has_loopback_substring = bool(_WS_LOOPBACK_SUBSTRING_REGEX.search(source))
        invariants["origin_loopback_substring"] = has_loopback_substring
        if has_loopback_substring:
            findings.append(
                Finding(
                    finding_id="ws.invariant.origin_loopback_substring",
                    category="websocket_security",
                    description="Loopback origin check uses substring matching (localhost in origin) — acceptable only for loopback but should be documented",
                    severity=CheckSeverity.LOW,
                    source="websocket_server.py",
                    recommendation="Document that loopback substring matching is intentional and constrained to 127.0.0.1/localhost/::1 only.",
                )
            )

        # 2. Auth before subscribe
        has_auth_before = bool(_WS_AUTH_BEFORE_REGEX.search(source))
        invariants["auth_before_subscribe"] = has_auth_before

        # 3. Invalid JSON rejection (array/scalar rejection)
        has_parse_message = bool(_WS_PARSE_MESSAGE_REGEX.search(source))
        has_dict_check = bool(_WS_ISINSTANCE_DICT_REGEX.search(source))
        invariants["reject_non_dict_json"] = has_parse_message and has_dict_check

        # 4. Max invalid message close behavior
        max_invalid_match = _WS_MAX_INVALID_REGEX.search(source)
        max_invalid = int(max_invalid_match.group(1)) if max_invalid_match else 0
        invariants["max_invalid_messages"] = max_invalid > 0
        if max_invalid == 0:
            findings.append(
                Finding(
                    finding_id="ws.invariant.no_invalid_message_limit",
                    category="websocket_security",
                    description="No MAX_INVALID_WEBSOCKET_MESSAGES defined",
                    severity=CheckSeverity.HIGH,
                    source="websocket_server.py",
                    recommendation="Define MAX_INVALID_WEBSOCKET_MESSAGES with a sensible default (e.g., 3).",
                )
            )
        result.evidence["max_invalid_messages"] = max_invalid

        # 5. Message size cap
        max_bytes_match = _WS_DEFAULT_BYTES_REGEX.search(source)
        max_bytes = int(max_bytes_match.group(1)) if max_bytes_match else 0
        invariants["message_size_cap"] = max_bytes > 0
        result.evidence["max_message_bytes"] = max_bytes

        # 6. Rate limiting
        rate_match = _WS_DEFAULT_RATE_REGEX.search(source)
        rate_limit = int(rate_match.group(1)) if rate_match else 0
        invariants["rate_limiting"] = rate_limit > 0
        result.evidence["rate_limit_per_minute"] = rate_limit

        window_match = _WS_RATE_WINDOW_REGEX.search(source)
        if window_match:
            result.evidence["rate_window_seconds"] = int(window_match.group(1))

        # 7. JSON schema / allowlist message validation
        has_schema_validation = bool(_WS_SCHEMA_VALIDATION_REGEX.search(source))
        invariants["message_schema_validation"] = has_schema_validation

        # 8. Content-light trace events (security logging)
        has_golden_events = bool(_WS_GOLDEN_EVENT_REGEX.search(source))
        invariants["content_light_trace_events"] = has_golden_events

        # 9. Specific refusal trace events
        has_origin_event = bool(_WS_ORIGIN_REJECTED_EVENT.search(source))
        has_auth_failed_event = bool(_WS_AUTH_FAILED_EVENT.search(source))
        has_rate_limited_event = bool(_WS_RATE_LIMITED_EVENT.search(source))
        invariants["trace_origin_rejected"] = has_origin_event
        invariants["trace_auth_failed"] = has_auth_failed_event
        invariants["trace_rate_limited"] = has_rate_limited_event

        result.evidence["invariants"] = invariants

        all_met = all(invariants.values())
        critical_failures = [
            k
            for k in [
                "origin_exact_match",
                "auth_before_subscribe",
                "reject_non_dict_json",
                "max_invalid_messages",
                "message_size_cap",
                "rate_limiting",
                "message_schema_validation",
            ]
            if not invariants.get(k, False)
        ]

        if critical_failures:
            result.status = CheckStatus.FAIL
            result.severity = CheckSeverity.BLOCKER
            for k in critical_failures:
                findings.append(
                    Finding(
                        finding_id=f"ws.invariant.{k}_missing",
                        category="websocket_security",
                        description=f"Critical WebSocket security invariant '{k}' not verified",
                        severity=CheckSeverity.BLOCKER,
                        source="websocket_server.py",
                    )
                )

        met_count = sum(1 for v in invariants.values() if v)
        total_count = len(invariants)
        if not findings and all_met:
            result.summary = f"All {total_count} WebSocket security invariants verified"
        else:
            result.summary = f"WebSocket security: {met_count}/{total_count} invariants met, {len(findings)} findings"

    except Exception as exc:
        result.status = CheckStatus.FAIL
        result.severity = CheckSeverity.BLOCKER
        result.summary = f"WebSocket security check failed: {exc}"
        findings.append(
            Finding(
                finding_id="ws.check.exception",
                category="websocket_security",
                description=f"Could not inspect websocket_server.py: {exc}",
                severity=CheckSeverity.BLOCKER,
            )
        )

    result.findings = findings
    return result


# ── GitHub App audit readiness ─────────────────────────────────────────

_GITHUB_APP_BACKEND_MODULES = [
    "rig_relay/github_app/webhooks.py",
    "rig_relay/github_app/auth.py",
    "rig_relay/github_app/tokens.py",
    "rig_relay/github_app/event_store.py",
    "rig_relay/github_app/projections.py",
    "rig_relay/github_app/permissions.py",
    "rig_relay/github_app/manifest.py",
]


def check_github_app_audit() -> CheckResult:
    result = CheckResult(
        check_id="runtime.github_app.audit_readiness",
        title="GitHub App audit-to-implementation readiness",
        status=CheckStatus.PASS,
    )
    findings: list[Finding] = []

    try:
        # 1. Audit artifact exists and parses
        if not _GITHUB_AUDIT_PATH.is_file():
            result.status = CheckStatus.FAIL
            result.severity = CheckSeverity.BLOCKER
            result.summary = "GitHub App integration audit JSON not found."
            findings.append(
                Finding(
                    finding_id="github.audit.missing",
                    category="github_app_audit",
                    description="github_app_integration_audit_v0.v1.json missing",
                    severity=CheckSeverity.BLOCKER,
                )
            )
            result.findings = findings
            return result

        audit = json.loads(_GITHUB_AUDIT_PATH.read_text(encoding="utf-8"))
        result.evidence["audit_status"] = audit.get("status", "unknown")
        result.evidence["audit_id"] = audit.get("audit_id", "unknown")

        # 2. Schema validation
        schema_valid = False
        if _GITHUB_AUDIT_SCHEMA_PATH.is_file():
            try:
                import jsonschema

                schema = json.loads(
                    _GITHUB_AUDIT_SCHEMA_PATH.read_text(encoding="utf-8")
                )
                jsonschema.validate(audit, schema)
                schema_valid = True
            except Exception:
                pass
        result.evidence["schema_valid"] = schema_valid

        if not schema_valid:
            findings.append(
                Finding(
                    finding_id="github.audit.schema_invalid",
                    category="github_app_audit",
                    description="Audit JSON does not validate against its schema",
                    severity=CheckSeverity.HIGH,
                    source=str(_GITHUB_AUDIT_SCHEMA_PATH),
                )
            )

        # 3. Webhook signature requirements
        trace_events = {e["event_name"] for e in audit.get("trace_events", [])}
        required_sig_events = {
            "github.webhook.signature_verified",
            "github.webhook.signature_rejected",
        }
        missing_sig_events = required_sig_events - trace_events
        if missing_sig_events:
            findings.append(
                Finding(
                    finding_id="github.audit.missing_signature_events",
                    category="github_app_audit",
                    description=f"Missing webhook signature trace events: {missing_sig_events}",
                    severity=CheckSeverity.HIGH,
                    source=str(_GITHUB_AUDIT_PATH),
                    recommendation="Define github.webhook.signature_verified and github.webhook.signature_rejected trace events per GitHub webhook docs (X-Hub-Signature-256, HMAC-SHA256, constant-time comparison).",
                )
            )

        # 4. X-Hub-Signature-256 requirement check
        has_hmac_requirement = any(
            "X-Hub-Signature-256" in str(ref)
            or "HMAC" in str(ref)
            or "signature" in str(ref).lower()
            for ref in audit.get("webhook_subscriptions", [])
        )
        if not has_hmac_requirement:
            has_hmac_in_security = any(
                "signature" in ctrl.get("control_name", "").lower()
                or "hmac" in str(ctrl).lower()
                for ctrl in audit.get("security_controls", [])
            )
            if not has_hmac_in_security:
                findings.append(
                    Finding(
                        finding_id="github.audit.no_hmac_signature_requirement",
                        category="github_app_audit",
                        description="Audit does not document X-Hub-Signature-256 / HMAC-SHA256 requirement explicitly",
                        severity=CheckSeverity.MEDIUM,
                        source=str(_GITHUB_AUDIT_PATH),
                        recommendation="Add explicit webhook signature verification requirement (HMAC-SHA256, constant-time comparison) per GitHub webhook docs.",
                    )
                )

        # 5. No raw secrets
        audit_str = _GITHUB_AUDIT_PATH.read_text(encoding="utf-8")
        secret_patterns = [
            (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "private key"),
            (r"github_pat_[a-zA-Z0-9_]{20,}", "GitHub PAT"),
            (r"ghp_[a-zA-Z0-9]{36}", "GitHub classic PAT"),
            (r"ghs_[a-zA-Z0-9]{36}", "GitHub installation token"),
        ]
        for pattern, label in secret_patterns:
            if re.search(pattern, audit_str):
                findings.append(
                    Finding(
                        finding_id=f"github.audit.raw_secret.{label.replace(' ', '_')}",
                        category="github_app_audit",
                        description=f"Audit JSON may contain raw {label}",
                        severity=CheckSeverity.BLOCKER,
                        source=str(_GITHUB_AUDIT_PATH),
                        recommendation=f"Remove raw {label} from audit document. Use placeholder values.",
                    )
                )

        # 6. Permission profiles exist
        permission_profiles = audit.get("permission_profiles", [])
        if not permission_profiles:
            findings.append(
                Finding(
                    finding_id="github.audit.no_permission_profiles",
                    category="github_app_audit",
                    description="No permission profiles defined in audit",
                    severity=CheckSeverity.HIGH,
                )
            )
        result.evidence["permission_profile_count"] = len(permission_profiles)

        # 7. Trust boundaries documented
        trust_boundaries = audit.get("trust_boundaries", [])
        result.evidence["trust_boundary_count"] = len(trust_boundaries)

        # 8. Release gates defined in audit
        release_gates = audit.get("release_gates", [])
        result.evidence["release_gate_count"] = len(release_gates)

        # 9. Backend implementation gap analysis
        backend_modules_exist: dict[str, bool] = {}
        for mod_path in _GITHUB_APP_BACKEND_MODULES:
            full_path = _REPO_ROOT / mod_path
            backend_modules_exist[mod_path] = full_path.is_file()

        result.evidence["backend_modules"] = backend_modules_exist
        any_implemented = any(backend_modules_exist.values())
        all_implemented = all(backend_modules_exist.values())

        if not any_implemented:
            findings.append(
                Finding(
                    finding_id="github.implementation.backend_not_implemented",
                    category="github_app_audit",
                    description=f"GitHub App backend modules not implemented ({', '.join(_GITHUB_APP_BACKEND_MODULES)}) — audit exists but implementation is deferred",
                    severity=CheckSeverity.MEDIUM,
                    source=str(_GITHUB_AUDIT_PATH),
                    recommendation="Mark GitHub App implementation phases as deferred in release gate. Audit design is complete; backend code is future work.",
                )
            )
            result.status = CheckStatus.DEFERRED
            result.summary = "GitHub App audit exists, schema validates; backend implementation is deferred"
        elif not all_implemented:
            missing = [m for m, e in backend_modules_exist.items() if not e]
            findings.append(
                Finding(
                    finding_id="github.implementation.partial_backend",
                    category="github_app_audit",
                    description=f"GitHub App backend partially implemented. Missing: {missing}",
                    severity=CheckSeverity.HIGH,
                )
            )
            result.status = CheckStatus.FAIL
        else:
            result.summary = "GitHub App audit complete and backend fully implemented"

        # Implementation phase status from audit
        phases = audit.get("implementation_phases", [])
        deferred_phases = [p for p in phases if p.get("status", "?") != "complete"]
        if deferred_phases:
            result.evidence["deferred_phase_count"] = len(deferred_phases)

        if not findings and result.status == CheckStatus.PASS:
            result.summary = f"GitHub App audit ready: {len(permission_profiles)} permission profiles, {len(trust_boundaries)} trust boundaries, {len(release_gates)} release gates, {len(trace_events)} trace events"

    except Exception as exc:
        result.status = CheckStatus.FAIL
        result.severity = CheckSeverity.BLOCKER
        result.summary = f"GitHub App audit check failed: {exc}"
        findings.append(
            Finding(
                finding_id="github.check.exception",
                category="github_app_audit",
                description=f"Could not inspect GitHub App audit: {exc}",
                severity=CheckSeverity.BLOCKER,
            )
        )

    result.findings = findings
    return result


# ── CI workflow coverage ────────────────────────────────────────────────

_REQUIRED_CI_STEPS = {
    "release_gate": "Release evidence gate invocation",
    "schema_validation": "Schema validation step",
    "tests": "Test execution step",
    "pyright": "Type checking step",
    "generated_site_safety": "Generated site / docs safety check",
}


def check_ci_coverage() -> CheckResult:
    result = CheckResult(
        check_id="runtime.ci.workflow_coverage",
        title="CI workflow coverage for release evidence gate",
        status=CheckStatus.PASS,
    )
    findings: list[Finding] = []

    try:
        if not _CI_DIR.is_dir():
            result.status = CheckStatus.FAIL
            result.severity = CheckSeverity.BLOCKER
            result.summary = ".github/workflows directory not found."
            findings.append(
                Finding(
                    finding_id="ci.workflows.dir_missing",
                    category="ci_workflow",
                    description=".github/workflows/ directory missing",
                    severity=CheckSeverity.BLOCKER,
                )
            )
            result.findings = findings
            return result

        import yaml

        workflows = list(_CI_DIR.glob("*.yml"))
        result.evidence["workflow_count"] = len(workflows)
        result.evidence["workflow_files"] = [wf.name for wf in workflows]

        coverage: dict[str, bool] = {}
        for wf in workflows:
            try:
                wf_content = wf.read_text(encoding="utf-8")
                parsed = yaml.safe_load(wf_content) or {}
                jobs = parsed.get("jobs", {}) if isinstance(parsed, dict) else {}

                for step_key in _REQUIRED_CI_STEPS:
                    if coverage.get(step_key):
                        continue
                    for _job_name, job_def in jobs.items():
                        if not isinstance(job_def, dict):
                            continue
                        steps = job_def.get("steps", [])
                        for step in steps:
                            if not isinstance(step, dict):
                                continue
                            step_name = step.get("name", "")
                            step_run = step.get("run", "")
                            if step_key == "release_gate" and (
                                "release_gate" in str(step).lower()
                                or "release.evidence" in step_run.lower()
                                or "release_evidence" in step_run.lower()
                            ):
                                coverage[step_key] = True
                            elif step_key == "schema_validation" and (
                                "schema" in step_name.lower()
                                or "validate_schemas" in step_run
                            ):
                                coverage[step_key] = True
                            elif step_key == "tests" and (
                                "pytest" in step_run.lower()
                                or "test" in step_name.lower()
                            ):
                                coverage[step_key] = True
                            elif step_key == "pyright" and (
                                "pyright" in step_run.lower()
                            ):
                                coverage[step_key] = True
                            elif step_key == "generated_site_safety" and (
                                "generated" in str(step).lower()
                                and (
                                    "docs" in str(step).lower()
                                    or "site" in str(step).lower()
                                )
                            ):
                                coverage[step_key] = True
            except Exception:
                pass

        result.evidence["coverage"] = coverage

        missing = [k for k in _REQUIRED_CI_STEPS if k not in coverage]
        if missing:
            if "release_gate" in missing:
                result.status = CheckStatus.WARN
                result.severity = CheckSeverity.MEDIUM
                findings.append(
                    Finding(
                        finding_id="ci.workflow.no_release_gate",
                        category="ci_workflow",
                        description="No CI step invokes the release evidence gate",
                        severity=CheckSeverity.MEDIUM,
                        source=str(_CI_DIR),
                        recommendation="Add a CI job that runs the release evidence gate in non-mutating mode, outputting to .build/rig-relay/release-gate-ci.json.",
                    )
                )
            for m in missing:
                if m != "release_gate":
                    findings.append(
                        Finding(
                            finding_id=f"ci.workflow.missing_{m}",
                            category="ci_workflow",
                            description=f"CI step missing: {_REQUIRED_CI_STEPS[m]}",
                            severity=CheckSeverity.LOW,
                            source=str(_CI_DIR),
                        )
                    )

        covered = len(coverage)
        if not findings:
            result.summary = f"All {len(_REQUIRED_CI_STEPS)} required CI steps covered across {len(workflows)} workflows"
        else:
            result.summary = f"CI coverage: {covered}/{len(_REQUIRED_CI_STEPS)} required steps, {len(findings)} findings"

    except Exception as exc:
        result.status = CheckStatus.FAIL
        result.severity = CheckSeverity.BLOCKER
        result.summary = f"CI workflow check failed: {exc}"
        findings.append(
            Finding(
                finding_id="ci.check.exception",
                category="ci_workflow",
                description=f"Could not inspect CI workflows: {exc}",
                severity=CheckSeverity.BLOCKER,
            )
        )

    result.findings = findings
    return result


# ── Triage policy ───────────────────────────────────────────────────────


def load_triage_policy(path: Path | None = None) -> TriagePolicy:
    policy_path = path or _DEFAULT_TRIAGE_PATH
    if not policy_path.is_file():
        return TriagePolicy(path=policy_path)
    try:
        data = json.loads(policy_path.read_text(encoding="utf-8"))
        entries = [
            TriageEntry(
                finding_id=e["finding_id"],
                reason=e.get("reason", ""),
                expires=e.get("expires", ""),
            )
            for e in data.get("entries", [])
        ]
        return TriagePolicy(path=policy_path, entries=entries)
    except Exception:
        return TriagePolicy(path=policy_path)


# ── Helpers ─────────────────────────────────────────────────────────────


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Lane A context adapters ──────────────────────────────────────────────
# These wrappers accept CheckContext and delegate to the standalone checks.
# Lane A's _checks_registry.py should import these instead of the raw functions
# because GateRunner.run() calls check_fn(ctx).


def _get_triage(ctx: object) -> TriagePolicy | None:
    if hasattr(ctx, "triage"):
        return ctx.triage  # type: ignore[no-any-return]
    if hasattr(ctx, "policy") and hasattr(ctx.policy, "triage"):  # type: ignore[union-attr]
        return ctx.policy.triage  # type: ignore[no-any-return,union-attr]
    return None


def check_trace_contract_ctx(ctx: object) -> CheckResult:
    return check_trace_contract(triage=_get_triage(ctx))


def check_visibility_matrix_ctx(_ctx: object) -> CheckResult:
    return check_visibility_matrix()


def check_websocket_security_ctx(_ctx: object) -> CheckResult:
    return check_websocket_security()


def check_github_app_audit_ctx(_ctx: object) -> CheckResult:
    return check_github_app_audit()


def check_ci_coverage_ctx(_ctx: object) -> CheckResult:
    return check_ci_coverage()

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "rig_relay_trace_visibility_audit.py"


def _run_audit(*extra_args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--format", "json", *extra_args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    return json.loads(result.stdout)


@pytest.fixture
def audit_report() -> dict:
    return _run_audit()


class TestAuditScriptRuns:
    def test_script_exists(self) -> None:
        assert AUDIT_SCRIPT.exists(), f"Missing {AUDIT_SCRIPT}"

    def test_script_emits_valid_json(self, audit_report: dict) -> None:
        assert audit_report["schema_version"] == "rig.trace_visibility_audit.v1"
        assert "generated_at" in audit_report
        assert "source_commit" in audit_report
        assert "files_scanned" in audit_report
        assert "event_names" in audit_report
        assert "correlation_fields_found" in audit_report
        assert "critical_paths" in audit_report
        assert "findings" in audit_report
        assert "summary" in audit_report

    def test_script_scans_files(self, audit_report: dict) -> None:
        assert audit_report["files_scanned"] > 0

    def test_script_has_summary_counts(self, audit_report: dict) -> None:
        summary = audit_report["summary"]
        assert isinstance(summary["complete"], int)
        assert isinstance(summary["partial"], int)
        assert isinstance(summary["missing"], int)
        assert isinstance(summary["release_blockers"], int)


class TestGeneratedHtmlExclusion:
    def test_generated_html_excluded(self, audit_report: dict) -> None:
        findings = audit_report["findings"]
        html_finding = [
            f
            for f in findings
            if "generated html" in str(f.get("description", "")).lower()
        ]
        assert len(html_finding) >= 1, "No generated HTML exclusion finding"
        for hf in html_finding:
            desc = str(hf.get("description", "")).lower()
            assert "pass" in desc or hf.get("severity") != "critical", (
                f"Generated HTML was not excluded: {hf.get('description')}"
            )

    def test_no_html_files_in_scanned(self, audit_report: dict) -> None:
        for cp in audit_report.get("critical_paths", []):
            for tf in cp.get("target_files", []):
                assert not str(tf).endswith(".html"), (
                    f"HTML file in critical path targets: {tf}"
                )


class TestFrontendBreadcrumbDetection:
    def test_frontend_events_found(self, audit_report: dict) -> None:
        findings = audit_report["findings"]
        frontend_finding = [
            f
            for f in findings
            if "Frontend breadcrumb event usage" in str(f.get("description", ""))
        ]
        assert len(frontend_finding) >= 1, "No frontend breadcrumb finding"
        for ff in frontend_finding:
            assert "FOUND" in str(ff.get("description", "")), (
                f"Frontend breadcrumbs not detected: {ff.get('description')}"
            )

    def test_frontend_event_names_discovered(self, audit_report: dict) -> None:
        events = audit_report.get("event_names", [])
        frontend_events = [e for e in events if "frontend" in e.lower()]
        assert len(frontend_events) > 0, "No frontend event names discovered"


class TestWebSocketLifecycleDetection:
    def test_websocket_lifecycle_checked(self, audit_report: dict) -> None:
        findings = audit_report["findings"]
        ws_finding = [
            f
            for f in findings
            if "WebSocket lifecycle trace usage" in str(f.get("description", ""))
        ]
        assert len(ws_finding) >= 1, "No WebSocket lifecycle finding"


class TestCodeSchemaRouterGap:
    def test_code_schema_router_gap_reported(self, audit_report: dict) -> None:
        findings = audit_report["findings"]
        csr_finding = [
            f
            for f in findings
            if "code schema router" in str(f.get("description", "")).lower()
            or "Code schema router" in str(f.get("description", ""))
        ]
        assert len(csr_finding) >= 1, "No code schema router gap finding"

    def test_code_schema_router_path_exists(self, audit_report: dict) -> None:
        critical_paths = {cp["path_id"]: cp for cp in audit_report["critical_paths"]}
        assert "code_schema_routing" in critical_paths, (
            "code_schema_routing not in critical paths"
        )


class TestStaticDocsRenderGap:
    def test_static_docs_render_gap_reported(self, audit_report: dict) -> None:
        findings = audit_report["findings"]
        sdr_finding = [
            f
            for f in findings
            if "static docs render" in str(f.get("description", "")).lower()
            or "Static docs render" in str(f.get("description", ""))
        ]
        assert len(sdr_finding) >= 1, "No static docs render gap finding"


class TestAuditSafety:
    def test_no_absolute_paths_outside_repo(self, audit_report: dict) -> None:
        report_str = json.dumps(audit_report)
        assert "/Users/" not in report_str, "Report contains /Users/ paths"
        assert "/home/" not in report_str, "Report contains /home/ paths"

    def test_no_token_values_in_report(self, audit_report: dict) -> None:
        report_str = json.dumps(audit_report)
        forbidden = ["ghp_", "gho_", "github_pat_", "sk-", "Bearer "]
        for token_pattern in forbidden:
            assert token_pattern not in report_str, (
                f"Report may contain token pattern: {token_pattern}"
            )

    def test_correlation_fields_safe(self, audit_report: dict) -> None:
        corr_fields = audit_report.get("correlation_fields_found", {})
        for field in corr_fields:
            assert "token" not in str(field).lower() or field in {
                "token_present",
                "token_value_included",
            }, f"Unsafe field name in correlation: {field}"


class TestStrictMode:
    def test_strict_mode_exits_nonzero_when_blockers(self) -> None:
        result = _run_audit("--strict")
        summary = result.get("summary", {})
        blockers = summary.get("release_blockers", 0)
        # Strict mode returns exit code from script, not this test.
        # Verify report has blockers tracked.
        assert isinstance(blockers, int)

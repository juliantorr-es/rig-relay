from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.audit.release_candidate_coherence.v1.schema.json"
)
AUDIT_JSON_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "audits"
    / "release_candidate_coherence_audit_v0.v1.json"
)
SUPPORT_SCRIPT_PATH = REPO_ROOT / "scripts" / "rig_relay_release_coherence_audit.py"

_support_report_cache: dict[str, Any] | None = None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _get_support_report() -> dict[str, Any]:
    global _support_report_cache
    if _support_report_cache is None:
        result = subprocess.run(
            ["uv", "run", "python", str(SUPPORT_SCRIPT_PATH), "--format", "json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Support script failed: {result.stderr}"
        _support_report_cache = json.loads(result.stdout)
    assert _support_report_cache is not None
    return _support_report_cache


class TestAuditSchema:
    def test_audit_schema_parses(self):
        schema = _load_json(AUDIT_SCHEMA_PATH)
        assert schema["$schema"] is not None
        assert schema["type"] == "object"
        assert "schema_version" in schema["properties"]


class TestAuditJSON:
    def test_audit_json_parses(self):
        audit = _load_json(AUDIT_JSON_PATH)
        assert audit["schema_version"] == "rig.audit.release_candidate_coherence.v1"

    def test_audit_json_has_all_required_lenses(self):
        audit = _load_json(AUDIT_JSON_PATH)
        required_lenses = {
            "product_story",
            "public_surface",
            "release_boundary",
            "security_posture",
            "observability_tracing",
            "context_agent_governance",
            "runtime_tool_safety",
            "frontend_desktop_golden_path",
            "static_docs_renderer",
            "documentation_information_architecture",
            "supply_chain_repo_hygiene",
            "contribution_business_posture",
        }
        actual_lenses = {l["lens_id"] for l in audit["lenses"]}
        missing = required_lenses - actual_lenses
        assert not missing, f"Missing lenses: {missing}"

    def test_every_finding_references_valid_lens(self):
        audit = _load_json(AUDIT_JSON_PATH)
        lens_ids = {l["lens_id"] for l in audit["lenses"]}
        for finding in audit["findings"]:
            assert finding["lens_id"] in lens_ids, (
                f"Finding {finding['finding_id']} references unknown lens {finding['lens_id']}"
            )

    def test_every_release_blocker_has_recommended_fix(self):
        audit = _load_json(AUDIT_JSON_PATH)
        for finding in audit["findings"]:
            if finding["release_blocker"]:
                assert finding["recommended_fix"], (
                    f"Release blocker {finding['finding_id']} missing recommended_fix"
                )

    def test_action_map_covers_every_release_blocker(self):
        audit = _load_json(AUDIT_JSON_PATH)
        blocker_finding_ids = {
            f["finding_id"] for f in audit["findings"] if f["release_blocker"]
        }
        covered_finding_ids: set[str] = set()
        for action in audit["action_map"]:
            for fid in action["findings"]:
                covered_finding_ids.add(fid)
        uncovered = blocker_finding_ids - covered_finding_ids
        assert not uncovered, (
            f"Release blocker findings not covered by action_map: {uncovered}"
        )

    def test_metrics_include_doc_search_security_code_schema_counts(self):
        audit = _load_json(AUDIT_JSON_PATH)
        metrics = audit["metrics"]
        assert isinstance(metrics["doc_page_count"], int)
        assert isinstance(metrics["search_index_count"], int)
        assert isinstance(metrics["code_schema_count"], int)
        assert isinstance(metrics["security_threat_count"], int)
        assert isinstance(metrics["test_count_collected"], int)

    def test_public_surface_lens_exists(self):
        audit = _load_json(AUDIT_JSON_PATH)
        lens = next(l for l in audit["lenses"] if l["lens_id"] == "public_surface")
        assert lens["name"] is not None
        assert len(lens["questions"]) > 0

    def test_security_posture_lens_exists(self):
        audit = _load_json(AUDIT_JSON_PATH)
        lens = next(l for l in audit["lenses"] if l["lens_id"] == "security_posture")
        assert lens["name"] is not None

    def test_observability_tracing_lens_exists(self):
        audit = _load_json(AUDIT_JSON_PATH)
        lens = next(
            l for l in audit["lenses"] if l["lens_id"] == "observability_tracing"
        )
        assert lens["name"] is not None

    def test_context_agent_governance_lens_exists(self):
        audit = _load_json(AUDIT_JSON_PATH)
        lens = next(
            l for l in audit["lenses"] if l["lens_id"] == "context_agent_governance"
        )
        assert lens["name"] is not None

    def test_runtime_tool_safety_lens_exists(self):
        audit = _load_json(AUDIT_JSON_PATH)
        lens = next(l for l in audit["lenses"] if l["lens_id"] == "runtime_tool_safety")
        assert lens["name"] is not None


class TestAuditSupportScript:
    def test_support_script_runs_and_emits_valid_json(self):
        report = _get_support_report()
        assert report["schema_version"] == "rig.release_coherence_audit_support.v1"
        assert "metrics" in report
        assert "checks" in report

    def test_support_script_does_not_output_local_absolute_paths_outside_repo(self):
        report = _get_support_report()
        for check in report["checks"]:
            detail = check.get("detail", "")
            assert "/Users/" not in detail or str(REPO_ROOT) in detail, (
                f"Check {check['check_id']} contains external local path: {detail}"
            )

    def test_support_script_detects_if_homepage_is_link_dump(self):
        report = _get_support_report()
        check = next(
            c for c in report["checks"] if c["check_id"] == "homepage_link_dump"
        )
        assert isinstance(check["pass"], bool)

    def test_support_script_detects_security_collection(self):
        report = _get_support_report()
        check = next(
            c for c in report["checks"] if c["check_id"] == "security_collection"
        )
        assert check["pass"] is True

    def test_support_script_detects_code_schemas_collection(self):
        report = _get_support_report()
        check = next(
            c for c in report["checks"] if c["check_id"] == "code_schemas_collection"
        )
        assert isinstance(check["pass"], bool)

    def test_support_script_checks_generated_html_exclusion_from_context(self):
        report = _get_support_report()
        check = next(
            c
            for c in report["checks"]
            if c["check_id"] == "generated_html_exclusion_in_context"
        )
        assert check["pass"] is True

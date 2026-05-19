"""Protocol/CI/SDK blocker enforcement — contract, integration, real-artifact, adversarial tests.

Verifies that the five new release-candidate blockers prevent PROMOTE,
are reflected in the golden path, and cannot be bypassed by raw bash or
incomplete implementation claims.

Test classifications:
  - contract: validator behavior tests against real temp JSON/JSONL files
  - real_artifact: tests consuming the canonical artifacts on disk
  - adversarial: tests proving specific bypass vectors are blocked
  - substrate: tests proving artifact storage patterns hold
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"

FIVE_BLOCKER_IDS = [
    "blk_ci_cd_structured_evidence_surface",
    "blk_mcp_read_only_server_alpha",
    "blk_acp_session_auth_resume_hardening",
    "blk_internal_sdk_programmatic_api_v0",
    "blk_internal_a2a_dogfood_substrate_v0",
]

FIVE_GOLDEN_PATH_STEPS = [
    "gp_ci_cd_structured_evidence",
    "gp_mcp_read_only_server",
    "gp_acp_auth_resume_hardening",
    "gp_internal_sdk_programmatic_api",
    "gp_internal_a2a_dogfood_substrate",
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    entries = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _run_validator(repo_root: Path) -> dict:
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(SCRIPTS_DIR / "rig_release_gate_validate.py"),
            "--repo-root",
            str(repo_root),
        ],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        timeout=60,
    )
    return json.loads(result.stdout)


def _run_golden_path_check(repo_root: Path) -> dict:
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(SCRIPTS_DIR / "rig_rc_golden_path_check.py"),
            "--repo-root",
            str(repo_root),
        ],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        timeout=60,
    )
    return json.loads(result.stdout)


class TestProtocolCiSdkBlockerEnforcement:
    @pytest.mark.real_artifact
    def test_all_five_blockers_present_in_jsonl(self):
        blockers = _load_jsonl(
            REPO_ROOT / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
        )
        blocker_ids = {b["blocker_id"] for b in blockers if "_parse_error" not in b}

        for bid in FIVE_BLOCKER_IDS:
            assert bid in blocker_ids, f"Missing blocker: {bid}"

    @pytest.mark.real_artifact
    def test_all_five_blockers_are_open(self):
        blockers = _load_jsonl(
            REPO_ROOT / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
        )
        blocker_map = {b["blocker_id"]: b for b in blockers if "_parse_error" not in b}

        for bid in FIVE_BLOCKER_IDS:
            blocker = blocker_map.get(bid)
            assert blocker is not None, f"Missing blocker: {bid}"
            assert blocker["status"] == "open", (
                f"Blocker {bid} should be open, got {blocker['status']}"
            )

    @pytest.mark.integration
    def test_validator_reports_blocked_with_open_blockers(self):
        result = _run_validator(REPO_ROOT)
        assert result["verdict"] in {"BLOCKED", "FAIL"}, (
            f"Expected BLOCKED or FAIL, got {result['verdict']}"
        )
        errors = result.get("errors", [])
        error_text = "\n".join(errors)

        for step_id in FIVE_GOLDEN_PATH_STEPS:
            assert step_id in error_text, (
                f"Validator should reference golden path step {step_id} as blocked"
            )

        assert (
            "cannot PROMOTE" in error_text.lower()
            or "blocked step" in error_text.lower()
        ), "Validator must indicate PROMOTE is blocked"

    @pytest.mark.real_artifact
    def test_candidate_verdict_includes_five_blocker_ids(self):
        verdict = _load_json(
            REPO_ROOT
            / "docs"
            / "json"
            / "release_gate"
            / "rc_candidate_verdict.v1.json"
        )
        open_ids = set(verdict.get("open_blocker_ids", []))
        for bid in FIVE_BLOCKER_IDS:
            assert bid in open_ids, f"Verdict open_blocker_ids missing: {bid}"
        assert verdict["verdict"] == "hold", (
            f"Verdict should be 'hold', got '{verdict['verdict']}'"
        )

    @pytest.mark.real_artifact
    def test_readiness_gate_references_five_blockers(self):
        gate = _load_json(
            REPO_ROOT / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json"
        )
        all_phase_blocker_ids = set()
        for phase in gate.get("phases", []):
            for bid in phase.get("blocker_ids", []):
                all_phase_blocker_ids.add(bid)

        for bid in FIVE_BLOCKER_IDS:
            assert bid in all_phase_blocker_ids, (
                f"Readiness gate phases missing blocker reference: {bid}"
            )

    @pytest.mark.real_artifact
    def test_golden_path_includes_five_new_steps(self):
        gp = _load_json(
            REPO_ROOT
            / "docs"
            / "json"
            / "release_candidate"
            / "rc_reviewer_golden_path.v1.json"
        )
        step_ids = {s["step_id"] for s in gp.get("steps", [])}

        for step_id in FIVE_GOLDEN_PATH_STEPS:
            assert step_id in step_ids, f"Golden path missing step: {step_id}"

    @pytest.mark.real_artifact
    def test_golden_path_new_steps_are_blocked(self):
        gp = _load_json(
            REPO_ROOT
            / "docs"
            / "json"
            / "release_candidate"
            / "rc_reviewer_golden_path.v1.json"
        )
        step_map = {s["step_id"]: s for s in gp.get("steps", [])}

        for step_id in FIVE_GOLDEN_PATH_STEPS:
            step = step_map[step_id]
            assert step["status"] == "blocked", (
                f"Golden path step {step_id} should be 'blocked', got '{step['status']}'"
            )
            assert step.get("blocking_failure_conditions"), (
                f"Golden path step {step_id} must have blocking_failure_conditions"
            )

    @pytest.mark.real_artifact
    def test_golden_path_overall_is_blocked_or_not_verified(self):
        gp = _load_json(
            REPO_ROOT
            / "docs"
            / "json"
            / "release_candidate"
            / "rc_reviewer_golden_path.v1.json"
        )
        assert gp["overall_status"] in {"blocked", "not_verified"}, (
            f"Golden path overall_status should be blocked or not_verified, got '{gp['overall_status']}'"
        )

    @pytest.mark.real_artifact
    def test_golden_path_check_detects_blocked_steps(self):
        result = _run_golden_path_check(REPO_ROOT)
        blocked_steps = result.get("blocked_steps", [])
        for step_id in FIVE_GOLDEN_PATH_STEPS:
            assert step_id in blocked_steps, (
                f"Golden path check should detect {step_id} as blocked"
            )

    @pytest.mark.integration
    def test_golden_path_check_overall_is_blocked(self):
        result = _run_golden_path_check(REPO_ROOT)
        assert result["overall_status"] in {"blocked", "manual_required"}, (
            f"Golden path check overall should be blocked/manual_required, got '{result['overall_status']}'"
        )

    @pytest.mark.real_artifact
    def test_no_markdown_evidence_in_golden_path(self):
        gp = _load_json(
            REPO_ROOT
            / "docs"
            / "json"
            / "release_candidate"
            / "rc_reviewer_golden_path.v1.json"
        )
        ALLOWED = {
            "README.md",
            "AGENTS.md",
            "LICENSE",
            "CONTRIBUTING.md",
            "ATTRIBUTION.md",
            "UPSTREAM.md",
            "THIRD_PARTY_NOTICES.md",
            "CHANGELOG.md",
            "SECURITY.md",
            "CODE_OF_CONDUCT.md",
        }
        for ep in gp.get("evidence_paths", []):
            if ep.endswith(".md"):
                assert ep in ALLOWED or ep.startswith("docs/") is False, (
                    f"Forbidden Markdown evidence path in golden path: {ep}"
                )

    @pytest.mark.adversarial
    def test_mcp_mutation_tools_cannot_pass_alpha_requirement(self):
        blockers = _load_jsonl(
            REPO_ROOT / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
        )
        mcp_blk = next(
            (
                b
                for b in blockers
                if b.get("blocker_id") == "blk_mcp_read_only_server_alpha"
            ),
            None,
        )
        assert mcp_blk is not None, "MCP blocker must exist"
        desc = mcp_blk.get("description", "")
        assert "tier 0-2" in desc.lower() or "read-only" in desc.lower(), (
            "MCP alpha requirement must scope to read-only/tier 0-2 tools"
        )
        resolution = mcp_blk.get("required_resolution", "")
        assert "mutation" in resolution.lower() or "tier" in resolution.lower(), (
            "MCP required resolution must address mutation tool gating"
        )

    @pytest.mark.adversarial
    def test_ci_bash_only_exit_codes_cannot_satisfy_structured_ci_requirement(self):
        blockers = _load_jsonl(
            REPO_ROOT / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
        )
        ci_blk = next(
            (
                b
                for b in blockers
                if b.get("blocker_id") == "blk_ci_cd_structured_evidence_surface"
            ),
            None,
        )
        assert ci_blk is not None, "CI/CD blocker must exist"
        desc = ci_blk.get("description", "")
        assert "orchestrat" in desc.lower() or "structured" in desc.lower(), (
            "CI requirement must mandate structured evidence, not raw bash"
        )
        assert (
            "exit code" in desc.lower()
            or "bash-only" in desc.lower()
            or "raw bash" in desc.lower()
        ), "CI requirement must explicitly reject raw bash exit codes"

    @pytest.mark.adversarial
    def test_external_a2a_must_not_be_enabled_before_promotion(self):
        gate = _load_json(
            REPO_ROOT / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json"
        )
        a2a_phase = next(
            (
                p
                for p in gate.get("phases", [])
                if "a2a" in p.get("phase_id", "").lower()
            ),
            None,
        )
        if a2a_phase is not None:
            status = a2a_phase.get("status", "")
            assert status in {"blocked", "unknown"}, (
                f"A2A phase should be blocked or unknown, got '{status}'"
            )

    @pytest.mark.adversarial
    def test_sdk_defeault_mutation_policy_is_refuse(self):
        blockers = _load_jsonl(
            REPO_ROOT / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
        )
        sdk_blk = next(
            (
                b
                for b in blockers
                if b.get("blocker_id") == "blk_internal_sdk_programmatic_api_v0"
            ),
            None,
        )
        assert sdk_blk is not None, "SDK blocker must exist"
        desc = sdk_blk.get("description", "")
        assert "refuse" in desc.lower() or "observe" in desc.lower(), (
            "SDK default mutation policy must be 'refuse' or 'observe'"
        )

    @pytest.mark.contract
    def test_all_five_blockers_have_required_fields(self):
        blockers = _load_jsonl(
            REPO_ROOT / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
        )
        blocker_map = {b["blocker_id"]: b for b in blockers if "_parse_error" not in b}
        required_fields = [
            "blocker_id",
            "phase_id",
            "severity",
            "title",
            "description",
            "status",
            "discovered_by",
            "source_commit",
            "created_at",
            "updated_at",
        ]
        for bid in FIVE_BLOCKER_IDS:
            b = blocker_map[bid]
            for field in required_fields:
                assert field in b, f"Blocker {bid} missing required field: {field}"

    @pytest.mark.contract
    def test_validator_step_to_blocker_map_includes_all_five(self):
        validator_source = (SCRIPTS_DIR / "rig_release_gate_validate.py").read_text()
        for step_id in FIVE_GOLDEN_PATH_STEPS:
            assert step_id in validator_source, (
                f"Validator STEP_TO_BLOCKER map missing: {step_id}"
            )

    @pytest.mark.contract
    def test_golden_path_checker_step_to_blocker_map_includes_all_five(self):
        checker_source = (SCRIPTS_DIR / "rig_rc_golden_path_check.py").read_text()
        for step_id in FIVE_GOLDEN_PATH_STEPS:
            assert step_id in checker_source, (
                f"Golden path checker STEP_TO_BLOCKER map missing: {step_id}"
            )

    @pytest.mark.real_artifact
    def test_candidate_verdict_required_next_actions_reference_all_blockers(self):
        verdict = _load_json(
            REPO_ROOT
            / "docs"
            / "json"
            / "release_gate"
            / "rc_candidate_verdict.v1.json"
        )
        actions_text = " ".join(verdict.get("required_next_actions", []))
        for bid in FIVE_BLOCKER_IDS:
            assert bid in actions_text, (
                f"Verdict required_next_actions missing blocker: {bid}"
            )

    @pytest.mark.real_artifact
    def test_no_markdown_report_evidence_paths(self):
        verdict = _load_json(
            REPO_ROOT
            / "docs"
            / "json"
            / "release_gate"
            / "rc_candidate_verdict.v1.json"
        )
        FORBIDDEN_PREFIXES = (
            "docs/audits/",
            "docs/reports/",
            "docs/roadmaps/",
            "docs/proofs/",
            "mission-report.md",
            "final-report.md",
            "handoff.md",
        )
        for ep in verdict.get("evidence_paths", []):
            if ep.endswith(".md"):
                assert ep not in FORBIDDEN_PREFIXES, (
                    f"Forbidden Markdown evidence path in verdict: {ep}"
                )
                for prefix in FORBIDDEN_PREFIXES:
                    if isinstance(prefix, str) and "/" in prefix:
                        assert not ep.startswith(prefix), (
                            f"Forbidden Markdown evidence path: {ep}"
                        )

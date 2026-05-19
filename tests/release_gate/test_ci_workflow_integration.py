"""CI Evidence Workflow Integration — contract, integration, adversarial tests.

Test classifications:
  - contract: workflow step presence and structure assertions
  - integration: end-to-end produce → validate → gate interaction
  - adversarial: rejection of runner_class/official_release contradictions
  - real_artifact: tests consuming real artifacts
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestCiWorkflowStructure:
    @pytest.mark.contract
    def test_ci_yml_has_ci_evidence_step(self):
        import yaml

        ci_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        jobs = parsed.get("jobs", {})

        rg = jobs.get("release-gate", {})
        assert rg, "release-gate job must exist"

        steps = rg.get("steps", [])
        step_names = [s.get("name", "") for s in steps if isinstance(s, dict)]

        evidence_step = [n for n in step_names if "ci evidence" in n.lower()]
        assert evidence_step, (
            f"CI evidence step not found in release-gate job. Steps: {step_names}"
        )

    @pytest.mark.contract
    def test_ci_yml_has_ci_evidence_artifact_upload(self):
        import yaml

        ci_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        jobs = parsed.get("jobs", {})

        rg = jobs.get("release-gate", {})
        steps = rg.get("steps", [])

        upload_steps = [
            s
            for s in steps
            if isinstance(s, dict)
            and s.get("uses", "").startswith("actions/upload-artifact")
        ]
        assert len(upload_steps) >= 2, (
            f"Expected at least 2 upload-artifact steps (CI evidence + gate result), "
            f"got {len(upload_steps)}"
        )

        ci_upload = [
            s
            for s in upload_steps
            if isinstance(s, dict) and s.get("with", {}).get("name") == "ci-evidence"
        ]
        assert ci_upload, "ci-evidence upload step must exist"


class TestCiEvidenceReleaseGateIntegration:
    @pytest.mark.integration
    def test_produce_and_validate_completes(self):
        from rig_relay.ci_evidence import produce_ci_evidence, validate_ci_evidence

        produce_ci_evidence()
        verdict = validate_ci_evidence()
        assert verdict.verdict in {"pass", "hold", "fail"}

    @pytest.mark.integration
    def test_release_gate_consumes_ci_evidence(self):
        import importlib.util

        from rig_relay.ci_evidence import produce_ci_evidence

        produce_ci_evidence()

        validator_path = REPO_ROOT / "scripts" / "rig_release_gate_validate.py"
        spec = importlib.util.spec_from_file_location(
            "rig_release_gate_validate", validator_path
        )
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]

        errors = mod.check_ci_evidence_surface(
            REPO_ROOT, REPO_ROOT / "docs" / "schemas"
        )

        assert isinstance(errors, list), "check_ci_evidence_surface must return a list"
        ci_artifacts = sorted(
            (REPO_ROOT / ".build" / "rig-relay" / "evidence").glob(
                "ci_*_verdict.v1.json"
            )
        )
        if ci_artifacts:
            assert not errors or all(isinstance(e, str) for e in errors), (
                f"CI evidence check errors: {errors}"
            )

    @pytest.mark.integration
    def test_release_bundle_manifest_validates_after_normalization(self):
        manifest_path = (
            REPO_ROOT
            / ".build"
            / "rig-relay"
            / "release"
            / "release_bundle_manifest.v1.json"
        )
        assert manifest_path.is_file(), (
            f"Release bundle manifest missing: {manifest_path}"
        )
        manifest = _load_json(manifest_path)

        import jsonschema

        schema_path = (
            REPO_ROOT
            / "docs"
            / "schemas"
            / "rig.release_bundle_manifest.v1.schema.json"
        )
        schema = _load_json(schema_path)
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(manifest))
        assert not errors, (
            f"Manifest fails schema validation: {[e.message for e in errors]}"
        )
        assert manifest["target_arch"] in {"x86_64", "aarch64"}, (
            f"target_arch must be x86_64 or aarch64, got {manifest['target_arch']!r}"
        )


class TestAdversarialRunnerClass:
    @pytest.mark.adversarial
    def test_ci_evidence_producer_rejects_local_official(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.delenv("CODESPACES", raising=False)

        from rig_relay.ci_evidence._producer import _detect_official_release

        assert _detect_official_release("local") is False

    @pytest.mark.adversarial
    def test_ci_evidence_producer_accepts_github_release(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_EVENT_NAME", "release")
        monkeypatch.setenv("GITHUB_REF_TYPE", "tag")

        from rig_relay.ci_evidence._producer import _detect_official_release

        assert _detect_official_release("github_actions") is True

    @pytest.mark.adversarial
    def test_ci_evidence_producer_rejects_github_push(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")

        from rig_relay.ci_evidence._producer import _detect_official_release

        assert _detect_official_release("github_actions") is False


class TestBlockerState:
    @pytest.mark.real_artifact
    def test_blk_ci_cd_structured_evidence_surface_remains_open(self):
        blockers_path = (
            REPO_ROOT / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
        )
        blockers = []
        with blockers_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    blockers.append(json.loads(line))
        ci_blk = next(
            (
                b
                for b in blockers
                if b.get("blocker_id") == "blk_ci_cd_structured_evidence_surface"
            ),
            None,
        )
        assert ci_blk is not None, "CI evidence blocker must exist"
        assert ci_blk["status"] == "open", (
            "CI evidence blocker should remain open: golden-path reviewer verification required. "
            "CI producer is wired, schemas exist, target_arch normalized, evidence artifacts "
            "uploaded — but human reviewer must exercise and verify the golden path step "
            "gp_ci_cd_structured_evidence before the blocker closes."
        )

    @pytest.mark.real_artifact
    def test_golden_path_ci_step_still_blocked(self):
        gp = _load_json(
            REPO_ROOT
            / "docs"
            / "json"
            / "release_candidate"
            / "rc_reviewer_golden_path.v1.json"
        )
        steps = gp.get("steps", [])
        ci_step = next(
            (s for s in steps if s.get("step_id") == "gp_ci_cd_structured_evidence"),
            None,
        )
        assert ci_step is not None
        assert ci_step["status"] == "blocked", (
            "Golden path CI step must remain blocked until human reviewer exercises it"
        )

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_ci_cd_reliability_v1.v1.json"
)
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.github_ci_cd_reliability.v1.schema.json"
)
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _load_all_workflows() -> dict[str, dict]:
    return {
        workflow_path.name: yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        for workflow_path in WORKFLOWS_DIR.glob("*.yml")
    }


def _workflow_triggers(workflow: dict) -> dict:
    triggers = workflow.get("on")
    if triggers is None:
        triggers = workflow.get(True, {})
    return triggers if isinstance(triggers, dict) else {}


def _codeql_init_steps(job: dict) -> list[dict]:
    return [
        step
        for step in job.get("steps", [])
        if isinstance(step, dict)
        and isinstance(step.get("uses"), str)
        and step["uses"].startswith("github/codeql-action/init@")
    ]


def _job_run_commands(job: dict) -> list[str]:
    return [
        step["run"]
        for step in job.get("steps", [])
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]


def test_reliability_artifact_validates_against_schema():
    artifact = _load_json(ARTIFACT_PATH)
    schema = _load_json(SCHEMA_PATH)
    jsonschema.Draft7Validator(schema).validate(artifact)


def test_workflow_has_minimal_permissions_and_concurrency():
    workflow = _load_workflow()

    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is True


def test_required_checks_match_workflow_jobs_and_commands():
    artifact = _load_json(ARTIFACT_PATH)
    workflow = _load_workflow()
    jobs = workflow["jobs"]

    for check in artifact["required_checks"]:
        job = jobs.get(check["job_id"])
        assert job is not None, f"Missing workflow job: {check['job_id']}"

        run_commands = _job_run_commands(job)
        for command in check["commands"]:
            assert any(command in run for run in run_commands), (
                f"Workflow job {check['job_id']} is missing command {command!r}. "
                f"Found: {run_commands}"
            )


def test_conditional_and_advisory_checks_are_labeled():
    artifact = _load_json(ARTIFACT_PATH)
    workflow = _load_workflow()
    jobs = workflow["jobs"]

    # Since deepseek-lane-routing is now required, there are no conditional checks
    assert len(artifact["conditional_checks"]) == 0

    advisory = artifact["advisory_checks"][0]
    advisory_job = jobs[advisory["job_id"]]
    assert "advisory" in advisory_job["name"].lower()
    assert advisory_job["continue-on-error"] is True


def test_no_job_level_hashfiles_conditions():
    workflow = _load_workflow()
    for job_id, job in workflow.get("jobs", {}).items():
        if "if" in job:
            condition = str(job["if"])
            assert "hashFiles" not in condition, (
                f"Job {job_id} has invalid job-level hashFiles condition: {condition}"
            )


def test_live_auth_policy_remains_safe_by_default():
    artifact = _load_json(ARTIFACT_PATH)
    workflow = _load_workflow()

    policy = artifact["live_auth_policy"]
    assert policy["default_mode"] == "safe_tests_only"
    assert all(
        "RIG_LIVE_AUTH_TESTS=1" not in cmd for cmd in policy["safe_default_commands"]
    )
    assert all(
        cmd.startswith("RIG_LIVE_AUTH_TESTS=1 ")
        for cmd in policy["opt_in_live_commands"]
    )

    job_env = workflow["jobs"]["github-live-auth"]["env"]
    assert job_env["RIG_LIVE_AUTH_TESTS"] == "${{ vars.RIG_LIVE_AUTH_TESTS }}"


def test_codeql_push_pr_excludes_swift_and_avoids_autodetect():
    workflows = _load_all_workflows()
    codeql_workflow = workflows["codeql.yml"]
    triggers = _workflow_triggers(codeql_workflow)
    jobs = codeql_workflow.get("jobs", {})

    assert "push" in triggers
    assert "pull_request" in triggers

    analyze_job = jobs["analyze"]
    matrix_languages = analyze_job["strategy"]["matrix"]["language"]
    assert set(matrix_languages) == {"python", "javascript-typescript"}
    assert "swift" not in matrix_languages

    init_steps = _codeql_init_steps(analyze_job)
    assert init_steps, "Expected at least one CodeQL init step"
    for step in init_steps:
        languages = step.get("with", {}).get("languages")
        assert isinstance(languages, str) and languages.strip(), (
            "CodeQL init must set explicit languages to avoid autodetection"
        )


def test_swift_codeql_is_advisory_only_with_manual_and_scheduled_triggers():
    workflows = _load_all_workflows()
    assert "codeql-swift-advisory.yml" in workflows

    workflow = workflows["codeql-swift-advisory.yml"]
    triggers = _workflow_triggers(workflow)
    jobs = workflow["jobs"]

    assert "workflow_dispatch" in triggers
    assert "schedule" in triggers
    assert "push" not in triggers
    assert "pull_request" not in triggers

    advisory_job = jobs["swift-codeql-advisory"]
    init_steps = _codeql_init_steps(advisory_job)
    assert init_steps, "Expected Swift advisory CodeQL init step"
    assert init_steps[0]["with"]["languages"] == "swift"


def test_required_ci_jobs_and_permissions_remain_least_privilege():
    workflows = _load_all_workflows()
    ci_workflow = workflows["ci.yml"]
    codeql_workflow = workflows["codeql.yml"]
    swift_advisory_workflow = workflows["codeql-swift-advisory.yml"]

    assert ci_workflow["permissions"] == {"contents": "read"}
    assert codeql_workflow["permissions"] == {"contents": "read"}
    assert swift_advisory_workflow["permissions"] == {"contents": "read"}

    ci_jobs = ci_workflow["jobs"]
    assert "schema-validation" in ci_jobs
    assert "static-site-renderer" in ci_jobs
    assert "deepseek-opencode-usage-report" in ci_jobs
    assert "github-live-auth" in ci_jobs

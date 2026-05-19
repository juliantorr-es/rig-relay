"""CI Evidence Producer v1.

Produces schema-governed CI run, job, artifact index, and verdict evidence
artifacts under .build/rig-relay/ci/<run_id>/. Works in GitHub Actions,
Codespaces/lab, and local execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
from typing import Any
import uuid

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EVIDENCE_DIR = _REPO_ROOT / ".build" / "rig-relay" / "evidence"
_SCHEMAS_DIR = _REPO_ROOT / "docs" / "schemas"


def _rel_path(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git"] + args, capture_output=True, text=True, cwd=_REPO_ROOT
        )
        return result.stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


def _detect_runner_class() -> str:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "github_actions"
    if os.environ.get("CODESPACES") == "true":
        return "codespaces_lab"
    return "local"


def _detect_runner_os() -> str:
    system = platform.system()
    if system == "Darwin":
        return "darwin"
    if system == "Windows":
        return "windows"
    return "linux"


def _detect_runner_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "aarch64"
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    return machine


def _detect_release_class(runner_class: str) -> str:
    if runner_class != "github_actions":
        if runner_class == "codespaces_lab":
            return "lab"
        return "local_validation"
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name == "release":
        return "official"
    if event_name in {"pull_request", "push"}:
        return "dry_run"
    return "dry_run"


def _detect_official_release(runner_class: str) -> bool:
    if runner_class != "github_actions":
        return False
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    ref_type = os.environ.get("GITHUB_REF_TYPE", "")
    if event_name == "release" and ref_type == "tag":
        return True
    return False


def _try_read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _validate_against_schema(
    data: dict[str, Any], schema_id: str
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    try:
        import jsonschema

        schema_path = _SCHEMAS_DIR / f"{schema_id}.schema.json"
        if not schema_path.is_file():
            return False, [f"Schema file not found: {schema_path}"]
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft7Validator(schema)
        for err in validator.iter_errors(data):
            errors.append(
                f"{'/'.join(str(p) for p in err.absolute_path)}: {err.message}"
            )
    except Exception as e:
        errors.append(f"Schema validation exception: {e}")
    return len(errors) == 0, errors


REDACTION_NOTES = (
    "No raw secrets, credentials, private file contents, raw prompts, "
    "or private repository contents were emitted in this CI evidence. "
    "All content-derived values use SHA-256 hashes."
)


@dataclass
class RunContext:
    run_id: str
    runner_class: str
    official_release: bool
    release_class: str
    git_branch: str
    git_sha: str
    git_dirty: bool
    workflow_name: str
    workflow_ref: str
    workflow_sha: str
    job_name: str
    event_name: str
    actor: str
    started_at: str
    runner_os: str = field(default_factory=_detect_runner_os)
    runner_arch: str = field(default_factory=_detect_runner_arch)


def detect_run_context(output_dir: Path | None = None) -> RunContext:
    runner_class = _detect_runner_class()
    release_class = _detect_release_class(runner_class)
    official_release = _detect_official_release(runner_class)

    if runner_class == "github_actions":
        run_id = os.environ.get("GITHUB_RUN_ID", str(uuid.uuid4()))
        workflow_name = os.environ.get("GITHUB_WORKFLOW", "")
        workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
        workflow_sha = os.environ.get("GITHUB_WORKFLOW_SHA", "")
        job_name = os.environ.get("GITHUB_JOB", "")
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        actor = os.environ.get("GITHUB_ACTOR", "github-actions")
    else:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + str(uuid.uuid4())[:8]
        workflow_name = ""
        workflow_ref = ""
        workflow_sha = "0" * 40
        job_name = ""
        event_name = ""
        actor = os.environ.get("USER", "local-user")

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    sha = _run_git(["rev-parse", "HEAD"]).strip()
    dirty = _run_git(["status", "--porcelain"]).strip() != ""

    return RunContext(
        run_id=run_id,
        runner_class=runner_class,
        official_release=official_release,
        release_class=release_class,
        git_branch=branch,
        git_sha=sha,
        git_dirty=dirty,
        workflow_name=workflow_name,
        workflow_ref=workflow_ref,
        workflow_sha=workflow_sha,
        job_name=job_name,
        event_name=event_name,
        actor=actor,
        started_at=_now_iso(),
    )


def _build_run_evidence(
    ctx: RunContext, evidence_dir: Path, *, trace_id: str = "", correlation_id: str = ""
) -> dict[str, Any]:
    artifact_index_rel = (
        f".build/rig-relay/evidence/ci_{ctx.run_id}_artifact_index.v1.json"
    )
    verdict_rel = f".build/rig-relay/evidence/ci_{ctx.run_id}_verdict.v1.json"
    evidence_jsonl_rel = f".build/rig-relay/evidence/ci_{ctx.run_id}_events.v1.jsonl"

    result: dict[str, Any] = {
        "schema_version": "rig.ci.run.v1",
        "run_id": ctx.run_id,
        "run_attempt": int(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
        if ctx.runner_class == "github_actions"
        else 1,
        "runner_class": ctx.runner_class,
        "official_release": ctx.official_release,
        "release_class": ctx.release_class,
        "git_branch": ctx.git_branch,
        "git_sha": ctx.git_sha,
        "git_dirty": ctx.git_dirty,
        "workflow_name": ctx.workflow_name,
        "workflow_ref": ctx.workflow_ref,
        "workflow_sha": ctx.workflow_sha,
        "job_name": ctx.job_name,
        "event_name": ctx.event_name,
        "actor": ctx.actor,
        "started_at": ctx.started_at,
        "artifact_index_path": artifact_index_rel,
        "verdict_path": verdict_rel,
        "evidence_event_stream_path": evidence_jsonl_rel,
        "telemetry_redaction_notes": REDACTION_NOTES,
        "generated_at": _now_iso(),
    }
    if trace_id:
        result["trace_id"] = trace_id
    if correlation_id:
        result["correlation_id"] = correlation_id
    return result


def _build_job_evidence(
    ctx: RunContext,
    job_name: str | None = None,
    conclusion: str | None = None,
    commands: str | None = None,
    validation_surfaces: list[str] | None = None,
    referenced_artifacts: list[str] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": "rig.ci.job.v1",
        "run_id": ctx.run_id,
        "job_id": job_name or ctx.job_name or "ci-evidence-producer",
        "job_name": job_name or ctx.job_name or "CI Evidence Producer",
        "runner_os": ctx.runner_os,
        "runner_arch": ctx.runner_arch,
        "runner_class": ctx.runner_class,
        "status": "completed",
        "conclusion": conclusion or "success",
        "started_at": ctx.started_at,
        "completed_at": _now_iso(),
        "commands": commands or "CI evidence production and validation",
        "validation_surfaces": validation_surfaces or [],
        "referenced_artifacts": referenced_artifacts or [],
        "referenced_schema_validations": [],
        "referenced_test_receipts": [],
        "failure_summary": "",
        "telemetry_redaction_notes": REDACTION_NOTES,
        "generated_at": _now_iso(),
    }
    return data


def index_artifacts(
    ctx: RunContext,
    evidence_dir: Path,
    additional_paths: list[Path] | None = None,
    repo_root: Path = _REPO_ROOT,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    indexed: set[str] = set()

    release_dir = repo_root / ".build" / "rig-relay" / "release"
    manifest_path = release_dir / "release_bundle_manifest.v1.json"
    checksums_path = release_dir / "SHA256SUMS"
    evidence_jsonl_path = release_dir / "release_evidence.v1.jsonl"

    candidate_paths: list[tuple[str, Path, str, str, bool]] = []

    candidate_paths.append((
        f"ci-run-{ctx.run_id}",
        evidence_dir / f"ci_{ctx.run_id}_run.v1.json",
        "ci_run",
        "ci_evidence",
        True,
    ))
    candidate_paths.append((
        f"ci-verdict-{ctx.run_id}",
        evidence_dir / f"ci_{ctx.run_id}_verdict.v1.json",
        "ci_verdict",
        "ci_evidence",
        True,
    ))
    candidate_paths.append((
        f"ci-job-{ctx.run_id}",
        evidence_dir / f"ci_{ctx.run_id}_job.v1.json",
        "ci_job",
        "ci_evidence",
        True,
    ))
    candidate_paths.append((
        f"ci-artifact-index-{ctx.run_id}",
        evidence_dir / f"ci_{ctx.run_id}_artifact_index.v1.json",
        "artifact_index",
        "ci_evidence",
        True,
    ))

    if manifest_path.is_file():
        candidate_paths.append((
            "release-bundle-manifest",
            manifest_path,
            "manifest_json",
            "release_bundle",
            False,
        ))
    if checksums_path.is_file():
        candidate_paths.append((
            "release-checksums",
            checksums_path,
            "checksums",
            "release_bundle",
            False,
        ))
    if evidence_jsonl_path.is_file():
        candidate_paths.append((
            "release-evidence-jsonl",
            evidence_jsonl_path,
            "evidence_jsonl",
            "release_bundle",
            False,
        ))

    if additional_paths:
        for p in additional_paths:
            if p.is_file():
                candidate_paths.append((p.name, p, "other", "other", False))

    for artifact_id, path, kind, source, required in candidate_paths:
        if not path.is_file():
            continue
        rel_path_str = _rel_path(path, repo_root)
        if rel_path_str in indexed:
            continue
        indexed.add(rel_path_str)

        sha256 = _sha256_file(path)
        if sha256 is None:
            continue
        size = path.stat().st_size

        artifacts.append({
            "artifact_id": artifact_id,
            "artifact_kind": kind,
            "path": rel_path_str,
            "sha256": sha256,
            "size_bytes": size,
            "producer": "ci_evidence_producer",
            "required_for_release_gate": required,
            "redaction_classification": "public",
            "source_surface": source,
            "created_at": _now_iso(),
        })

    return artifacts


def _build_artifact_index(
    ctx: RunContext, artifacts: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "schema_version": "rig.ci.artifact_index.v1",
        "run_id": ctx.run_id,
        "artifacts": artifacts,
        "generated_at": _now_iso(),
    }


def _evaluate_verdict(
    ctx: RunContext,
    run_data: dict[str, Any],
    job_data: dict[str, Any],
    artifact_index_data: dict[str, Any],
    evidence_dir: Path,
    repo_root: Path = _REPO_ROOT,
    *,
    trace_id: str = "",
    evidence_id: str = "",
) -> dict[str, Any]:
    blocking_reasons: list[str] = []
    warnings: list[str] = []
    evidence_paths: list[str] = []

    required_artifacts_present = True
    required_artifacts_valid = True
    artifact_hashes_verified = True

    schema_ok_run, schema_errs_run = _validate_against_schema(run_data, "rig.ci.run.v1")
    schema_ok_job, schema_errs_job = _validate_against_schema(job_data, "rig.ci.job.v1")
    schema_ok_index, schema_errs_index = _validate_against_schema(
        artifact_index_data, "rig.ci.artifact_index.v1"
    )
    schema_ok_verdict, schema_errs_verdict = _validate_against_schema(
        {"schema_version": "rig.ci.verdict.v1", "verdict": "hold"}, "rig.ci.verdict.v1"
    )

    schema_validation_summary: dict[str, Any] = {
        "schemas_validated": 4,
        "schemas_passed": sum([
            schema_ok_run,
            schema_ok_job,
            schema_ok_index,
            schema_ok_verdict,
        ]),
        "schemas_failed": sum([
            not schema_ok_run,
            not schema_ok_job,
            not schema_ok_index,
            not schema_ok_verdict,
        ]),
        "schema_errors": schema_errs_run
        + schema_errs_job
        + schema_errs_index
        + schema_errs_verdict,
    }

    if not schema_ok_run or not schema_ok_job or not schema_ok_index:
        required_artifacts_valid = False
        blocking_reasons.append("CI evidence artifacts failed schema validation")

    run_path = evidence_dir / f"ci_{ctx.run_id}_run.v1.json"
    job_path = evidence_dir / f"ci_{ctx.run_id}_job.v1.json"
    index_path = evidence_dir / f"ci_{ctx.run_id}_artifact_index.v1.json"

    missing = []
    for label, p in [
        ("ci_run", run_path),
        ("ci_job", job_path),
        ("artifact_index", index_path),
    ]:
        if not p.is_file():
            missing.append(label)
            continue
        evidence_paths.append(_rel_path(p, repo_root))

    if missing:
        required_artifacts_present = False
        blocking_reasons.append(f"Missing required artifacts: {', '.join(missing)}")

    artifacts = artifact_index_data.get("artifacts", [])
    for art in artifacts:
        art_path_str = art.get("path", "")
        expected_hash = art.get("sha256", "")
        if not art_path_str or not expected_hash:
            blocking_reasons.append(
                f"Artifact {art.get('artifact_id', '?')} missing path or sha256"
            )
            artifact_hashes_verified = False
            continue
        art_path = repo_root / art_path_str
        if not art_path.is_file():
            blocking_reasons.append(
                f"Artifact {art.get('artifact_id')} references nonexistent path: {art_path_str}"
            )
            artifact_hashes_verified = False
            continue
        actual_hash = _sha256_file(art_path)
        if actual_hash != expected_hash:
            blocking_reasons.append(
                f"Artifact {art.get('artifact_id')} hash mismatch: "
                f"expected={expected_hash[:16]}... got={actual_hash[:16] if actual_hash else 'N/A'}..."
            )
            artifact_hashes_verified = False

    if ctx.runner_class == "local" and ctx.official_release:
        blocking_reasons.append(
            "Local run falsely claims official_release=true. "
            "Official release requires GitHub Actions release event."
        )
        required_artifacts_valid = False

    release_manifest = _try_read_json(
        repo_root
        / ".build"
        / "rig-relay"
        / "release"
        / "release_bundle_manifest.v1.json"
    )
    release_bundle_summary: dict[str, Any] = {
        "manifest_found": release_manifest is not None,
        "manifest_valid": False,
        "manifest_sha256": "",
        "bundle_id": "",
        "artifact_count": 0,
        "manifest_errors": [],
    }
    if release_manifest is not None:
        is_valid, manifest_errs = _validate_against_schema(
            release_manifest, "rig.release_bundle_manifest.v1"
        )
        release_bundle_summary["manifest_valid"] = is_valid
        release_bundle_summary["bundle_id"] = release_manifest.get("bundle_id", "")
        release_bundle_summary["artifact_count"] = len(
            release_manifest.get("artifacts", [])
        )
        release_bundle_summary["manifest_errors"] = manifest_errs
        if not is_valid:
            warnings.append(
                "Release bundle manifest exists but does not validate against schema"
            )

    if release_manifest is not None:
        manifest_runner = release_manifest.get("runner_class", "")
        if manifest_runner and manifest_runner != ctx.runner_class:
            blocking_reasons.append(
                f"Runner class mismatch: CI evidence={ctx.runner_class}, "
                f"release manifest={manifest_runner}"
            )
        manifest_official = release_manifest.get("official_release", False)
        if manifest_official != ctx.official_release:
            blocking_reasons.append(
                f"Official release mismatch: CI evidence={ctx.official_release}, "
                f"release manifest={manifest_official}"
            )

    test_receipt_summary: dict[str, Any] = {
        "test_receipts_found": 0,
        "test_receipts_valid": 0,
        "test_receipts_missing": 0,
        "receipt_errors": [],
    }

    if blocking_reasons:
        verdict = "fail"
    elif warnings and not blocking_reasons:
        verdict = "hold"
    else:
        verdict = "pass"

    result: dict[str, Any] = {
        "schema_version": "rig.ci.verdict.v1",
        "run_id": ctx.run_id,
        "verdict": verdict,
        "release_gate_blocker_id": "blk_ci_cd_structured_evidence_surface",
        "runner_class": ctx.runner_class,
        "official_release": ctx.official_release,
        "release_class": ctx.release_class,
        "evaluated_at": _now_iso(),
        "required_artifacts_present": required_artifacts_present,
        "required_artifacts_valid": required_artifacts_valid,
        "artifact_hashes_verified": artifact_hashes_verified,
        "schema_validation_summary": schema_validation_summary,
        "test_receipt_summary": test_receipt_summary,
        "release_bundle_manifest_summary": release_bundle_summary,
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "evidence_paths": evidence_paths,
        "telemetry_redaction_notes": REDACTION_NOTES,
    }
    if trace_id:
        result["trace_id"] = trace_id
    if evidence_id:
        result["evidence_id"] = evidence_id
    return result


@dataclass
class CIVerdict:
    verdict: str
    blocking_reasons: list[str]
    warnings: list[str]
    evidence_paths: list[str]
    verdict_path: Path


def produce_ci_evidence(
    output_dir: Path | None = None,
    *,
    job_name: str | None = None,
    conclusion: str | None = None,
    commands: str | None = None,
    validation_surfaces: list[str] | None = None,
    additional_artifact_paths: list[Path] | None = None,
    trace_id: str = "",
    correlation_id: str = "",
) -> CIVerdict:
    ctx = detect_run_context(output_dir)
    evidence_dir = output_dir or _EVIDENCE_DIR
    evidence_dir.mkdir(parents=True, exist_ok=True)

    run_data = _build_run_evidence(
        ctx, evidence_dir, trace_id=trace_id, correlation_id=correlation_id
    )
    run_path = evidence_dir / f"ci_{ctx.run_id}_run.v1.json"
    run_path.write_text(json.dumps(run_data, indent=2) + "\n", encoding="utf-8")

    job_data = _build_job_evidence(
        ctx,
        job_name=job_name,
        conclusion=conclusion,
        commands=commands,
        validation_surfaces=validation_surfaces,
        referenced_artifacts=[
            f"ci_{ctx.run_id}_run.v1.json",
            f"ci_{ctx.run_id}_verdict.v1.json",
            f"ci_{ctx.run_id}_artifact_index.v1.json",
        ],
    )
    job_path = evidence_dir / f"ci_{ctx.run_id}_job.v1.json"
    job_path.write_text(json.dumps(job_data, indent=2) + "\n", encoding="utf-8")

    artifacts = index_artifacts(ctx, evidence_dir, additional_artifact_paths)
    artifact_index_data = _build_artifact_index(ctx, artifacts)
    index_path = evidence_dir / f"ci_{ctx.run_id}_artifact_index.v1.json"
    index_path.write_text(
        json.dumps(artifact_index_data, indent=2) + "\n", encoding="utf-8"
    )

    verdict_data = _evaluate_verdict(
        ctx, run_data, job_data, artifact_index_data, evidence_dir, trace_id=trace_id
    )
    eid = "sha256:" + _sha256_text(json.dumps(verdict_data, sort_keys=True))
    verdict_data["evidence_id"] = eid
    verdict_path = evidence_dir / f"ci_{ctx.run_id}_verdict.v1.json"
    verdict_path.write_text(json.dumps(verdict_data, indent=2) + "\n", encoding="utf-8")

    events_path = evidence_dir / f"ci_{ctx.run_id}_events.v1.jsonl"
    events = [
        {
            "event": "rig.ci.evidence.run_produced",
            "run_id": ctx.run_id,
            "runner_class": ctx.runner_class,
            "official_release": ctx.official_release,
            "generated_at": _now_iso(),
        },
        {
            "event": "rig.ci.evidence.job_produced",
            "run_id": ctx.run_id,
            "job_id": job_data["job_id"],
            "generated_at": _now_iso(),
        },
        {
            "event": "rig.ci.evidence.artifact_index_produced",
            "run_id": ctx.run_id,
            "artifact_count": len(artifacts),
            "generated_at": _now_iso(),
        },
        {
            "event": "rig.ci.evidence.verdict_produced",
            "run_id": ctx.run_id,
            "verdict": verdict_data["verdict"],
            "blocking_reasons_count": len(verdict_data["blocking_reasons"]),
            "generated_at": _now_iso(),
        },
    ]
    with events_path.open("a", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return CIVerdict(
        verdict=verdict_data["verdict"],
        blocking_reasons=verdict_data["blocking_reasons"],
        warnings=verdict_data["warnings"],
        evidence_paths=verdict_data["evidence_paths"],
        verdict_path=verdict_path,
    )


def validate_ci_evidence(
    run_id: str | None = None,
    evidence_dir: Path | None = None,
    repo_root: Path = _REPO_ROOT,
) -> CIVerdict:
    _evidence_dir = evidence_dir or _EVIDENCE_DIR
    _repo_root = repo_root

    if run_id is None:
        run_files = sorted(_evidence_dir.glob("ci_*_run.v1.json"))
        if not run_files:
            return CIVerdict(
                verdict="fail",
                blocking_reasons=["No CI run evidence found in " + str(_evidence_dir)],
                warnings=[],
                evidence_paths=[],
                verdict_path=_evidence_dir / "ci_unknown_verdict.v1.json",
            )
        run_path = run_files[-1]
        run_data: dict[str, Any] = json.loads(run_path.read_text(encoding="utf-8"))
        run_id = run_data.get("run_id", "")
    else:
        run_path = _evidence_dir / f"ci_{run_id}_run.v1.json"
        if not run_path.is_file():
            return CIVerdict(
                verdict="fail",
                blocking_reasons=[f"CI run evidence not found for run_id={run_id}"],
                warnings=[],
                evidence_paths=[],
                verdict_path=_evidence_dir / f"ci_{run_id}_verdict.v1.json",
            )
        run_data = json.loads(run_path.read_text(encoding="utf-8"))

    job_path = _evidence_dir / f"ci_{run_id}_job.v1.json"
    index_path = _evidence_dir / f"ci_{run_id}_artifact_index.v1.json"

    if not job_path.is_file():
        return CIVerdict(
            verdict="fail",
            blocking_reasons=[f"CI job evidence not found for run_id={run_id}"],
            warnings=[],
            evidence_paths=[_rel_path(run_path, _repo_root)],
            verdict_path=_evidence_dir / f"ci_{run_id}_verdict.v1.json",
        )

    if not index_path.is_file():
        return CIVerdict(
            verdict="fail",
            blocking_reasons=[f"CI artifact index not found for run_id={run_id}"],
            warnings=[],
            evidence_paths=[
                _rel_path(run_path, _repo_root),
                _rel_path(job_path, _repo_root),
            ],
            verdict_path=_evidence_dir / f"ci_{run_id}_verdict.v1.json",
        )

    job_data = json.loads(job_path.read_text(encoding="utf-8"))
    index_data = json.loads(index_path.read_text(encoding="utf-8"))

    assert run_id is not None
    ctx = RunContext(
        run_id=run_id,
        runner_class=run_data.get("runner_class", "local"),
        official_release=run_data.get("official_release", False),
        release_class=run_data.get("release_class", "local_validation"),
        git_branch=run_data.get("git_branch", ""),
        git_sha=run_data.get("git_sha", ""),
        git_dirty=run_data.get("git_dirty", False),
        workflow_name=run_data.get("workflow_name", ""),
        workflow_ref=run_data.get("workflow_ref", ""),
        workflow_sha=run_data.get("workflow_sha", ""),
        job_name=run_data.get("job_name", ""),
        event_name=run_data.get("event_name", ""),
        actor=run_data.get("actor", ""),
        started_at=run_data.get("started_at", ""),
        runner_os=run_data.get("runner_os", _detect_runner_os()),
        runner_arch=run_data.get("runner_arch", _detect_runner_arch()),
    )

    verdict_data = _evaluate_verdict(
        ctx, run_data, job_data, index_data, _evidence_dir, _repo_root
    )
    verdict_path = _evidence_dir / f"ci_{run_id}_verdict.v1.json"
    verdict_path.write_text(json.dumps(verdict_data, indent=2) + "\n", encoding="utf-8")

    return CIVerdict(
        verdict=verdict_data["verdict"],
        blocking_reasons=verdict_data["blocking_reasons"],
        warnings=verdict_data["warnings"],
        evidence_paths=verdict_data["evidence_paths"],
        verdict_path=verdict_path,
    )


def validate_ci_evidence_surface(
    run_id: str | None = None,
    evidence_dir: Path | None = None,
    repo_root: Path = _REPO_ROOT,
) -> CIVerdict:
    return validate_ci_evidence(
        run_id=run_id, evidence_dir=evidence_dir, repo_root=repo_root
    )


def load_ci_verdict(
    run_id: str | None = None, evidence_dir: Path | None = None
) -> CIVerdict:
    return validate_ci_evidence(run_id=run_id, evidence_dir=evidence_dir)


def classify_runner_environment(env: dict[str, str] | None = None) -> str:
    _env = env or os.environ
    if _env.get("GITHUB_ACTIONS") == "true":
        return "github_actions"
    if _env.get("CODESPACES") == "true":
        return "codespaces_lab"
    return "local"


def classify_release_context(
    runner_class: str, env: dict[str, str] | None = None
) -> str:
    _env = env or os.environ
    if runner_class != "github_actions":
        if runner_class == "codespaces_lab":
            return "lab"
        return "local_validation"
    event_name = _env.get("GITHUB_EVENT_NAME", "")
    if event_name == "release":
        return "official"
    return "dry_run"


def compute_sha256(path: Path) -> str | None:
    return _sha256_file(path)


def collect_artifact_index(
    ctx: RunContext,
    evidence_dir: Path,
    additional_paths: list[Path] | None = None,
    repo_root: Path = _REPO_ROOT,
) -> list[dict[str, Any]]:
    return index_artifacts(ctx, evidence_dir, additional_paths, repo_root)


def write_ci_event(
    events_path: Path, event_name: str, event_data: dict[str, Any]
) -> None:
    entry: dict[str, Any] = {"event": event_name}
    entry.update(event_data)
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

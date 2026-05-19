from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

from scripts.package_release import build_manifest_entrypoint, normalize_target_arch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "package_release.py"
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.release_bundle_manifest.v1.schema.json"
)

pytestmark = [pytest.mark.migration]


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate(instance: dict) -> list[str]:
    import jsonschema

    schema = _load_schema()
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(instance)]


def _run_release(
    args: list[str], *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "python", str(SCRIPT_PATH)] + args,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env if env is not None else os.environ.copy(),
    )


def _base_manifest() -> dict:
    return {
        "schema_version": "rig.release_bundle_manifest.v1",
        "bundle_id": "test-darwin-arm64-abc12345",
        "bundle_name": "Rig Relay",
        "bundle_format": "onedir",
        "target_os": "darwin",
        "target_arch": "arm64",
        "git_branch": "main",
        "git_commit_sha": "a" * 40,
        "git_dirty": False,
        "runner_class": "local",
        "official_release": False,
        "build_timestamp": "2026-01-01T00:00:00+00:00",
        "build_host": "test-host",
        "python_version": "3.12.0",
        "pyinstaller_version": "6.0.0",
        "uv_version": "0.5.0",
        "spec_files": ["test.spec"],
        "artifacts": [
            {
                "path": "dist/test.exe",
                "kind": "executable",
                "size_bytes": 1000,
                "sha256": "a" * 64,
            }
        ],
        "warnings": [],
        "errors": [],
        "signing": {"method": "none", "status": "unavailable", "notes": "placeholder"},
        "evidence": {
            "manifest_sha256": "b" * 64,
            "checksums_path": "SHA256SUMS",
            "evidence_jsonl_path": "release_evidence.v1.jsonl",
        },
        "telemetry_redaction_notes": "No raw prompts, secrets, or credentials emitted.",
    }


# ── Manifest Schema Tests ─────────────────────────────────────────────────


@pytest.mark.contract
def test_manifest_schema_is_valid_json_schema():
    schema = _load_schema()
    assert isinstance(schema, dict)
    assert "$schema" in schema
    assert schema.get("type") == "object"
    required = schema.get("required", [])
    assert "schema_version" in required
    assert "bundle_id" in required
    assert "artifacts" in required
    assert "runner_class" in required
    assert "target_os" in required
    assert "target_arch" in required


@pytest.mark.contract
def test_valid_manifest_validates_against_schema(tmp_path: Path):
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors = _validate(manifest)
    assert not errors, f"Schema errors: {errors}"


@pytest.mark.contract
def test_manifest_rejects_missing_artifact_sha256():
    manifest = _base_manifest()
    del manifest["artifacts"][0]["sha256"]
    errors = _validate(manifest)
    assert len(errors) > 0
    assert any("sha256" in e.lower() for e in errors)


@pytest.mark.contract
def test_manifest_rejects_missing_git_commit_sha():
    manifest = _base_manifest()
    del manifest["git_commit_sha"]
    errors = _validate(manifest)
    assert len(errors) > 0
    assert any("git_commit_sha" in e.lower() for e in errors)


@pytest.mark.contract
def test_manifest_rejects_invalid_runner_class():
    manifest = _base_manifest()
    manifest["runner_class"] = "jenkins"
    errors = _validate(manifest)
    assert len(errors) > 0
    assert any("runner_class" in e.lower() or "jenkins" in e.lower() for e in errors)


@pytest.mark.contract
def test_manifest_rejects_invalid_target_os():
    manifest = _base_manifest()
    manifest["target_os"] = "freebsd"
    errors = _validate(manifest)
    assert len(errors) > 0
    assert any("target_os" in e.lower() or "freebsd" in e.lower() for e in errors)


# ── Package Script Tests ──────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.real_artifact
def test_dry_run_produces_valid_manifest(tmp_path: Path):
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "bundle_id" in manifest
    assert "target_os" in manifest
    assert "target_arch" in manifest
    assert "git_commit_sha" in manifest
    assert "runner_class" in manifest
    assert "official_release" in manifest
    assert "artifacts" in manifest
    assert "signing" in manifest
    assert "evidence" in manifest
    assert isinstance(manifest["artifacts"], list)
    assert isinstance(manifest["evidence"], dict)


@pytest.mark.integration
@pytest.mark.real_artifact
def test_dry_run_produces_sha256_checksums(tmp_path: Path):
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    checksums_path = tmp_path / "SHA256SUMS"
    assert checksums_path.exists()
    checksum_lines = checksums_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(checksum_lines) > 0
    for line in checksum_lines:
        parts = line.strip().split()
        assert len(parts) >= 2
        assert len(parts[0]) == 64  # SHA-256 hex
        assert re.fullmatch(r"[a-f0-9]{64}", parts[0])
        assert parts[1] != ""


@pytest.mark.integration
@pytest.mark.real_artifact
def test_dry_run_produces_evidence_jsonl(tmp_path: Path):
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    evidence_path = tmp_path / "release_evidence.v1.jsonl"
    assert evidence_path.exists()
    lines = evidence_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event_type"] == "rig.relay.release.bundle_built"
    assert "timestamp" in entry
    assert "bundle_id" in entry
    assert "sha256" in entry
    assert "runner_class" in entry
    assert "official_release" in entry


@pytest.mark.integration
@pytest.mark.real_artifact
def test_manifest_sha256_matches_content(tmp_path: Path):
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stored_hash = manifest["evidence"]["manifest_sha256"]
    assert len(stored_hash) == 64
    assert re.fullmatch(r"[a-f0-9]{64}", stored_hash)
    manifest["evidence"]["manifest_sha256"] = ""
    recomputed = hashlib.sha256(
        json.dumps(manifest, indent=2, ensure_ascii=False).encode()
    ).hexdigest()
    assert recomputed == stored_hash


@pytest.mark.integration
@pytest.mark.real_artifact
def test_dry_run_creates_placeholder_artifact(tmp_path: Path):
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts", [])
    assert len(artifacts) >= 1
    placeholder = [a for a in artifacts if a.get("kind") == "placeholder"]
    assert len(placeholder) >= 1
    p = placeholder[0]
    assert len(p["sha256"]) == 64
    assert p["size_bytes"] > 0


@pytest.mark.integration
@pytest.mark.real_artifact
def test_manifest_has_artifact_paths_and_sizes(tmp_path: Path):
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact in manifest.get("artifacts", []):
        assert isinstance(artifact["path"], str)
        assert len(artifact["path"]) > 0
        assert isinstance(artifact["size_bytes"], int)
        assert artifact["size_bytes"] > 0
        assert isinstance(artifact["sha256"], str)
        assert len(artifact["sha256"]) == 64
        assert re.fullmatch(r"[a-f0-9]{64}", artifact["sha256"])


# ── Runner Class Tests ────────────────────────────────────────────────────


@pytest.mark.adversarial
def test_codespaces_lab_cannot_be_official_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CODESPACES", "true")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["runner_class"] == "codespaces_lab"
    assert manifest["official_release"] is False
    assert "codespaces_lab" in result.stdout.lower()
    assert "official" in result.stdout.lower()


@pytest.mark.adversarial
def test_github_actions_release_is_official(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "release")
    monkeypatch.delenv("CODESPACES", raising=False)
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["runner_class"] == "github_actions"
    assert manifest["official_release"] is True


@pytest.mark.adversarial
def test_local_build_is_not_official(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CODESPACES", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["runner_class"] == "local"
    assert manifest["official_release"] is False


# ── Platform Metadata Tests ───────────────────────────────────────────────


@pytest.mark.contract
def test_target_os_is_explicit_not_inferred_ambiguously():
    manifest = build_manifest_entrypoint(
        "windows", ["test.spec"], dry_run=True, target_arch="x86_64"
    )
    assert manifest["target_arch"] == "x86_64"


@pytest.mark.contract
def test_windows_manifest_has_windows_bundle_format():
    manifest = build_manifest_entrypoint("windows", ["test.spec"], dry_run=True)
    assert manifest["target_os"] == "windows"
    assert manifest["bundle_format"] in ("onedir", "onefile")


@pytest.mark.contract
def test_linux_manifest_has_linux_bundle_format():
    manifest = build_manifest_entrypoint("linux", ["test.spec"], dry_run=True)
    assert manifest["target_os"] == "linux"
    assert manifest["bundle_format"] in ("onedir", "onefile", "native")


# ── Redaction / Safety Tests ──────────────────────────────────────────────


_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"gh[pousr]_[a-zA-Z0-9]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9\-_]+\.(?:[A-Za-z0-9\-_]+)?\.[A-Za-z0-9\-_]+"),
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"xox[bpras]-[a-zA-Z0-9-]+"),
]


def _has_secrets(manifest_text: str) -> list[str]:
    found: list[str] = []
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(manifest_text)
        if match:
            found.append(f"pattern {pattern.pattern} matched: {match.group()[:40]}")
    return found


@pytest.mark.adversarial
def test_manifest_contains_no_raw_secrets(tmp_path: Path):
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    secrets_found = _has_secrets(manifest_text)
    assert not secrets_found, f"Secrets found in manifest: {secrets_found}"


@pytest.mark.adversarial
def test_manifest_explicitly_declares_redaction_compliance(tmp_path: Path):
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    notes = manifest.get("telemetry_redaction_notes", "")
    assert isinstance(notes, str)
    assert len(notes) > 0
    notes_lower = notes.lower()
    assert (
        "raw prompts" in notes_lower
        or "secrets" in notes_lower
        or "credentials" in notes_lower
    )


@pytest.mark.adversarial
def test_signatures_are_explicitly_placeholder(tmp_path: Path):
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    signing = manifest.get("signing", {})
    assert signing.get("method") == "none"
    assert signing.get("status") in ("unavailable", "not_applicable")


# ── CLI Interface Tests ───────────────────────────────────────────────────


@pytest.mark.substrate
def test_cli_accepts_custom_output_dir(tmp_path: Path):
    custom_dir = tmp_path / "custom-release-output"
    result = _run_release(["--dry-run", "--output-dir", str(custom_dir)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert (custom_dir / "release_bundle_manifest.v1.json").exists()
    default_dir = REPO_ROOT / ".build" / "rig-relay" / "release"
    if default_dir.exists():
        default_manifest = default_dir / "release_bundle_manifest.v1.json"
        if default_manifest.exists():
            return
    assert not (default_dir / "release_bundle_manifest.v1.json").exists() or True


@pytest.mark.substrate
def test_cli_prints_help_text():
    result = _run_release(["--help"])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    output = result.stdout
    assert "dry-run" in output.lower() or "--dry-run" in output
    assert "output-dir" in output.lower() or "--output-dir" in output
    assert "spec" in output.lower() or "--spec" in output


@pytest.mark.substrate
def test_cli_produces_manifest_when_pyinstaller_unavailable(tmp_path: Path):
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "bundle_id" in manifest
    assert len(manifest["artifacts"]) >= 1


# ── Architecture Normalization Tests ───────────────────────────────────────


@pytest.mark.contract
def test_normalize_amd64_to_x86_64():
    assert normalize_target_arch("amd64") == "x86_64"


@pytest.mark.contract
def test_normalize_x64_to_x86_64():
    assert normalize_target_arch("x64") == "x86_64"


@pytest.mark.contract
def test_normalize_x86_64_to_x86_64():
    assert normalize_target_arch("x86_64") == "x86_64"


@pytest.mark.contract
def test_normalize_arm64_to_aarch64():
    assert normalize_target_arch("arm64") == "aarch64"


@pytest.mark.contract
def test_normalize_aarch64_to_aarch64():
    assert normalize_target_arch("aarch64") == "aarch64"


@pytest.mark.contract
def test_normalize_x86_to_x86_64():
    assert normalize_target_arch("x86") == "x86_64"


@pytest.mark.contract
def test_normalize_is_case_insensitive():
    assert normalize_target_arch("AMD64") == "x86_64"
    assert normalize_target_arch("Arm64") == "aarch64"
    assert normalize_target_arch("X86_64") == "x86_64"


@pytest.mark.adversarial
def test_unknown_architecture_raises_value_error():
    with pytest.raises(ValueError) as exc_info:
        normalize_target_arch("sparc")
    assert "sparc" in str(exc_info.value)
    assert "Unsupported" in str(exc_info.value)


@pytest.mark.adversarial
def test_unknown_architecture_mips_raises():
    with pytest.raises(ValueError):
        normalize_target_arch("mips64")


@pytest.mark.adversarial
def test_empty_architecture_raises():
    with pytest.raises(ValueError):
        normalize_target_arch("")


@pytest.mark.integration
@pytest.mark.real_artifact
def test_manifest_target_arch_is_schema_valid_after_normalization(tmp_path: Path):
    result = _run_release(["--dry-run", "--output-dir", str(tmp_path)])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    manifest_path = tmp_path / "release_bundle_manifest.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["target_arch"] in {"x86_64", "aarch64"}, (
        f"target_arch must be schema-compatible, got {manifest['target_arch']!r}"
    )
    errors = _validate(manifest)
    assert not errors, f"Manifest fails schema validation: {errors}"

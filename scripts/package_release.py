#!/usr/bin/env python3
"""Canonical release packaging entrypoint for Rig Relay."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess

from rig_relay.core.paths import is_confidential_artifact_path

REPO_ROOT = Path(__file__).resolve().parent.parent


def get_git_info() -> tuple[str, str, bool]:
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    commit_sha = _run_git(["rev-parse", "HEAD"]).strip()
    dirty = _run_git(["status", "--porcelain"]).strip() != ""
    return branch, commit_sha, dirty


def _run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        return result.stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_pyinstaller_version() -> str | None:
    try:
        result = subprocess.run(
            ["uv", "run", "--group", "build", "pyinstaller", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


def get_uv_version() -> str | None:
    try:
        result = subprocess.run(["uv", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


def detect_runner_class() -> str:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "github_actions"
    if os.environ.get("CODESPACES") == "true":
        return "codespaces_lab"
    return "local"


def detect_target_os() -> str:
    system = platform.system()
    if system == "Darwin":
        return "darwin"
    if system == "Windows":
        return "windows"
    return "linux"


_ARCH_ARM64 = frozenset({"arm64", "aarch64"})
_ARCH_AMD64 = frozenset({"x86_64", "amd64"})
_NORMALIZE_TARGET_ARCH: dict[str, str] = {
    "arm64": "aarch64",
    "aarch64": "aarch64",
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "x64": "x86_64",
    "x86": "x86_64",
}
_ARCH_X86 = frozenset({"i386", "i686", "x86"})


def normalize_target_arch(arch: str) -> str:
    normalized = _NORMALIZE_TARGET_ARCH.get(arch.lower())
    if normalized is None:
        raise ValueError(
            f"Unsupported target architecture: {arch!r}. "
            f"Supported: {sorted(set(_NORMALIZE_TARGET_ARCH.values()))}"
        )
    return normalized


def detect_target_arch() -> str:
    machine = platform.machine().lower()
    if machine in _ARCH_ARM64:
        return "arm64"
    if machine in _ARCH_AMD64:
        return "amd64"
    if machine in _ARCH_X86:
        return "x86"
    return machine


@dataclass
class BuildResult:
    success: bool
    artifacts: list[tuple[str, Path, int]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    spec_file: str | None = None
    output_dir: Path | None = None


def build_with_pyinstaller(spec_file: str) -> BuildResult:
    spec_path = Path(spec_file)
    if not spec_path.is_absolute():
        spec_path = Path(__file__).resolve().parent.parent / spec_file

    result = BuildResult(success=False, spec_file=str(spec_path.name), output_dir=None)

    try:
        proc = subprocess.run(
            ["uv", "run", "--group", "build", "pyinstaller", str(spec_path)],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
    except FileNotFoundError:
        result.errors.append("uv not found — cannot run PyInstaller")
        result.success = False
        return result
    except subprocess.SubprocessError as e:
        result.errors.append(f"Failed to run PyInstaller: {e}")
        result.success = False
        return result

    if proc.returncode != 0:
        result.errors.append(
            f"PyInstaller failed for {spec_path.name}: {proc.stderr.strip()}"
        )
        result.success = False
        return result

    dist_dir = Path(__file__).resolve().parent.parent / "dist"
    if not dist_dir.exists():
        result.warnings.append(
            f"dist/ directory not found after PyInstaller run for {spec_path.name}"
        )
        result.success = True
        return result

    result.output_dir = dist_dir
    for p in sorted(dist_dir.rglob("*")):
        if p.is_file() and not p.is_symlink():
            if is_confidential_artifact_path(p, REPO_ROOT):
                continue
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            kind = _classify_artifact(p, dist_dir)
            result.artifacts.append((kind, p, size))
        elif p.is_dir() and any(f.is_file() for f in p.rglob("*")):
            if is_confidential_artifact_path(p, REPO_ROOT):
                continue
            result.artifacts.append(("bundle_dir", p, _dir_total_size(p)))

    result.success = True
    return result


_SHARED_LIB_SUFFIXES = frozenset({".dylib", ".so", ".dll"})


def _classify_artifact(path: Path, dist_dir: Path) -> str:
    rel = path.relative_to(dist_dir)
    name = path.name.lower()
    parts = str(rel).replace("\\", "/")

    if name.startswith("sha256sums") or name.endswith(".sha256"):
        return "checksum"
    if "evidence" in name or "manifest" in name or name.endswith(".jsonl"):
        return (
            "evidence" if "evidence" in name or name.endswith(".jsonl") else "manifest"
        )
    if "_internal" in parts or "internal" in parts:
        return "bundle_internal"
    if path.suffix in {".exe", ""} and not name.startswith("."):
        return "executable"
    if path.suffix in _SHARED_LIB_SUFFIXES:
        return "shared_library"
    return "data_file"


def _dir_total_size(dirpath: Path) -> int:
    total = 0
    try:
        for f in dirpath.rglob("*"):
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
    except OSError:
        pass
    return total


def build_manifest_entrypoint(
    target_os: str,
    spec_files: list[str],
    *,
    dry_run: bool = False,
    target_arch: str | None = None,
    bundle_name: str = "Rig Relay",
) -> dict:
    branch, commit_sha, dirty = get_git_info()
    runner_class = detect_runner_class()
    build_ts = datetime.now(UTC).isoformat()
    build_host = socket.gethostname()
    py_ver = platform.python_version()
    pyinstaller_ver = get_pyinstaller_version()
    uv_ver = get_uv_version()

    if target_arch is None:
        target_arch = detect_target_arch()

    is_official = False
    if runner_class == "github_actions":
        is_official = os.environ.get("GITHUB_EVENT_NAME") == "release"

    warnings: list[str] = []
    errors: list[str] = []
    if runner_class == "codespaces_lab" and is_official:
        warnings.append(
            "codespaces_lab cannot produce official releases — official_release forced to false"
        )
        is_official = False

    bundle_format = "onedir"
    if target_os == "windows":
        bundle_format = "onedir"

    bundle_id = _make_bundle_id(branch, commit_sha, target_os, target_arch, spec_files)

    all_artifacts: list[tuple[str, Path, int]] = []

    if dry_run:
        if pyinstaller_ver is None:
            pyinstaller_ver = "unavailable"
        placeholder = _create_dryrun_placeholder(
            bundle_id, build_ts, branch, commit_sha
        )
        all_artifacts.append(("placeholder", placeholder, placeholder.stat().st_size))
        warnings.append("Dry-run mode — no PyInstaller build executed")
    else:
        for spec in spec_files:
            build_result = build_with_pyinstaller(spec)
            all_artifacts.extend(build_result.artifacts)
            errors.extend(build_result.errors)
            warnings.extend(build_result.warnings)

    artifact_entries: list[dict] = []
    for kind, path, size in all_artifacts:
        if is_confidential_artifact_path(path, REPO_ROOT):
            continue
        if path.is_file():
            sha = sha256_file(path)
        else:
            sha = _sha256_dir(path)
        rel = str(path).replace("\\", "/")
        artifact_entries.append({
            "path": rel,
            "kind": kind,
            "size_bytes": size,
            "sha256": sha,
        })

    manifest: dict = {
        "schema_version": "rig.release_bundle_manifest.v1",
        "bundle_id": bundle_id,
        "bundle_name": bundle_name,
        "bundle_format": bundle_format,
        "target_os": target_os,
        "target_arch": normalize_target_arch(target_arch),
        "git_branch": branch,
        "git_commit_sha": commit_sha,
        "git_dirty": dirty,
        "runner_class": runner_class,
        "official_release": is_official,
        "build_timestamp": build_ts,
        "build_host": build_host,
        "python_version": py_ver,
        "pyinstaller_version": pyinstaller_ver,
        "uv_version": uv_ver,
        "spec_files": spec_files,
        "artifacts": artifact_entries,
        "warnings": warnings,
        "errors": errors,
        "signing": {
            "method": "none",
            "status": "unavailable",
            "notes": "Code signing not yet implemented — placeholder for future",
        },
        "evidence": {
            "manifest_sha256": "",
            "checksums_path": "",
            "evidence_jsonl_path": "",
        },
        "telemetry_redaction_notes": (
            "No raw prompts, secrets, credentials, or private files "
            "are emitted in this manifest. All content-derived data "
            "uses SHA-256 hashes."
        ),
    }

    return manifest


def _create_dryrun_placeholder(
    bundle_id: str, build_ts: str, branch: str, commit_sha: str
) -> Path:
    output_dir = (
        Path(__file__).resolve().parent.parent / ".build" / "rig-relay" / "release"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    placeholder = output_dir / "dryrun_placeholder.txt"
    content = (
        f"bundle_id: {bundle_id}\n"
        f"build_timestamp: {build_ts}\n"
        f"branch: {branch}\n"
        f"commit_sha: {commit_sha}\n"
        f"note: Dry-run placeholder — no actual PyInstaller build was performed.\n"
    )
    placeholder.write_text(content)
    return placeholder


def _sha256_dir(dirpath: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(dirpath.rglob("*")):
        if f.is_file() and not f.is_symlink():
            if is_confidential_artifact_path(f, REPO_ROOT):
                continue
            h.update(str(f.relative_to(dirpath)).encode())
            h.update(sha256_file(f).encode())
    return h.hexdigest()


def _make_bundle_id(
    branch: str,
    commit_sha: str,
    target_os: str,
    target_arch: str,
    spec_files: list[str],
) -> str:
    short_sha_len = 8
    short_sha = (
        commit_sha[:short_sha_len] if len(commit_sha) >= short_sha_len else commit_sha
    )
    label = spec_files[0].replace(".spec", "") if spec_files else "rig-relay"
    return f"{label}-{target_os}-{target_arch}-{short_sha}"


def write_manifest(manifest: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "release_bundle_manifest.v1.json"
    content = json.dumps(manifest, indent=2, ensure_ascii=False)
    path.write_text(content)
    manifest["evidence"]["manifest_sha256"] = sha256_bytes(content.encode())
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return path


def write_checksums(manifest: dict, output_dir: Path) -> Path:
    path = output_dir / "SHA256SUMS"
    lines: list[str] = []
    for artifact in manifest["artifacts"]:
        if artifact["kind"] == "bundle_dir":
            continue
        if is_confidential_artifact_path(artifact["path"], REPO_ROOT):
            continue
        fname = Path(artifact["path"]).name
        lines.append(f"{artifact['sha256']}  {fname}")
    path.write_text("\n".join(lines) + "\n")
    manifest["evidence"]["checksums_path"] = str(path)
    return path


def write_evidence_jsonl(manifest: dict, output_dir: Path) -> Path:
    path = output_dir / "release_evidence.v1.jsonl"
    entry = {
        "event_type": "rig.relay.release.bundle_built",
        "timestamp": manifest["build_timestamp"],
        "bundle_id": manifest["bundle_id"],
        "sha256": manifest["evidence"]["manifest_sha256"],
        "runner_class": manifest["runner_class"],
        "official_release": manifest["official_release"],
    }
    path.write_text(json.dumps(entry, ensure_ascii=False) + "\n")
    manifest["evidence"]["evidence_jsonl_path"] = str(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Canonical release packaging entrypoint for Rig Relay."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip PyInstaller build, still produce manifest and evidence.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".build/rig-relay/release/"),
        help="Directory to write manifest, checksums, and evidence (default: .build/rig-relay/release/).",
    )
    parser.add_argument(
        "--spec",
        dest="spec_files",
        action="append",
        default=None,
        help="PyInstaller spec file(s) to build. May be repeated. Default: rig-relay-acp.spec",
    )
    parser.add_argument(
        "--target-os",
        default=None,
        choices=["darwin", "linux", "windows"],
        help="Override target OS (default: detected from platform).",
    )
    parser.add_argument(
        "--target-arch",
        default=None,
        choices=["arm64", "amd64", "x86"],
        help="Override target architecture (default: detected from platform).",
    )
    parser.add_argument(
        "--bundle-name",
        default="Rig Relay",
        help="Human-readable bundle name (default: 'Rig Relay').",
    )
    args = parser.parse_args()

    spec_files = (
        args.spec_files if args.spec_files is not None else ["rig-relay-acp.spec"]
    )
    target_os = args.target_os if args.target_os is not None else detect_target_os()
    target_arch = (
        args.target_arch if args.target_arch is not None else detect_target_arch()
    )
    output_dir = args.output_dir.resolve()

    print("Rig Relay — Release Bundler v1")
    print(f"  Target OS:   {target_os}")
    print(f"  Target Arch: {target_arch}")
    print(f"  Output Dir:  {output_dir}")
    print(f"  Spec Files:  {', '.join(spec_files)}")
    print(f"  Dry Run:     {args.dry_run}")
    print()

    branch, commit_sha, dirty = get_git_info()
    runner_class = detect_runner_class()
    print(f"  Branch:      {branch}")
    print(f"  Commit:      {commit_sha}")
    print(f"  Dirty:       {dirty}")
    print(f"  Runner:      {runner_class}")
    print()

    if runner_class == "codespaces_lab":
        print("  Warning: codespaces_lab — official_release will be forced to false.")
        print()

    manifest = build_manifest_entrypoint(
        target_os=target_os,
        spec_files=spec_files,
        dry_run=args.dry_run,
        target_arch=target_arch,
        bundle_name=args.bundle_name,
    )

    manifest["evidence"]["checksums_path"] = str(output_dir / "SHA256SUMS")
    manifest["evidence"]["evidence_jsonl_path"] = str(
        output_dir / "release_evidence.v1.jsonl"
    )

    manifest_path = write_manifest(manifest, output_dir)
    checksums_path = write_checksums(manifest, output_dir)
    evidence_path = write_evidence_jsonl(manifest, output_dir)

    print("Build complete.")
    print()
    print(f"  Manifest:  {manifest_path}")
    print(f"  Checksums: {checksums_path}")
    print(f"  Evidence:  {evidence_path}")
    print(f"  Bundle ID: {manifest['bundle_id']}")
    print(f"  Artifacts: {len(manifest['artifacts'])}")
    for a in manifest["artifacts"]:
        marker = " [DIR]" if a["kind"] == "bundle_dir" else ""
        print(f"    [{a['kind']}]{marker} {a['path']}  ({a['size_bytes']} bytes)")
    if manifest["warnings"]:
        print(f"  Warnings:  {len(manifest['warnings'])}")
        for w in manifest["warnings"]:
            print(f"    - {w}")
    if manifest["errors"]:
        print(f"  Errors:    {len(manifest['errors'])}")
        for e in manifest["errors"]:
            print(f"    - {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

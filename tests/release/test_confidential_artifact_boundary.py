from __future__ import annotations

from pathlib import Path

import pytest

from scripts.package_release import BuildResult, build_manifest_entrypoint


@pytest.mark.integration
@pytest.mark.sabotage
def test_build_manifest_entrypoint_excludes_confidential_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public_artifact = tmp_path / "public.txt"
    public_artifact.write_text("public", encoding="utf-8")

    confidential_artifact = (
        tmp_path / ".build" / "rig-relay" / "confidential" / "secret.txt"
    )
    confidential_artifact.parent.mkdir(parents=True)
    confidential_artifact.write_text("secret", encoding="utf-8")

    def fake_build_with_pyinstaller(_spec_file: str) -> BuildResult:
        return BuildResult(
            success=True,
            artifacts=[
                ("data_file", public_artifact, public_artifact.stat().st_size),
                (
                    "data_file",
                    confidential_artifact,
                    confidential_artifact.stat().st_size,
                ),
            ],
        )

    def fake_sha256_file(path: Path) -> str:
        if "confidential" in str(path):
            raise AssertionError("confidential artifacts must not be hashed")
        return "a" * 64

    monkeypatch.setattr(
        "scripts.package_release.build_with_pyinstaller", fake_build_with_pyinstaller
    )
    monkeypatch.setattr("scripts.package_release.sha256_file", fake_sha256_file)
    monkeypatch.setattr(
        "scripts.package_release.get_git_info",
        lambda: ("feature/confidential", "a" * 40, False),
    )
    monkeypatch.setattr("scripts.package_release.get_pyinstaller_version", lambda: "6")
    monkeypatch.setattr("scripts.package_release.get_uv_version", lambda: "0.8")
    monkeypatch.setattr(
        "scripts.package_release.detect_runner_class", lambda: "local"
    )

    manifest = build_manifest_entrypoint(
        target_os="linux",
        spec_files=["demo.spec"],
        dry_run=False,
        target_arch="amd64",
        bundle_name="Rig Relay",
    )

    artifact_paths = [artifact["path"] for artifact in manifest["artifacts"]]
    assert artifact_paths == [str(public_artifact).replace("\\", "/")]
    assert all("confidential" not in path for path in artifact_paths)

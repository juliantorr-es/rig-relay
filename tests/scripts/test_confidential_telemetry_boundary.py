from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from rig_relay.core.paths import filter_exportable_artifact_paths
from scripts.rig_relay_contribute_telemetry_bundle import contribute_bundle
from scripts.rig_relay_create_telemetry_bundle import create_bundle
from scripts.rig_relay_upload_google_drive import upload_bundle

pytestmark = [pytest.mark.integration, pytest.mark.sabotage]


def test_create_bundle_refuses_confidential_derived_dir_before_body_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    derived_dir = tmp_path / ".build" / "rig-relay" / "confidential"
    reports_dir = tmp_path / "reports"
    output_dir = tmp_path / "out"
    derived_dir.mkdir(parents=True)
    reports_dir.mkdir()

    def fail(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("body-read helper must not run for confidential roots")

    monkeypatch.setattr(
        "scripts.rig_relay_create_telemetry_bundle._count_jsonl_rows", fail
    )
    monkeypatch.setattr(
        "scripts.rig_relay_create_telemetry_bundle._count_json_rows", fail
    )
    monkeypatch.setattr("scripts.rig_relay_create_telemetry_bundle._sha256_file", fail)

    with pytest.raises(ValueError, match="confidential_artifact_refused"):
        create_bundle(
            participant_id="anon_test_001",
            share_level="derived_only",
            derived_dir=derived_dir,
            reports_dir=reports_dir,
            output_dir=output_dir,
            dry_run=False,
        )


def test_upload_bundle_refuses_confidential_bundle_before_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path = tmp_path / ".build" / "rig-relay" / "confidential" / "bundle.zip"

    def fail(_path: Path) -> str:
        raise AssertionError("_sha256_file must not run for confidential bundles")

    monkeypatch.setattr("scripts.rig_relay_upload_google_drive._sha256_file", fail)

    receipt = upload_bundle(
        bundle_path=bundle_path,
        folder_id="folder-123",
        participant_id="anon_test_001",
        share_level="derived_only",
        dry_run=True,
        confirm=False,
    )

    assert receipt["status"] == "failed"
    assert receipt["upload_method"] == "dry_run"
    assert receipt["warnings"] == ["confidential_artifact_refused:google_drive_upload_bundle"]


def test_contribute_bundle_refuses_confidential_bundle_before_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path = tmp_path / ".build" / "rig-relay" / "confidential" / "bundle.zip"

    def fail(*_args: object, **_kwargs: object) -> tuple[bool, list[str]]:
        raise AssertionError("validate_bundle must not run for confidential bundles")

    monkeypatch.setattr(
        "scripts.rig_relay_contribute_telemetry_bundle.validate_bundle", fail
    )

    result = contribute_bundle(
        bundle_path=bundle_path,
        folder_id="folder-123",
        participant_id="anon_test_001",
        share_level="derived_only",
        state_root=tmp_path / "state",
        dry_run=True,
        confirm=False,
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "confidential_artifact_refused:telemetry_contribution_bundle"
    assert result["steps"]["validate_bundle"]["status"] == "refused"


@pytest.mark.e2e
def test_end_to_end_public_tree_excludes_confidential_subtree(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    build_root = repo_root / ".build" / "rig-relay"
    derived_dir = build_root / "derived"
    reports_dir = build_root / "reports"
    confidential_dir = build_root / "confidential"
    output_dir = build_root / "telemetry-bundles"
    state_root = tmp_path / "state"

    derived_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    confidential_dir.mkdir(parents=True)
    state_root.mkdir(parents=True)

    public_derived = derived_dir / "public.jsonl"
    public_derived.write_text('{"event":"public"}\n', encoding="utf-8")
    public_report = reports_dir / "public.md"
    public_report.write_text("# Public\n", encoding="utf-8")
    confidential_leaf = confidential_dir / "secret.jsonl"
    confidential_leaf.write_text('{"event":"secret"}\n', encoding="utf-8")

    eligible_roots = filter_exportable_artifact_paths(
        [derived_dir, reports_dir, confidential_dir], repo_root
    )
    assert eligible_roots == [derived_dir, reports_dir]

    manifest = create_bundle(
        participant_id="anon_test_001",
        share_level="derived_only",
        derived_dir=eligible_roots[0],
        reports_dir=eligible_roots[1],
        output_dir=output_dir,
        state_root=state_root,
        dry_run=False,
    )

    bundle_path = output_dir / f"{manifest['bundle_id']}.zip"
    assert bundle_path.is_file()

    with zipfile.ZipFile(bundle_path, "r") as zf:
        names = set(zf.namelist())

    assert names == {
        "derived/public.jsonl",
        "reports/public.md",
        "telemetry_bundle_manifest.json",
    }
    assert all("confidential" not in name for name in names)

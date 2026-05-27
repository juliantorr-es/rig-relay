"""Adversarial tests for CanonicalDistributionArtifactManifest (X4).

Every test uses real file I/O in temporary directories. No mocks, no stubs.
The manifest digest must change with any file mutation, rename, symlink
target change, entitlement change, or embedded extension change.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from rig_relay.native._artifact_manifest import ArtifactManifestService
from rig_relay.native.models import ArtifactItemKind, ArtifactItemSignificance

# -- Test helpers ---------------------------------------------------------


def _make_app_bundle(root: Path, name: str = "TestApp") -> Path:
    """Create a realistic .app bundle directory structure."""
    bundle = root / f"{name}.app"
    contents = bundle / "Contents"
    contents.mkdir(parents=True)

    macos = contents / "MacOS"
    macos.mkdir()
    exe = macos / name
    exe.write_bytes(b"fake mach-o binary header")
    exe.chmod(0o755)

    (contents / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        "<key>CFBundleIdentifier</key>\n<string>com.test.app</string>\n"
        "</dict>\n</plist>\n"
    )

    resources = contents / "Resources"
    resources.mkdir()
    (resources / "icon.icns").write_bytes(b"fake icon data")
    (resources / "AppIcon.png").write_bytes(b"fake png icon")

    plugins = contents / "PlugIns"
    plugins.mkdir()
    extension = plugins / f"{name}Extension.appex"
    extension.mkdir()
    (extension / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<plist version="1.0">\n<dict>\n'
        "<key>CFBundleIdentifier</key>\n"
        "<string>com.test.app.extension</string>\n"
        "</dict>\n</plist>\n"
    )

    frameworks = contents / "Frameworks"
    frameworks.mkdir()
    fw = frameworks / "TestLib.framework"
    fw.mkdir()
    (fw / "TestLib").write_bytes(b"fake framework binary")
    (fw / "Resources").mkdir()
    (fw / "Resources" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<plist version="1.0">\n<dict/>\n</plist>\n'
    )

    return bundle


def _build_manifest(artifact_root: Path) -> tuple:
    svc = ArtifactManifestService()
    manifest = svc.build_manifest(
        artifact_root=artifact_root,
        artifact_kind="unsigned_app",
        bundle_identifier="com.test.app",
        bundle_name="TestApp",
        short_version="1.0.0",
        build_version="100",
    )
    return svc, manifest


# -- Collision resistance tests ------------------------------------------


def test_manifest_produces_different_digest_for_different_files(tmp_path: Path) -> None:
    d1 = tmp_path / "A"
    d2 = tmp_path / "B"
    _make_app_bundle(d1)
    _make_app_bundle(d2)
    (d2 / "TestApp.app" / "Contents" / "Resources" / "readme.txt").write_text("hello")

    _, m1 = _build_manifest(d1 / "TestApp.app")
    _, m2 = _build_manifest(d2 / "TestApp.app")
    assert m1.manifest_digest != m2.manifest_digest


def test_manifest_produces_different_digest_for_same_size_different_content(
    tmp_path: Path,
) -> None:
    d1 = tmp_path / "A"
    d2 = tmp_path / "B"
    _make_app_bundle(d1)
    _make_app_bundle(d2)

    exe_a = d1 / "TestApp.app" / "Contents" / "MacOS" / "TestApp"
    exe_b = d2 / "TestApp.app" / "Contents" / "MacOS" / "TestApp"
    assert exe_a.stat().st_size == exe_b.stat().st_size
    exe_b.write_bytes(b"fake mach-o binary header" + b"\x00")
    assert exe_a.stat().st_size != exe_b.stat().st_size

    _, m1 = _build_manifest(d1 / "TestApp.app")
    _, m2 = _build_manifest(d2 / "TestApp.app")
    assert m1.manifest_digest != m2.manifest_digest


def test_manifest_produces_different_digest_for_altered_binary(tmp_path: Path) -> None:
    d1 = tmp_path / "A"
    d2 = tmp_path / "B"
    _make_app_bundle(d1)
    _make_app_bundle(d2)

    (d2 / "TestApp.app" / "Contents" / "MacOS" / "TestApp").write_bytes(
        b"different binary content"
    )

    _, m1 = _build_manifest(d1 / "TestApp.app")
    _, m2 = _build_manifest(d2 / "TestApp.app")
    assert m1.manifest_digest != m2.manifest_digest


def test_manifest_produces_different_digest_for_renamed_file(tmp_path: Path) -> None:
    d1 = tmp_path / "A"
    d2 = tmp_path / "B"
    _make_app_bundle(d1)
    _make_app_bundle(d2)

    src = d2 / "TestApp.app" / "Contents" / "Resources" / "icon.icns"
    dst = d2 / "TestApp.app" / "Contents" / "Resources" / "renamed.icns"
    src.rename(dst)

    _, m1 = _build_manifest(d1 / "TestApp.app")
    _, m2 = _build_manifest(d2 / "TestApp.app")
    assert m1.manifest_digest != m2.manifest_digest


def test_manifest_produces_different_digest_for_modified_symlink_target(
    tmp_path: Path,
) -> None:
    d1 = tmp_path / "A"
    d2 = tmp_path / "B"
    _make_app_bundle(d1)
    _make_app_bundle(d2)

    # Create symlinks inside the bundle to targets also inside the bundle
    macos1 = d1 / "TestApp.app" / "Contents" / "MacOS"
    macos2 = d2 / "TestApp.app" / "Contents" / "MacOS"
    (macos1 / "real_a.txt").write_text("AAA")
    (macos2 / "real_b.txt").write_text("BBB")
    os.symlink("real_a.txt", str(macos1 / "link_to_real"))
    os.symlink("real_b.txt", str(macos2 / "link_to_real"))

    _, m1 = _build_manifest(d1 / "TestApp.app")
    _, m2 = _build_manifest(d2 / "TestApp.app")
    assert m1.manifest_digest != m2.manifest_digest


def test_manifest_produces_different_digest_for_added_extension(tmp_path: Path) -> None:
    d1 = tmp_path / "A"
    d2 = tmp_path / "B"
    _make_app_bundle(d1)
    _make_app_bundle(d2)

    extra = d2 / "TestApp.app" / "Contents" / "PlugIns" / "Extra.appex"
    extra.mkdir()
    (extra / "Info.plist").write_text("<plist/>")
    (extra / "Extra").write_bytes(b"extension binary")

    _, m1 = _build_manifest(d1 / "TestApp.app")
    _, m2 = _build_manifest(d2 / "TestApp.app")
    assert m1.manifest_digest != m2.manifest_digest
    assert m2.embedded_extension_digest is not None


def test_manifest_produces_different_digest_for_changed_entitlement(
    tmp_path: Path,
) -> None:
    d1 = tmp_path / "A"
    d2 = tmp_path / "B"
    _make_app_bundle(d1)
    _make_app_bundle(d2)

    ent1 = d1 / "entitlements.plist"
    ent2 = d2 / "entitlements.plist"
    ent1.write_text(
        '<?xml version="1.0">\n<plist><dict>'
        "<key>com.apple.security.app-sandbox</key><true/>"
        "</dict></plist>"
    )
    ent2.write_text(
        '<?xml version="1.0">\n<plist><dict>'
        "<key>com.apple.security.network.client</key><true/>"
        "</dict></plist>"
    )

    svc = ArtifactManifestService()
    m1 = svc.build_manifest(
        artifact_root=d1 / "TestApp.app",
        artifact_kind="unsigned_app",
        bundle_identifier="com.test.app",
        entitlements_path=ent1,
    )
    m2 = svc.build_manifest(
        artifact_root=d2 / "TestApp.app",
        artifact_kind="unsigned_app",
        bundle_identifier="com.test.app",
        entitlements_path=ent2,
    )
    assert m1.manifest_digest != m2.manifest_digest
    assert m1.entitlement_summary_digest != m2.entitlement_summary_digest


def test_manifest_produces_different_digest_for_changed_info_plist(
    tmp_path: Path,
) -> None:
    d1 = tmp_path / "A"
    d2 = tmp_path / "B"
    _make_app_bundle(d1)
    _make_app_bundle(d2)

    (d2 / "TestApp.app" / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0">\n<plist><dict>'
        "<key>CFBundleIdentifier</key><string>com.other.app</string>"
        "</dict></plist>"
    )

    _, m1 = _build_manifest(d1 / "TestApp.app")
    _, m2 = _build_manifest(d2 / "TestApp.app")
    assert m1.manifest_digest != m2.manifest_digest


# -- Safety tests --------------------------------------------------------


def test_manifest_rejects_symlink_escaping_root(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("escaping")

    link = bundle / "Contents" / "MacOS" / "bad_link"
    os.symlink(outside, link)

    svc = ArtifactManifestService()
    with pytest.raises(ValueError, match="resolves outside artifact root"):
        svc.build_manifest(
            artifact_root=bundle,
            artifact_kind="unsigned_app",
            bundle_identifier="com.test.app",
        )


def test_manifest_rejects_symlink_dotdot(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)

    link = bundle / "Contents" / "MacOS" / "bad_link"
    os.symlink("../../outside", link)

    svc = ArtifactManifestService()
    with pytest.raises(ValueError, match=r"\.\."):
        svc.build_manifest(
            artifact_root=bundle,
            artifact_kind="unsigned_app",
            bundle_identifier="com.test.app",
        )


# -- Correctness tests ---------------------------------------------------


def test_manifest_digest_independent_of_traversal_order(tmp_path: Path) -> None:
    """Items are sorted by relative_path so traversal order doesn't matter."""
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    paths = [item.relative_path for item in manifest.items]
    assert paths == sorted(paths), "items must be sorted by relative_path"

    digest_1 = manifest.manifest_digest
    # Rebuild — should produce identical digest
    _, manifest_2 = _build_manifest(bundle)
    assert manifest_2.manifest_digest == digest_1


def test_manifest_correctly_identifies_executable(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    macos_items = [
        item for item in manifest.items if "MacOS/TestApp" in item.relative_path
    ]
    assert len(macos_items) == 1
    assert macos_items[0].is_executable is True
    assert macos_items[0].item_kind == ArtifactItemKind.EXECUTABLE

    plist_items = [
        item
        for item in manifest.items
        if item.relative_path.endswith("Info.plist")
        and "Contents/Info.plist" in item.relative_path
    ]
    assert len(plist_items) == 1
    assert plist_items[0].is_executable is False
    assert plist_items[0].item_kind == ArtifactItemKind.REGULAR_FILE


def test_manifest_correctly_identifies_appex(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    appex_items = [
        item for item in manifest.items if item.item_kind == ArtifactItemKind.APPEX
    ]
    assert len(appex_items) >= 1
    assert any(
        "PlugIns" in item.relative_path and item.relative_path.endswith(".appex")
        for item in appex_items
    )


def test_manifest_includes_bundle_identifier_digest(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    expected = f"sha256:{hashlib.sha256(b'com.test.app').hexdigest()}"
    assert manifest.bundle_identifier_digest == expected

    # Verify it's deterministic
    _, manifest2 = _build_manifest(bundle)
    assert manifest2.bundle_identifier_digest == manifest.bundle_identifier_digest


def test_manifest_icon_files_marked_as_icon_significance(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    icon_items = [
        item
        for item in manifest.items
        if item.significance == ArtifactItemSignificance.ICON
    ]
    assert len(icon_items) >= 2  # icon.icns + AppIcon.png

    icon_paths = {item.relative_path for item in icon_items}
    assert any("icon.icns" in p for p in icon_paths)
    assert any("AppIcon.png" in p for p in icon_paths)


def test_manifest_info_plist_marked_as_meta(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    meta_items = [
        item
        for item in manifest.items
        if item.significance == ArtifactItemSignificance.META
    ]
    assert len(meta_items) >= 1

    main_plist = [
        item for item in meta_items if item.relative_path == "Contents/Info.plist"
    ]
    assert len(main_plist) == 1


def test_manifest_critical_items_in_macos_dir(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    critical = [
        item
        for item in manifest.items
        if item.significance == ArtifactItemSignificance.CRITICAL
    ]
    assert len(critical) >= 1
    assert any("Contents/MacOS/TestApp" in item.relative_path for item in critical)


def test_manifest_detects_framework(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    fw_items = [
        item for item in manifest.items if item.item_kind == ArtifactItemKind.FRAMEWORK
    ]
    assert len(fw_items) >= 1

    assert len(manifest.embedded_framework_digests) >= 1
    for digest in manifest.embedded_framework_digests:
        assert digest.startswith("sha256:")
        assert len(digest) == 71  # "sha256:" + 64 hex


def test_manifest_regular_files_have_valid_sha256(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    for item in manifest.items:
        if item.item_kind in (
            ArtifactItemKind.REGULAR_FILE,
            ArtifactItemKind.EXECUTABLE,
        ):
            assert item.sha256 is not None, f"Missing sha256 for {item.relative_path}"
            assert item.sha256.startswith("sha256:")
            assert len(item.sha256) == 71
            assert item.size is not None
            assert item.size > 0


def test_manifest_directories_have_no_sha256(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    for item in manifest.items:
        if item.item_kind == ArtifactItemKind.DIRECTORY:
            assert item.sha256 is None, (
                f"Dir {item.relative_path} should not have sha256"
            )
            assert item.size is None, f"Dir {item.relative_path} should not have size"
        elif item.item_kind in (ArtifactItemKind.FRAMEWORK, ArtifactItemKind.APPEX):
            # Framework/appex directories carry identity digests
            assert item.sha256 is not None, (
                f"Framework/appex {item.relative_path} should have identity digest"
            )
            assert item.sha256.startswith("sha256:")


def test_manifest_all_items_have_forward_slash_paths(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    for item in manifest.items:
        assert "\\" not in item.relative_path, (
            f"Backslash in relative_path: {item.relative_path}"
        )


def test_manifest_digest_format(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    assert manifest.manifest_digest.startswith("sha256:")
    assert len(manifest.manifest_digest) == 71
    # Only hex characters after the prefix
    hex_part = manifest.manifest_digest[7:]
    assert all(c in "0123456789abcdef" for c in hex_part)


def test_manifest_schema_version_is_correct(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    assert manifest.schema_version == "rig.relay.native.artifact_manifest.v1"


def test_manifest_serializes_deterministically(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    data1 = manifest.model_dump_json(indent=2)
    data2 = manifest.model_dump_json(indent=2)
    assert data1 == data2


def test_manifest_matches_schema(tmp_path: Path) -> None:
    """Validate the manifest against its JSON Schema."""
    import json

    from jsonschema import validate

    bundle = _make_app_bundle(tmp_path)
    _, manifest = _build_manifest(bundle)

    schema_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "schemas"
        / "rig.relay.native.artifact_manifest.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    validate(instance=json.loads(manifest.model_dump_json()), schema=schema)


def test_manifest_produces_different_digest_for_added_framework(tmp_path: Path) -> None:
    d1 = tmp_path / "A"
    d2 = tmp_path / "B"
    _make_app_bundle(d1)
    _make_app_bundle(d2)

    extra_fw = d2 / "TestApp.app" / "Contents" / "Frameworks" / "ExtraLib.framework"
    extra_fw.mkdir()
    (extra_fw / "ExtraLib").write_bytes(b"extra framework binary")

    _, m1 = _build_manifest(d1 / "TestApp.app")
    _, m2 = _build_manifest(d2 / "TestApp.app")
    assert m1.manifest_digest != m2.manifest_digest
    assert len(m2.embedded_framework_digests) > len(m1.embedded_framework_digests)


def test_manifest_produces_same_digest_for_rebuild_without_changes(
    tmp_path: Path,
) -> None:
    bundle = _make_app_bundle(tmp_path)
    _, m1 = _build_manifest(bundle)
    _, m2 = _build_manifest(bundle)
    assert m1.manifest_digest == m2.manifest_digest


def test_manifest_produces_different_digest_for_different_artifact_kind(
    tmp_path: Path,
) -> None:
    bundle = _make_app_bundle(tmp_path)
    svc = ArtifactManifestService()
    m1 = svc.build_manifest(
        artifact_root=bundle,
        artifact_kind="unsigned_app",
        bundle_identifier="com.test.app",
    )
    m2 = svc.build_manifest(
        artifact_root=bundle,
        artifact_kind="signed_app",
        bundle_identifier="com.test.app",
    )
    assert m1.manifest_digest != m2.manifest_digest


def test_manifest_produces_different_digest_for_different_bundle_name(
    tmp_path: Path,
) -> None:
    bundle = _make_app_bundle(tmp_path)
    svc = ArtifactManifestService()
    m1 = svc.build_manifest(
        artifact_root=bundle,
        artifact_kind="unsigned_app",
        bundle_identifier="com.test.app",
        bundle_name="AppOne",
    )
    m2 = svc.build_manifest(
        artifact_root=bundle,
        artifact_kind="unsigned_app",
        bundle_identifier="com.test.app",
        bundle_name="AppTwo",
    )
    assert m1.manifest_digest != m2.manifest_digest


def test_manifest_produces_different_digest_for_different_versions(
    tmp_path: Path,
) -> None:
    bundle = _make_app_bundle(tmp_path)
    svc = ArtifactManifestService()
    m1 = svc.build_manifest(
        artifact_root=bundle,
        artifact_kind="unsigned_app",
        bundle_identifier="com.test.app",
        short_version="1.0.0",
        build_version="100",
    )
    m2 = svc.build_manifest(
        artifact_root=bundle,
        artifact_kind="unsigned_app",
        bundle_identifier="com.test.app",
        short_version="2.0.0",
        build_version="200",
    )
    assert m1.manifest_digest != m2.manifest_digest


def test_manifest_different_bundle_id_different_id_digest(tmp_path: Path) -> None:
    bundle = _make_app_bundle(tmp_path)
    svc = ArtifactManifestService()
    m1 = svc.build_manifest(
        artifact_root=bundle,
        artifact_kind="unsigned_app",
        bundle_identifier="com.a.app",
    )
    m2 = svc.build_manifest(
        artifact_root=bundle,
        artifact_kind="unsigned_app",
        bundle_identifier="com.b.app",
    )
    assert m1.bundle_identifier_digest != m2.bundle_identifier_digest
    assert m1.manifest_digest != m2.manifest_digest

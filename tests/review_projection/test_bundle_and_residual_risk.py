from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

from rig_relay.review_projection.bundle_builder import BundleBuilder
from rig_relay.review_projection.models import (
    BundleManifest,
    DisclosureReceipt,
    LocalCrosswalk,
    ProjectionMode,
)
from rig_relay.review_projection.residual_scanner import ResidualRiskScanner


def test_deterministic_zip_and_separation():
    with TemporaryDirectory() as td:
        output_dir = Path(td)
        builder = BundleBuilder(output_dir)

        manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
        crosswalk = LocalCrosswalk(projection_id="proj_1")
        crosswalk.mappings["MySecretClass"] = "C_0001"
        receipt = DisclosureReceipt(
            projection_id="proj_1",
            mode=ProjectionMode.MAINTAINABILITY_REVIEW,
            created_at="now",
            source_root_fingerprint="fp",
            branch="main",
            head_sha="sha",
            public_baseline_status="none",
            policy_version="1.0",
            input_file_count=1,
            classification_counts={},
            included_path_hashes=[],
            excluded_path_hashes={},
            applied_rules=[],
            crosswalk_hash="",
            residual_scan_result="passed",
            output_status="candidate_generated",
        )

        files = {"src.py": "def foo(): pass"}
        builder.write_bundle("proj_1", files, manifest, crosswalk, receipt)

        zip_path = output_dir / "review_projection_proj_1.zip"
        assert zip_path.is_file()

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert "src.py" in names
            assert "bundle_manifest.json" in names
            # Assert separation!
            assert not any("crosswalk" in n for n in names)
            assert not any("receipt" in n for n in names)

        # Assert local-only artifacts exist outside zip
        assert (output_dir / "crosswalk_proj_1.json").is_file()
        assert (output_dir / "receipt_proj_1.json").is_file()

        # Test determinism
        with zipfile.ZipFile(zip_path, "r") as zf:
            zinfo = zf.getinfo("src.py")
            assert zinfo.date_time == (2026, 1, 1, 0, 0, 0)

        hash1 = receipt.candidate_zip_sha256

        # Build again
        builder2 = BundleBuilder(output_dir)
        crosswalk2 = LocalCrosswalk(projection_id="proj_1")
        crosswalk2.mappings["MySecretClass"] = "C_0001"
        receipt2 = receipt.model_copy()
        manifest2 = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
        files2 = {"src.py": "def foo(): pass"}

        builder2.write_bundle("proj_1_2", files2, manifest2, crosswalk2, receipt2)
        assert receipt2.candidate_zip_sha256 == hash1


def test_residual_risk_scanner_semantic_leak():
    mapping = {"SecretAlgo": "C_0001"}
    scanner = ResidualRiskScanner(mapping, "/my/repo")

    # 1. Safe source
    safe_src = "class C_0001: pass"
    assert scanner.scan(safe_src) is None

    # 2. Semantic leak (original symbol appears in string literal somehow bypassed or added)
    leaked_src = "class C_0001:\n  name = 'SecretAlgo'"
    res = scanner.scan(leaked_src)
    assert "Semantic leakage" in res
    assert "SecretAlgo" in res

    # 3. Absolute path leak
    path_leak = "path = '/my/repo/src/main.py'"
    assert "unredacted local absolute path" in scanner.scan(path_leak)

    # 4. Secret leak
    key_leak = "api_key = 'sk-12345678901234567890123456789012'"
    assert "secret or key-like" in scanner.scan(key_leak)


def test_zip_deep_determinism():
    """Deep debug: compare two DiffBundler builds byte-for-byte to find ZIP non-determinism."""
    import hashlib
    import json
    import os

    from git import Repo

    from rig_relay.review_projection.diff_bundler import (
        DiffBundler,
        _derive_projection_id,
    )
    from rig_relay.review_projection.provenance import ProjectionSnapshot

    def _init_temp_repo(tmp_path):
        repo = Repo.init(str(tmp_path))
        repo.git.config("user.name", "test")
        repo.git.config("user.email", "test@test.test")
        src = tmp_path / "src.py"
        src.write_text(
            "import os\n\n"
            'STATUS_OK = "completed"\n'
            'STATUS_FAIL = "failed"\n\n'
            "def public_api(value: str) -> str:\n"
            "    result = value.strip()\n"
            "    return result\n\n"
            "def _private_helper(x: int) -> int:\n"
            "    local_result = x * 2\n"
            "    return local_result\n\n"
            "class PublicClass:\n"
            "    def public_method(self, arg1: str) -> str:\n"
            "        return arg1.upper()\n\n"
            "    def _private_method(self, secret_input: str) -> str:\n"
            "        return secret_input[::-1]\n"
        )
        repo.index.add(["src.py"])
        repo.index.commit("baseline")
        schema_dir = tmp_path / "docs" / "schemas"
        schema_dir.mkdir(parents=True, exist_ok=True)
        (schema_dir / "test_schema.json").write_text(
            json.dumps(
                {
                    "schema_version": "test.v1",
                    "properties": {"status": {"enum": ["completed", "failed"]}},
                },
                indent=2,
            )
        )
        repo.index.add(["docs/schemas/test_schema.json"])
        repo.index.commit("add schema")
        toml_file = tmp_path / "pyproject.toml"
        toml_file.write_text('[project]\nname = "test"\nversion = "0.1.0"\n')
        repo.index.add(["pyproject.toml"])
        repo.index.commit("add toml")
        return repo

    with TemporaryDirectory() as td:
        tmp_path = Path(td)
        repo = _init_temp_repo(tmp_path)

        src = tmp_path / "src.py"
        original = src.read_text()
        modified = original.replace("return result", "return result.upper()")
        src.write_text(modified)

        toml_file = tmp_path / "pyproject.toml"
        toml_file.write_text('[project]\nname = "test-updated"\nversion = "0.2.0"\n')
        repo.index.add(["pyproject.toml"])
        os.rename(
            str(tmp_path / "pyproject.toml"), str(tmp_path / "pyproject_new.toml")
        )
        repo.index.add(["pyproject_new.toml"])
        repo.index.remove(["pyproject.toml"])
        (tmp_path / "docs/schemas/test_schema.json").unlink()
        repo.index.remove(["docs/schemas/test_schema.json"])
        untracked_schema = tmp_path / "docs" / "schemas" / "untracked_schema.json"
        untracked_schema.parent.mkdir(parents=True, exist_ok=True)
        untracked_schema.write_text(
            json.dumps(
                {
                    "schema_version": "untracked.v1",
                    "description": "An untracked schema",
                },
                indent=2,
            )
        )

        # Snapshot 1
        snap1 = ProjectionSnapshot(tmp_path)
        print("\n=== Snapshot 1 ===")
        print(f"HEAD: {snap1.head_sha}")
        print(f"Changed paths: {snap1.changed_path_names}")
        print(f"Untracked: {snap1.untracked_files}")
        print(f"Projection ID (derived): {_derive_projection_id(snap1)}")

        bundler1 = DiffBundler(tmp_path)
        result1 = bundler1.build()

        # Snapshot 2 — same state, no mutations
        snap2 = ProjectionSnapshot(tmp_path)
        print("\n=== Snapshot 2 ===")
        print(f"HEAD: {snap2.head_sha}")
        print(f"Changed paths: {snap2.changed_path_names}")
        print(f"Untracked: {snap2.untracked_files}")
        print(f"Projection ID (derived): {_derive_projection_id(snap2)}")

        bundler2 = DiffBundler(tmp_path)
        result2 = bundler2.build()

        print("\n=== ZIP Hashes ===")
        print(f"Build 1: {result1.zip_sha256}")
        print(f"Build 2: {result2.zip_sha256}")
        print(f"Same IDs? {result1.projection_id == result2.projection_id}")
        print(f"ID1: {result1.projection_id}")
        print(f"ID2: {result2.projection_id}")

        print("\n=== ZIP Content Comparison ===")
        with (
            zipfile.ZipFile(result1.zip_path, "r") as z1,
            zipfile.ZipFile(result2.zip_path, "r") as z2,
        ):
            names1 = sorted(z1.namelist())
            names2 = sorted(z2.namelist())
            print(f"Same names? {names1 == names2}")
            if names1 != names2:
                print(f"Only in 1: {set(names1) - set(names2)}")
                print(f"Only in 2: {set(names2) - set(names1)}")

            diffs_found = False
            for name in sorted(set(names1) | set(names2)):
                in1 = name in names1
                in2 = name in names2
                c1 = z1.read(name) if in1 else None
                c2 = z2.read(name) if in2 else None
                if not in1:
                    print(f"\nONLY IN 2: {name} (size {len(c2)})")
                    diffs_found = True
                elif not in2:
                    print(f"\nONLY IN 1: {name} (size {len(c1)})")
                    diffs_found = True
                elif c1 != c2:
                    print(f"\nDIFFER: {name} (sizes: {len(c1)} vs {len(c2)})")
                    h1 = hashlib.sha256(c1).hexdigest()
                    h2 = hashlib.sha256(c2).hexdigest()
                    print(f"  SHA256: {h1} vs {h2}")
                    diffs_found = True
                    if len(c1) < 2000:
                        t1 = c1.decode("utf-8", errors="replace")
                        t2 = c2.decode("utf-8", errors="replace")
                        if t1 != t2:
                            lines1 = t1.split("\n")
                            lines2 = t2.split("\n")
                            for i, (l1, l2) in enumerate(zip(lines1, lines2)):
                                if l1 != l2:
                                    print(f"  Line {i} differs:")
                                    print(f"    1: {l1!r}")
                                    print(f"    2: {l2!r}")
                                    break
                            if len(lines1) != len(lines2):
                                print(
                                    f"  Line count differs: {len(lines1)} vs {len(lines2)}"
                                )
                    else:
                        for i in range(min(len(c1), len(c2))):
                            if c1[i] != c2[i]:
                                print(
                                    f"  First diff at byte {i}: {c1[i]:02x} vs {c2[i]:02x}"
                                )
                                ctx_start = max(0, i - 20)
                                print(f"  Context 1: ...{c1[ctx_start : i + 20].hex()}")
                                print(f"  Context 2: ...{c2[ctx_start : i + 20].hex()}")
                                break
                        if len(c1) != len(c2):
                            print(f"  Length differs: {len(c1)} vs {len(c2)}")

            if not diffs_found:
                print("ALL FILES IDENTICAL — ZIP is deterministic")

        # The test assertion: ZIPs should be identical
        assert result1.zip_sha256 == result2.zip_sha256, (
            f"ZIP non-determinism detected!\n"
            f"Build 1: {result1.zip_sha256} (ID: {result1.projection_id})\n"
            f"Build 2: {result2.zip_sha256} (ID: {result2.projection_id})\n"
            f"Paths: {result1.zip_path} vs {result2.zip_path}"
        )

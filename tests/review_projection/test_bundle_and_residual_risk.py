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
            output_status="candidate_generated"
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

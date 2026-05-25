from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


def test_cli_refusal_on_live_dirty_without_manifest():
    # E2E test to ensure the CLI cannot just run on the repo root without a manifest
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "test.py").write_text("def a(): pass")

        # Test running CLI
        # We invoke the module directly since it's a script
        env = {"PYTHONPATH": str(Path(__file__).parent.parent.parent)}
        cmd = [
            sys.executable,
            "-m",
            "rig_relay.review_projection.cli",
            "project",
            "--repo-root",
            str(root),
        ]

        res = subprocess.run(cmd, env=env, capture_output=True, text=True)
        # Should fail missing --manifest
        assert res.returncode != 0
        assert "the following arguments are required: --manifest" in res.stderr


def test_cli_default_dry_run_and_candidate_emission():
    with TemporaryDirectory() as td:
        root = Path(td)
        src = root / "src.py"
        src.write_text("class InternalLogic:\n  pass")

        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps({
                "schema_version": "rig.review_projection.inclusion_manifest.v1",
                "mode": "maintainability_review",
                "approved_files": ["src.py"],
            })
        )

        env = {"PYTHONPATH": str(Path(__file__).parent.parent.parent)}

        # 1. Dry run (default)
        cmd_dry = [
            sys.executable,
            "-m",
            "rig_relay.review_projection.cli",
            "project",
            "--repo-root",
            str(root),
            "--manifest",
            str(manifest_path),
        ]
        res_dry = subprocess.run(cmd_dry, env=env, capture_output=True, text=True)
        assert res_dry.returncode == 0
        assert "Dry-run only" in res_dry.stdout

        # 2. Emit bundle
        cmd_emit = cmd_dry + ["--emit-candidate-bundle"]
        res_emit = subprocess.run(cmd_emit, env=env, capture_output=True, text=True)
        assert res_emit.returncode == 0
        assert "Candidate ZIP generated" in res_emit.stdout

        # 3. Verify inspect-only
        # Find the generated zip
        output_dir = root / ".build" / "rig-relay" / "review_projection"
        zips = list(output_dir.glob("*.zip"))
        assert len(zips) == 1

        cmd_verify = [
            sys.executable,
            "-m",
            "rig_relay.review_projection.cli",
            "verify",
            "--zip-path",
            str(zips[0]),
        ]
        res_verify = subprocess.run(cmd_verify, env=env, capture_output=True, text=True)
        assert res_verify.returncode == 0
        assert "Inspect-only ZIP verification successful" in res_verify.stdout

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

from rig_relay.site_renderer.loaders import validate_json_schema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """Fixture to isolate environment inputs and outputs using tmp_path."""
    # Clear sys.modules cache for the renderer script to force reloading globals
    for key in list(sys.modules.keys()):
        if "rig_site_render" in key:
            del sys.modules[key]

    # Copy the entire docs directory to tmp_path / "docs" to simulate repository root
    shutil.copytree(REPO_ROOT / "docs", tmp_path / "docs")

    input_dir = tmp_path / "docs" / "json" / "site"
    manifest_path = input_dir / "input_manifest.v1.json"
    output_dir = tmp_path / "outputs"

    monkeypatch.setenv("RIG_SITE_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("RIG_SITE_INPUT_DIR", str(input_dir))
    monkeypatch.setenv("RIG_SITE_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("RIG_SITE_OUTPUT_DIR", str(output_dir))

    return {
        "input_dir": input_dir,
        "manifest_path": manifest_path,
        "output_dir": output_dir,
    }


# Test 1
def test_contract_artifact_validates():
    contract_path = (
        REPO_ROOT / "docs" / "json" / "site" / "static_site_compiler_contract.v1.json"
    )
    assert contract_path.is_file()
    with open(contract_path, encoding="utf-8") as f:
        data = json.load(f)
    is_valid, err = validate_json_schema(
        data, "rig.static_site.compiler_contract.v1", REPO_ROOT
    )
    assert is_valid, f"Contract validation failed: {err}"


# Test 2 & Test 14 (uses real docs json artifacts)
def test_renderer_validates_source_artifacts_before_render(clean_env, monkeypatch):
    # Alter page_frontend model to make it invalid (missing required route field)
    page_frontend_path = clean_env["input_dir"] / "page_frontend.v1.json"
    with open(page_frontend_path, encoding="utf-8") as f:
        pm = json.load(f)
    del pm["route"]
    with open(page_frontend_path, "w", encoding="utf-8") as f:
        json.dump(pm, f)

    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()

    assert exit_code == 1
    # Verify we did not produce normal index.html but did produce render_report.v1.json
    assert not (clean_env["output_dir"] / "index.html").exists()
    report_path = clean_env["output_dir"] / "site_render_report.v1.json"
    assert report_path.exists()
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["verdict"] == "fail"


# Test 3 & Test 13
def test_renderer_rejects_invalid_schema_artifact(clean_env, monkeypatch):
    # Make one of the release candidate json files invalid
    # For example, let's load readiness gate and corrupt its schema_version
    gate_path = (
        clean_env["input_dir"].parent / "release_gate" / "rc_readiness_gate.v1.json"
    )
    with open(gate_path, encoding="utf-8") as f:
        data = json.load(f)
    data["schema_version"] = "invalid.schema.name.v1"  # Not a valid schema
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 1

    report_path = clean_env["output_dir"] / "site_render_report.v1.json"
    assert report_path.exists()
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert report["verdict"] == "fail"
    assert "artifact_validation_error" in report["failure_reasons"][0]


# Test 4
def test_renderer_outputs_deterministic_page_order(clean_env, monkeypatch):
    monkeypatch.setattr(
        "sys.argv", ["rig_site_render.py", "--candidate-id", "det-order"]
    )
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 0

    report_path = clean_env["output_dir"] / "site_render_report.v1.json"
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    pages = [p["page_id"] for p in report["pages"]]
    # Verify pages are sorted alphabetically by page_id
    assert pages == sorted(pages)


# Test 5
def test_renderer_outputs_stable_slug_for_same_artifact(clean_env, monkeypatch):
    monkeypatch.setattr(
        "sys.argv", ["rig_site_render.py", "--candidate-id", "slug-test"]
    )
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 0

    report_path = clean_env["output_dir"] / "site_render_report.v1.json"
    with open(report_path, encoding="utf-8") as f:
        report1 = json.load(f)

    # Re-run rendering
    exit_code2 = main()
    assert exit_code2 == 0
    with open(report_path, encoding="utf-8") as f:
        report2 = json.load(f)

    # Routes must be identical
    routes1 = [p["route"] for p in report1["pages"]]
    routes2 = [p["route"] for p in report2["pages"]]
    assert routes1 == routes2


# Test 6
def test_renderer_regeneration_is_byte_or_hash_stable(clean_env, monkeypatch):
    monkeypatch.setattr(
        "sys.argv", ["rig_site_render.py", "--candidate-id", "hash-test"]
    )
    from scripts.rig_site_render import main

    exit_code1 = main()
    assert exit_code1 == 0
    report_path = clean_env["output_dir"] / "site_render_report.v1.json"
    with open(report_path, encoding="utf-8") as f:
        report1 = json.load(f)
    digest1 = report1["deterministic_digest"]

    # Re-run rendering
    exit_code2 = main()
    assert exit_code2 == 0
    with open(report_path, encoding="utf-8") as f:
        report2 = json.load(f)
    digest2 = report2["deterministic_digest"]

    assert digest1 == digest2
    assert len(digest1) == 64  # SHA-256 hex digest length


# Test 7
def test_renderer_emits_render_report(clean_env, monkeypatch):
    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 0
    assert (clean_env["output_dir"] / "site_render_report.v1.json").exists()


# Test 8
def test_renderer_report_validates_against_schema(clean_env, monkeypatch):
    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 0

    report_path = clean_env["output_dir"] / "site_render_report.v1.json"
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    is_valid, err = validate_json_schema(report, "rig.site.render_report.v1", REPO_ROOT)
    assert is_valid, f"Report schema validation failed: {err}"


# Test 9
def test_renderer_does_not_emit_raw_forbidden_fields(clean_env, monkeypatch):
    # Inject a private key / credential pattern in a page model
    page_frontend_path = clean_env["input_dir"] / "page_frontend.v1.json"
    with open(page_frontend_path, encoding="utf-8") as f:
        pm = json.load(f)
    pm["title"] = (
        "Page with a secret: -----BEGIN RSA PRIVATE KEY-----\nsecret_token_data\n-----END RSA PRIVATE KEY-----"
    )
    with open(page_frontend_path, "w", encoding="utf-8") as f:
        json.dump(pm, f)

    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()
    # It must fail because safety scan blocks the run
    assert exit_code == 1

    # The normal HTML output should not exist or be cleaned up
    assert not (clean_env["output_dir"] / "frontend" / "index.html").exists()


# Test 10
def test_renderer_escapes_or_sanitizes_html_content(clean_env, monkeypatch):
    # Inject a script tag into a page model title
    page_frontend_path = clean_env["input_dir"] / "page_frontend.v1.json"
    with open(page_frontend_path, encoding="utf-8") as f:
        pm = json.load(f)
    pm["title"] = "<script>alert('xss')</script>"
    with open(page_frontend_path, "w", encoding="utf-8") as f:
        json.dump(pm, f)

    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 0

    # Check that HTML is escaped
    html_file = clean_env["output_dir"] / "frontend" / "index.html"
    assert html_file.exists()
    content = html_file.read_text(encoding="utf-8")
    assert "<script>alert" not in content
    assert "&lt;script&gt;alert" in content


# Test 11
def test_renderer_nav_manifest_is_deterministic(clean_env, monkeypatch):
    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 0

    manifest_path = clean_env["output_dir"] / "site_manifest.v1.json"
    assert manifest_path.exists()
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)

    routes = [r["page_id"] for r in data["routes"]]
    assert routes == sorted(routes)


# Test 12
def test_renderer_handles_missing_optional_fields_without_crash(clean_env, monkeypatch):
    # Description is an optional field in rig.site.page.v1 schema
    page_frontend_path = clean_env["input_dir"] / "page_frontend.v1.json"
    with open(page_frontend_path, encoding="utf-8") as f:
        pm = json.load(f)
    pm["description"] = "Optional page description"
    with open(page_frontend_path, "w", encoding="utf-8") as f:
        json.dump(pm, f)

    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 0
    assert (clean_env["output_dir"] / "frontend" / "index.html").exists()

    # Delete the optional description and compile again
    del pm["description"]
    with open(page_frontend_path, "w", encoding="utf-8") as f:
        json.dump(pm, f)

    # Clear cache and reload main
    for key in list(sys.modules.keys()):
        if "rig_site_render" in key:
            del sys.modules[key]
    from scripts.rig_site_render import main as main2

    exit_code2 = main2()
    assert exit_code2 == 0
    assert (clean_env["output_dir"] / "frontend" / "index.html").exists()

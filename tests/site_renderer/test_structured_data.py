from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """Fixture to isolate environment inputs and outputs using tmp_path."""
    for key in list(sys.modules.keys()):
        if "rig_site_render" in key:
            del sys.modules[key]

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


@pytest.mark.contract
def test_structured_data_validation(clean_env, monkeypatch):
    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 0

    # 1. Homepage has JSON-LD WebSite and SoftwareApplication structured data
    homepage_html = clean_env["output_dir"] / "index.html"
    assert homepage_html.is_file()
    homepage_content = homepage_html.read_text(encoding="utf-8")

    json_ld_matches = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        homepage_content,
        re.DOTALL,
    )
    assert len(json_ld_matches) > 0
    homepage_data = json.loads(json_ld_matches[0])

    # Check for WebSite and SoftwareApplication
    types_found = {
        item.get("@type") for item in homepage_data if isinstance(item, dict)
    }
    assert "WebSite" in types_found
    assert "SoftwareApplication" in types_found

    # 2. Evidence pages have JSON-LD TechArticle
    html_files = list(clean_env["output_dir"].glob("**/*.html"))
    homepage_html_resolved = (clean_env["output_dir"] / "index.html").resolve()
    evidence_pages = [p for p in html_files if p.resolve() != homepage_html_resolved]
    assert len(evidence_pages) > 0

    for ep in evidence_pages:
        ep_content = ep.read_text(encoding="utf-8")
        matches = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', ep_content, re.DOTALL
        )
        assert len(matches) > 0, (
            f"Evidence page {ep.name} missing structured data block"
        )

        data = json.loads(matches[0])
        assert isinstance(data, dict)
        assert data.get("@type") == "TechArticle"

        # 3. JSON-LD @type matches page content (e.g. title/headline is present in HTML body)
        headline = data.get("headline")
        assert headline
        import html

        assert headline in html.unescape(ep_content), (
            f"Structured data headline '{headline}' not found in body of {ep.name}"
        )

        # 4. No structured data claims not visible on page (ensure it's not a generic placeholder/leak)
        assert "TODO" not in headline
        assert "placeholder" not in headline.lower()

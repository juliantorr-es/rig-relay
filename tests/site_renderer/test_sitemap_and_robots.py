from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

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


@pytest.mark.integration
def test_sitemap_and_robots_generation(clean_env, monkeypatch):
    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 0

    # 1. sitemap.xml exists in output
    sitemap_path = clean_env["output_dir"] / "sitemap.xml"
    assert sitemap_path.is_file()

    # 2. robots.txt exists in output
    robots_path = clean_env["output_dir"] / "robots.txt"
    assert robots_path.is_file()

    # Verify robots.txt contents
    robots_txt = robots_path.read_text(encoding="utf-8")
    assert "User-agent: *" in robots_txt
    assert "Allow: /" in robots_txt
    assert "Sitemap: ./sitemap.xml" in robots_txt

    # 3. All sitemap URLs map to generated pages
    tree = ET.parse(sitemap_path)
    root = tree.getroot()
    namespaces = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [elem.text for elem in root.findall(".//ns:loc", namespaces)]

    assert len(locs) > 0
    for loc in locs:
        # loc will look like ./index.html or ./frontend/index.html
        assert loc.startswith(".")
        loc_clean = (
            loc[2:]
            if loc.startswith("./")
            else (loc[1:] if loc.startswith(".") else loc)
        )
        html_file = clean_env["output_dir"] / loc_clean
        assert html_file.is_file(), f"Sitemap references non-existent file: {loc}"

    # 4. Canonical URLs are unique per page, and JSON-LD parses as valid JSON
    canonical_urls = set()
    html_files = list(clean_env["output_dir"].glob("**/*.html"))
    for hf in html_files:
        content = hf.read_text(encoding="utf-8")

        # Extract canonical URL
        match = re.search(r'<link rel="canonical" href="([^"]+)">', content)
        if match:
            canonical_url = match.group(1)
            assert canonical_url not in canonical_urls, (
                f"Duplicate canonical URL found: {canonical_url}"
            )
            canonical_urls.add(canonical_url)

        # Extract and parse JSON-LD
        json_ld_matches = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', content, re.DOTALL
        )
        for json_ld_str in json_ld_matches:
            # 5. JSON-LD parses as valid JSON
            try:
                data = json.loads(json_ld_str)
                assert data is not None
            except Exception as e:
                pytest.fail(
                    f"Invalid JSON-LD in file {hf.name}: {e}\nPayload: {json_ld_str}"
                )

            # 6. JSON-LD describes only visible page content (checking for page titles or descriptions)
            # WebSite/SoftwareApplication/TechArticle name should be present
            if isinstance(data, list):
                for item in data:
                    assert "@context" in item
                    assert "@type" in item
                    assert "name" in item or "headline" in item
            else:
                assert "@context" in data
                assert "@type" in data
                assert "headline" in data

        # 7. Breadcrumbs match page structure
        # eyebrow div should contain Breadcrumbs: Rig Relay / <nav_section>
        assert 'class="eyebrow"' in content
        # Breadcrumbs are structured as: <a href="...index.html">Rig Relay</a> / <nav_section>
        assert "Rig Relay" in content

    # 8. All internal links in rendered pages resolve to existing files
    for hf in html_files:
        content = hf.read_text(encoding="utf-8")
        # Find all href links
        links = re.findall(r'href="([^"]+)"', content)
        for link in links:
            # Ignore absolute URLs, hashes, mailto, etc.
            if link.startswith(("http://", "https://", "#", "mailto:")):
                continue

            # Resolve link: if absolute, route it relative to the output directory root.
            if link.startswith("/"):
                link_path = (clean_env["output_dir"] / link.lstrip("/")).resolve()
            else:
                link_path = (hf.parent / link).resolve()
            # It must exist (either as a file or directory with index.html)
            assert link_path.exists() or (link_path / "index.html").exists(), (
                f"Link '{link}' in {hf.name} does not resolve to an existing file/dir"
            )

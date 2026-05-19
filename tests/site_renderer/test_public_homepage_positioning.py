from __future__ import annotations

from pathlib import Path
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


@pytest.mark.integration
def test_public_homepage_content_and_positioning(clean_env, monkeypatch):
    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 0

    index_html = clean_env["output_dir"] / "index.html"
    assert index_html.is_file()
    html = index_html.read_text(encoding="utf-8")

    # 1. Homepage contains hero section with thesis text
    assert 'class="public-hero"' in html
    assert 'class="thesis"' in html
    assert "A governed local agent platform" in html

    # 2. Homepage has one H1
    h1_count = html.count("<h1")
    assert h1_count == 1, f"Expected exactly 1 H1 on homepage, found {h1_count}"

    # 3. Homepage has "What Rig Relay Does" section
    assert "What Rig Relay Does" in html
    assert 'class="feature-grid"' in html
    assert "Governed Execution" in html
    assert "Trace-Correlated Evidence" in html
    assert "Refusal-First Boundaries" in html

    # 4. Homepage has "What Is Proven Now" section
    assert "What Is Proven Now" in html
    assert 'class="metrics-row"' in html
    assert "Schemas Validated" in html

    # 5. Homepage has claim boundary block with supported/rejected
    assert 'class="claim-boundary claims-supported"' in html
    assert "What We Claim" in html
    assert "What We Do Not Claim" in html
    assert 'class="claim-boundary claims-rejected"' in html

    # 6. Homepage has audience-specific sections (investor, hiring, technical, open-source)
    assert 'class="audience-grid"' in html
    assert "Investors" in html
    assert "Hiring Managers" in html
    assert "Technical Reviewers" in html
    assert "Open-Source Users" in html

    # 7. Homepage has FAQ section with required questions
    assert 'class="faq-section"' in html
    assert "What is Rig Relay?" in html
    assert "Who is it for?" in html
    assert "What makes it different?" in html
    assert "What is proven?" in html
    assert "What is deferred?" in html

    # 8. Homepage has CTA links to evidence pages
    assert "Evidence You Can Inspect" in html
    assert 'href="#evidence"' in html
    assert 'href="/proof-chain/index.html"' in html
    assert 'href="/release-candidate/index.html"' in html
    assert 'href="/contracts/index.html"' in html

    # 9. Homepage title and H1 are not empty
    assert "<title>Rig Relay" in html
    assert "<h1>Rig Relay" in html

    # 10. Homepage meta description exists and is reasonable length
    assert '<meta name="description"' in html
    # description maxLength 160 is in schema, let's verify a description is present and not empty
    assert 'content="Rig Relay is a governed local agent platform' in html

    # 11. Homepage does not contain unsupported claims as positive assertions in the hero/thesis section
    hero_content = html.split("public-hero")[1].split("</section>")[0]
    assert "proven safe" not in hero_content.lower()
    assert "formally verified" not in hero_content.lower()

    # 12. Homepage links to GitHub repository
    assert "https://github.com/juliantorr-es/rig-relay" in html

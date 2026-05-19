from __future__ import annotations

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
def test_css_mobile_responsiveness():
    css_path = REPO_ROOT / "rig_relay" / "site_renderer" / "assets" / "site.css"
    assert css_path.is_file()
    css_content = css_path.read_text(encoding="utf-8")

    # 1. CSS includes responsive breakpoint @media rules
    assert "@media" in css_content
    assert "max-width: 768px" in css_content
    assert "max-width: 480px" in css_content

    # 2. No fixed-width layout traps (no "width:" values > 960px without max-width)
    # Search for widths like "width: 1000px" or similar
    fixed_widths = re.findall(r"(?<!-)\bwidth\s*:\s*(\d+)px", css_content)
    for width_str in fixed_widths:
        width_val = int(width_str)
        assert width_val <= 960, f"Found fixed width trap of {width_val}px (> 960px)"

    # 3. pre/code blocks have overflow rules
    assert "overflow-x" in css_content
    # typically "pre" or "code" style
    assert "pre" in css_content or "code" in css_content

    # 4. No external font URLs in CSS
    assert "fonts.googleapis.com" not in css_content
    assert "fonts.gstatic.com" not in css_content
    assert "url(http" not in css_content

    # 5. Touch targets have minimum sizing rules in CSS (e.g. min-height: 44px or min-width: 44px)
    assert "44px" in css_content


@pytest.mark.contract
def test_html_static_constraints(clean_env, monkeypatch):
    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()
    assert exit_code == 0

    html_files = list(clean_env["output_dir"].glob("**/*.html"))
    assert len(html_files) > 0

    for hf in html_files:
        content = hf.read_text(encoding="utf-8")

        # 1. HTML includes viewport meta tag
        assert '<meta name="viewport" content="width=device-width' in content

        # 2. No external script sources in HTML
        # Script tags should either be JSON-LD or not contain external src links (src="http...")
        script_srcs = re.findall(r'<script\b[^>]*\bsrc=["\']([^"\']+)["\']', content)
        for src in script_srcs:
            assert not src.startswith(("http://", "https://", "//")), (
                f"External script src found: {src}"
            )

        # 3. No external stylesheet URLs in HTML
        stylesheet_hrefs = re.findall(
            r'<link\b[^>]*\brel=["\']stylesheet["\'][^>]*\bhref=["\']([^"\']+)["\']',
            content,
        )
        for href in stylesheet_hrefs:
            assert not href.startswith(("http://", "https://", "//")), (
                f"External stylesheet href found: {href}"
            )

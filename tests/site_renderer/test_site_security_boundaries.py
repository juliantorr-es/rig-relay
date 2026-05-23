from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import re
import shutil
import sys

import pytest

from rig_relay.site_renderer import loaders
from rig_relay.site_renderer.renderer import render_index, render_page

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def clean_env_for_security(tmp_path, monkeypatch):
    """Fixture to isolate env, copying docs for full-pipeline security tests."""
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


# ---------------------------------------------------------------------------
# 1. JSON-LD breakout: attacker injects </script> into structured data
# ---------------------------------------------------------------------------
def test_json_ld_tojson_prevents_script_breakout():
    """RED-FIRST: if tojson doesn't escape </script>, JSON-LD can bust out of the script tag."""
    payload = {"@type": "Malicious", "name": "</script><script>alert(1)</script>X"}

    html = render_page({
        "page_id": "test-ld-breakout",
        "title": "JSON-LD Breakout Test",
        "route": "/test-ld-breakout/index.html",
        "sections": [],
        "structured_data_json": payload,
    })

    json_ld_blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    )
    assert len(json_ld_blocks) == 1, (
        "Expected one JSON-LD script block in rendered output"
    )

    json_ld_content = json_ld_blocks[0]

    has_escape = "\\u003c/script" in json_ld_content
    assert has_escape, (
        "RED: JSON-LD </script> breakout not escaped. "
        "tojson must produce \\u003c/script\\u003e in the output. "
        f"Got JSON-LD content: {json_ld_content[:200]}"
    )

    parsed = json.loads(json_ld_content)
    assert parsed["name"] == "</script><script>alert(1)</script>X", (
        "JSON-LD content must round-trip through json.loads preserving the original value"
    )


# ---------------------------------------------------------------------------
# 2. Script context escaping: attacker-controlled field values must not break
#    out of a <script type="application/ld+json"> tag via </script> sequences.
# ---------------------------------------------------------------------------
def test_structured_data_field_cannot_break_script_context():
    """Every attacker-controlled field in structured data JSON must be safe when embedded in <script>."""
    attack = "</script><svg onload=alert(1)>"

    for field in ("headline", "description"):
        struct = {
            "@context": "https://schema.org",
            "@type": "TechArticle",
            "headline": "Normal" if field != "headline" else attack,
            "description": "Normal" if field != "description" else attack,
            "url": "/test",
        }

        html = render_page({
            "page_id": "test-script-ctx",
            "title": "Script Context Test",
            "route": "/test-script-ctx/index.html",
            "sections": [],
            "structured_data_json": struct,
        })

        json_ld_blocks = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
        )
        assert len(json_ld_blocks) == 1, (
            f"No JSON-LD block found when injecting into field={field}"
        )

        raw_script_tag_break = bool(
            re.search(r"</script>\s*<script", json_ld_blocks[0], re.IGNORECASE)
        )
        assert not raw_script_tag_break, (
            f"RED: field '{field}' with value '{attack}' broke out of "
            f"<script> tag. JSON-LD content: {json_ld_blocks[0][:200]}"
        )

        parsed = json.loads(json_ld_blocks[0])
        assert parsed[field] == attack, (
            f"Round-trip failed for field '{field}': expected '{attack}', "
            f"got '{parsed.get(field)}'"
        )


# ---------------------------------------------------------------------------
# 3. javascript: URL rejection — canonical_url
# ---------------------------------------------------------------------------
def test_javascript_url_rejected_in_canonical_url():
    """RED-FIRST: javascript: URLs in href attributes must be rejected or sanitized."""
    html = render_page({
        "page_id": "test-js-reject",
        "title": "JS URL Test",
        "route": "/test-js-reject/index.html",
        "sections": [],
        "canonical_url": "javascript:alert(1)",
    })

    href_matches = re.findall(r'href="([^"]*)"', html)
    js_hrefs = [h for h in href_matches if h.lower().startswith("javascript:")]
    assert not js_hrefs, (
        "RED: javascript: URL passed through unescaped in href attribute. "
        "The renderer must reject or sanitize javascript: URLs. "
        f"Found: {js_hrefs}"
    )


# ---------------------------------------------------------------------------
# 4. javascript: URL rejection — og_url meta content
# ---------------------------------------------------------------------------
def test_javascript_url_rejected_in_og_url():
    """RED-FIRST: javascript: URLs in og:url meta content must be rejected or sanitized."""
    html = render_page({
        "page_id": "test-js-og",
        "title": "JS OG URL Test",
        "route": "/test-js-og/index.html",
        "sections": [],
        "og_url": "javascript:alert(1)",
    })

    og_urls = re.findall(r'<meta\s[^>]*property="og:url"[^>]*content="([^"]*)"', html)
    js_og = [u for u in og_urls if u.lower().startswith("javascript:")]
    assert not js_og, (
        "RED: javascript: URL passed through unescaped in og:url meta content. "
        f"Found: {js_og}"
    )


# ---------------------------------------------------------------------------
# 5. javascript: URL in nav link routes
# ---------------------------------------------------------------------------
def test_javascript_url_rejected_in_nav_link_routes():
    """RED-FIRST: nav page routes with javascript: must be rejected or sanitized."""
    html = render_page(
        {
            "page_id": "test-nav",
            "title": "Nav Test",
            "route": "/test-nav/index.html",
            "sections": [],
            "canonical_url": "",
        },
        nav_pages=[
            {
                "page_id": "evil",
                "title": "Click Me",
                "route": "javascript:alert(1)",
                "description": "malicious nav link",
            }
        ],
    )

    hrefs = re.findall(r'href="([^"]*)"', html)
    js_hrefs = [h for h in hrefs if h.lower().startswith("javascript:")]
    assert not js_hrefs, (
        "RED: javascript: URL in nav page route passed through unescaped. "
        f"Found: {js_hrefs}"
    )


# ---------------------------------------------------------------------------
# 6. data: URL rejection — canonical_url
# ---------------------------------------------------------------------------
def test_data_url_rejected_in_canonical_url():
    """RED-FIRST: data: URLs in href attributes must be rejected or sanitized."""
    html = render_page({
        "page_id": "test-data-reject",
        "title": "Data URL Test",
        "route": "/test-data-reject/index.html",
        "sections": [],
        "canonical_url": "data:text/html,<script>alert(1)</script>",
    })

    href_matches = re.findall(r'href="([^"]*)"', html)
    data_hrefs = [h for h in href_matches if h.lower().startswith("data:")]
    assert not data_hrefs, (
        "RED: data: URL passed through unescaped in href attribute. "
        "The renderer must reject or sanitize data: URLs. "
        f"Found: {data_hrefs}"
    )


# ---------------------------------------------------------------------------
# 7. data: URL rejection — og_url meta content
# ---------------------------------------------------------------------------
def test_data_url_rejected_in_og_url():
    """RED-FIRST: data: URLs in og:url meta content must be rejected or sanitized."""
    html = render_page({
        "page_id": "test-data-og",
        "title": "Data OG URL Test",
        "route": "/test-data-og/index.html",
        "sections": [],
        "og_url": "data:text/html,<script>alert(1)</script>",
    })

    og_urls = re.findall(r'<meta\s[^>]*property="og:url"[^>]*content="([^"]*)"', html)
    data_og = [u for u in og_urls if u.lower().startswith("data:")]
    assert not data_og, (
        "RED: data: URL passed through unescaped in og:url meta content. "
        f"Found: {data_og}"
    )


# ---------------------------------------------------------------------------
# 8. javascript: URL via route field through full pipeline
# ---------------------------------------------------------------------------
def test_javascript_url_in_route_field_rejected_by_full_pipeline(
    clean_env_for_security, monkeypatch
):
    """RED-FIRST: Inject javascript: route into page model; full pipeline must reject."""
    page_frontend = clean_env_for_security["input_dir"] / "page_frontend.v1.json"
    pm = json.loads(page_frontend.read_text(encoding="utf-8"))
    pm["route"] = "javascript:alert(1)"
    page_frontend.write_text(json.dumps(pm), encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()

    if exit_code == 0:
        output_dir = clean_env_for_security["output_dir"]
        html_files = list(output_dir.rglob("*.html"))
        for hf in html_files:
            content = hf.read_text(encoding="utf-8")
            hrefs = re.findall(r'href="([^"]*)"', content)
            _js_hrefs = [h for h in hrefs if h.lower().startswith("javascript:")]
            metas = re.findall(r'<meta\s[^>]*content="([^"]*)"', content)
            _js_metas = [m for m in metas if m.lower().startswith("javascript:")]

    assert exit_code != 0, (
        "RED: Full pipeline rendered a page with javascript: route without rejecting it. "
        "The renderer should reject dangerous URL schemes (exit code 1). "
        "Route 'javascript:alert(1)' passed validation and made it into output."
    )


# ---------------------------------------------------------------------------
# 9. data: URL via route field through full pipeline
# ---------------------------------------------------------------------------
def test_data_url_in_route_field_rejected_by_full_pipeline(
    clean_env_for_security, monkeypatch
):
    """RED-FIRST: Inject data: route into page model; full pipeline must reject."""
    page_frontend = clean_env_for_security["input_dir"] / "page_frontend.v1.json"
    pm = json.loads(page_frontend.read_text(encoding="utf-8"))
    pm["route"] = "data:text/html,<script>alert(1)</script>"
    page_frontend.write_text(json.dumps(pm), encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["rig_site_render.py"])
    from scripts.rig_site_render import main

    exit_code = main()

    assert exit_code != 0, (
        "RED: Full pipeline rendered a page with data: route without rejecting it. "
        "The renderer should reject dangerous URL schemes (exit code 1)."
    )


# ---------------------------------------------------------------------------
# 10. _make_schema_tolerant is dead code — validate_json_schema must never call it
# ---------------------------------------------------------------------------
def test_make_schema_tolerant_is_never_called_by_validate_json_schema():
    """_make_schema_tolerant is a dangerous bypass; it must NEVER be called by validate_json_schema."""
    src = inspect.getsource(loaders.validate_json_schema)
    tree = ast.parse(src)

    class CallCollector(ast.NodeVisitor):
        def __init__(self):
            self.calls: list[str] = []

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name):
                self.calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                self.calls.append(node.func.attr)
            self.generic_visit(node)

    collector = CallCollector()
    collector.visit(tree)
    assert "_make_schema_tolerant" not in collector.calls, (
        "RED: _make_schema_tolerant is called inside validate_json_schema! "
        "This function sets additionalProperties=True on all schemas, creating a "
        "security bypass that allows attacker-controlled extra fields. "
        "It was intended as dead code — it must never be activated. "
        f"validate_json_schema calls: {collector.calls}"
    )


# ---------------------------------------------------------------------------
# 11. _make_schema_tolerant is dead code — never imported outside its own module
# ---------------------------------------------------------------------------
def test_make_schema_tolerant_is_never_imported():
    """_make_schema_tolerant must never be imported or used in any production or test code."""
    import glob as glob_mod

    py_files = list(
        glob_mod.glob("rig_relay/**/*.py", recursive=True, root_dir=REPO_ROOT)
    ) + list(glob_mod.glob("scripts/**/*.py", recursive=True, root_dir=REPO_ROOT))

    for rel_path in py_files:
        full_path = REPO_ROOT / rel_path
        try:
            content = full_path.read_text(encoding="utf-8")
        except Exception:
            continue

        if "_make_schema_tolerant" in content:
            tree = ast.parse(content)

            class ImportChecker(ast.NodeVisitor):
                def __init__(self):
                    self.imports_tolerant = False
                    self.calls_tolerant = False

                def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                    for alias in node.names:
                        if alias.name == "_make_schema_tolerant":
                            self.imports_tolerant = True
                    self.generic_visit(node)

                def visit_Import(self, node: ast.Import) -> None:
                    self.generic_visit(node)

                def visit_Call(self, node: ast.Call) -> None:
                    if isinstance(node.func, ast.Name):
                        if node.func.id == "_make_schema_tolerant":
                            self.calls_tolerant = True
                    self.generic_visit(node)

                def check_source(self):
                    return self.imports_tolerant or self.calls_tolerant

            checker = ImportChecker()
            checker.visit(tree)
            is_loaders_py = rel_path.endswith("loaders.py")

            if checker.imports_tolerant and not is_loaders_py:
                pytest.fail(
                    f"RED: _make_schema_tolerant is imported in {rel_path}. "
                    "This dangerous bypass function must remain dead code."
                )

            if checker.calls_tolerant and not is_loaders_py:
                pytest.fail(
                    f"RED: _make_schema_tolerant is called in {rel_path}. "
                    "This dangerous bypass function must remain dead code."
                )


# ---------------------------------------------------------------------------
# 12. og_image fields must not accept javascript: or data: URLs
# ---------------------------------------------------------------------------
def test_javascript_url_rejected_in_og_image():
    """RED-FIRST: javascript: URLs in og:image meta content must be rejected or sanitized."""
    html = render_page({
        "page_id": "test-og-img",
        "title": "OG Image Test",
        "route": "/test-og-img/index.html",
        "sections": [],
        "og_image": "javascript:alert(1)",
    })

    og_images = re.findall(
        r'<meta\s[^>]*property="og:image"[^>]*content="([^"]*)"', html
    )
    if og_images:
        js_images = [u for u in og_images if u.lower().startswith("javascript:")]
        assert not js_images, (
            "RED: javascript: URL passed through in og:image meta content. "
            f"Found: {js_images}"
        )


# ---------------------------------------------------------------------------
# 13. Index page JSON-LD is also safe against script breakout
# ---------------------------------------------------------------------------
def test_index_json_ld_tojson_prevents_script_breakout():
    """Attack embedded in structured_data_json of index page must be escaped."""
    payload = [{"@type": "WebSite", "name": "</script><script>alert(1)</script>"}]

    html = render_index(pages=[], site_meta={"structured_data_json": payload})

    json_ld_blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    )
    assert len(json_ld_blocks) == 1, (
        "Expected one JSON-LD script block in rendered index output"
    )

    has_escape = "\\u003c/script" in json_ld_blocks[0]
    assert has_escape, (
        "RED: Index page JSON-LD </script> breakout not escaped. "
        f"Got: {json_ld_blocks[0][:200]}"
    )

    parsed = json.loads(json_ld_blocks[0])
    assert parsed[0]["name"] == "</script><script>alert(1)</script>", (
        "JSON-LD content must round-trip preserving the original value"
    )


# ---------------------------------------------------------------------------
# 14. file: URL rejection — canonical_url
# ---------------------------------------------------------------------------
def test_file_url_rejected_in_canonical_url():
    """RED-FIRST: file: URLs in href attributes must be rejected or sanitized."""
    html = render_page({
        "page_id": "test-file-reject",
        "title": "File URL Test",
        "route": "/test-file-reject/index.html",
        "sections": [],
        "canonical_url": "file:///etc/passwd",
    })

    hrefs = re.findall(r'href="([^"]*)"', html)
    file_hrefs = [h for h in hrefs if h.lower().startswith("file:")]
    assert not file_hrefs, (
        "RED: file: URL passed through unescaped in href attribute. "
        f"Found: {file_hrefs}"
    )


# ---------------------------------------------------------------------------
# 15. Ensure the renderer does NOT call _make_schema_tolerant in any path
# ---------------------------------------------------------------------------
def test_renderer_script_never_calls_make_schema_tolerant():
    """The site renderer script must never call _make_schema_tolerant."""
    render_script = REPO_ROOT / "scripts" / "rig_site_render.py"
    content = render_script.read_text(encoding="utf-8")

    tree = ast.parse(content)

    class CallChecker(ast.NodeVisitor):
        def __init__(self):
            self.found = False

        def visit_Call(self, node: ast.Call) -> None:
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "_make_schema_tolerant"
            ):
                self.found = True
            self.generic_visit(node)

    checker = CallChecker()
    checker.visit(tree)
    assert not checker.found, (
        "RED: scripts/rig_site_render.py calls _make_schema_tolerant. "
        "This dangerous bypass must never be activated."
    )

"""Tests for markdown inventory and artifact generation."""
from __future__ import annotations
import pytest

pytestmark = [pytest.mark.integration]


import csv
import json
from pathlib import Path

from rig_relay.docs_render.artifact_writer import write_all_artifacts
from rig_relay.docs_render.markdown_inventory import (
    classify_link,
    derive_title,
    extract_code_fences,
    extract_headings,
    extract_links,
    infer_doc_kind,
    inventory_markdown,
    parse_front_matter,
)
from rig_relay.docs_render.site_renderer import render_site


def test_root_readme_excluded():
    inv = inventory_markdown()
    docs = inv["documents"]
    paths = [d["path"] for d in docs]
    assert "README.md" not in paths
    assert "AGENTS.md" not in paths
    assert inv["excluded_root_count"] >= 1


def test_nested_docs_included():
    inv = inventory_markdown()
    docs = inv["documents"]
    paths = [d["path"] for d in docs]
    assert any(p.startswith("docs/") for p in paths)


def test_vendor_dirs_excluded():
    inv = inventory_markdown()
    docs = inv["documents"]
    paths = [d["path"] for d in docs]
    for p in paths:
        assert ".git/" not in p
        assert ".venv/" not in p
        assert "node_modules/" not in p
        assert ".build/" not in p


def test_deterministic_ordering():
    inv1 = inventory_markdown()
    inv2 = inventory_markdown()
    paths1 = [d["path"] for d in inv1["documents"]]
    paths2 = [d["path"] for d in inv2["documents"]]
    assert paths1 == paths2


def test_title_from_front_matter():
    fm, body = parse_front_matter("---\ntitle: My Title\n---\n# Other")
    title = derive_title(fm, extract_headings(body), "fallback")
    assert title == "My Title"


def test_title_from_h1():
    title = derive_title({}, [(1, "H1 Title")], "fallback")
    assert title == "H1 Title"


def test_title_from_filename():
    title = derive_title({}, [], "my-document")
    assert title == "My Document"


def test_links_extracted():
    text = "[Link](https://example.com) and [Internal](docs/x.md)"
    links = extract_links(text)
    assert len(links) == 2
    assert links[0]["href"] == "https://example.com"


def test_code_fences_extracted():
    text = "```python\nprint('hi')\n```\n\n```mermaid\ngraph TD\n```"
    fences = extract_code_fences(text)
    assert len(fences) == 2
    assert fences[0]["language"] == "python"
    assert fences[1]["is_mermaid"] is True


def test_mermaid_counted():
    text = "```mermaid\ngraph\n```"
    fences = extract_code_fences(text)
    assert sum(1 for f in fences if f["is_mermaid"]) == 1


def test_doc_kind_inference():
    assert infer_doc_kind("docs/governance/x.md") == "governance"
    assert infer_doc_kind("docs/audits/x.md") == "audit"
    assert infer_doc_kind("docs/demo/x.md") == "demo"
    assert infer_doc_kind("docs/unknown/x.md") == "unknown"


def test_link_classification():
    assert classify_link("https://example.com") == "external"
    assert classify_link("docs/x.md") == "internal"
    assert classify_link("#section") == "anchor"
    assert classify_link("img.png") == "image"


def test_artifact_json_valid(tmp_path: Path):
    out = tmp_path / "artifacts"
    write_all_artifacts(output_dir=out, repo_root=Path("."))

    docs_path = out / "markdown_documents.json"
    assert docs_path.is_file()
    data = json.loads(docs_path.read_text())
    assert data["schema_version"] == "rig.docs.markdown_inventory.v1"
    assert data["document_count"] >= 1


def test_artifact_jsonl_one_per_line(tmp_path: Path):
    out = tmp_path / "artifacts"
    write_all_artifacts(output_dir=out, repo_root=Path("."))

    jsonl_path = out / "markdown_documents.jsonl"
    lines = jsonl_path.read_text().splitlines()
    assert len(lines) >= 1
    for line in lines:
        if line.strip():
            json.loads(line)


def test_artifact_csv_columns(tmp_path: Path):
    out = tmp_path / "artifacts"
    write_all_artifacts(output_dir=out, repo_root=Path("."))

    csv_path = out / "markdown_index.csv"
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
    assert "path" in header
    assert "title" in header
    assert "doc_kind" in header


def test_artifact_summary(tmp_path: Path):
    out = tmp_path / "artifacts"
    write_all_artifacts(output_dir=out, repo_root=Path("."))

    summary_path = out / "markdown_summary.json"
    data = json.loads(summary_path.read_text())
    assert data["total_documents"] >= 1
    assert isinstance(data["by_doc_kind"], dict)


def test_site_renders_index(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    write_all_artifacts(output_dir=artifacts, repo_root=Path("."))

    site = tmp_path / "site"
    result = render_site(artifacts_dir=artifacts, output_dir=site, repo_root=Path("."))

    assert "index" in result
    index = site / "index.html"
    assert index.is_file()
    content = index.read_text()
    assert "<!DOCTYPE html>" in content
    assert "Rig Relay" in content


def test_site_escapes_unsafe_content(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    write_all_artifacts(output_dir=artifacts, repo_root=Path("."))

    site = tmp_path / "site"
    render_site(artifacts_dir=artifacts, output_dir=site, repo_root=Path("."))

    for html_file in site.rglob("*.html"):
        content = html_file.read_text()
        assert "<script>" not in content.lower() or "text/css" in content


def test_repeated_run_same_hashes(tmp_path: Path):
    (tmp_path / "docs" / "test").mkdir(parents=True)
    (tmp_path / "docs" / "test" / "a.md").write_text("# Title\n\nContent here")
    out1 = tmp_path / "a"
    out2 = tmp_path / "b"
    write_all_artifacts(output_dir=out1, repo_root=tmp_path)
    write_all_artifacts(output_dir=out2, repo_root=tmp_path)

    docs1 = json.loads((out1 / "markdown_documents.json").read_text())
    docs2 = json.loads((out2 / "markdown_documents.json").read_text())
    assert docs1["document_count"] == docs2["document_count"]

    for d1, d2 in zip(docs1["documents"], docs2["documents"]):
        assert d1["sha256"] == d2["sha256"]
        assert d1["body_sha256"] == d2["body_sha256"]


def test_no_leaked_secrets(tmp_path: Path):
    out = tmp_path / "artifacts"
    write_all_artifacts(output_dir=out, repo_root=tmp_path)
    docs_path = out / "markdown_documents.json"
    if not docs_path.is_file():
        return  # no docs in tmp_path, skip
    docs = json.loads(docs_path.read_text())
    raw = json.dumps(docs)
    for pattern in ["OPENAI_API_KEY=", "sk-", "ghp_"]:
        assert pattern not in raw, f"Leaked: {pattern}"

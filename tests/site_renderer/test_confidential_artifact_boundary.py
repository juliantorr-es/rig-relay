from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.docs_renderer.writer import render_manifest
from rig_relay.site_renderer.loaders import load_input_manifest
from rig_relay.site_renderer.renderer import render_page

pytestmark = [pytest.mark.integration, pytest.mark.sabotage]


def test_input_manifest_and_rendering_exclude_confidential_sources(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifest_path = tmp_path / "site_renderer_input_manifest.v1.json"

    public_source = "docs/json/public.json"
    confidential_source = ".build/rig-relay/confidential/secret.json"

    manifest_path.write_text(
        json.dumps(
            {
                "$schema": "rig.site.input_manifest.v1",
                "generated_at": "2026-05-22T00:00:00Z",
                "head_sha": "deadbeef",
                "branch": "feature/test",
                "inputs": [
                    {
                        "source_path": public_source,
                        "source_type": "json",
                        "page_id": "public-page",
                        "renderer_kind": "input_manifest",
                        "public_safe": True,
                        "redaction_required": False,
                    },
                    {
                        "source_path": confidential_source,
                        "source_type": "json",
                        "page_id": "secret-page",
                        "renderer_kind": "input_manifest",
                        "public_safe": False,
                        "redaction_required": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_input_manifest(manifest_path, repo_root=repo_root)
    assert loaded is not None
    assert [entry["source_path"] for entry in loaded["inputs"]] == [public_source]

    html = render_page(
        {
            "page_id": "public-page",
            "title": "Public Page",
            "route": "/public-page/index.html",
            "sections": [],
            "source_artifact_paths": [public_source, confidential_source],
        }
    )
    assert confidential_source not in html
    assert public_source in html


def test_render_manifest_excludes_confidential_pages(tmp_path: Path) -> None:
    public_source = "docs/json/public.json"
    confidential_source = ".build/rig-relay/confidential/secret.json"

    rendered = json.loads(
        render_manifest(
            [
                {
                    "document_id": "public-page",
                    "title": "Public Page",
                    "_source_path": public_source,
                },
                {
                    "document_id": "secret-page",
                    "title": "Secret Page",
                    "_source_path": confidential_source,
                },
            ],
            [],
            "deadbeef",
        )
    )

    assert rendered["page_count"] == 1
    assert [page["source_json_path"] for page in rendered["pages"]] == [public_source]

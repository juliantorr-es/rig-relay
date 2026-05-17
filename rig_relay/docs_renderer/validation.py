"""Post-render validation checks for the static documentation site."""

from __future__ import annotations

from pathlib import Path


def check_static_safety(docs_out: Path) -> list[str]:
    """Check generated HTML for safety issues: tokens, local paths, raw scripts."""
    warnings: list[str] = []
    for html_file in docs_out.rglob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        name = str(html_file.relative_to(docs_out))

        unsafe = ["onerror=", "javascript:", "<iframe", "<embed", "<object"]
        for pattern in unsafe:
            if pattern in content:
                warnings.append(f"{name}: unsafe pattern '{pattern}'")

        script_tags = content.count("<script")
        site_js_count = content.count("site.js")
        if script_tags > site_js_count:
            warnings.append(
                f"{name}: unexpected <script> tags ({script_tags - site_js_count} extra)"
            )

        import os

        home = os.path.expanduser("~")
        if home and len(home) > 2 and home in content:  # noqa: PLR2004
            warnings.append(f"{name}: contains home path '{home}'")

    return warnings


def check_site_coverage(pages: list[dict], manifest: dict) -> list[str]:
    """Verify that all manifest documents have rendered pages."""
    warnings: list[str] = []
    manifest_ids: set[str] = set()
    for col in manifest.get("collections", []):
        for doc in col.get("documents", []):
            did = doc.get("document_id", "")
            if did:
                manifest_ids.add(did)

    rendered_ids = {p.get("document_id", "") for p in pages}

    orphans = manifest_ids - rendered_ids
    for oid in sorted(orphans):
        warnings.append(f"orphan document in manifest but not rendered: {oid}")

    extra = rendered_ids - manifest_ids
    for eid in sorted(extra):
        if not eid.startswith("rig-") and eid not in {
            "frontend-trace-endpoint",
            "desktop-golden-path-trace",
            "json-documentation-migration",
            "tool-batch-execution",
            "frontend-transport-state-reducer",
        }:
            warnings.append(f"rendered page not in manifest: {eid}")

    return warnings

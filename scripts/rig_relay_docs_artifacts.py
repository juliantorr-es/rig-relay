#!/usr/bin/env python3
"""Generate structured documentation artifacts and static site from Markdown.

Usage:
    uv run python scripts/rig_relay_docs_artifacts.py          # generate artifacts
    uv run python scripts/rig_relay_docs_artifacts.py --render # also render site
    uv run python scripts/rig_relay_docs_artifacts.py --doctor # check outputs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate Rig Relay documentation artifacts and static site."
    )
    parser.add_argument("--render", action="store_true", help="Also render static site")
    parser.add_argument("--doctor", action="store_true", help="Check artifact and site health")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Repo root")
    args = parser.parse_args(argv)

    root = args.root.resolve()

    if args.doctor:
        return _doctor(root)

    from rig_relay.docs_render.artifact_writer import write_all_artifacts

    written = write_all_artifacts(repo_root=root)
    print(f"Artifacts written ({len(written)} files):")
    for name, path in sorted(written.items()):
        print(f"  {name}: {path}")

    if args.render:
        from rig_relay.docs_render.site_renderer import render_site

        rendered = render_site(repo_root=root)
        print(f"\nSite rendered ({len(rendered)} pages):")
        for name, path in sorted(rendered.items()):
            print(f"  {name}: {path}")

    return 0


def _doctor(root: Path) -> int:
    issues = 0

    artifacts_dir = root / "docs" / "artifacts" / "markdown"
    site_dir = root / "site"

    for f in ["markdown_documents.json", "markdown_index.csv", "markdown_summary.json"]:
        if not (artifacts_dir / f).is_file():
            print(f"MISSING: {artifacts_dir / f}")
            issues += 1

    if site_dir.is_dir():
        if not (site_dir / "index.html").is_file():
            print(f"MISSING: {site_dir / 'index.html'}")
            issues += 1
        if not (site_dir / ".nojekyll").is_file():
            print(f"MISSING: {site_dir / '.nojekyll'}")
            issues += 1

    import json
    docs_path = artifacts_dir / "markdown_documents.json"
    if docs_path.is_file():
        data = json.loads(docs_path.read_text(encoding="utf-8"))
        count = data.get("document_count", 0)
        print(f"Documents: {count}")
        if count == 0:
            print("WARNING: zero documents in artifacts")
            issues += 1

        excluded = data.get("excluded_root_count", 0)
        print(f"Root excluded: {excluded}")
        if excluded == 0:
            print("WARNING: no root files excluded (expected >= 1)")
            issues += 1

        leaked = _check_leaks(data)
        if leaked:
            print(f"INFO (docs may reference secrets in examples): {len(leaked)} pattern(s) found")
            for l in leaked:
                print(f"  - {l}")

    if issues == 0:
        print("Doctor: all checks passed")
    else:
        print(f"Doctor: {issues} issue(s) found")
    return min(issues, 1)


def _check_leaks(data: dict) -> list[str]:
    """Check for common secret patterns. Returns informational findings only."""
    import json
    raw = json.dumps(data)
    findings: list[str] = []
    patterns = {
        "OPENAI_API_KEY=": "Literal API key assignment (likely docs example)",
        "sk-": "API key prefix (likely docs example)",
        "ghp_": "GitHub token prefix",
        "/Users/": "Absolute local path",
        ".env": "Dotenv reference (likely docs)",
        "-----BEGIN": "PEM private key marker",
    }
    for pattern, desc in patterns.items():
        if pattern in raw:
            findings.append(f"Pattern '{pattern}': {desc}")
    return findings


if __name__ == "__main__":
    raise SystemExit(main())

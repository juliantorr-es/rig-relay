# GitHub Pages — Artifact-Rendered Documentation Site

Rig Relay's documentation site is generated from structured artifacts, not
raw Markdown. The pipeline is:

```
Markdown files (docs/, non-root)
  → inventory_markdown()      scan + extract metadata
  → write_all_artifacts()     JSON/JSONL/CSV artifacts
  → render_site()             static HTML + CSS
  → GitHub Pages deploy       actions/pages
```

## Local render

```bash
uv run python scripts/rig_relay_docs_artifacts.py --render
```

Outputs under `site/` (not committed):
- `index.html` — overview, counts, recent docs
- `documents.html` — all documents
- `governance.html`, `audits.html`, `demos.html` — by kind
- `code-fences.html` — extracted code blocks
- `links.html` — extracted hyperlinks
- `assets/site.css` — dark theme, no external CDN
- `.nojekyll` — disables Jekyll processing

## Local doctor

```bash
uv run python scripts/rig_relay_docs_artifacts.py --doctor
```

Checks: artifacts exist, `site/index.html` exists, `.nojekyll`
exists, no private paths leaked, no root Markdown converted.

## Excluded files

Root Markdown files (README.md, AGENTS.md, CONTRIBUTING.md, etc.)
are excluded from the artifact pipeline. They remain as project-level
documentation, not docs-site content.

Vendor/cache directories (`.git`, `.venv`, `.build`, `node_modules`,
`__pycache__`) are excluded from scanning.

## GitHub Pages deployment

The workflow at `.github/workflows/pages.yml` runs on push to `main`
when `docs/`, `rig_relay/docs_render/`, or the workflow itself changes.

It:
1. Checks out the repo
2. Installs uv and syncs dependencies
3. Runs `scripts/rig_relay_docs_artifacts.py --render`
4. Verifies `site/index.html` and `.nojekyll`
5. Uploads `site/` as a Pages artifact
6. Deploys to GitHub Pages

Manual dispatch is also available from the Actions tab.

## Configuration

GitHub Pages source must be set to "GitHub Actions" in the repository
settings: Settings → Pages → Build and deployment → Source: GitHub Actions.

No branch-based deployment is needed.

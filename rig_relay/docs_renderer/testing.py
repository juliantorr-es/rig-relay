from __future__ import annotations

import hashlib
import html as _html
import json

from rig_relay.docs_renderer.metadata import (
    extract_site_meta,
    make_head_tags,
    make_og_tags,
)
from rig_relay.docs_renderer.models import SiteMeta
from rig_relay.docs_renderer.paths import REPO_ROOT

_TEST_INVENTORY_PATH = (
    REPO_ROOT / "docs" / "json" / "testing" / "test_inventory.v1.json"
)
_TEST_CLASSIFICATION_PATH = (
    REPO_ROOT / "docs" / "json" / "testing" / "test_classification.v1.jsonl"
)

_CLASSIFICATION_DEFS: dict[str, str] = {
    "smoke": "Fastest confidence checks; must pass before demo/share. Covers critical-path functionality that would block development if broken.",
    "contract": "Domain contract/unit tests. Verifies that individual modules honour their public contracts and invariants.",
    "integration": "Crosses multiple components, processes, or filesystem boundaries. Verifies that subsystems compose correctly.",
    "e2e": "Broad-stack or full-flow tests. Exercises the system from entry point to output through as many real paths as possible.",
    "adversarial": "Adversarial or injection-focused coverage. Tests the system against malicious inputs, corruption, and sabotage scenarios.",
    "packaging": "Packaged app, installer, or bundle checks. Verifies that the distributable artifact is well-formed and installable.",
    "slow": "Intentionally slow tests. Not included in default suite; run separately on CI or pre-release gates.",
    "legacy": "Retained for compatibility but not part of the default suite. May reference deprecated APIs or old patterns.",
    "flaky": "Known non-deterministic; must not run in the default suite. Runs only in dedicated quarantine jobs.",
    "network": "Requires external network access. Skipped in air-gapped or offline CI environments.",
    "provider": "Requires an external model, provider, or API endpoint. Skipped unless provider credentials are configured.",
    "destructive": "Mutates worktrees, branches, or files beyond temp directories. Requires explicit opt-in to run.",
    "migration": "Test being relocated during test-layout canonicalization. Temporary marker for tests in transit.",
    "quarantine": "Quarantined test; runs only in a dedicated quarantine job. Failing quarantined tests do not block the build.",
    "sabotage": "Corruption or sabotage injection tests for runtime hardening. Injects malformed data to verify detection and recovery.",
    "real_artifact": "Tests using real file artifacts with no mocking. Verifies behaviour against actual on-disk data.",
    "substrate": "Storage, cache, or infrastructure substrate coverage. Verifies that DuckDB, JSONL stores, and coordination layers behave correctly.",
}


def _warning_card(title: str, message: str) -> str:
    t = _html.escape(title)
    m = _html.escape(message)
    return f'<div class="callout callout-warning"><strong>{t}</strong><p>{m}</p></div>'


def _table(headers: list[str], rows: list[list[str]], caption: str = "") -> str:
    cap = f"<caption>{_html.escape(caption)}</caption>" if caption else ""
    h = "<tr>" + "".join(f"<th>{_html.escape(c)}</th>" for c in headers) + "</tr>"
    r = "\n".join(
        "<tr>" + "".join(f"<td>{_html.escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table>\n{cap}\n{h}\n{r}\n</table>"


def _source_ref(source_path: str, data: dict | None) -> str:
    enc = source_path.encode("utf-8")
    sha = hashlib.sha256(enc).hexdigest()[:12]
    sp = _html.escape(source_path)
    schema_version = _html.escape(
        str(data.get("schema_version", "unknown")) if data else "none"
    )
    generated_at = _html.escape(
        str(data.get("generated_at", "unknown")) if data else "unknown"
    )
    return (
        f'<p class="meta">Source: <code class="file-ref">{sp}</code>'
        f" (sha256:{sha}, schema: {schema_version}, generated: {generated_at})</p>"
    )


def _nav_prev_next(
    prev_label: str, prev_href: str, next_label: str, next_href: str, base_path: str
) -> str:
    from rig_relay.docs_renderer.paths import make_relative_link

    p = ""
    n = ""
    if prev_href:
        p = f'<a href="{_html.escape(make_relative_link(prev_href, "..", base_path))}">← {_html.escape(prev_label)}</a>'
    if next_href:
        n = f'<a href="{_html.escape(make_relative_link(next_href, "..", base_path))}"> {_html.escape(next_label)} →</a>'
    if p or n:
        sep = " | " if p and n else ""
        return f'<nav class="page-nav" aria-label="Pagination">{p}{sep}{n}</nav>'
    return ""


def _page_wrapper(
    sm: SiteMeta,
    title: str,
    description: str,
    body: str,
    foot_note: str = "",
    did: str = "",
    collection_title: str = "Test Evidence",
    og_type: str = "article",
) -> str:
    from rig_relay.docs_renderer.paths import make_relative_link

    canonical_url = f"{sm.base_url}/pages/{did}.html" if sm.base_url and did else ""
    og_tags = make_og_tags(canonical_url, title, description, og_type)
    head_tags = make_head_tags(sm, canonical_url, og_tags, relative_root="..")
    home_href = make_relative_link(f"{sm.base_path}/", "..", sm.base_path)
    col_href = make_relative_link(
        f"{sm.base_path}/collections/index.html", "..", sm.base_path
    )
    breadcrumb = (
        f'<p class="eyebrow"><a href="{home_href}">{_html.escape(sm.site_title)}</a>'
        f' / <a href="{col_href}">Evidence Archive</a>'
        f" / {_html.escape(collection_title)}</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_html.escape(title)} — Rig Relay Docs</title>
<meta name="description" content="{_html.escape(description)}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{home_href}">{_html.escape(sm.site_title)}</a>
  </nav>
  {breadcrumb}
  <h1>{_html.escape(title)}</h1>
  <p class="doc-summary">{_html.escape(description)}</p>
</header>
<main id="main" class="doc-page">
  <article>
{body}
  </article>
</main>
<footer>
  {foot_note}
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def _normalize_meta(site_meta: SiteMeta | dict | None) -> SiteMeta:
    if isinstance(site_meta, SiteMeta):
        return site_meta
    return extract_site_meta(site_meta)


def _classification_summary_html(surfaces: list[dict]) -> str:
    rows: list[list[str]] = []
    total = 0
    for sf in surfaces:
        name = _html.escape(str(sf.get("surface_name", "")))
        fc = str(sf.get("file_count", 0))
        tfc = str(sf.get("test_function_count", 0))
        assessment = _html.escape(str(sf.get("seam_coverage_assessment", "")))
        rows.append([name, fc, tfc, assessment])
        total += int(fc) if fc.isdigit() else 0
    if not rows:
        return ""
    table_html = _table(
        ["Stress Surface", "Files", "Functions", "Coverage Assessment"],
        rows,
        caption=f"Test coverage across {len(surfaces)} stress surfaces ({total} files total)",
    )
    return f"<section><h2>Stress Surface Coverage</h2>\n{table_html}\n</section>"


def _known_gaps_html(surfaces: list[dict]) -> str:
    gaps: list[dict] = []
    for sf in surfaces:
        for g in sf.get("critical_gaps", []):
            gaps.append({"surface": sf.get("surface_name", ""), "gap": g})
    if not gaps:
        return "<p>No critical gaps recorded.</p>"
    rows = [
        [_html.escape(str(g.get("surface", ""))), _html.escape(str(g.get("gap", "")))]
        for g in gaps
    ]
    table_html = _table(
        ["Stress Surface", "Critical Gap"],
        rows,
        caption=f"Known Test Seams — {len(gaps)} critical gaps identified",
    )
    return f'<section><h2>Known Test Seams</h2>\n{table_html}\n<p class="meta">These are known gaps in test coverage that have been intentionally deferred. They do not block RC promotion.</p>\n</section>'


def _build_inventory_summary_table(summary: dict, test_inventory: dict) -> str:
    items = [
        ("Total Test Files", "total_test_files"),
        ("Total Test Functions", "total_test_functions"),
        ("Classified Keep", "classified_keep"),
        ("Classified Harden", "classified_harden"),
        ("Classified Replace", "classified_replace"),
        ("Classified Delete", "classified_delete"),
    ]
    rows = [[label, str(summary.get(key, "N/A"))] for label, key in items]
    rows.append([
        "Branch",
        _html.escape(str(summary.get("branch", test_inventory.get("branch", "N/A")))),
    ])
    rows.append(["HEAD SHA", _html.escape(str(test_inventory.get("head_sha", "N/A")))])
    return _table(["Metric", "Value"], rows, caption="Inventory Summary")


def render_test_inventory_page(
    test_inventory: dict | None, site_meta: SiteMeta | dict | None = None
) -> str:
    sm = _normalize_meta(site_meta)
    if test_inventory is None or not test_inventory.get("stress_surfaces"):
        body = _warning_card(
            "Test Inventory",
            "Test inventory data not yet available. Run the test inventory scan to populate this page.",
        )
        return _page_wrapper(
            sm,
            "Test Inventory",
            "Structured evidence of test coverage across all stress surfaces.",
            body,
        )

    summary: dict = test_inventory.get("summary", {})
    surfaces = test_inventory.get("stress_surfaces", [])

    nav = _nav_prev_next(
        "Release Candidate",
        f"{sm.base_path}/collections/release-gate.html",
        "Integrations",
        f"{sm.base_path}/collections/integration-audits.html",
        sm.base_path,
    )

    body = f"""{nav}
<section><h2>Summary</h2>
{_build_inventory_summary_table(summary, test_inventory)}
</section>
{_classification_summary_html(surfaces)}
{_known_gaps_html(surfaces)}
{_source_ref("docs/json/testing/test_inventory.v1.json", test_inventory)}"""

    total_files = str(summary.get("total_test_files", "N/A"))
    total_funcs = str(summary.get("total_test_functions", "N/A"))
    return _page_wrapper(
        sm,
        "Test Inventory",
        f"Structured evidence of test coverage: {total_files} test files, {total_funcs} test functions across {len(surfaces)} stress surfaces.",
        body,
        did="test-inventory",
        collection_title="Test Evidence",
    )


def render_test_classifications_page(
    classifications: dict | None, site_meta: SiteMeta | dict | None = None
) -> str:
    sm = _normalize_meta(site_meta)
    if classifications is None or not classifications:
        body = _warning_card(
            "Test Classifications",
            "Test classification data not yet available. Run the test classifier to populate this page.",
        )
        return _page_wrapper(
            sm,
            "Test Classifications",
            "Taxonomy of test classification markers used across the project.",
            body,
            did="test-classifications",
            collection_title="Test Evidence",
        )

    def_rows: list[list[str]] = []
    for key, desc in sorted(_CLASSIFICATION_DEFS.items()):
        marker_cmd = f"pytest -m {key}"
        def_rows.append([key, desc, f"<code>{_html.escape(marker_cmd)}</code>"])

    def_table = _table(
        ["Classification", "Definition", "Run Command"],
        def_rows,
        caption=f"Test classification taxonomy — {len(def_rows)} markers",
    )

    counts_data = classifications.get("counts", {})
    counts_rows: list[list[str]] = []
    for key in sorted(_CLASSIFICATION_DEFS.keys()):
        count = str(counts_data.get(key, "—"))
        counts_rows.append([key, count])
    counts_table = ""
    if counts_data:
        counts_table = _table(
            ["Classification", "Count"], counts_rows, caption="Tests per classification"
        )
        counts_table = (
            f"<section><h2>Classification Counts</h2>\n{counts_table}\n</section>"
        )

    val_cmds_html = ""
    cmds = classifications.get("validation_commands", [])
    if cmds:
        cmd_items = "\n".join(
            f"<li><code>{_html.escape(str(c))}</code></li>" for c in cmds
        )
        val_cmds_html = (
            f"<section><h2>Validation Commands</h2>\n<ul>{cmd_items}</ul>\n</section>"
        )

    source_note = _source_ref(
        "docs/json/testing/test_classification.v1.jsonl", classifications
    )

    body = f"""<section><h2>Classification Definitions</h2>
{def_table}
</section>
{counts_table}
{val_cmds_html}
{source_note}"""

    return _page_wrapper(
        sm,
        "Test Classifications",
        "Taxonomy of test classification markers: smoke, contract, integration, e2e, adversarial, and more.",
        body,
        did="test-classifications",
        collection_title="Test Evidence",
    )


def render_known_seams_page(
    seams: list | None, site_meta: SiteMeta | dict | None = None
) -> str:
    sm = _normalize_meta(site_meta)
    if seams is None or not seams:
        body = _warning_card(
            "Known Test Seams",
            "Known test seams data not yet available. Run the seam scanner to populate this page.",
        )
        return _page_wrapper(
            sm,
            "Known Test Seams",
            "Known gaps in test coverage that have been intentionally deferred.",
            body,
            did="known-test-seams",
            collection_title="Test Evidence",
        )

    rows: list[list[str]] = []
    for i, s in enumerate(seams):
        sid = _html.escape(str(s.get("protected_seam", s.get("seam_id", f"seam-{i}"))))
        desc = _html.escape(str(s.get("reason", s.get("description", ""))))
        area = _html.escape(str(s.get("stress_surface", "")))
        classification = _html.escape(str(s.get("classification", "")))
        priority_map = {"resolved": "Resolved", "open_blocker": "Blocking"}
        priority = priority_map.get(classification, classification.capitalize())
        deferral = _html.escape(str(s.get("reason", "")))
        rows.append([sid, desc, area, priority, deferral])

    table_html = _table(
        ["Seam ID", "Description", "Stress Surface", "Status", "Details"],
        rows,
        caption=f"Known Test Seams — {len(seams)} entries",
    )

    source_note = ""
    if seams and isinstance(seams[0], dict):
        source_note = _source_ref(
            "docs/json/testing/known_test_seams.v1.jsonl", seams[0] if seams else {}
        )

    body = f"""<section><h2>Seam Inventory</h2>
{table_html}
</section>
<section>
<h2>Context</h2>
<p>These are known gaps in test coverage that have been intentionally deferred. They do not block RC promotion. Each seam was evaluated against the test classification taxonomy and marked with a priority and deferral reason.</p>
</section>
{source_note}"""

    return _page_wrapper(
        sm,
        "Known Test Seams",
        "Known gaps in test coverage that have been intentionally deferred — do not block RC promotion.",
        body,
        did="known-test-seams",
        collection_title="Test Evidence",
    )


def load_test_artifacts() -> dict:
    result: dict[str, object] = {"inventory": None, "classifications": None}
    if _TEST_INVENTORY_PATH.is_file():
        try:
            result["inventory"] = json.loads(
                _TEST_INVENTORY_PATH.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            pass
    if _TEST_CLASSIFICATION_PATH.is_file():
        try:
            rows: list[dict] = []
            for line in _TEST_CLASSIFICATION_PATH.read_text(
                encoding="utf-8"
            ).splitlines():
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
            result["classifications"] = rows
        except (json.JSONDecodeError, OSError):
            pass
    return result

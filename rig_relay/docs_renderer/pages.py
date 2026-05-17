"""Page renderers: document pages, code schema pages, threat model pages."""

from __future__ import annotations

import html as _html

from rig_relay.docs_renderer.blocks import render_block
from rig_relay.docs_renderer.metadata import (
    extract_site_meta,
    make_head_tags,
    make_og_tags,
)
from rig_relay.docs_renderer.models import SiteMeta


def make_breadcrumb(
    sm: SiteMeta, site_manifest: dict | None, collection_title: str, did: str
) -> str:
    if not collection_title:
        return ""
    site_title_html = _html.escape(sm.site_title)
    cid = ""
    if site_manifest:
        for col in site_manifest.get("collections", []):
            if col.get("title") == collection_title:
                cid = col.get("collection_id", "")
                break
    if cid:
        return f'<p class="eyebrow"><a href="{sm.base_path}/">{site_title_html}</a> / <a href="{sm.base_path}/collections/{cid}.html">{_html.escape(collection_title)}</a></p>\n'
    return f'<p class="eyebrow"><a href="{sm.base_path}/">{site_title_html}</a> / {_html.escape(collection_title)}</p>\n'


def build_toc(data: dict) -> str:
    doc_disc = data.get("disclosure", {})
    if not doc_disc.get("show_table_of_contents", False):
        return ""
    headings: list[tuple[int, str, str]] = []
    for s in data.get("sections", []):
        if s.get("type") == "heading":
            hlevel = s.get("level", 2)
            hcontent = str(s.get("content", ""))
            hid = str(s.get("block_id", ""))
            if hcontent and hid:
                headings.append((hlevel, hcontent, hid))
    if not headings:
        return ""
    toc_items = "\n".join(
        f'<li><a href="#{_html.escape(h[2], quote=True)}">{_html.escape(h[1])}</a></li>'
        for h in headings
    )
    return (
        f'<nav class="doc-toc" aria-label="Table of contents">\n'
        f"  <h2>On this page</h2>\n"
        f"  <ol>\n{toc_items}\n  </ol>\n"
        f"</nav>\n"
    )


def find_collection_title(site_manifest: dict | None, did: str) -> str:
    if not site_manifest:
        return ""
    for col in site_manifest.get("collections", []):
        for doc in col.get("documents", []):
            if doc.get("document_id") == did:
                return str(col.get("title", ""))
    return ""


def render_document_page(data: dict, site_manifest: dict | None = None) -> str:
    title = _html.escape(str(data.get("title", "Untitled")))
    summary = _html.escape(str(data.get("summary", "")))
    did = str(data.get("document_id", ""))
    status = _html.escape(str(data.get("status", "draft")))
    updated = _html.escape(str(data.get("updated_at", data.get("created_at", ""))))
    source_path = str(data.get("_source_path", data.get("canonical_path", "")))
    doc_disc = data.get("disclosure", {})

    sm = extract_site_meta(site_manifest)
    canonical_url = f"{sm.base_url}/pages/{did}.html" if sm.base_url else ""

    collection_title = find_collection_title(site_manifest, did)
    breadcrumb = make_breadcrumb(sm, site_manifest, collection_title, did)
    toc_html = build_toc(data)

    sections_html = "\n".join(
        render_block(s, doc_disc) for s in data.get("sections", [])
    )
    og_tags = make_og_tags(canonical_url, title, summary, "article")
    head_tags = make_head_tags(sm, canonical_url, og_tags)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{summary}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{sm.base_path}/">{_html.escape(sm.site_title)}</a>
  </nav>
  {breadcrumb}  <h1>{title}</h1>
  <p class="doc-summary">{summary}</p>
  <dl class="doc-meta">
    <dt>Status</dt><dd>{status}</dd>
    {"<dt>Updated</dt><dd>" + updated + "</dd>" if updated else ""}
    {"<dt>Source</dt><dd><code>" + _html.escape(source_path) + "</code></dd>" if source_path else ""}
  </dl>
</header>
<div class="page-controls">
  <div class="disclosure-controls" role="group" aria-label="Disclosure level"></div>
  <div class="expand-collapse-controls" role="group" aria-label="Expand/collapse"></div>
</div>
<main
  id="main"
  class="doc-page"
  data-render-strategy="{doc_disc.get("render_strategy", "linear")}"
  data-default-disclosure-level="{doc_disc.get("default_level", "standard")}"
  data-initial-mode="{doc_disc.get("initial_mode", "reviewer")}">
  <article>
{toc_html}{sections_html}
  </article>
</main>
<footer>
  {"<p>Generated from <code>" + _html.escape(source_path) + "</code></p>" if source_path else ""}
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def render_code_schema(
    data: dict, source_path: str, site_manifest: dict | None = None
) -> str:
    title = _html.escape(str(data.get("title", "Untitled")))
    summary = _html.escape(str(data.get("summary", "")))
    status = _html.escape(str(data.get("status", "draft")))
    updated = _html.escape(str(data.get("updated_at", data.get("created_at", ""))))
    schema_id = _html.escape(str(data.get("schema_id", "")))
    change_kind = _html.escape(str(data.get("change_kind", "")))
    model_summary = _html.escape(str(data.get("model_facing_summary", "")))

    sm = extract_site_meta(site_manifest)
    did = str(data.get("document_id", ""))
    head_tags = make_head_tags(
        sm,
        f"{sm.base_url}/pages/{did}.html" if sm.base_url else "",
        make_og_tags(
            f"{sm.base_url}/pages/{did}.html" if sm.base_url else "",
            title,
            summary,
            "article",
        ),
    )

    def _list(items: object) -> str:
        if not isinstance(items, list) or not items:
            return "<li>None</li>"
        return "\n".join(f"<li>{_html.escape(str(item))}</li>" for item in items)

    authority = data.get("authority", {})
    context_pack = data.get("context_pack", {})

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{summary}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{sm.base_path}/">{_html.escape(sm.site_title)}</a>
  </nav>
  <h1>{title}</h1>
  <p class="doc-summary">{summary}</p>
  <dl class="doc-meta">
    <dt>Status</dt><dd>{status}</dd>
    {"<dt>Updated</dt><dd>" + updated + "</dd>" if updated else ""}
    <dt>Source</dt><dd><code>{_html.escape(source_path)}</code></dd>
  </dl>
</header>
<main id="main" class="doc-page">
  <article>
    <h2>Metadata</h2>
    <table>
      <tr><th>Schema ID</th><td>{schema_id}</td></tr>
      <tr><th>Change kind</th><td>{change_kind}</td></tr>
      <tr><th>Source</th><td class="file-ref"><code>{_html.escape(source_path)}</code></td></tr>
    </table>
  </section>
  <section>
    <h2>Authority</h2>
    <table>
      <tr><th>Authority kind</th><td>{_html.escape(str(authority.get("authority_kind", "")))}</td></tr>
      <tr><th>Trusted</th><td>{_html.escape(str(authority.get("trusted", False)))}</td></tr>
      <tr><th>Source path</th><td class="file-ref"><code>{_html.escape(str(authority.get("source_path", "")))}</code></td></tr>
      <tr><th>Review status</th><td>{_html.escape(str(authority.get("review_status", "")))}</td></tr>
      <tr><th>Last reviewed</th><td>{_html.escape(str(authority.get("last_reviewed_at", "")))}</td></tr>
    </table>
  </section>
  <section>
    <h2>Model Summary</h2>
    <p>{model_summary}</p>
  </section>
  <section>
    <h2>Required Invariants</h2>
    <ul>{_list(data.get("required_invariants", []))}</ul>
  </section>
  <section>
    <h2>Forbidden Patterns</h2>
    <ul>{_list(data.get("forbidden_patterns", []))}</ul>
  </section>
  <section>
    <h2>Required Files</h2>
    <ul>{_list(data.get("required_files", []))}</ul>
  </section>
  <section>
    <h2>Required Tests</h2>
    <ul>{_list(data.get("required_tests", []))}</ul>
  </section>
  <section>
    <h2>Required Trace Events</h2>
    <ul>{_list(data.get("required_trace_events", []))}</ul>
  </section>
  <section>
    <h2>Validation Commands</h2>
    <ul>{_list(data.get("validation_commands", []))}</ul>
  </section>
  <section>
    <h2>Context Pack</h2>
    <h3>Include Files</h3>
    <ul>{_list(context_pack.get("include_files", []))}</ul>
    <h3>Include Docs</h3>
    <ul>{_list(context_pack.get("include_docs", []))}</ul>
    <h3>Include Schemas</h3>
    <ul>{_list(context_pack.get("include_schemas", []))}</ul>
    <h3>Exclude Patterns</h3>
    <ul>{_list(context_pack.get("exclude_patterns", []))}</ul>
  </section>
</article>
</main>
<footer>
  <p>Generated from <code>{_html.escape(data.get("canonical_path", source_path))}</code></p>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def render_threat_model(
    data: dict, source_path: str, site_manifest: dict | None = None
) -> str:
    title = _html.escape(str(data.get("title", "Untitled")))
    summary = _html.escape(str(data.get("summary", "")))
    status = _html.escape(str(data.get("status", "draft")))
    updated = _html.escape(str(data.get("updated_at", data.get("created_at", ""))))

    sm = extract_site_meta(site_manifest)
    did = str(data.get("document_id", data.get("threat_model_id", "")))
    head_tags = make_head_tags(
        sm,
        f"{sm.base_url}/pages/{did}.html" if sm.base_url else "",
        make_og_tags(
            f"{sm.base_url}/pages/{did}.html" if sm.base_url else "",
            title,
            summary,
            "article",
        ),
    )

    def _esc(v: object) -> str:
        return _html.escape(str(v)) if v else ""

    def _li(items: object) -> str:
        if not isinstance(items, list) or not items:
            return "<li>None</li>"
        return "\n".join(f"<li>{_html.escape(str(i))}</li>" for i in items)

    def _badge(color: str, text: str) -> str:
        return f'<span class="badge" style="background:{color}">{_html.escape(text)}</span>'

    assets_html = ""
    for a in data.get("assets", []):
        obj_list = ", ".join(a.get("security_objectives", []))
        assets_html += f"""<tr>
  <td>{_esc(a.get("asset_id"))}</td>
  <td>{_esc(a.get("name"))}</td>
  <td>{_esc(a.get("classification"))}</td>
  <td>{_esc(a.get("owner_area"))}</td>
  <td>{obj_list}</td>
</tr>\n"""

    boundaries_html = ""
    for b in data.get("trust_boundaries", []):
        boundaries_html += f"""<tr>
  <td>{_esc(b.get("boundary_id"))}</td>
  <td>{_esc(b.get("name"))}</td>
  <td>{_esc(b.get("source_zone"))} → {_esc(b.get("target_zone"))}</td>
  <td>{_esc(b.get("data_crossing"))}</td>
</tr>\n"""

    _pc = {
        "critical": "#dc3545",
        "high": "#fd7e14",
        "medium": "#ffc107",
        "low": "#28a745",
    }
    threats_html = ""
    for t in data.get("threats", []):
        rb = "⚠ Release Blocker" if t.get("release_blocker") else ""
        threats_html += f"""<tr>
  <td>{_esc(t.get("threat_id"))}</td>
  <td>{_esc(t.get("name"))}</td>
  <td>{_esc(t.get("category"))}</td>
  <td>{_badge(_pc.get(t.get("priority", "low"), "#6c757d"), t.get("priority", "low"))}</td>
  <td>{_badge("#6c757d", t.get("status", "open"))}</td>
  <td>{_esc(rb)}</td>
</tr>\n"""

    gates_html = ""
    for g in data.get("release_gates", []):
        rb = "⚠ Release Blocker" if g.get("release_blocker") else ""
        gates_html += f"""<tr>
  <td>{_esc(g.get("gate_id"))}</td>
  <td>{_esc(g.get("name"))}</td>
  <td>{_esc(rb)}</td>
  <td>{_esc(g.get("pass_condition"))}</td>
</tr>\n"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{summary}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{sm.base_path}/">{_html.escape(sm.site_title)}</a>
  </nav>
  <h1>{title}</h1>
  <p class="doc-summary">{summary}</p>
  <dl class="doc-meta">
    <dt>Status</dt><dd>{status}</dd>
    {"<dt>Updated</dt><dd>" + updated + "</dd>" if updated else ""}
    <dt>Source</dt><dd><code>{_html.escape(source_path)}</code></dd>
  </dl>
</header>
<main id="main" class="doc-page">
  <article>
    <section><h2>Scope</h2><p>{_esc(data.get("scope", {}).get("description", ""))}</p></section>
    <section><h2>Assets ({len(data.get("assets", []))})</h2><table><tr><th>Asset ID</th><th>Name</th><th>Classification</th><th>Owner</th><th>Security Objectives</th></tr>{assets_html}</table></section>
    <section><h2>Trust Boundaries ({len(data.get("trust_boundaries", []))})</h2><table><tr><th>ID</th><th>Name</th><th>Zone Flow</th><th>Data Crossing</th></tr>{boundaries_html}</table></section>
    <section><h2>Entry Points</h2><ul>{_li([f"{e.get('name', '')} ({e.get('protocol', '')})" for e in data.get("entry_points", [])])}</ul></section>
    <section><h2>Threats ({len(data.get("threats", []))})</h2><table><tr><th>ID</th><th>Name</th><th>Category</th><th>Priority</th><th>Status</th><th>Blocker</th></tr>{threats_html}</table>
    <details><summary>Threat Details</summary>{"".join(f"<h4>{_esc(t.get('threat_id'))}: {_esc(t.get('name'))}</h4><p>{_esc(t.get('description'))}</p><p><strong>Attack scenario:</strong> {_esc(t.get('attack_scenario', ''))}</p><p><strong>Existing mitigations:</strong></p><ul>{_li(t.get('existing_mitigations', []))}</ul><p><strong>Missing mitigations:</strong></p><ul>{_li(t.get('missing_mitigations', []))}</ul><p><strong>Detection signals:</strong></p><ul>{_li(t.get('detection_signals', []))}</ul>" for t in data.get("threats", []))}</details></section>
    <section><h2>Release Gates ({len(data.get("release_gates", []))})</h2><table><tr><th>ID</th><th>Name</th><th>Blocker</th><th>Pass Condition</th></tr>{gates_html}</table></section>
    <section><h2>References</h2><ul>{_li([f"{r.get('anchor_name', '')}: {r.get('relevance', '')}" for r in data.get("references", [])])}</ul></section>
    <section><h2>Deferred Items</h2><ul>{_li([f"{d.get('name', '')} — {d.get('reason', '')}" for d in data.get("deferred_items", [])])}</ul></section>
  </article>
</main>
<footer>
  <p>Generated from <code>{_html.escape(source_path)}</code></p>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def _audit_esc(v: object) -> str:
    return _html.escape(str(v)) if v else ""


def _audit_badge(color: str, text: str) -> str:
    return f'<span class="badge" style="background:{color}">{_html.escape(text)}</span>'


def _audit_list(items: list) -> str:
    if not items:
        return "<p>None</p>"
    return "<ul>" + "".join(f"<li>{_audit_esc(i)}</li>" for i in items) + "</ul>"


def _audit_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "<p>None</p>"
    h = "<tr>" + "".join(f"<th>{_audit_esc(c)}</th>" for c in headers) + "</tr>"
    r = "\n".join(
        "<tr>" + "".join(f"<td>{_audit_esc(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table>{h}\n{r}\n</table>"


_PRIORITY_COLORS = {
    "critical": "#dc3545",
    "high": "#fd7e14",
    "medium": "#ffc107",
    "low": "#28a745",
}


def _build_audit_registration_section(app_reg: dict) -> str:
    e = _audit_esc
    return f"""<section>
  <h2>App Registration</h2>
  <dl>
    <dt>App name recommendation</dt><dd>{e(app_reg.get("app_name_recommendation"))}</dd>
    <dt>Owner type</dt><dd>{e(app_reg.get("owner_type"))}</dd>
    <dt>Homepage URL</dt><dd>{e(app_reg.get("homepage_url"))}</dd>
    <dt>Callback URL needed</dt><dd>{app_reg.get("callback_url_needed")}</dd>
    <dt>Setup URL needed</dt><dd>{app_reg.get("setup_url_needed")}</dd>
    <dt>Webhook URL needed</dt><dd>{app_reg.get("webhook_url_needed")}</dd>
    <dt>Webhook secret required</dt><dd>{app_reg.get("webhook_secret_required")}</dd>
    <dt>SSL verification required</dt><dd>{app_reg.get("ssl_verification_required")}</dd>
    <dt>Public/private</dt><dd>{e(app_reg.get("public_or_private"))}</dd>
    <dt>Device flow needed</dt><dd>{app_reg.get("device_flow_needed")}</dd>
    <dt>User authorization needed</dt><dd>{app_reg.get("user_authorization_needed")}</dd>
    <dt>Notes</dt><dd>{e(app_reg.get("notes"))}</dd>
  </dl>
</section>"""


def _build_audit_profiles_section(profiles: list[dict]) -> str:
    e = _audit_esc
    li = _audit_list
    tbl = _audit_table
    rows = []
    details = []
    for p in profiles:
        perms = ", ".join(
            f"{k}: {v}" for k, v in p.get("repository_permissions", {}).items()
        )
        rows.append([
            p.get("profile_id", ""),
            p.get("title", ""),
            p.get("use_case", ""),
            p.get("minimum_for_phase", ""),
            perms,
        ])
        details.append(
            f"<details><summary>{e(p.get('profile_id'))}: {e(p.get('title'))}</summary>"
            f"<p>{e(p.get('description'))}</p><p><strong>Rationale:</strong> {e(p.get('rationale'))}</p>"
            f"<p><strong>Risks:</strong></p>{li(p.get('risks', []))}"
            f"<p><strong>User consent copy:</strong> {e(p.get('user_consent_copy'))}</p></details>"
        )
    return f"""<section>
  <h2>Permission Profiles ({len(profiles)})</h2>
  {tbl(["ID", "Title", "Use Case", "Phase", "Repo Permissions"], rows)}
  {"".join(details)}
</section>"""


def _build_audit_webhooks_section(webhooks: list[dict]) -> str:
    tbl = _audit_table
    rows = []
    for w in webhooks:
        actions = ", ".join(w.get("actions", [])) or "*"
        rows.append([
            w.get("event_name", ""),
            actions,
            w.get("risk_level", "low"),
            w.get("handler_component", ""),
        ])
    return f"""<section>
  <h2>Webhook Subscriptions ({len(webhooks)})</h2>
  {tbl(["Event", "Actions", "Risk", "Handler"], rows)}
</section>"""


def _build_audit_flows_section(flows: list[dict]) -> str:
    tbl = _audit_table
    rows = [
        [
            f.get("flow_id", ""),
            f.get("title", ""),
            f"{f.get('source', '')} → {f.get('destination', '')}",
            f.get("trigger", ""),
        ]
        for f in flows
    ]
    return f"""<section>
  <h2>Data Flows ({len(flows)})</h2>
  {tbl(["ID", "Title", "Flow", "Trigger"], rows)}
</section>"""


def _build_audit_boundaries_section(boundaries: list[dict]) -> str:
    e = _audit_esc
    li = _audit_list
    tbl = _audit_table
    rows = []
    details = []
    for bd in boundaries:
        rows.append([
            bd.get("boundary_id", ""),
            f"{bd.get('source_zone', '')} → {bd.get('target_zone', '')}",
            "Authority change" if bd.get("authority_change") else "No auth change",
            bd.get("data_crossing", ""),
        ])
        details.append(
            f"<details><summary>{e(bd.get('boundary_id'))}</summary>"
            f"<p><strong>Threats:</strong></p>{li(bd.get('threats', []))}"
            f"<p><strong>Controls:</strong></p>{li(bd.get('controls', []))}"
            f"<p><strong>Required Tests:</strong></p>{li(bd.get('required_tests', []))}</details>"
        )
    return f"""<section>
  <h2>Trust Boundaries ({len(boundaries)})</h2>
  {tbl(["ID", "Zone Flow", "Authority", "Data"], rows)}
  {"".join(details)}
</section>"""


def _build_audit_controls_section(controls: list[dict]) -> str:
    tbl = _audit_table
    rows = [
        [
            c.get("control_id", ""),
            c.get("title", ""),
            c.get("status", "planned"),
            c.get("description", ""),
        ]
        for c in controls
    ]
    return f"""<section>
  <h2>Security Controls ({len(controls)})</h2>
  {tbl(["ID", "Title", "Status", "Description"], rows)}
</section>"""


def _build_audit_trace_section(events: list[dict]) -> str:
    tbl = _audit_table
    rows = [
        [
            ev.get("event_name", ""),
            ev.get("source_component", ""),
            str(ev.get("safe_to_log", True)),
            ", ".join(ev.get("correlation_fields", [])),
        ]
        for ev in events
    ]
    return f"""<section>
  <h2>Trace Events ({len(events)})</h2>
  {tbl(["Event Name", "Source Component", "Safe to Log", "Correlation Fields"], rows)}
</section>"""


def _build_audit_storage_section(storage_model: dict) -> str:
    li = _audit_list
    tbl = _audit_table
    rows = [
        [
            a.get("artifact_path", ""),
            a.get("content_type", ""),
            "Secrets" if a.get("contains_secrets") else "No secrets",
            a.get("format", ""),
        ]
        for a in storage_model.get("artifacts", [])
    ]
    return f"""<section>
  <h2>Storage Model</h2>
  {tbl(["Path", "Content", "Secrets", "Format"], rows)}
  <h3>Rules</h3>
  {li(storage_model.get("rules", []))}
</section>"""


def _build_audit_ui_section(states: list[dict]) -> str:
    tbl = _audit_table
    rows = [
        [u.get("state_id", ""), u.get("title", ""), u.get("empty_state_copy", "")]
        for u in states
    ]
    return f"""<section>
  <h2>UI States ({len(states)})</h2>
  {tbl(["ID", "Title", "Empty State"], rows)}
</section>"""


def _build_audit_phases_section(phases: list[dict]) -> str:
    tbl = _audit_table
    rows = [
        [
            p.get("phase_id", ""),
            p.get("title", ""),
            p.get("goal", ""),
            "Blocked by: " + (", ".join(p.get("blocked_by", [])) or "None"),
        ]
        for p in phases
    ]
    return f"""<section>
  <h2>Implementation Phases ({len(phases)})</h2>
  {tbl(["ID", "Title", "Goal", "Dependencies"], rows)}
</section>"""


def _build_audit_risks_section(risks: list[dict]) -> str:
    e = _audit_esc
    li = _audit_list
    tbl = _audit_table
    rows = []
    details = []
    for r in risks:
        rb = "⚠ Release Blocker" if r.get("release_blocker") else ""
        rows.append([
            r.get("risk_id", ""),
            r.get("title", ""),
            r.get("severity", "low"),
            rb,
        ])
        details.append(
            f"<details><summary>{e(r.get('risk_id'))}: {e(r.get('title'))}</summary><p>{e(r.get('description'))}</p><p><strong>Mitigations:</strong></p>{li(r.get('mitigations', []))}</details>"
        )
    return f"""<section>
  <h2>Risks ({len(risks)})</h2>
  {tbl(["ID", "Title", "Severity", "Blocker"], rows)}
  {"".join(details)}
</section>"""


def _build_audit_gates_section(gates: list[dict]) -> str:
    tbl = _audit_table
    rows = [
        [
            g.get("gate_id", ""),
            g.get("title", ""),
            "⚠ Release Blocker" if g.get("release_blocker") else "",
            g.get("pass_condition", ""),
        ]
        for g in gates
    ]
    return f"""<section>
  <h2>Release Gates ({len(gates)})</h2>
  {tbl(["ID", "Title", "Blocker", "Pass Condition"], rows)}
</section>"""


def _build_audit_remaining_sections(data: dict) -> str:
    e = _audit_esc
    li = _audit_list
    parts: list[str] = []
    parts.append(
        f"""<section>
  <h2>Open Questions</h2>
  {"".join(f"<details><summary>{e(q.get('question'))}</summary><p>{e(q.get('context'))}</p><p>Needed for: {e(q.get('needed_for_phase'))}</p></details>" for q in data.get("open_questions", []))}
</section>"""
    )
    parts.append(
        f"""<section>
  <h2>Backend Components ({len(data.get("backend_components", []))})</h2>
  {"".join(f"<details><summary>{e(c.get('component_id'))} — {e(c.get('module_path'))}</summary>{li(c.get('responsibilities', []))}</details>" for c in data.get("backend_components", []))}
</section>"""
    )
    parts.append(
        f"""<section>
  <h2>Frontend Components ({len(data.get("frontend_components", []))})</h2>
  {"".join(f"<details><summary>{e(c.get('component_id'))}: {e(c.get('title'))}</summary><p>{e(c.get('description'))}</p><p><strong>Must never display:</strong></p>{li(c.get('must_never_display', []))}</details>" for c in data.get("frontend_components", []))}
</section>"""
    )
    return "\n".join(parts)


def _build_audit_body(data: dict) -> str:
    return "\n".join([
        _build_audit_registration_section(data.get("app_registration", {})),
        _build_audit_profiles_section(data.get("permission_profiles", [])),
        _build_audit_webhooks_section(data.get("webhook_subscriptions", [])),
        _build_audit_flows_section(data.get("data_flows", [])),
        _build_audit_boundaries_section(data.get("trust_boundaries", [])),
        _build_audit_controls_section(data.get("security_controls", [])),
        _build_audit_trace_section(data.get("trace_events", [])),
        _build_audit_storage_section(data.get("storage_model", {})),
        _build_audit_ui_section(data.get("ui_states", [])),
        _build_audit_phases_section(data.get("implementation_phases", [])),
        _build_audit_risks_section(data.get("risks", [])),
        _build_audit_gates_section(data.get("release_gates", [])),
        _build_audit_remaining_sections(data),
    ])


def render_integration_audit(
    data: dict, source_path: str, site_manifest: dict | None = None
) -> str:
    title = _html.escape(str(data.get("title", "Untitled")))
    summary = _html.escape(str(data.get("summary", "")))
    status = _html.escape(str(data.get("status", "draft")))
    updated = _html.escape(str(data.get("updated_at", data.get("created_at", ""))))
    did = str(data.get("audit_id", ""))
    source_commit = _html.escape(str(data.get("source_commit", "")))

    sm = extract_site_meta(site_manifest)
    collection_title = find_collection_title(site_manifest, did)
    breadcrumb = make_breadcrumb(sm, site_manifest, collection_title, did)
    head_tags = make_head_tags(
        sm,
        f"{sm.base_url}/pages/{did}.html" if sm.base_url else "",
        make_og_tags(
            f"{sm.base_url}/pages/{did}.html" if sm.base_url else "",
            title,
            summary,
            "article",
        ),
    )

    body = _build_audit_body(data)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{summary}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{sm.base_path}/">{_html.escape(sm.site_title)}</a>
  </nav>
  {breadcrumb}
  <h1>{title}</h1>
  <p class="doc-summary">{summary}</p>
  <dl class="doc-meta">
    <dt>Status</dt><dd>{status}</dd>
    {"<dt>Updated</dt><dd>" + updated + "</dd>" if updated else ""}
    {"<dt>Commit</dt><dd><code>" + source_commit + "</code></dd>" if source_commit else ""}
    <dt>Source</dt><dd><code>{_html.escape(source_path)}</code></dd>
  </dl>
</header>
<main id="main" class="doc-page">
  <article>
    <section><h2>Product Intent</h2><p>{_audit_esc(data.get("summary"))}</p></section>
{body}
  </article>
</main>
<footer>
  <p>Generated from <code>{_html.escape(source_path)}</code></p>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""

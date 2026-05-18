from __future__ import annotations

import html as _html
import json

from rig_relay.docs_renderer.metadata import make_head_tags, make_og_tags
from rig_relay.docs_renderer.models import SiteMeta
from rig_relay.docs_renderer.paths import REPO_ROOT, make_relative_link


def _esc(v: object) -> str:
    return _html.escape(str(v)) if v else ""


def _badge(status: str) -> str:
    colors = {
        "passed": "#28a745",
        "pass": "#28a745",
        "failed": "#dc3545",
        "fail": "#dc3545",
        "warning": "#ffc107",
        "warn": "#ffc107",
    }
    color = colors.get(str(status).lower(), "#6c757d")
    return f'<span class="badge" style="background:{color}">{_esc(status)}</span>'


def _warning_card(message: str) -> str:
    return f'<div class="callout callout-warning"><strong>Warning</strong><p>{_html.escape(message)}</p></div>'


def _shell_html(
    title: str, summary: str, body: str, sm: SiteMeta, canonical_path: str
) -> str:
    canonical_url = f"{sm.base_url}/pages/{canonical_path}" if sm.base_url else ""
    og_tags = make_og_tags(canonical_url, title, summary, "article")
    head_tags = make_head_tags(sm, canonical_url, og_tags, relative_root="..")
    home_href = make_relative_link(f"{sm.base_path}/", "..", sm.base_path)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{_esc(summary)}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{home_href}">{_esc(sm.site_title)}</a>
  </nav>
  <h1>{title}</h1>
  <p class="doc-summary">{_esc(summary)}</p>
</header>
<main id="main" class="doc-page">
  <article>
{body}
  </article>
</main>
<footer>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def load_security_artifacts() -> dict:
    result: dict[str, object] = {}
    policy_path = (
        REPO_ROOT / "docs" / "json" / "security" / "security_policy_v0.v1.json"
    )
    if policy_path.is_file():
        result["policy"] = json.loads(policy_path.read_text(encoding="utf-8"))
    hygiene_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "release_candidate"
        / "rc_security_repository_hygiene.v1.json"
    )
    if hygiene_path.is_file():
        result["hygiene"] = json.loads(hygiene_path.read_text(encoding="utf-8"))
    return result


def _policy_section_card(section: dict) -> str:
    stype = section.get("type", "paragraph")
    title = section.get("title", "")
    content = section.get("content", "")
    items = section.get("items", [])
    if stype == "paragraph" and content:
        return (
            f'<div class="policy-card">'
            f"<h3>{_esc(title)}</h3>"
            f"<p>{_esc(content)}</p>"
            f"</div>"
        )
    if stype == "list" and items:
        items_html = "\n".join(f"<li>{_esc(i)}</li>" for i in items)
        return (
            f'<div class="policy-card">'
            f"<h3>{_esc(title)}</h3>"
            f"<ul>{items_html}</ul>"
            f"</div>"
        )
    if title:
        return f'<div class="policy-card"><h3>{_esc(title)}</h3></div>'
    return ""


def render_security_policy_page(policy: dict | None, site_meta: SiteMeta) -> str:
    if policy is None:
        return _shell_html(
            "Security Policy",
            "Security policy not available",
            _warning_card("Security policy not available"),
            site_meta,
            "security-policy.html",
        )

    title = _esc(policy.get("title", "Security Policy"))
    summary = _esc(policy.get("summary", ""))
    status = _esc(policy.get("status", ""))
    updated = _esc(policy.get("updated_at", policy.get("created_at", "")))
    canonical_path = _esc(
        policy.get("canonical_path", "docs/json/security/security_policy_v0.v1.json")
    )

    sections = policy.get("sections", [])
    section_map: dict[str, list[dict]] = {}
    for s in sections:
        btitle = s.get("title", "")
        if btitle in {"Reporting"}:
            section_map.setdefault("reporting", []).append(s)
        elif btitle in {
            "Security Posture",
            "Loopback Bridge Expectation",
            "Token Redaction Expectation",
            "No Token in Traces, Docs, or Static Output",
            "Code Schema Trust Rules",
            "Prompt Injection Awareness",
            "WebSocket Origin, Auth, and Message Validation",
            "User-Owned Dirty Files and Mutation Safety",
            "Threat Model",
            "WebSocket Security Hardening Status",
        }:
            section_map.setdefault("security_model", []).append(s)
        elif btitle in {"Supported Versions"}:
            section_map.setdefault("supported_versions", []).append(s)
        elif btitle in {"Disclosure"}:
            section_map.setdefault("disclosure", []).append(s)

    reporting_html = "\n".join(
        _policy_section_card(s) for s in section_map.get("reporting", [])
    )
    security_model_html = "\n".join(
        _policy_section_card(s) for s in section_map.get("security_model", [])
    )
    supported_html = "\n".join(
        _policy_section_card(s) for s in section_map.get("supported_versions", [])
    )
    disclosure_data = policy.get("disclosure", {})
    disclosure_html = ""
    if disclosure_data:
        disclosure_html = (
            f'<div class="policy-card">'
            f"<h3>Disclosure Metadata</h3>"
            f"<table>"
            f"<tr><th>Default Level</th><td>{_esc(disclosure_data.get('default_level', ''))}</td></tr>"
            f"<tr><th>Render Strategy</th><td>{_esc(disclosure_data.get('render_strategy', ''))}</td></tr>"
            f"<tr><th>Available Levels</th><td>{_esc(', '.join(disclosure_data.get('available_levels', [])))}</td></tr>"
            f"<tr><th>Show TOC</th><td>{disclosure_data.get('show_table_of_contents', False)}</td></tr>"
            f"</table></div>"
        )

    body = f"""
    <section><h2>Metadata</h2>
      <dl class="doc-meta">
        <dt>Status</dt><dd>{status}</dd>
        {"<dt>Updated</dt><dd>" + updated + "</dd>" if updated else ""}
        <dt>Source</dt><dd><code>{canonical_path}</code></dd>
      </dl>
    </section>
    {"<section><h2>Reporting</h2>" + reporting_html + "</section>" if reporting_html else ""}
    {"<section><h2>Disclosure</h2>" + disclosure_html + "</section>" if disclosure_html else ""}
    {"<section><h2>Supported Versions</h2>" + supported_html + "</section>" if supported_html else ""}
    {"<section><h2>Security Model</h2>" + security_model_html + "</section>" if security_model_html else ""}
"""

    return _shell_html(title, summary, body, site_meta, "security-policy.html")


def _render_hygiene_checks(checks: list[dict]) -> str:
    return "\n".join(
        f"""<tr>
  <td><code>{_esc(c.get("check_id", ""))}</code></td>
  <td>{_esc(c.get("detail", ""))}</td>
  <td>{_badge(c.get("status", "unknown"))}</td>
</tr>"""
        for c in checks
    )


def _render_hygiene_body(hygiene: dict) -> str:
    overall = hygiene.get("overall_status", "unknown")
    checks = hygiene.get("checks", [])
    statuses: dict[str, int] = {}
    for c in checks:
        s = c.get("status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1

    workflow_findings = hygiene.get("workflow_findings", [])
    wf_section = ""
    if workflow_findings:
        wf_rows = "\n".join(
            f"""<tr>
  <td><code>{_esc(w.get("workflow", ""))}</code></td>
  <td><code>{_esc(w.get("finding_id", ""))}</code></td>
  <td>{_esc(w.get("severity", ""))}</td>
  <td>{_esc(w.get("detail", ""))}</td>
</tr>"""
            for w in workflow_findings
        )
        wf_section = f"<section><h2>Workflow Findings ({len(workflow_findings)})</h2><table><thead><tr><th>Workflow</th><th>Finding</th><th>Severity</th><th>Detail</th></tr></thead><tbody>{wf_rows}</tbody></table></section>"

    files_checked = hygiene.get("files_checked", [])
    files_section = ""
    if files_checked:
        files_section = f"<section><h2>Files Checked ({len(files_checked)})</h2><details><summary>View files</summary><ul>{''.join(f'<li><code>{_esc(f)}</code></li>' for f in files_checked)}</ul></details></section>"

    return f"""
    <section><h2>Summary</h2>
      <div class="callout callout-{"info" if overall == "passed" else "warning"}">
        <strong>Overall Status:</strong> {_badge(overall)}
      </div>
      <dl class="doc-meta">
        <dt>Generated</dt><dd>{_esc(hygiene.get("generated_at", ""))}</dd>
        <dt>Commit</dt><dd><code>{_esc(hygiene.get("head_sha", ""))}</code></dd>
        <dt>Source</dt><dd><code>docs/json/release_candidate/rc_security_repository_hygiene.v1.json</code></dd>
      </dl>
    </section>
    <section><h2>Checks ({len(checks)})</h2>
      <table>
        <thead><tr><th>Check ID</th><th>Description</th><th>Status</th></tr></thead>
        <tbody>{_render_hygiene_checks(checks)}</tbody>
      </table>
    </section>
    <section><h2>Tally</h2>
      <table>
        <tr><th>Passed</th><td>{statuses.get("pass", 0)}</td></tr>
        <tr><th>Failed</th><td>{statuses.get("fail", 0)}</td></tr>
        <tr><th>Warning</th><td>{statuses.get("warning", 0)}</td></tr>
      </table>
    </section>
    {f"<section><h2>Release Gates</h2><p>Hygiene gates depend on all checks passing. Current overall status: {_esc(overall)}.</p></section>"}
    {wf_section}
    {files_section}
"""


def render_security_hygiene_page(hygiene: dict | None, site_meta: SiteMeta) -> str:
    if hygiene is None:
        return _shell_html(
            "Repository Security Hygiene",
            "Repository hygiene data not available",
            _warning_card("Repository hygiene data not available"),
            site_meta,
            "security-hygiene.html",
        )

    body = _render_hygiene_body(hygiene)
    return _shell_html(
        "Repository Security Hygiene",
        "Security repository hygiene checks, release gate alignment, and tally.",
        body,
        site_meta,
        "security-hygiene.html",
    )


def _derive_schema_id(filename: str) -> str:
    return (
        filename.replace(".schema.json", "").replace(".v1.json", "").replace(".v1", "")
    )


def _derive_description(filename: str) -> str:
    sid = _derive_schema_id(filename)
    parts = sid.split(".")
    return (
        parts[-1].replace("_", " ").title()
        if len(parts) > 1
        else sid.replace("_", " ").title()
    )


_DOMAIN_PREFIXES: list[tuple[str, str]] = [
    ("rig.release_gate.", "release_gate"),
    ("rig.release_candidate.", "release_gate"),
    ("rig.relay.", "relay"),
    ("rig.fleet.", "fleet"),
    ("rig.documentation.", "documentation"),
    ("rig.security.", "security"),
    ("rig.ide.", "ide"),
    ("rig.github_app.", "github_app"),
    ("rig.context.", "context"),
    ("rig.bash.", "bash"),
    ("rig.report.", "report"),
    ("rig.ralph.", "ralph"),
    ("rig.tracing.", "tracing"),
    ("rig.trace", "tracing"),
    ("rig.diagram.", "diagram"),
    ("rig.audit.", "audit"),
]


def _domain_from_filename(filename: str) -> str:
    sid = _derive_schema_id(filename)
    for prefix, domain in _DOMAIN_PREFIXES:
        if sid.startswith(prefix):
            return domain
    return "other"


def render_schemas_page(site_meta: SiteMeta) -> str:
    schemas_dir = REPO_ROOT / "docs" / "schemas"
    if not schemas_dir.is_dir():
        return _shell_html(
            "Schema Index",
            "Schema index not available",
            _warning_card("Schemas directory not found. No schemas to index."),
            site_meta,
            "schemas.html",
        )

    schema_files = sorted(schemas_dir.rglob("*.json"))
    if not schema_files:
        return _shell_html(
            "Schema Index",
            "No schemas found",
            _warning_card("No JSON schema files found in docs/schemas/."),
            site_meta,
            "schemas.html",
        )

    groups: dict[str, list[tuple[str, str, str]]] = {}
    for sf in schema_files:
        try:
            rel_path = str(sf.relative_to(REPO_ROOT))
        except ValueError:
            rel_path = sf.name
        fname = sf.name
        schema_id = _derive_schema_id(fname)
        desc = _derive_description(fname)
        domain = _domain_from_filename(fname)
        groups.setdefault(domain, []).append((rel_path, schema_id, desc))

    domain_labels = {
        "release_gate": "Release Gates",
        "relay": "Rig Relay Core",
        "fleet": "Fleet",
        "documentation": "Documentation",
        "security": "Security",
        "ide": "IDE",
        "github_app": "GitHub App",
        "context": "Context",
        "bash": "Bash",
        "report": "Reports",
        "ralph": "Ralph",
        "tracing": "Tracing",
        "diagram": "Diagram",
        "audit": "Audit",
        "other": "Other",
    }

    all_sections = []
    for domain, label in domain_labels.items():
        entries = groups.get(domain, [])
        if not entries:
            continue
        rows = "\n".join(
            f"""<tr>
  <td><code>{_esc(entry[0])}</code></td>
  <td><code>{_esc(entry[1])}</code></td>
  <td>{_esc(entry[2])}</td>
</tr>"""
            for entry in entries
        )
        all_sections.append(
            f"<section><h3>{_esc(label)} ({len(entries)})</h3>"
            f"<table><thead><tr><th>Schema Path</th><th>Schema ID</th><th>Description</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></section>"
        )

    body = f"""<section>
    <h2>Schema Index</h2>
    <p class="callout callout-info">These JSON Schemas define the canonical structure for all Rig Relay structured artifacts.</p>
  </section>
  {"".join(all_sections)}"""

    return _shell_html(
        "Schema Index",
        "Index of all JSON Schema files in docs/schemas/",
        body,
        site_meta,
        "schemas.html",
    )

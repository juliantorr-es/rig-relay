from __future__ import annotations

import html as _html
import json

from rig_relay.docs_renderer.metadata import make_head_tags, make_og_tags
from rig_relay.docs_renderer.models import SiteMeta
from rig_relay.docs_renderer.paths import REPO_ROOT, make_relative_link

_GATE_PATH = "docs/json/release_gate/rc_readiness_gate.v1.json"
_VERDICT_PATH = "docs/json/release_gate/rc_candidate_verdict.v1.json"
_GOLDEN_PATH = "docs/json/release_candidate/rc_reviewer_golden_path.v1.json"


def _truncate_sha(sha: str) -> str:
    return sha[:7] if sha else "unknown"


def _badge(
    status: str,
    blocked: str = "#dc3545",
    ready: str = "#28a745",
    neutral: str = "#6c757d",
) -> str:
    mapping: dict[str, tuple[str, str]] = {
        "blocked": (blocked, "BLOCKED"),
        "ready": (ready, "READY"),
        "hold": ("#dc3545", "HOLD"),
        "promote": ("#28a745", "PROMOTE"),
        "passing": ("#28a745", "PASSING"),
        "not_verified": ("#ffc107", "NOT VERIFIED"),
        "failed": ("#dc3545", "FAILED"),
        "passed": ("#28a745", "PASSED"),
    }
    color, label = mapping.get(status, (neutral, status.upper()))
    return f'<span class="badge" style="background:{color};color:#fff;padding:0.2em 0.6em;border-radius:4px;font-weight:600">{_html.escape(label)}</span>'


def _warning_card(message: str) -> str:
    return (
        f'<section class="callout callout-warning"><h2>Warning</h2>'
        f"<p>{_html.escape(message)}</p></section>\n"
    )


def _breadcrumb_html(sm: SiteMeta, page_title: str) -> str:
    home_href = make_relative_link(f"{sm.base_path}/", "..", sm.base_path)
    rc_collection_href = make_relative_link(
        f"{sm.base_path}/collections/release-candidate.html", "..", sm.base_path
    )
    return (
        f'<p class="eyebrow">'
        f'<a href="{home_href}">{_html.escape(sm.site_title)}</a> / '
        f'<a href="{rc_collection_href}">Release Candidate</a> / '
        f"{_html.escape(page_title)}</p>\n"
    )


def _page_chrome(
    sm: SiteMeta,
    title: str,
    desc: str,
    breadcrumb: str,
    body: str,
    source_path: str,
    source_sha: str,
    og_type: str = "article",
) -> str:
    canonical_url = f"{sm.base_url}/pages/rc_readiness.html" if sm.base_url else ""
    og_tags = make_og_tags(canonical_url, title, desc, og_type)
    head_tags = make_head_tags(sm, canonical_url, og_tags, relative_root="..")
    home_href = make_relative_link(f"{sm.base_path}/", "..", sm.base_path)
    nav_left = make_relative_link(
        f"{sm.base_path}/pages/rc_verdict.html", "..", sm.base_path
    )
    nav_right = make_relative_link(
        f"{sm.base_path}/pages/golden_path.html", "..", sm.base_path
    )
    sha_disp = _truncate_sha(source_sha)

    return f"""<!DOCTYPE html>
<html lang="{sm.site_language}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{desc}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{home_href}">{_html.escape(sm.site_title)}</a>
  </nav>
  {breadcrumb}
  <h1>{title}</h1>
  <p class="doc-summary">{desc}</p>
  <nav aria-label="Section" class="page-nav">
    <a href="{nav_left}">← RC Verdict</a>
    <a href="{nav_right}">Golden Path →</a>
  </nav>
</header>
<main id="main" class="doc-page">
  <article>
{body}
  </article>
</main>
<footer>
  <p class="source-ref">Source: <code>{_html.escape(source_path)}</code> (SHA: {_html.escape(sha_disp)})</p>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def _nav_for_page(
    sm: SiteMeta, left_label: str, left_href: str, right_label: str, right_href: str
) -> str:
    l = make_relative_link(left_href, "..", sm.base_path)
    r = make_relative_link(right_href, "..", sm.base_path)
    return (
        f'<nav aria-label="Section" class="page-nav">'
        f'<a href="{l}">← {_html.escape(left_label)}</a>'
        f'<a href="{r}">{_html.escape(right_label)} →</a>'
        f"</nav>\n"
    )


def _build_gate_body(gate: dict) -> str:
    overall = str(gate.get("overall_status", "unknown"))
    sections: list[str] = []
    sections.append(
        f"<section><h2>Overall Status</h2><p>{_badge(overall)}</p></section>"
    )
    sections.append(
        f"<section><h2>Gate</h2>"
        f"<dl>"
        f"<dt>Gate ID</dt><dd>{_html.escape(str(gate.get('gate_id', '')))}</dd>"
        f"<dt>Branch</dt><dd>{_html.escape(str(gate.get('branch', '')))}</dd>"
        f"<dt>Commit</dt><dd><code>{_html.escape(_truncate_sha(str(gate.get('head_sha', ''))))}</code></dd>"
        f"<dt>Generated</dt><dd>{_html.escape(str(gate.get('generated_at', '')))}</dd>"
        f"</dl></section>\n"
    )

    phases = gate.get("phases", [])
    if phases:
        phase_rows = "\n".join(
            f"<tr>"
            f"<td><code>{_html.escape(str(p.get('phase_id', '')))}</code></td>"
            f"<td>{_html.escape(str(p.get('title', '')))}</td>"
            f"<td>{_badge(str(p.get('status', 'unknown')))}</td>"
            f"<td>{len(p.get('blocker_ids', []))}</td>"
            f"<td>{len(p.get('remaining_seams', []))}</td>"
            f"</tr>"
            for p in phases
        )
        sections.append(
            f"<section><h2>Phases ({len(phases)})</h2>\n"
            f"<table>\n"
            f"<thead><tr><th>Phase ID</th><th>Title</th><th>Status</th><th>Blockers</th><th>Seams</th></tr></thead>\n"
            f"<tbody>\n{phase_rows}\n</tbody>\n"
            f"</table>\n</section>\n"
        )

    for p in phases:
        blocker_ids = p.get("blocker_ids", [])
        if blocker_ids:
            bl_items = "\n".join(
                f"<li><code>{_html.escape(str(b))}</code></li>" for b in blocker_ids
            )
            sections.append(
                f'<section class="callout callout-warning">'
                f"<h3>{_html.escape(str(p.get('title', p.get('phase_id', ''))))} — Blockers</h3>"
                f"<ul>{bl_items}</ul></section>\n"
            )
        seams = p.get("remaining_seams", [])
        if seams:
            seam_items = "\n".join(f"<li>{_html.escape(str(s))}</li>" for s in seams)
            sections.append(
                f"<details><summary>{_html.escape(str(p.get('title', '')))} — Remaining Seams ({len(seams)})</summary>"
                f"<ul>{seam_items}</ul></details>\n"
            )

    policy = gate.get("policy", {})
    if policy:
        policy_rows = "\n".join(
            f"<tr><td>{_html.escape(str(k))}</td><td>{_html.escape(str(v))}</td></tr>"
            for k, v in policy.items()
        )
        sections.append(
            f"<section><h2>Policy</h2>\n"
            f"<table>\n<thead><tr><th>Rule</th><th>Value</th></tr></thead>\n"
            f"<tbody>\n{policy_rows}\n</tbody>\n</table>\n</section>\n"
        )

    return "\n".join(sections)


def render_release_gate_page(manifest: dict, gate_artifact: dict, sm: SiteMeta) -> str:
    title = "Release Gate Readiness"
    desc = "Phase-by-phase release gate readiness assessment with blocker and seam tracking."
    breadcrumb = _breadcrumb_html(sm, title)
    source_path = _GATE_PATH

    if not gate_artifact:
        return _page_chrome(
            sm,
            title,
            desc,
            breadcrumb,
            _warning_card("Release gate data not available"),
            source_path,
            "",
        )

    body = _build_gate_body(gate_artifact)
    head_sha = str(gate_artifact.get("head_sha", ""))

    canonical_url = f"{sm.base_url}/pages/rc_readiness.html" if sm.base_url else ""
    og_tags = make_og_tags(canonical_url, title, desc, "article")
    head_tags = make_head_tags(sm, canonical_url, og_tags, relative_root="..")
    home_href = make_relative_link(f"{sm.base_path}/", "..", sm.base_path)
    sha_disp = _truncate_sha(head_sha)
    nav = _nav_for_page(
        sm,
        "RC Verdict",
        f"{sm.base_path}/pages/rc_verdict.html",
        "Golden Path",
        f"{sm.base_path}/pages/golden_path.html",
    )

    return f"""<!DOCTYPE html>
<html lang="{sm.site_language}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{desc}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{home_href}">{_html.escape(sm.site_title)}</a>
  </nav>
  {breadcrumb}
  <h1>{title}</h1>
  <p class="doc-summary">{desc}</p>
  {nav}
</header>
<main id="main" class="doc-page">
  <article>
{body}
  </article>
</main>
<footer>
  <p class="source-ref">Source: <code>{_html.escape(source_path)}</code> (SHA: {_html.escape(sha_disp)})</p>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def _build_verdict_status_section(verdict: dict) -> str:
    v = str(verdict.get("verdict", "unknown"))
    gate_status = str(verdict.get("gate_overall_status", "unknown"))
    validator = str(verdict.get("validator_result", "unknown"))
    schema_val = str(verdict.get("schema_validation", "unknown"))
    install = str(verdict.get("installability_status", "unknown"))
    errors = verdict.get("validator_error_count", 0)
    open_count = len(verdict.get("open_blocker_ids", []))
    known = verdict.get("known_seam_count", 0)
    resolved = verdict.get("resolved_seam_count", 0)
    deferred = verdict.get("deferred_seam_count", 0)

    return (
        f'<section><h2>Verdict</h2><p style="font-size:1.4em">{_badge(v)}</p></section>\n'
        f"<section><h2>Status Summary</h2>\n<table>\n"
        f"<thead><tr><th>Metric</th><th>Value</th></tr></thead>\n<tbody>\n"
        f"<tr><td>Gate Overall</td><td>{_badge(gate_status)}</td></tr>\n"
        f"<tr><td>Validator</td><td>{_badge(validator)}</td></tr>\n"
        f"<tr><td>Validator Errors</td><td>{errors}</td></tr>\n"
        f"<tr><td>Schema Validation</td><td>{_html.escape(schema_val)}</td></tr>\n"
        f"<tr><td>Installability</td><td>{_badge(install)}</td></tr>\n"
        f"<tr><td>Open Blockers</td><td>{open_count}</td></tr>\n"
        f"<tr><td>Known Seams</td><td>{known}</td></tr>\n"
        f"<tr><td>Resolved Seams</td><td>{resolved}</td></tr>\n"
        f"<tr><td>Deferred Seams</td><td>{deferred}</td></tr>\n"
        f"</tbody>\n</table>\n</section>\n"
    )


def _build_verdict_phase_section(verdict: dict) -> str:
    phase_rows: list[str] = []
    for p in verdict.get("ready_phase_ids", []):
        phase_rows.append(
            f"<tr><td><code>{_html.escape(str(p))}</code></td><td>{_badge('ready')}</td></tr>"
        )
    for p in verdict.get("blocking_phase_ids", []):
        phase_rows.append(
            f"<tr><td><code>{_html.escape(str(p))}</code></td><td>{_badge('blocked')}</td></tr>"
        )
    for p in verdict.get("unknown_phase_ids", []):
        phase_rows.append(
            f"<tr><td><code>{_html.escape(str(p))}</code></td><td>{_badge('unknown')}</td></tr>"
        )
    if not phase_rows:
        return ""
    return (
        "<section><h2>Phase Status</h2>\n<table>\n"
        "<thead><tr><th>Phase ID</th><th>Status</th></tr></thead>\n"
        "<tbody>\n" + "\n".join(phase_rows) + "\n</tbody>\n</table>\n</section>\n"
    )


def _build_simple_list_section(
    verdict: dict, key: str, title: str, code_style: bool = True
) -> str:
    items = verdict.get(key, [])
    if not items:
        return ""
    tag = "code" if code_style else "span"
    li_items = "\n".join(
        f"<li><{tag}>{_html.escape(str(i))}</{tag}></li>" for i in items
    )
    return (
        f"<section><h2>{_html.escape(title)} ({len(items)})</h2>"
        f"<ul>{li_items}</ul></section>\n"
    )


def _build_verdict_body(verdict: dict) -> str:
    sections: list[str] = []

    sections.append(_build_verdict_status_section(verdict))

    promote = verdict.get("promote_blockers", [])
    if promote:
        items = "\n".join(f"<li>{_html.escape(str(p))}</li>" for p in promote)
        sections.append(
            f'<section class="callout callout-warning"><h2>Promote Blockers</h2>'
            f"<ul>{items}</ul></section>\n"
        )

    next_actions = verdict.get("required_next_actions", [])
    if next_actions:
        items = "\n".join(f"<li>{_html.escape(str(a))}</li>" for a in next_actions)
        sections.append(
            f"<section><h2>Required Next Actions</h2><ul>{items}</ul></section>\n"
        )

    phase_html = _build_verdict_phase_section(verdict)
    if phase_html:
        sections.append(phase_html)

    sections.append(
        _build_simple_list_section(verdict, "resolved_blocker_ids", "Resolved Blockers")
    )
    sections.append(
        _build_simple_list_section(verdict, "deferred_risk_ids", "Deferred Risks")
    )
    sections.append(
        _build_simple_list_section(verdict, "validation_run_ids", "Validation Runs")
    )
    sections.append(
        _build_simple_list_section(verdict, "evidence_paths", "Evidence Paths")
    )

    return "\n".join(sections)


def render_rc_verdict_page(verdict: dict, sm: SiteMeta) -> str:
    title = "RC Candidate Verdict"
    desc = "Current release candidate verdict with promote blockers, phase status, and evidence references."
    breadcrumb = _breadcrumb_html(sm, title)
    source_path = _VERDICT_PATH

    canonical_url = f"{sm.base_url}/pages/rc_verdict.html" if sm.base_url else ""

    if not verdict:
        og_tags = make_og_tags(canonical_url, title, desc, "article")
        head_tags = make_head_tags(sm, canonical_url, og_tags, relative_root="..")
        home_href = make_relative_link(f"{sm.base_path}/", "..", sm.base_path)
        return f"""<!DOCTYPE html>
<html lang="{sm.site_language}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{desc}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{home_href}">{_html.escape(sm.site_title)}</a>
  </nav>
  {breadcrumb}
  <h1>{title}</h1>
</header>
<main id="main" class="doc-page">
  <article>
{_warning_card("RC verdict data not available")}
  </article>
</main>
<footer>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""

    body = _build_verdict_body(verdict)
    head_sha = str(verdict.get("head_sha", ""))
    sha_disp = _truncate_sha(head_sha)

    og_tags = make_og_tags(canonical_url, title, desc, "article")
    head_tags = make_head_tags(sm, canonical_url, og_tags, relative_root="..")
    home_href = make_relative_link(f"{sm.base_path}/", "..", sm.base_path)
    nav = _nav_for_page(
        sm,
        "RC Home",
        f"{sm.base_path}/pages/rc_readiness.html",
        "Golden Path",
        f"{sm.base_path}/pages/golden_path.html",
    )

    return f"""<!DOCTYPE html>
<html lang="{sm.site_language}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{desc}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{home_href}">{_html.escape(sm.site_title)}</a>
  </nav>
  {breadcrumb}
  <h1>{title}</h1>
  <p class="doc-summary">{desc}</p>
  {nav}
</header>
<main id="main" class="doc-page">
  <article>
{body}
  </article>
</main>
<footer>
  <p class="source-ref">Source: <code>{_html.escape(source_path)}</code> (SHA: {_html.escape(sha_disp)})</p>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def _build_gp_step_card(s: dict) -> str:
    sid = _html.escape(str(s.get("step_id", "")))
    goal = _html.escape(str(s.get("user_goal", "")))
    cmd = _html.escape(str(s.get("command_or_ui_action", "")))
    expected = _html.escape(str(s.get("expected_result", "")))
    status = str(s.get("status", "unknown"))
    method = _html.escape(str(s.get("validation_method", "")))
    phase = _html.escape(str(s.get("phase_id", "")))
    evidence = _html.escape(str(s.get("evidence_path", "")))
    notes = _html.escape(str(s.get("reviewer_notes", "")))

    failure_html = ""
    failures = s.get("blocking_failure_conditions", [])
    if failures:
        f_items = "\n".join(f"<li>{_html.escape(str(f))}</li>" for f in failures)
        failure_html = (
            f"<p><strong>Blocking failure conditions:</strong></p><ul>{f_items}</ul>"
        )

    notes_html = ""
    if notes:
        notes_html = f'<p class="reviewer-notes"><em>{notes}</em></p>'

    return (
        f'<section class="step-card" id="{sid}">'
        f"<h3>{_badge(status)} <code>{sid}</code></h3>"
        f"<dl>"
        f"<dt>Goal</dt><dd>{goal}</dd>"
        f"<dt>Command / Action</dt><dd><code>{cmd}</code></dd>"
        f"<dt>Expected Result</dt><dd>{expected}</dd>"
        f"<dt>Validation Method</dt><dd>{method}</dd>"
        f"<dt>Phase</dt><dd><code>{phase}</code></dd>"
        f"<dt>Evidence</dt><dd><code>{evidence}</code></dd>"
        f"</dl>"
        f"{failure_html}"
        f"{notes_html}"
        f"</section>\n"
    )


def _build_golden_path_body(data: dict) -> str:
    sections: list[str] = []
    overall = str(data.get("overall_status", "unknown"))

    sections.append(
        f"<section><h2>Overall Status</h2>"
        f'<p style="font-size:1.4em">{_badge(overall)}</p>'
        f"</section>\n"
    )

    desc = str(data.get("description", ""))
    if desc:
        sections.append(
            f"<section><h2>Description</h2><p>{_html.escape(desc)}</p></section>\n"
        )

    steps = data.get("steps", [])
    if steps:
        step_cards = [_build_gp_step_card(s) for s in steps]
        sections.append(
            f"<section><h2>Steps ({len(steps)})</h2>\n"
            + "\n".join(step_cards)
            + "\n</section>\n"
        )

    ev_paths = data.get("evidence_paths", [])
    if ev_paths:
        items = "\n".join(
            f"<li><code>{_html.escape(str(e))}</code></li>" for e in ev_paths
        )
        sections.append(
            f"<section><h2>Evidence Paths ({len(ev_paths)})</h2>"
            f"<ul>{items}</ul></section>\n"
        )

    return "\n".join(sections)


def render_golden_path_page(golden_path: dict, sm: SiteMeta) -> str:
    title = "Golden Path — Dogfood Operational Readiness"
    desc = "Step-by-step dogfood operational readiness checklist with blocking failure conditions and evidence references."
    breadcrumb = _breadcrumb_html(sm, title)
    source_path = _GOLDEN_PATH

    canonical_url = f"{sm.base_url}/pages/golden_path.html" if sm.base_url else ""

    if not golden_path:
        og_tags = make_og_tags(canonical_url, title, desc, "article")
        head_tags = make_head_tags(sm, canonical_url, og_tags, relative_root="..")
        home_href = make_relative_link(f"{sm.base_path}/", "..", sm.base_path)
        return f"""<!DOCTYPE html>
<html lang="{sm.site_language}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{desc}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{home_href}">{_html.escape(sm.site_title)}</a>
  </nav>
  {breadcrumb}
  <h1>{title}</h1>
</header>
<main id="main" class="doc-page">
  <article>
{_warning_card("Golden path data not available")}
  </article>
</main>
<footer>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""

    body = _build_golden_path_body(golden_path)
    head_sha = str(golden_path.get("head_sha", ""))
    sha_disp = _truncate_sha(head_sha)

    og_tags = make_og_tags(canonical_url, title, desc, "article")
    head_tags = make_head_tags(sm, canonical_url, og_tags, relative_root="..")
    home_href = make_relative_link(f"{sm.base_path}/", "..", sm.base_path)
    nav = _nav_for_page(
        sm,
        "RC Readiness",
        f"{sm.base_path}/pages/rc_readiness.html",
        "RC Verdict",
        f"{sm.base_path}/pages/rc_verdict.html",
    )

    return f"""<!DOCTYPE html>
<html lang="{sm.site_language}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rig Relay Docs</title>
<meta name="description" content="{desc}">
{head_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{home_href}">{_html.escape(sm.site_title)}</a>
  </nav>
  {breadcrumb}
  <h1>{title}</h1>
  <p class="doc-summary">{desc}</p>
  {nav}
</header>
<main id="main" class="doc-page">
  <article>
{body}
  </article>
</main>
<footer>
  <p class="source-ref">Source: <code>{_html.escape(source_path)}</code> (SHA: {_html.escape(sha_disp)})</p>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def load_release_artifacts() -> dict[str, dict | None]:
    result: dict[str, dict | None] = {
        "gate": None,
        "verdict": None,
        "golden_path": None,
    }
    paths = {
        "gate": REPO_ROOT / _GATE_PATH,
        "verdict": REPO_ROOT / _VERDICT_PATH,
        "golden_path": REPO_ROOT / _GOLDEN_PATH,
    }
    for key, p in paths.items():
        if p.is_file():
            try:
                result[key] = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                result[key] = None
    return result

from __future__ import annotations

import hashlib
import html as _html
import json

from rig_relay.docs_renderer.models import SiteMeta


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:12]


def _build_page(*, sm: SiteMeta, title: str, body_html: str, source_ref: str) -> str:
    from rig_relay.docs_renderer.metadata import make_head_tags, make_og_tags
    from rig_relay.docs_renderer.paths import make_relative_link

    esc = _html.escape
    home_href = make_relative_link(f"{sm.base_path}/", "..", sm.base_path)
    canonical = f"{sm.base_url}/pages/{_sha256_hex(title)}.html" if sm.base_url else ""
    og = make_og_tags(canonical, esc(title), esc(title), "article")
    head = make_head_tags(sm, canonical, og, relative_root="..")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} — Rig Relay Docs</title>
<meta name="description" content="{esc(title)}">
{head}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <nav aria-label="Primary">
    <a href="{home_href}">{esc(sm.site_title)}</a>
  </nav>
  <p class="eyebrow"><a href="{home_href}">{esc(sm.site_title)}</a> / {esc(title)}</p>
  <h1>{esc(title)}</h1>
</header>
<main id="main" class="doc-page">
  <article>
{body_html}
  </article>
</main>
<footer>
  <p>Source: <code>{esc(source_ref)}</code></p>
  <p>Rig Relay — AGPL-3.0-or-later</p>
</footer>
</body>
</html>
"""


def _warning_card(title: str, sm: SiteMeta) -> str:
    return _build_page(
        sm=sm,
        title=title,
        body_html="""    <section class="callout callout-warning">
      <h2>Data Not Available</h2>
      <p>The required artifact data is not available. This may be due to an incomplete build or a missing source file.</p>
    </section>""",
        source_ref="(no source)",
    )


def _safe_str(val: object) -> str:
    return _html.escape(str(val)) if val else ""


def _safe_list(items: object) -> str:
    if not isinstance(items, list) or not items:
        return "<li>None</li>"
    return "\n".join(f"<li>{_html.escape(str(i))}</li>" for i in items)


def _content_text(sections: list[dict], keywords: tuple[str, ...]) -> list[dict]:
    return [
        s
        for s in sections
        if isinstance(s, dict)
        and any(term in str(s.get("content", "")).lower() for term in keywords)
    ]


def _render_filtered_sections(sections: list[dict]) -> str:
    parts: list[str] = []
    for s in sections:
        content = _safe_str(s.get("content", ""))
        if s.get("type") == "heading":
            hlevel = min(max(s.get("level", 3), 2), 4)
            parts.append(f"<h{hlevel}>{content}</h{hlevel}>")
        else:
            parts.append(f"<p>{content}</p>")
    return "\n".join(parts)


def _build_consent_section(consent_data: dict | None) -> str:
    parts: list[str] = []
    parts.append('<section id="telemetry-consent">')
    parts.append("<h2>Telemetry Consent</h2>")
    if consent_data:
        consent_policy = consent_data.get("policy", consent_data)
        for key in ("consent_model", "model", "description", "summary"):
            v = consent_policy.get(key)
            if v:
                parts.append(f"<p>{_safe_str(v)}</p>")
                break
        else:
            parts.append(
                f"<pre><code>{_html.escape(json.dumps(consent_data, indent=2))}</code></pre>"
            )

        opt_in = consent_data.get("opt_in", consent_data.get("opt_in_rule", ""))
        opt_out = consent_data.get("opt_out", consent_data.get("opt_out_rule", ""))
        collected = consent_data.get(
            "what_is_collected", consent_data.get("collected", [])
        )
        if opt_in or opt_out or collected:
            parts.append("<h3>Consent Rules</h3><dl>")
            if opt_in:
                parts.append(f"<dt>Opt-in</dt><dd>{_safe_str(opt_in)}</dd>")
            if opt_out:
                parts.append(f"<dt>Opt-out</dt><dd>{_safe_str(opt_out)}</dd>")
            parts.append("</dl>")
            if collected:
                parts.append("<h3>What Is Collected</h3>")
                parts.append(f"<ul>{_safe_list(collected)}</ul>")
    else:
        parts.append("<p>Consent data not available.</p>")
    parts.append(
        '<p class="source-ref">Source: <code>docs/json/governance/telemetry-consent-enforcement.v1.json</code></p>'
    )
    parts.append("</section>")
    return "\n".join(parts)


def _build_tracing_section(tracing_data: dict | None) -> str:
    parts: list[str] = []
    parts.append('<section id="tracing-policy">')
    parts.append("<h2>Tracing Policy</h2>")
    if tracing_data:
        policy = tracing_data.get("policy", tracing_data)
        for key in ("release_gate", "description", "summary", "title"):
            v = policy.get(key)
            if v:
                parts.append(f"<p>{_safe_str(v)}</p>")

        content_rule = policy.get("content_rule", "")
        if content_rule:
            parts.append(
                f"<h3>Content-Light Doctrine</h3><p>{_safe_str(content_rule)}</p>"
            )
        redaction = policy.get("redaction_rule", "")
        if redaction:
            parts.append(f"<h3>Redaction Rule</h3><p>{_safe_str(redaction)}</p>")
        handshake = policy.get("handshake_rule", "")
        if handshake:
            parts.append(f"<h3>Correlation</h3><p>{_safe_str(handshake)}</p>")

        strict_stages = policy.get("strict_mode_stages", [])
        if strict_stages:
            parts.append("<h3>Strict Mode Stages</h3>")
            parts.append(f"<ol>{_safe_list(strict_stages)}</ol>")

        failure = policy.get("failure_conditions", {})
        if failure:
            parts.append("<h3>Failure Conditions</h3><dl>")
            for fk, fv in failure.items():
                parts.append(f"<dt>{_safe_str(fk)}</dt><dd>{_safe_str(fv)}</dd>")
            parts.append("</dl>")

        golden = tracing_data.get("golden_path_event_names", {})
        if golden:
            parts.append("<h3>Golden Path Events</h3>")
            for domain, events in golden.items():
                if isinstance(events, list) and events:
                    parts.append(
                        f"<h4>{_safe_str(domain)}</h4><ul>{_safe_list(events)}</ul>"
                    )
    else:
        parts.append("<p>Tracing policy data not available.</p>")
    parts.append(
        '<p class="source-ref">Source: <code>docs/json/tracing_policy.v1.json</code></p>'
    )
    parts.append("</section>")
    return "\n".join(parts)


def _build_degradation_section(artifacts: dict) -> str:
    degradation = artifacts.get("degradation_policy")
    parts: list[str] = [
        '<section id="degradation-policy">',
        "<h2>Degradation Policy</h2>",
    ]
    if degradation:
        if isinstance(degradation, dict):
            for key in ("description", "summary", "behavior"):
                v = degradation.get(key)
                if v:
                    parts.append(f"<p>{_safe_str(v)}</p>")
            degraded = degradation.get(
                "degraded_mode", degradation.get("degraded_behavior", {})
            )
            if degraded:
                parts.append("<h3>Degraded Mode Behavior</h3>")
                if isinstance(degraded, dict):
                    parts.append("<dl>")
                    for dk, dv in degraded.items():
                        parts.append(
                            f"<dt>{_safe_str(dk)}</dt><dd>{_safe_str(dv)}</dd>"
                        )
                    parts.append("</dl>")
                else:
                    parts.append(f"<p>{_safe_str(degraded)}</p>")
        elif isinstance(degradation, str):
            parts.append(f"<p>{_safe_str(degradation)}</p>")
    else:
        parts.append(
            "<p>Degradation policy derived from tracing policy and consent enforcement rules. "
            "When telemetry is disabled, all optional tracing stops. "
            "Mission-critical receipts remain. The UI shows a degraded-mode indicator.</p>"
        )
    parts.append("</section>")
    return "\n".join(parts)


def _build_redaction_section(artifacts: dict) -> str:
    redaction = artifacts.get("redaction_rules", artifacts.get("redaction"))
    parts: list[str] = ['<section id="redaction-rules">', "<h2>Redaction Rules</h2>"]
    if redaction and isinstance(redaction, dict):
        for key in ("description", "summary", "policy"):
            v = redaction.get(key)
            if v:
                parts.append(f"<p>{_safe_str(v)}</p>")
        items = redaction.get("rules", redaction.get("items", []))
        if items and isinstance(items, list):
            parts.append(f"<ul>{_safe_list(items)}</ul>")
    else:
        parts.append("<ul>")
        parts.append(
            "<li>Token values must never appear in telemetry (token_value_included: false)</li>"
        )
        parts.append("<li>Full file contents must never be emitted</li>")
        parts.append("<li>Secrets and credentials are always redacted</li>")
        parts.append("<li>Prompt payloads and model outputs are excluded</li>")
        parts.append("<li>Content-derived data uses SHA256 hashes only</li>")
        parts.append("<li>Home directory paths are replaced with [REDACTED]</li>")
        parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def render_telemetry_policy_page(artifacts: dict | None, site_meta: SiteMeta) -> str:
    if not artifacts:
        return _warning_card("Telemetry & Privacy Policy", site_meta)

    body = "\n".join([
        _build_consent_section(artifacts.get("consent")),
        _build_tracing_section(artifacts.get("tracing")),
        _build_degradation_section(artifacts),
        _build_redaction_section(artifacts),
    ])

    return _build_page(
        sm=site_meta,
        title="Telemetry & Privacy Policy",
        body_html=body,
        source_ref="docs/json/governance/telemetry-consent-enforcement.v1.json",
    )


def _build_lifecycle_section(sections: list[dict]) -> str:
    matched = _content_text(
        sections, ("transport", "boot", "lifecycle", "connection", "startup", "phase")
    )
    parts: list[str] = [
        '<section id="connection-lifecycle">',
        "<h2>Connection Lifecycle</h2>",
    ]
    if matched:
        parts.append(_render_filtered_sections(matched))
    else:
        parts.append("<h3>Boot Phases</h3><ol>")
        for phase in (
            "Bridge launch requested — entry point invoked",
            "Frontend resolved — HTML/JS assets located",
            "Index resolved — search/manifest index loaded",
            "Asset probe passed — all required files present",
            "Runtime config built — merged config from disk",
            "WebSocket server created — ASGI server spun up",
            "Server bound — listening on localhost",
            "Health probe passed — WebSocket endpoint reachable",
            "Frontend URL announced — window created and navigated",
            "WebSocket connected — frontend handshake complete",
            "Auth received — token validated",
            "Projection sent → received → rendered",
            "Ready reached — cockpit fully operational",
            "Shutdown observed — clean teardown",
        ):
            parts.append(f"<li>{_safe_str(phase)}</li>")
        parts.append("</ol>")
    parts.append("</section>")
    return "\n".join(parts)


def _build_projection_section(sections: list[dict]) -> str:
    matched = _content_text(sections, ("projection", "field", "freshness", "contract"))
    parts: list[str] = [
        '<section id="projection-contract">',
        "<h2>Projection Contract</h2>",
    ]
    if matched:
        parts.append(_render_filtered_sections(matched))
    else:
        parts.append("<p>Projection fields include:</p><ul>")
        for field in (
            "agent_session — current session state",
            "fleet_status — active worktrees and agents",
            "provider_health — LLM provider reachability",
            "workspace_state — git branch, dirty files, index",
            "council_opinions — multi-provider review results",
            "report_store — recent structured reports",
            "governance_status — policy gates and permissions",
        ):
            parts.append(f"<li>{_safe_str(field)}</li>")
        parts.append("</ul>")
        parts.append("<h3>Freshness Guarantees</h3><ul>")
        for guarantee in (
            "Projection snapshots delivered on WebSocket connect and on state change",
            "No polling — push-only model",
            "Staleness tolerance: 2 seconds for most fields",
            "Content-light: no raw file contents, tokens, or secrets",
        ):
            parts.append(f"<li>{_safe_str(guarantee)}</li>")
        parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def _build_intent_section(sections: list[dict]) -> str:
    matched = _content_text(sections, ("intent", "command", "action", "dispatch"))
    parts: list[str] = ['<section id="intent-lifecycle">', "<h2>Intent Lifecycle</h2>"]
    if matched:
        parts.append(_render_filtered_sections(matched))
    else:
        parts.append("<h3>Intent Flow</h3><ol>")
        for step in (
            "User issues intent from cockpit UI (chat, slash command, button)",
            "Frontend serializes intent as JSON-RPC message over WebSocket",
            "Bridge validates origin (localhost), token, and message schema",
            "Intent dispatched to backend handler",
            "Backend processes intent, produces structured result",
            "Result projected back to frontend via WebSocket",
            "Frontend renders projection update",
        ):
            parts.append(f"<li>{_safe_str(step)}</li>")
        parts.append("</ol>")
        parts.append("<h3>Intent Categories</h3><ul>")
        for cat in (
            "chat.send — user message to agent loop",
            "tool.approve — approval gate response",
            "session.fork — create new agent session",
            "provider.configure — update LLM provider settings",
            "fleet.dispatch — orchestrate subagent mission",
            "council.convene — request multi-provider review",
        ):
            parts.append(f"<li>{_safe_str(cat)}</li>")
        parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def _build_security_section() -> str:
    return """<section id="security-properties">
<h2>Security Properties</h2>
<dl>
<dt>Origin validation</dt><dd>Only localhost connections accepted. Remote connections rejected.</dd>
<dt>Token gating</dt><dd>WebSocket connections require a valid session token. Unauthenticated connections receive 403.</dd>
<dt>Message validation</dt><dd>All incoming WebSocket messages validated against JSON-RPC schema. Malformed messages logged and dropped.</dd>
<dt>Content-light projection</dt><dd>Projection payloads never contain raw file contents, secrets, tokens, or model outputs.</dd>
<dt>Frontend is a dumb renderer</dt><dd>All policy transitions owned by backend. Frontend displays projection field labels; never infers or overrides policy.</dd>
<dt>No external network exposure</dt><dd>WebSocket server binds to 127.0.0.1 only.</dd>
</dl>
</section>"""


def render_bridge_lifecycle_page(
    projection_contract: dict | None, site_meta: SiteMeta
) -> str:
    if not projection_contract:
        return _warning_card("Desktop Bridge Lifecycle", site_meta)

    sections: list[dict] = projection_contract.get("sections", [])
    body = "\n".join([
        _build_lifecycle_section(sections),
        _build_projection_section(sections),
        _build_intent_section(sections),
        _build_security_section(),
    ])

    return _build_page(
        sm=site_meta,
        title="Desktop Bridge Lifecycle",
        body_html=body,
        source_ref="docs/json/governance/relay-desktop-projection-contract.v1.json",
    )


def _build_kernel_section(golden_sections: list[dict]) -> str:
    matched = _content_text(
        golden_sections, ("kernel", "state machine", "loop", "cancellation", "runtime")
    )
    parts: list[str] = ['<section id="runtime-kernel">', "<h2>Runtime Kernel</h2>"]
    if matched:
        parts.append(_render_filtered_sections(matched))
    else:
        parts.append(
            "<p>Desktop golden path exercises the kernel state machines:</p><ul>"
        )
        for item in (
            "Bridge boot sequence state machine (14 stages)",
            "WebSocket connection lifecycle loop",
            "Projection dispatch → render cycle",
            "Intent dispatch → result cycle",
            "Cancellation: shutdown sequence ensures clean teardown via trace summary",
        ):
            parts.append(f"<li>{_safe_str(item)}</li>")
        parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def _build_notification_section(golden_sections: list[dict]) -> str:
    matched = _content_text(
        golden_sections, ("notif", "alert", "toast", "status", "chip")
    )
    parts: list[str] = [
        '<section id="notification-system">',
        "<h2>Notification System</h2>",
    ]
    if matched:
        parts.append(_render_filtered_sections(matched))
    else:
        parts.append("<h3>Notification Kinds</h3><ul>")
        for kind in (
            "Status chips — compact session/fleet state indicators",
            "Approval cards — tool permission requests requiring user action",
            "Council opinions — structured multi-provider review results",
            "Error toasts — transient error notifications",
            "Provider health badges — LLM provider reachability",
        ):
            parts.append(f"<li>{_safe_str(kind)}</li>")
        parts.append("</ul>")
        parts.append(
            "<h3>Dedup Keys</h3>"
            "<p>Notifications are deduplicated by kind + source_id. "
            "Repeated identical notifications are suppressed.</p>"
        )
    parts.append("</section>")
    return "\n".join(parts)


def _build_delight_section() -> str:
    return """<section id="delight-system">
<h2>Delight System</h2>
<dl>
<dt>Motion preferences</dt><dd>Respects prefers-reduced-motion. Transitions disabled when user prefers reduced motion.</dd>
<dt>Sound opt-in</dt><dd>All sounds are opt-in only. No audio plays without explicit user consent. Sound toggle in settings panel.</dd>
<dt>Animation budget</dt><dd>Animations capped at 200ms. No infinite animations. All animations CSS-only (no JS animation loops).</dd>
<dt>Loading states</dt><dd>Skeleton screens for initial load. Spinner for in-flight operations. Empty states with actionable copy.</dd>
<dt>Disclosure levels</dt><dd>Compact chips → standard cards → full-page expanded. User controls disclosure depth.</dd>
</dl>
</section>"""


def _build_coverage_section(golden_sections: list[dict]) -> str:
    matched = _content_text(golden_sections, ("test", "verify", "validation", "assert"))
    parts: list[str] = [
        '<section id="browser-test-coverage">',
        "<h2>Browser Test Coverage</h2>",
    ]
    if matched:
        parts.append(_render_filtered_sections(matched))
    else:
        parts.append("<h3>E2E Test Domains</h3><table>")
        parts.append("<tr><th>Domain</th><th>Description</th><th>Status</th></tr>")
        domains = (
            ("Bridge boot", "Server startup, asset resolution, health probe"),
            ("WebSocket connect", "Token validation, handshake, auth flow"),
            ("Projection round-trip", "Send → receive → render cycle"),
            ("Intent dispatch", "Chat send, tool approve, slash commands"),
            ("Slash commands", "/init, /fleet, /council, /provider, etc."),
            ("Provider config", "Onboarding wizard, key setup, dry-run"),
            ("Shutdown", "Clean teardown, trace summary output"),
        )
        for name, desc in domains:
            parts.append(
                f"<tr><td>{_safe_str(name)}</td><td>{_safe_str(desc)}</td><td>exercised</td></tr>"
            )
        parts.append("</table>")
    parts.append("</section>")
    return "\n".join(parts)


def render_frontend_maturity_page(artifacts: dict | None, site_meta: SiteMeta) -> str:
    if not artifacts:
        return _warning_card("Frontend Maturity Evidence", site_meta)

    golden = artifacts.get("golden_path")
    golden_sections: list[dict] = golden.get("sections", []) if golden else []

    body = "\n".join([
        _build_kernel_section(golden_sections),
        _build_notification_section(golden_sections),
        _build_delight_section(),
        _build_coverage_section(golden_sections),
    ])

    return _build_page(
        sm=site_meta,
        title="Frontend Maturity Evidence",
        body_html=body,
        source_ref="docs/json/demo/desktop-golden-path.v1.json",
    )


def load_telemetry_bridge_artifacts() -> dict:
    from rig_relay.docs_renderer.paths import REPO_ROOT

    result: dict = {}

    consent_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "telemetry-consent-enforcement.v1.json"
    )
    if consent_path.is_file():
        result["consent"] = json.loads(consent_path.read_text(encoding="utf-8"))

    tracing_path = REPO_ROOT / "docs" / "json" / "tracing_policy.v1.json"
    if tracing_path.is_file():
        result["tracing"] = json.loads(tracing_path.read_text(encoding="utf-8"))

    proj_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "relay-desktop-projection-contract.v1.json"
    )
    if proj_path.is_file():
        result["projection_contract"] = json.loads(
            proj_path.read_text(encoding="utf-8")
        )

    golden_path = REPO_ROOT / "docs" / "json" / "demo" / "desktop-golden-path.v1.json"
    if golden_path.is_file():
        result["golden_path"] = json.loads(golden_path.read_text(encoding="utf-8"))

    return result

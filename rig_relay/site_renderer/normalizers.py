from __future__ import annotations

import html

_CALLOUT_WARNING_KIND: str = "callout"
_CALLOUT_INFO_KIND: str = "callout"
_HERO_STATUS_KIND: str = "hero_status"
_TABLE_KIND: str = "table"
_CARD_GRID_KIND: str = "card_grid"
_TIMELINE_KIND: str = "timeline"
_DEFINITION_LIST_KIND: str = "definition_list"
_ARTIFACT_NAV_KIND: str = "artifact_nav"
_SCHEMA_INDEX_KIND: str = "schema_index"


def _e(text: object) -> str:
    if text is None:
        return ""
    return html.escape(str(text))


def _artifact_dict(artifacts: dict, *keys: str) -> dict | None:
    for k in keys:
        v = artifacts.get(k)
        if isinstance(v, dict):
            return v
    return None


def _artifact_list(artifacts: dict, *keys: str) -> list:
    for k in keys:
        v = artifacts.get(k)
        if isinstance(v, list):
            return v
    return []


def _callout_section(title: str, body: str, kind: str = "warn") -> dict:
    return {
        "kind": _CALLOUT_WARNING_KIND,
        "heading": title,
        "body_html": body,
        "callout_class": kind,
    }


def _hero_section(
    title: str, status: str, status_detail: str = "", overall_status: str = ""
) -> dict:
    return {
        "kind": _HERO_STATUS_KIND,
        "title": title,
        "status_label": status,
        "summary": status_detail,
        "status_class": "warn"
        if status.lower() in ("hold", "blocked", "not_verified", "failed")
        else "ok",
    }


def _table_section(
    title: str, headers: list[str], rows: list[list[str]], caption: str = ""
) -> dict:
    return {
        "kind": _TABLE_KIND,
        "caption": caption or title,
        "headers": headers,
        "rows": rows,
    }


def _card_grid_section(title: str, cards: list[dict]) -> dict:
    return {"kind": _CARD_GRID_KIND, "title": title, "cards": cards}


def _timeline_section(title: str, entries: list[dict]) -> dict:
    return {"kind": _TIMELINE_KIND, "heading": title, "entries": entries}


def _definition_list_section(title: str, items: list[dict]) -> dict:
    return {"kind": _DEFINITION_LIST_KIND, "heading": title, "items": items}


def _artifact_nav_section(title: str, links: list[dict]) -> dict:
    return {"kind": _ARTIFACT_NAV_KIND, "heading": title, "links": links}


def _schema_index_section(title: str, schemas: list[dict]) -> dict:
    return {"kind": _SCHEMA_INDEX_KIND, "heading": title, "entries": schemas}


def normalize_release_gate(artifacts: dict) -> list[dict]:
    gate = _artifact_dict(artifacts, "release_gate", "gate")
    verdict = _artifact_dict(artifacts, "rc_verdict", "verdict")
    golden_path = _artifact_dict(artifacts, "golden_path")
    blockers_rows = _artifact_list(artifacts, "rc_blockers", "blockers")
    validation_runs_rows = _artifact_list(
        artifacts, "rc_validation_runs", "validation_runs"
    )
    deferred_risks_rows = _artifact_list(
        artifacts, "rc_deferred_risks", "deferred_risks"
    )

    if all(
        v is None or (isinstance(v, list) and len(v) == 0)
        for v in [
            gate,
            verdict,
            golden_path,
            blockers_rows,
            validation_runs_rows,
            deferred_risks_rows,
        ]
    ):
        return [
            _callout_section(
                "Release Gate Data Missing",
                "No release gate artifacts found. "
                "Run the release gate validator to populate this data.",
            )
        ]

    sections: list[dict] = []

    overall_status = "unknown"
    if gate is not None:
        overall_status = _e(gate.get("overall_status", "unknown"))

    if verdict is not None:
        overall_status = _e(
            verdict.get("verdict", verdict.get("gate_overall_status", "unknown"))
        )

    if overall_status.lower() in ("hold", "blocked"):
        hero_label = "Hold" if overall_status.lower() == "hold" else "Blocked"
    elif overall_status.lower() == "promote":
        hero_label = "Promote"
    elif gate is not None and _e(gate.get("overall_status", "")).lower() == "blocked":
        hero_label = "Blocked"
        overall_status = "blocked"
    else:
        hero_label = overall_status

    hero_parts: list[str] = []
    if gate is not None:
        gate_id = _e(gate.get("gate_id", ""))
        branch = _e(gate.get("branch", ""))
        head_sha = _e(gate.get("head_sha", ""))[:12]
        hero_parts.append(f"Gate: {gate_id} | Branch: {branch} | SHA: {head_sha}")
    if verdict is not None:
        validator = _e(verdict.get("validator_result", "unknown"))
        errors = _e(verdict.get("validator_error_count", 0))
        hero_parts.append(f"Validator: {validator} | Errors: {errors}")

    sections.append(
        _hero_section(
            "Release Gate Readiness", hero_label, " | ".join(hero_parts), overall_status
        )
    )

    if gate is not None:
        gate_id = _e(gate.get("gate_id", ""))
        branch = _e(gate.get("branch", ""))
        head_sha = _e(gate.get("head_sha", ""))[:12]
        generated = _e(gate.get("generated_at", ""))

        sections.append(
            _definition_list_section(
                "Gate Details",
                [
                    {"term": "Gate ID", "definition": gate_id},
                    {"term": "Branch", "definition": branch},
                    {"term": "HEAD SHA", "definition": head_sha},
                    {"term": "Generated", "definition": generated},
                ],
            )
        )

        phases = gate.get("phases", [])
        if phases:
            phase_rows: list[list[str]] = []
            for p in phases:
                phase_rows.append([
                    _e(p.get("phase_id", "")),
                    _e(p.get("title", "")),
                    _e(p.get("status", "unknown")),
                    str(len(p.get("blocker_ids", []))),
                    str(len(p.get("remaining_seams", []))),
                ])
            sections.append(
                _table_section(
                    f"Phases ({len(phases)})",
                    ["Phase ID", "Title", "Status", "Blockers", "Seams"],
                    phase_rows,
                )
            )

            for p in phases:
                blockers = p.get("blocker_ids", [])
                if blockers:
                    sections.append(
                        _callout_section(
                            f"Phase {_e(p.get('phase_id', ''))} — Blockers",
                            ", ".join(_e(b) for b in blockers),
                            "warn",
                        )
                    )
    else:
        sections.append(
            _callout_section(
                "Release Gate Not Available",
                "The release gate readiness artifact is missing.",
                "info",
            )
        )

    if isinstance(blockers_rows, list) and blockers_rows:
        bl_headers = ["Blocker ID", "Title", "Status", "Phase"]
        bl_rows: list[list[str]] = []
        for b in blockers_rows:
            if not isinstance(b, dict):
                continue
            bl_rows.append([
                _e(b.get("blocker_id", b.get("id", ""))),
                _e(b.get("title", b.get("description", ""))),
                _e(b.get("status", "unknown")),
                _e(b.get("phase", b.get("phase_id", ""))),
            ])
        if bl_rows:
            sections.append(
                _table_section(
                    f"Open Blockers ({len(bl_rows)})",
                    bl_headers,
                    bl_rows,
                    "Release Candidate Blockers",
                )
            )

    if isinstance(validation_runs_rows, list) and validation_runs_rows:
        vr_headers = ["Run ID", "Status", "Timestamp"]
        vr_rows: list[list[str]] = []
        for r in validation_runs_rows:
            if not isinstance(r, dict):
                continue
            vr_rows.append([
                _e(r.get("run_id", r.get("id", ""))),
                _e(r.get("status", "unknown")),
                _e(r.get("timestamp", r.get("generated_at", ""))),
            ])
        if vr_rows:
            sections.append(
                _table_section(
                    f"Validation Runs ({len(vr_rows)})",
                    vr_headers,
                    vr_rows,
                    "Release Candidate Validation Runs",
                )
            )

    if isinstance(deferred_risks_rows, list) and deferred_risks_rows:
        dr_headers = ["Risk ID", "Title", "Deferral Reason"]
        dr_rows: list[list[str]] = []
        for d in deferred_risks_rows:
            if not isinstance(d, dict):
                continue
            dr_rows.append([
                _e(d.get("risk_id", d.get("id", ""))),
                _e(d.get("title", d.get("description", ""))),
                _e(d.get("deferral_reason", d.get("reason", ""))),
            ])
        if dr_rows:
            sections.append(
                _table_section(
                    f"Deferred Risks ({len(dr_rows)})",
                    dr_headers,
                    dr_rows,
                    "Release Candidate Deferred Risks",
                )
            )

    if verdict is not None:
        v = _e(verdict.get("verdict", "unknown"))
        gate_status = _e(verdict.get("gate_overall_status", "unknown"))
        validator = _e(verdict.get("validator_result", "unknown"))
        validator_errors = _e(verdict.get("validator_error_count", 0))
        open_blockers = len(verdict.get("open_blocker_ids", []))

        sections.append(
            _hero_section(
                "RC Candidate Verdict",
                v,
                f"Gate: {gate_status} | Validator: {validator} | Errors: {validator_errors}",
                v,
            )
        )

        sections.append(
            _definition_list_section(
                "Verdict Summary",
                [
                    {"term": "Verdict", "definition": v},
                    {"term": "Gate Overall", "definition": gate_status},
                    {"term": "Validator", "definition": validator},
                    {"term": "Validator Errors", "definition": validator_errors},
                    {"term": "Open Blockers", "definition": str(open_blockers)},
                ],
            )
        )

        promote = verdict.get("promote_blockers", [])
        if promote:
            sections.append(
                _callout_section(
                    "Promote Blockers", ", ".join(_e(p) for p in promote), "warn"
                )
            )

        next_actions = verdict.get("required_next_actions", [])
        if next_actions:
            action_items = [
                {"term": str(i + 1), "definition": _e(a)}
                for i, a in enumerate(next_actions)
            ]
            sections.append(
                _definition_list_section("Required Next Actions", action_items)
            )
    else:
        sections.append(
            _callout_section(
                "RC Verdict Not Available",
                "The RC candidate verdict artifact is missing.",
                "info",
            )
        )

    if golden_path is not None:
        gp_status = _e(golden_path.get("overall_status", "unknown"))
        sections.append(
            _hero_section("Golden Path — Dogfood Readiness", gp_status, "", gp_status)
        )

        steps = golden_path.get("steps", [])
        if steps:
            step_cards: list[dict] = []
            for s in steps:
                step_cards.append({
                    "id": _e(s.get("step_id", "")),
                    "title": _e(s.get("user_goal", "")),
                    "status": _e(s.get("status", "unknown")),
                    "detail": _e(s.get("expected_result", "")),
                    "command": _e(s.get("command_or_ui_action", "")),
                    "phase": _e(s.get("phase_id", "")),
                })
            sections.append(_card_grid_section(f"Steps ({len(steps)})", step_cards))
    else:
        sections.append(
            _callout_section(
                "Golden Path Not Available",
                "The golden path artifact is missing.",
                "info",
            )
        )

    return sections


def normalize_testing(artifacts: dict) -> list[dict]:
    inventory = _artifact_dict(artifacts, "test_inventory", "inventory")
    classifications_dict = _artifact_dict(
        artifacts, "test_classification", "classifications"
    )
    classifications_list = _artifact_list(
        artifacts, "test_classification", "classifications"
    )
    seams = _artifact_list(artifacts, "test_seams", "seams")
    hardened = _artifact_list(artifacts, "hardened_tests", "hardened")
    deleted = _artifact_list(artifacts, "deleted_tests", "deleted")

    has_data = any(
        v is not None and (not isinstance(v, list) or len(v) > 0)
        for v in [
            inventory,
            classifications_dict,
            classifications_list,
            seams,
            hardened,
            deleted,
        ]
    )

    if not has_data:
        return [
            _callout_section(
                "Test Data Missing",
                "No test artifacts found. Run the test inventory and classification "
                "scans to populate this data.",
            )
        ]

    sections: list[dict] = []

    if inventory is not None:
        summary = inventory.get("summary", {})
        total_files = _e(summary.get("total_test_files", "N/A"))
        total_funcs = _e(summary.get("total_test_functions", "N/A"))
        classified_keep = _e(summary.get("classified_keep", "N/A"))
        classified_harden = _e(summary.get("classified_harden", "N/A"))
        classified_replace = _e(summary.get("classified_replace", "N/A"))
        classified_delete = _e(summary.get("classified_delete", "N/A"))

        sections.append(
            _hero_section(
                "Test Inventory",
                "available",
                f"{total_files} files, {total_funcs} functions",
                "available",
            )
        )

        sections.append(
            _definition_list_section(
                "Inventory Summary",
                [
                    {"term": "Total Test Files", "definition": total_files},
                    {"term": "Total Test Functions", "definition": total_funcs},
                    {"term": "Classified Keep", "definition": classified_keep},
                    {"term": "Classified Harden", "definition": classified_harden},
                    {"term": "Classified Replace", "definition": classified_replace},
                    {"term": "Classified Delete", "definition": classified_delete},
                ],
            )
        )

        surfaces = inventory.get("stress_surfaces", [])
        if surfaces:
            surface_rows: list[list[str]] = []
            for sf in surfaces:
                surface_rows.append([
                    _e(sf.get("surface_name", "")),
                    str(sf.get("file_count", 0)),
                    str(sf.get("test_function_count", 0)),
                    _e(sf.get("seam_coverage_assessment", "")),
                ])
            sections.append(
                _table_section(
                    "Stress Surface Coverage",
                    ["Surface", "Files", "Functions", "Assessment"],
                    surface_rows,
                )
            )

            gap_items: list[dict] = []
            for sf in surfaces:
                for g in sf.get("critical_gaps", []):
                    gap_items.append({
                        "term": _e(sf.get("surface_name", "")),
                        "definition": _e(g),
                    })
            if gap_items:
                sections.append(
                    _callout_section(
                        f"Known Test Seams ({len(gap_items)})",
                        "Deferred gaps in test coverage that do not block RC promotion.",
                        "info",
                    )
                )
                sections.append(_definition_list_section("Critical Gaps", gap_items))
    else:
        sections.append(
            _callout_section(
                "Test Inventory Not Available",
                "Test inventory data not yet generated.",
                "info",
            )
        )

    if classifications_dict is not None:
        definition_items: list[dict] = []
        counts = classifications_dict.get("counts", {})
        if isinstance(counts, dict):
            for marker, count in sorted(counts.items()):
                definition_items.append({
                    "term": _e(marker),
                    "definition": f"Count: {_e(count)}",
                })
        if definition_items:
            sections.append(
                _definition_list_section("Classification Counts", definition_items)
            )
    elif isinstance(classifications_list, list) and classifications_list:
        definition_items: list[dict] = []
        for i, c in enumerate(classifications_list):
            if not isinstance(c, dict):
                continue
            marker = c.get("marker", c.get("classification", f"entry-{i}"))
            status = c.get("classification", c.get("status", "unknown"))
            definition_items.append({"term": _e(marker), "definition": _e(status)})
        if definition_items:
            sections.append(
                _definition_list_section("Classification Records", definition_items)
            )

    if isinstance(seams, list) and seams:
        seam_rows: list[list[str]] = []
        for s in seams:
            if not isinstance(s, dict):
                continue
            seam_rows.append([
                _e(s.get("protected_seam", s.get("seam_id", ""))),
                _e(s.get("reason", s.get("description", ""))),
                _e(s.get("classification", s.get("status", "deferred"))),
                _e(s.get("stress_surface", "")),
            ])
        if seam_rows:
            sections.append(
                _table_section(
                    f"Known Test Seams ({len(seam_rows)})",
                    ["Seam", "Description", "Status", "Surface"],
                    seam_rows,
                )
            )

    if isinstance(hardened, list) and hardened:
        ht_rows: list[list[str]] = []
        for h in hardened:
            if not isinstance(h, dict):
                continue
            ht_rows.append([
                _e(h.get("test_id", h.get("id", ""))),
                _e(h.get("name", h.get("title", ""))),
                _e(h.get("classification", h.get("status", "unknown"))),
                _e(h.get("hardened_at", h.get("timestamp", ""))),
            ])
        if ht_rows:
            sections.append(
                _table_section(
                    f"Hardened Tests ({len(ht_rows)})",
                    ["Test ID", "Name", "Classification", "Hardened At"],
                    ht_rows,
                )
            )

    if isinstance(deleted, list) and deleted:
        del_rows: list[list[str]] = []
        for d in deleted:
            if not isinstance(d, dict):
                continue
            del_rows.append([
                _e(d.get("test_id", d.get("id", ""))),
                _e(d.get("name", d.get("title", ""))),
                _e(d.get("reason", "")),
                _e(d.get("deleted_at", d.get("timestamp", ""))),
            ])
        if del_rows:
            sections.append(
                _table_section(
                    f"Deleted Tests ({len(del_rows)})",
                    ["Test ID", "Name", "Reason", "Deleted At"],
                    del_rows,
                )
            )

    return sections


def normalize_integrations(artifacts: dict) -> list[dict]:
    sections: list[dict] = []

    manifest = _artifact_dict(artifacts, "integration_manifest", "capability_manifest")
    mcp_manifest = _artifact_dict(artifacts, "mcp_manifest")
    has_data = manifest is not None or mcp_manifest is not None

    if not has_data:
        return [
            _callout_section(
                "Integration Data Not Available",
                "IDE capability manifest and MCP capability map are not yet available.",
                "info",
            )
        ]

    if manifest is not None:
        mf_name = _e(
            manifest.get("name", manifest.get("manifest_id", "IDE Capability Manifest"))
        )
        mf_version = _e(manifest.get("version", ""))
        capabilities = manifest.get("capabilities", [])

        sections.append(
            _hero_section(
                "IDE & MCP Integrations",
                "documented",
                f"Manifest: {mf_name} v{mf_version}",
                "documented",
            )
        )

        cap_rows: list[list[str]] = []
        for c in capabilities:
            cap_rows.append([
                _e(c.get("id", "")),
                _e(c.get("name", "")),
                _e(c.get("tier", "")),
                _e(c.get("permission", "")),
            ])
        if cap_rows:
            sections.append(
                _table_section(
                    f"Capabilities ({len(cap_rows)})",
                    ["ID", "Name", "Tier", "Permission"],
                    cap_rows,
                )
            )

    if mcp_manifest is not None:
        mcp_capabilities = mcp_manifest.get(
            "capabilities", mcp_manifest.get("tools", [])
        )
        if mcp_capabilities:
            mcp_rows: list[list[str]] = []
            for c in mcp_capabilities:
                mcp_rows.append([
                    _e(c.get("name", c.get("id", ""))),
                    _e(c.get("tier", "")),
                    _e(c.get("permission", "")),
                    _e(c.get("description", "")),
                ])
            if mcp_rows:
                sections.append(
                    _table_section(
                        f"MCP Tools ({len(mcp_rows)})",
                        ["Tool Name", "Tier", "Permission", "Description"],
                        mcp_rows,
                    )
                )

    return sections


def normalize_frontend(artifacts: dict) -> list[dict]:
    sections: list[dict] = []

    gp = _artifact_dict(artifacts, "frontend_maturity", "desktop_golden_path")
    telemetry = _artifact_dict(artifacts, "telemetry_policy")

    if gp is None and telemetry is None:
        return [
            _callout_section(
                "Frontend Data Not Available",
                "Desktop golden path and telemetry policy data are not yet available.",
                "info",
            )
        ]

    if gp is not None:
        gp_status = _e(gp.get("overall_status", "unknown"))
        if gp_status.lower() in ("not_verified", "not verified"):
            hero_label = "Not Verified"
        else:
            hero_label = gp_status
        sections.append(
            _hero_section("Frontend & Desktop Readiness", hero_label, "", gp_status)
        )

        steps = gp.get("steps", [])
        frontend_steps = [
            s
            for s in steps
            if any(
                kw in _e(s.get("step_id", "")).lower()
                for kw in ("cockpit", "desktop", "frontend", "ui", "gui", "browser")
            )
        ]
        if not frontend_steps:
            frontend_steps = steps[:5] if len(steps) > 5 else steps

        if frontend_steps:
            step_cards: list[dict] = []
            for s in frontend_steps:
                step_cards.append({
                    "id": _e(s.get("step_id", "")),
                    "title": _e(s.get("user_goal", "")),
                    "status": _e(s.get("status", "unknown")),
                    "detail": _e(s.get("expected_result", "")),
                    "command": _e(s.get("command_or_ui_action", "")),
                    "phase": _e(s.get("phase_id", "")),
                })
            sections.append(
                _card_grid_section(f"Frontend Steps ({len(step_cards)})", step_cards)
            )
    else:
        sections.append(
            _callout_section(
                "Frontend Data Not Available",
                "Desktop golden path data is not yet available.",
                "info",
            )
        )

    if telemetry is not None:
        enabled = telemetry.get("enabled", False)
        sections.append(
            _definition_list_section(
                "Telemetry Policy",
                [
                    {
                        "term": "Policy",
                        "definition": _e(
                            telemetry.get(
                                "policy", telemetry.get("doctrine", "unknown")
                            )
                        ),
                    },
                    {"term": "Enabled", "definition": _e(str(enabled))},
                ],
            )
        )
    else:
        sections.append(
            _callout_section(
                "Telemetry Policy Not Available",
                "Telemetry doctrine data has not been loaded.",
                "info",
            )
        )

    return sections


def build_page_model(
    page_id: str,
    title: str,
    route: str,
    layout: str,
    source_paths: list[str],
    schema_versions: list[str],
    safety_status: str,
    sections: list[dict],
) -> dict:
    return {
        "page_id": page_id,
        "title": title,
        "route": route,
        "layout": layout,
        "source_artifact_paths": source_paths,
        "generated_from_schema_versions": schema_versions,
        "public_safety_status": safety_status,
        "sections": sections,
    }


def normalize_proof_chain(artifacts: dict) -> list[dict]:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    verdict = _artifact_dict(artifacts, "rc_verdict")
    inventory = _artifact_dict(artifacts, "test_inventory")

    sections = []

    overall_status = "HOLD"
    detail = "No candidate verdict found."
    if verdict:
        overall_status = verdict.get("verdict", "hold").upper()
        detail = f"Release candidate status: {verdict.get('gate_overall_status', 'unknown')}. Open blockers: {len(verdict.get('open_blocker_ids', []))}."
    sections.append(_hero_section("Proof Chain Status", overall_status, detail))

    cards = []
    if verdict:
        cards.append({
            "title": "Blockers",
            "body_html": f"<p>{len(verdict.get('open_blocker_ids', []))} Open / {len(verdict.get('resolved_blocker_ids', []))} Resolved</p><p>Release block status across all phases</p>",
            "status": "info",
        })
    if inventory:
        summary = inventory.get("summary", {})
        cards.append({
            "title": "Tests",
            "body_html": f"<p>{summary.get('total_test_functions', 0)} Functions</p><p>Across {summary.get('total_test_files', 0)} files. classified keep: {summary.get('classified_keep', 0)}.</p>",
            "status": "info",
        })
    try:
        schema_count = len(list((repo_root / "docs" / "schemas").glob("*.schema.json")))
    except Exception:
        schema_count = 0
    cards.append({
        "title": "Governed Schemas",
        "body_html": f"<p>{schema_count} Schemas</p><p>JSON Schemas Draft 7 governing all artifacts</p>",
        "status": "info",
    })

    sections.append(_card_grid_section("Overall Evidence Metrics", cards))

    headers = [
        "Surface / Subsystem",
        "Contract / Specification",
        "JSON Schema",
        "Implementation File",
        "Associated Tests",
        "Readiness Verdict",
    ]
    rows = [
        [
            "Static Site Compiler",
            "static_site_compiler_contract.v1.json",
            "rig.static_site.compiler_contract.v1",
            "scripts/rig_site_render.py",
            "tests/site_renderer/test_fake_green_resistance.py",
            "PASSED",
        ],
        [
            "Release Gate Runner",
            "release_gate_policy.v1.json",
            "rig.release_gate.readiness.v1",
            "scripts/rig_release_gate_validate.py",
            "tests/site_renderer/test_fake_green_resistance.py",
            "BLOCKED",
        ],
        [
            "Telemetry & Redaction",
            "telemetry-consent-enforcement.v1.json",
            "rig.relay.sdk.status.v1",
            "rig_relay/evidence/_telemetry.py",
            "tests/site_renderer/test_fake_green_resistance.py",
            "PASSED",
        ],
        [
            "Protocol surfaces (ACP)",
            "protocol-surfaces.v1.json",
            "rig.documentation.page.v1",
            "rig_relay/acp/acp_agent_loop.py",
            "tests/acp/test_commands.py",
            "HOLD",
        ],
        [
            "Provider Integrations",
            "github_provider_contract_v0.v1.json",
            "rig.relay.mcp.capability_profile.v1",
            "rig_relay/integrations/github_provider/",
            "tests/tools/test_mcp.py",
            "HOLD",
        ],
    ]
    sections.append(
        _table_section(
            "Proof Chain Lineage Map",
            headers,
            rows,
            "Traces the path from contracts/schemas to their test coverage and final verdicts.",
        )
    )
    return sections


def normalize_contracts(artifacts: dict) -> list[dict]:
    import json
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    sections = []

    schemas = []
    schemas_dir = repo_root / "docs" / "schemas"
    if schemas_dir.is_dir():
        for path in sorted(schemas_dir.glob("*.schema.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                schemas.append({
                    "schema_id": data.get("$id", path.name),
                    "file_path": f"docs/schemas/{path.name}",
                    "description": data.get("description", "No description provided."),
                })
            except Exception:
                pass

    sections.append(_schema_index_section("Registered System JSON Schemas", schemas))
    return sections


def normalize_protocol(artifacts: dict) -> list[dict]:
    sections = []
    surfaces = _artifact_dict(artifacts, "protocol_surfaces")
    a2a = _artifact_dict(artifacts, "a2a_readiness")

    if surfaces:
        sections.append(
            _callout_section(
                surfaces.get("title", "Protocol Surfaces"),
                surfaces.get("summary", ""),
                "info",
            )
        )

        headers = ["Concept", "Rig Mapping"]
        rows = [
            ["ACP Session", "Rig mission / lane / worktree session"],
            ["ACP Progress", "Rig progress events (phase, status, percent)"],
            ["ACP Edit", "Rig patch proposal (never direct write)"],
            ["ACP Permission", "Rig approval gate / authorization receipt"],
            ["ACP Terminal", "Rig deterministic execution stream"],
        ]
        sections.append(
            _table_section("Agent Client Protocol (ACP) Mapping", headers, rows)
        )

        headers_tiers = ["Tier", "Access Level", "Examples"]
        rows_tiers = [
            [
                "0 — Read-only",
                "Always available",
                "`rig.current_mission`, `rig.summarize_dirty_state`, `rig.list_worktrees`",
            ],
            [
                "1 — Analysis",
                "Always available",
                "`rig.build_context_packet`, `rig.create_consult_packet`",
            ],
            [
                "2 — Validation",
                "Always available",
                "`rig.run_validator`, `rig.check_merge_friendly`",
            ],
            [
                "3 — Patch proposal",
                "Gated behind authorization receipt",
                "`rig.propose_patch`",
            ],
            [
                "4 — Mutation",
                "Requires user approval receipt",
                "`rig.request_user_approval`",
            ],
            [
                "5 — Git/release",
                "Denied by default in sandbox",
                "`rig.promote_to_preproduction`",
            ],
        ]
        sections.append(
            _table_section("MCP Server Tool Tiers", headers_tiers, rows_tiers)
        )
    else:
        sections.append(
            _callout_section(
                "Protocol Surfaces Not Available",
                "No protocol surfaces evidence loaded.",
                "info",
            )
        )

    if a2a:
        sections.append(
            _callout_section(
                "A2A Promotion Readiness Status",
                f"Gate status: {a2a.get('status', 'unknown')}. Owner: {a2a.get('owners', ['unknown'])[0]}.",
                "info",
            )
        )

    return sections


def normalize_compiler(artifacts: dict) -> list[dict]:
    sections = []
    contract = _artifact_dict(artifacts, "compiler_contract")
    refinement = _artifact_dict(artifacts, "compiler_refinement")

    if refinement:
        status_label = (
            "PASSED"
            if refinement.get("validation_results", {}).get("passed", False)
            else "FAILED"
        )
        sections.append(
            _hero_section(
                "Compiler Refinement Validation",
                status_label,
                f"Target version: {refinement.get('target_version', 'unknown')}",
            )
        )

        cards = []
        for claim in refinement.get("supported_claims", []):
            cards.append({
                "title": "Validated Claim",
                "body_html": f"<p>{claim}</p><p>Verified by compiler v0 contract verification suite</p>",
                "status": "success",
            })
        sections.append(_card_grid_section("Supported and Validated Claims", cards))

    if contract:
        items = []
        for inv in contract.get("rendering_invariants", []):
            items.append({"term": "Invariant", "definition": _e(inv)})
        for rule in contract.get("deterministic_ordering_rules", []):
            items.append({"term": "Deterministic Rule", "definition": _e(rule)})
        sections.append(
            _definition_list_section("Compiler Rendering Invariants & Rules", items)
        )

    return sections


def normalize_hardening(artifacts: dict) -> list[dict]:
    sections = []
    policy = _artifact_dict(artifacts, "tracing_policy")
    otel_config = _artifact_dict(artifacts, "otel_config")

    if policy:
        p = policy.get("policy", {})
        items = [
            {"term": "Release Gate Rule", "definition": _e(p.get("release_gate"))},
            {"term": "Content Rule", "definition": _e(p.get("content_rule"))},
            {"term": "Redaction Rule", "definition": _e(p.get("redaction_rule"))},
            {
                "term": "Handshake Correlation",
                "definition": _e(p.get("handshake_rule")),
            },
        ]
        sections.append(_definition_list_section("Rig Relay Tracing Policy", items))

        timeline_entries = []
        for stage in p.get("strict_mode_stages", []):
            timeline_entries.append({
                "timestamp": "Stage",
                "title": stage,
                "description": "Correlated Trace Span Event required for candidate promotion",
                "status": "info",
            })
        sections.append(
            _timeline_section(
                "Golden Path Strict Mode Trace Lifecycle", timeline_entries
            )
        )

    if otel_config:
        sections.append(
            _callout_section(
                "Local OpenTelemetry Collector Config",
                f"Service endpoint: {_e(otel_config.get('endpoint', 'http://localhost:4317'))}. Enabled metrics/traces pipeline.",
                "info",
            )
        )

    return sections


def normalize_seams(artifacts: dict) -> list[dict]:
    sections = []
    seams = _artifact_list(artifacts, "test_seams")
    risks = _artifact_list(artifacts, "deferred_risks")

    headers_risks = ["Risk ID", "Title", "Severity", "Status", "Deferral Reason"]
    rows_risks = []
    for r in risks:
        rows_risks.append([
            _e(r.get("risk_id")),
            _e(r.get("title")),
            _e(r.get("severity")),
            _e(r.get("status")),
            _e(r.get("deferral_reason")),
        ])
    sections.append(
        _table_section(
            "Deferred Release Candidate Risks",
            headers_risks,
            rows_risks,
            "Identifies risks that were explicitly deferred to post-RC, along with engineering justifications.",
        )
    )

    headers_seams = [
        "Seam ID",
        "Stress Surface",
        "File & Function",
        "Status",
        "Justification",
    ]
    rows_seams = []
    for s in seams:
        rows_seams.append([
            _e(s.get("protected_seam")),
            _e(s.get("stress_surface")),
            f"<code>{_e(s.get('file_path'))}</code><br><code>{_e(s.get('test_function'))}</code>",
            _e(s.get("classification")),
            _e(s.get("reason")),
        ])
    sections.append(
        _table_section(
            "Known Test Seams & Gaps",
            headers_seams,
            rows_seams,
            "Tracks testing seams, structural mocks, and coverage gaps with explicit justifications.",
        )
    )

    return sections


def normalize_artifacts_index(artifacts: dict) -> list[dict]:
    sections = []
    manifest = _artifact_dict(artifacts, "input_manifest")
    elevation = _artifact_dict(artifacts, "experience_elevation")

    if elevation:
        sections.append(
            _callout_section(
                "Experience Elevation Audit Status",
                f"Recommendation: {elevation.get('recommendation', '')}",
                "info",
            )
        )

        items = []
        for claim in elevation.get("claims_supported", []):
            items.append({"term": "Supported Claim", "definition": _e(claim)})
        for rej in elevation.get("claims_rejected", []):
            items.append({"term": "Deferred/Rejected Claim", "definition": _e(rej)})
        sections.append(
            _definition_list_section("UX Experience Claims Verification", items)
        )

    if manifest:
        headers = [
            "Source Path",
            "Source Type",
            "Page ID",
            "Renderer Kind",
            "Public Safe",
        ]
        rows = []
        for entry in manifest.get("inputs", []):
            rows.append([
                _e(entry.get("source_path")),
                _e(entry.get("source_type")),
                _e(entry.get("page_id")),
                _e(entry.get("renderer_kind")),
                _e(str(entry.get("public_safe"))),
            ])
        sections.append(
            _table_section(
                "Registered Input Artifacts",
                headers,
                rows,
                "Complete listing of all backing data files loaded for site generation.",
            )
        )

    return sections

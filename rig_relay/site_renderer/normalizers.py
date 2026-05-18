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

_RELEASE_GATE_PATHS = {
    "gate": "docs/json/release_gate/rc_readiness_gate.v1.json",
    "verdict": "docs/json/release_gate/rc_candidate_verdict.v1.json",
    "golden_path": "docs/json/release_candidate/rc_reviewer_golden_path.v1.json",
}

_TESTING_PATHS = {
    "inventory": "docs/json/testing/test_inventory.v1.json",
    "classifications": "docs/json/testing/test_classification.v1.jsonl",
    "seams": "docs/json/testing/known_test_seams.v1.jsonl",
}

_INTEGRATION_PATHS = {
    "ide_capability_map": "docs/protocols/ide-capability-map.md",
    "mcp_capability_map": "docs/protocols/mcp-capability-map.md",
    "capability_manifest": "etc/rig.ide.capability_manifest.v1.json",
    "protocol_index": None,
}

_FRONTEND_PATHS = {
    "telemetry_doctrine": "docs/governance/usage-data-doctrine.md",
    "desktop_golden_path": "docs/json/release_candidate/rc_reviewer_golden_path.v1.json",
    "telemetry_policy": None,
}


def _e(text: object) -> str:
    if text is None:
        return ""
    return html.escape(str(text))


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
    gate = artifacts.get("gate")
    verdict = artifacts.get("verdict")
    golden_path = artifacts.get("golden_path")

    if gate is None and verdict is None and golden_path is None:
        return [
            _callout_section(
                "Release Gate Data Missing",
                "No release gate artifacts found. Run the release gate validator to populate this data.",
            )
        ]

    sections: list[dict] = []

    if gate is not None:
        overall = _e(gate.get("overall_status", "unknown"))
        gate_id = _e(gate.get("gate_id", ""))
        branch = _e(gate.get("branch", ""))
        head_sha = _e(gate.get("head_sha", ""))[:12]
        generated = _e(gate.get("generated_at", ""))

        sections.append(
            _hero_section(
                "Release Gate Readiness",
                overall,
                f"Gate: {gate_id} | Branch: {branch} | SHA: {head_sha}",
                overall,
            )
        )

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
    inventory = artifacts.get("inventory")
    classifications = artifacts.get("classifications")
    seams = artifacts.get("seams")

    if inventory is None and classifications is None and seams is None:
        return [
            _callout_section(
                "Test Data Missing",
                "No test artifacts found. Run the test inventory and classification scans.",
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

    if classifications is not None:
        definition_items: list[dict] = []
        counts = (
            classifications.get("counts", {})
            if isinstance(classifications, dict)
            else {}
        )

        for marker, count in sorted(counts.items()):
            definition_items.append({
                "term": _e(marker),
                "definition": f"Count: {_e(count)}",
            })

        if definition_items:
            sections.append(
                _definition_list_section("Classification Counts", definition_items)
            )

    if isinstance(seams, list) and seams:
        seam_entries: list[dict] = []
        for i, s in enumerate(seams):
            seam_entries.append({
                "id": _e(s.get("protected_seam", s.get("seam_id", f"seam-{i}"))),
                "title": _e(s.get("reason", s.get("description", ""))),
                "detail": _e(s.get("stress_surface", "")),
                "status": _e(s.get("classification", "unknown")),
            })
        sections.append(
            _timeline_section(f"Known Seams ({len(seam_entries)})", seam_entries)
        )

    return sections


def normalize_integrations(artifacts: dict) -> list[dict]:
    sections: list[dict] = []

    manifest = artifacts.get("capability_manifest")
    has_data = manifest is not None

    if has_data and manifest is not None:
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
    else:
        sections.append(
            _callout_section(
                "Integration Data Not Available",
                "IDE capability manifest and MCP capability map are not yet available.",
                "info",
            )
        )

    return sections


def normalize_frontend(artifacts: dict) -> list[dict]:
    sections: list[dict] = []

    gp = artifacts.get("desktop_golden_path")

    if gp is not None:
        gp_status = _e(gp.get("overall_status", "unknown"))
        sections.append(
            _hero_section("Frontend & Desktop Readiness", gp_status, "", gp_status)
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
                "Desktop golden path and telemetry policy data are not yet available.",
                "info",
            )
        )

    telemetry = artifacts.get("telemetry_policy")
    if telemetry is not None:
        sections.append(
            _definition_list_section(
                "Telemetry Policy",
                [
                    {
                        "term": "Policy",
                        "definition": _e(telemetry.get("policy", "unknown")),
                    },
                    {
                        "term": "Enabled",
                        "definition": str(telemetry.get("enabled", False)),
                    },
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

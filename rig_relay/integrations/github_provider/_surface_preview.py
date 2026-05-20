from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PACKETS_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_surface_packets_v1.v1.json"
)
_DEFAULT_OUTPUT_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_surface_preview_v1.v1.json"
)

_PREVIEW_TARGETS: frozenset[str] = frozenset({
    "project_readme_preview",
    "profile_readme_preview",
    "github_pages_preview",
    "badge_status_preview",
    "release_notes_preview",
    "security_posture_preview",
    "claim_cleanup_preview",
})

_SURFACE_ROLE_TO_PREVIEW_TARGET: dict[str, str] = {
    "project_readme": "project_readme_preview",
    "profile_readme": "profile_readme_preview",
    "static_site_pages": "github_pages_preview",
    "badge_status_block": "badge_status_preview",
    "changelog": "release_notes_preview",
    "security_policy": "security_posture_preview",
    "public_claims": "claim_cleanup_preview",
}


class GitHubSurfacePreviewError(Exception):
    """Raised when surface preview generation fails."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _derive_action(packet: dict) -> str:
    packet_type = packet.get("packet_type", "")
    role = packet.get("target_surface_role", "")
    actions: dict[str, str] = {
        "project_readme": "project_readme_update",
        "profile_readme": "profile_readme_update",
        "static_site_pages": "static_site_publish_check",
        "badge_status_block": "badge_status_block",
        "changelog": "changelog_update",
        "security_policy": "security_policy_review",
        "public_claims": "unsupported_claim_cleanup",
    }
    return actions.get(role, packet_type or "unknown_action")


def _derive_status(packet: dict) -> str:
    if packet.get("apply_ready") is True:
        return "ready"
    if packet.get("preview_ready") is False:
        return "blocked"
    return "proposed"


def _is_safe(packet: dict) -> tuple[bool, list[str]]:
    seams: list[str] = []

    if packet.get("apply_ready") is True:
        seams.append("apply_ready_is_true")
    if packet.get("remote_mutation") is True:
        seams.append("remote_mutation_is_true")
    if packet.get("generated_public_text_allowed") is True:
        seams.append("generated_public_text_allowed")
    packet_seams = packet.get("remaining_seams", [])
    if isinstance(packet_seams, list):
        seams.extend(packet_seams)

    if not seams:
        return True, ["no_safety_issues"]
    return False, seams


def _render_status_for(packet: dict) -> str:
    target = packet.get("target_surface_role", "")
    if target in {"profile_readme", "static_site_pages"}:
        return "blocked"
    if packet.get("preview_ready") is False:
        return "blocked"
    if packet.get("apply_ready") is True:
        return "not_rendered"
    return "rendered"


def _build_preview_entry(packet: dict) -> dict:
    packet_id = str(packet.get("packet_id", ""))
    surface_role = str(packet.get("target_surface_role", ""))
    target = _SURFACE_ROLE_TO_PREVIEW_TARGET.get(surface_role, surface_role)
    action = _derive_action(packet)
    proposed = str(packet.get("proposed_change_summary", ""))
    evidence_refs = packet.get("evidence_refs", [])

    payload = f"{packet_id}|{target}|{action}|{proposed}"
    preview_id = "sha256:" + _sha256_text(payload)
    preview_hash = _sha256_text(preview_id + "|v1")

    safety_ok, safety_seams = _is_safe(packet)
    render_status = _render_status_for(packet)

    human_review = bool(packet.get("human_review_required", False))
    if render_status == "blocked":
        human_review = True

    refs: list[str] = []
    if isinstance(evidence_refs, list):
        refs.extend(f"evidence:{e}" for e in evidence_refs if isinstance(e, str))
    refs.append(f"source_role:{surface_role}")

    return {
        "preview_id": preview_id,
        "packet_id": packet_id,
        "target_surface_role": target,
        "preview_artifact_path": None,
        "preview_hash": preview_hash,
        "render_status": render_status,
        "safety_status": "safe" if safety_ok else "blocked",
        "evidence_refs": refs,
        "human_review_required": human_review,
        "local_mutation": False,
        "remote_mutation": False,
        "remaining_seams": safety_seams,
    }


def _validate_packets(packets: list[dict]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_targets: set[str] = set()

    for idx, packet in enumerate(packets):
        packet_id = packet.get("packet_id")
        if not isinstance(packet_id, str) or not packet_id:
            errors.append(f"packet[{idx}]: missing or invalid packet_id")
            continue
        if packet_id in seen_ids:
            errors.append(f"packet[{idx}]: duplicate packet_id '{packet_id}'")
            continue
        seen_ids.add(packet_id)

        surface_role = packet.get("target_surface_role")
        if not isinstance(surface_role, str) or not surface_role:
            errors.append(f"packet[{idx}]: missing or invalid target_surface_role")
            continue

        target = _SURFACE_ROLE_TO_PREVIEW_TARGET.get(surface_role, "")
        if not target:
            continue

        if target in seen_targets:
            errors.append(
                f"packet[{idx}]: duplicate preview target '{target}' "
                f"(from role '{surface_role}')"
            )
            continue
        seen_targets.add(target)

    return errors


def _filter_mappable_packets(packets: list[dict]) -> list[dict]:
    return [
        p
        for p in packets
        if isinstance(p.get("target_surface_role"), str)
        and p["target_surface_role"] in _SURFACE_ROLE_TO_PREVIEW_TARGET
    ]


def _build_summary(entries: list[dict]) -> dict:
    rendered = sum(1 for e in entries if e["render_status"] == "rendered")
    blocked = sum(1 for e in entries if e["render_status"] == "blocked")
    not_rendered = sum(1 for e in entries if e["render_status"] == "not_rendered")

    return {
        "total_packets": len(entries),
        "previewed_count": rendered,
        "blocked_count": blocked,
        "not_rendered_count": not_rendered,
        "next_recommended_action": (
            "human_review_required"
            if any(e["human_review_required"] for e in entries)
            else "surfaces_inspected"
        ),
    }


@dataclass(slots=True)
class GitHubSurfacePreview:
    root: Path = field(default_factory=lambda: _REPO_ROOT)
    packets_path: Path | None = None
    output_path: Path | None = None

    def run(self) -> dict:
        packets_path = self.packets_path or _DEFAULT_PACKETS_JSON
        output_path = self.output_path or _DEFAULT_OUTPUT_JSON

        try:
            raw = json.loads(packets_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise GitHubSurfacePreviewError(
                f"Failed to load packets from {packets_path}"
            ) from e

        packets = raw.get("packets")
        if not isinstance(packets, list):
            raise GitHubSurfacePreviewError("Packets file missing 'packets' array")

        errors = _validate_packets(packets)
        if errors:
            raise GitHubSurfacePreviewError(
                f"Packet validation failed: {'; '.join(errors)}"
            )

        mappable = _filter_mappable_packets(packets)
        if not mappable:
            raise GitHubSurfacePreviewError("No packets map to preview targets")

        entries = [_build_preview_entry(p) for p in mappable]
        summary = _build_summary(entries)

        report: dict = {
            "schema_version": "rig.github.surface_preview.v1",
            "generated_at": _now_iso(),
            "content_light": True,
            "remote_mutation": False,
            "local_mutation": False,
            "preview_entries": entries,
            "summary": summary,
        }

        assert_content_light_mapping(report)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        return safe_summary(report)


def build_github_surface_preview(
    *, packets_path: Path | None = None, output_path: Path | None = None
) -> dict:
    return GitHubSurfacePreview(
        packets_path=packets_path, output_path=output_path
    ).run()


__all__ = [
    "GitHubSurfacePreview",
    "GitHubSurfacePreviewError",
    "build_github_surface_preview",
]

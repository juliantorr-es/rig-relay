from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PACKETS_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_surface_packets_v1.v1.json"
)
_DEFAULT_PREVIEW_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_surface_preview_v1.v1.json"
)
_DEFAULT_OUTPUT_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_publish_pr_v1.v1.json"
)

_MAX_TITLE_PACKETS = 3

_VALIDATION_COMMANDS = [
    "uv run python scripts/rig_relay_validate_schemas.py",
    "uv run pytest tests/integrations/test_github_publish_pr.py -v",
    "uv run pytest tests/adversarial/test_github_publish_pr_redaction.py -v",
    "uv run pytest tests/governance/test_github_publish_pr_artifact.py -v",
]


class GitHubPublishPrError(Exception):
    """Raised when publish PR pipeline fails."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else str(value) if value is not None else ""


def _as_bool(value: object) -> bool:
    return bool(value) if value is not None else False


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _read_json(path: Path) -> dict | None:
    try:
        result = read_safe(path)
        data = json.loads(result.text)
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def _summarize_packets(packets_data: dict) -> dict:
    packets = _as_list(packets_data.get("packets"))
    source_artifacts = _as_list(packets_data.get("source_artifacts"))
    return {
        "total_packets": len(packets),
        "ready_packets": sum(
            1 for p in packets if _as_str(_as_dict(p).get("status")) == "ready"
        ),
        "blocked_packets": sum(
            1 for p in packets if _as_str(_as_dict(p).get("status")) == "blocked"
        ),
        "deferred_packets": sum(
            1 for p in packets if _as_str(_as_dict(p).get("status")) == "deferred"
        ),
        "packet_type_summary": list({
            _as_str(_as_dict(p).get("packet_type"))
            for p in packets
            if isinstance(p, dict)
        }),
        "source_artifact_count": len(source_artifacts),
        "content_light": True,
    }


def _summarize_preview(preview_data: dict) -> dict:
    return {
        "preview_type": _as_str(preview_data.get("preview_type")),
        "branch": _as_str(preview_data.get("branch")),
        "ready_packets": _as_dict(preview_data.get("packet_summary", {})).get(
            "ready_count", 0
        ),
        "total_packets": _as_dict(preview_data.get("packet_summary", {})).get(
            "total_packets", 0
        ),
        "surface_ready_count": _as_dict(preview_data.get("surface_summary", {})).get(
            "ready_count", 0
        ),
        "content_light": True,
    }


def _build_proposal(packets_data: dict, preview_data: dict) -> dict:
    packets = _as_list(packets_data.get("packets"))
    ready_packets = [
        p
        for p in packets
        if isinstance(p, dict) and _as_str(p.get("status")) == "ready"
    ]

    surfaces = {_as_str(p.get("source_surface")) for p in ready_packets}
    titles = [p for p in ready_packets if isinstance(p, dict)]
    title_parts = sorted({_as_str(t.get("packet_id")) for t in titles})

    proposed_title = "Public Surface Program Wave 6: Publish PR v1 — " + ", ".join(
        title_parts[:_MAX_TITLE_PACKETS]
    )
    if len(title_parts) > _MAX_TITLE_PACKETS:
        proposed_title += f" (+{len(title_parts) - _MAX_TITLE_PACKETS} more)"

    recommended = _as_list(preview_data.get("recommended_actions"))

    return {
        "proposed_branch": "public-surface/wave6/publish-pr-v1",
        "proposed_pr_title": proposed_title,
        "proposed_pr_summary": (
            f"Publish PR v1 for GitHub Public Surface Program Wave 6.\n\n"
            f"Ready surfaces: {', '.join(sorted(surfaces))}.\n"
            f"Recommended actions: {'; '.join(recommended) if recommended else 'none'}."
        ),
        "proposed_files": sorted(surfaces),
        "proposed_base_branch": "main",
        "proposed_labels": ["public-surface", "wave-6", "publish-pr-v1"],
        "evidence_refs": _as_list(preview_data.get("evidence_refs")),
    }


def _build_report(
    *,
    config: GitHubPublishPrConfig,
    packets_data: dict | None,
    preview_data: dict | None,
    source_packets_hash: str,
    source_preview_hash: str,
    refusal_reasons: list[str],
    result_status: str,
) -> dict:
    proposal = (
        _build_proposal(packets_data, preview_data)
        if packets_data is not None and preview_data is not None
        else {
            "proposed_branch": "",
            "proposed_pr_title": "",
            "proposed_pr_summary": "",
            "proposed_files": [],
            "proposed_base_branch": "",
            "proposed_labels": [],
            "evidence_refs": [],
        }
    )

    return {
        "schema_version": "rig.github.publish_pr.v1",
        "generated_at": _now_iso(),
        "mode": "execute_remote" if config.execute_remote else "dry_run",
        "dry_run": config.dry_run,
        "execute_remote_flag_passed": config.execute_remote,
        "content_light": True,
        "remote_mutation": (
            config.execute_remote and not config.dry_run and result_status != "refused"
        ),
        "local_mutation": False,
        "result_status": result_status,
        "refusal_reasons": refusal_reasons,
        "source_packets_artifact": str(config.packets_path),
        "source_preview_artifact": str(config.preview_path),
        "source_packets_hash": source_packets_hash,
        "source_preview_hash": source_preview_hash,
        "approval_gate_status": "pending_review",
        "permission_audit_refs": [
            "docs/json/governance/github_app_permission_posture_v1.v1.json",
            "docs/json/governance/github_surface_audit_v1.v1.json",
        ],
        "source_packets": (
            _summarize_packets(packets_data)
            if packets_data is not None
            else {"content_light": True}
        ),
        "source_previews": (
            _summarize_preview(preview_data)
            if preview_data is not None
            else {"content_light": True}
        ),
        "proposal": proposal,
        "validation_commands": list(_VALIDATION_COMMANDS),
        "redaction_status": "content_light_verified",
        "remaining_seams": [],
    }


@dataclass(slots=True)
class GitHubPublishPrConfig:
    packets_path: Path = field(default_factory=lambda: _DEFAULT_PACKETS_JSON)
    preview_path: Path = field(default_factory=lambda: _DEFAULT_PREVIEW_JSON)
    dry_run: bool = True
    execute_remote: bool = False


def _validate_prerequisites(
    config: GitHubPublishPrConfig, packets_data: dict | None, preview_data: dict | None
) -> tuple[list[str], str] | None:
    refusals: list[str] = []

    if packets_data is None:
        refusals.append(
            f"packets_missing: source packets not found at {config.packets_path}"
        )
    if preview_data is None:
        refusals.append(
            f"preview_missing: source preview not found at {config.preview_path}"
        )
    if refusals:
        return (refusals, "refused")

    if config.execute_remote and config.dry_run:
        return (
            [
                "execute_remote_requested_in_dry_run: "
                "Cannot perform remote mutation when dry_run is True. "
                "Pass --execute-remote without --dry-run to proceed."
            ],
            "refused",
        )

    if config.execute_remote:
        return (
            [
                "execute_remote_not_implemented: "
                "Remote PR creation is not yet implemented. "
                "This is a proposal-only artifact."
            ],
            "refused",
        )

    return None


def build_github_publish_pr(
    *,
    packets_path: Path | None = None,
    preview_path: Path | None = None,
    dry_run: bool = True,
    execute_remote: bool = False,
) -> dict:
    config = GitHubPublishPrConfig(
        packets_path=packets_path or _DEFAULT_PACKETS_JSON,
        preview_path=preview_path or _DEFAULT_PREVIEW_JSON,
        dry_run=dry_run,
        execute_remote=execute_remote,
    )

    packets_data = _read_json(config.packets_path)
    preview_data = _read_json(config.preview_path)

    source_packets_hash = (
        _sha256_file(config.packets_path) if config.packets_path.exists() else ""
    )
    source_preview_hash = (
        _sha256_file(config.preview_path) if config.preview_path.exists() else ""
    )

    refusal = _validate_prerequisites(config, packets_data, preview_data)
    if refusal is not None:
        refusal_reasons, result_status = refusal
        report = _build_report(
            config=config,
            packets_data=packets_data,
            preview_data=preview_data,
            source_packets_hash=source_packets_hash,
            source_preview_hash=source_preview_hash,
            refusal_reasons=refusal_reasons,
            result_status=result_status,
        )
        return _finalize(report)

    assert packets_data is not None
    assert preview_data is not None

    report = _build_report(
        config=config,
        packets_data=packets_data,
        preview_data=preview_data,
        source_packets_hash=source_packets_hash,
        source_preview_hash=source_preview_hash,
        refusal_reasons=[],
        result_status="proposal_ready",
    )
    return _finalize(report)


def _finalize(report: dict) -> dict:
    assert_content_light_mapping(report)
    return safe_summary(report)


__all__ = ["GitHubPublishPrConfig", "GitHubPublishPrError", "build_github_publish_pr"]

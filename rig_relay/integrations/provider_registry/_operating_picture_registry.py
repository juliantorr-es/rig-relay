"""Cross-provider operating picture registry — deterministic, content-light.

Reads operating picture artifacts from GitHub, Google Workspace, and Meta
providers and produces a unified registry artifact.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from rig_relay.core.utils.io import read_safe

_REPO_ROOT = Path(__file__).resolve().parents[3]

_PROVIDER_DEFS: dict[str, dict[str, Any]] = {
    "github": {
        "display_name": "GitHub",
        "op_picture_path": _REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_operating_picture_v1.v1.json",
        "schema_version": "rig.github.operating_picture.v1",
    },
    "google_workspace": {
        "display_name": "Google Workspace",
        "op_picture_path": _REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "google_workspace_operating_picture_v1.v1.json",
        "schema_version": "rig.google_workspace.operating_picture.v1",
    },
    "meta": {
        "display_name": "Meta",
        "op_picture_path": _REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "meta_operating_picture_v1.v1.json",
        "schema_version": "rig.meta.operating_picture.v1",
    },
}

_HIGH_RISK_REFUSAL_THRESHOLD = 3


_DEFAULT_OUTPUT_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "provider_operating_picture_registry_v1.v1.json"
)

_FORBIDDEN_FIELDS = frozenset({
    "access_token",
    "refresh_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "code_snippet",
    "patch",
    "diff",
    "contents",
})


class ProviderRegistryError(Exception):
    """Raised when provider registry cannot be built."""


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_text(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip()
        return text if text else default
    text = str(value).strip()
    return text if text else default


def _load_git_metadata(repo_root: Path) -> tuple[str | None, str | None]:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return branch or None, head or None
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _load_op_picture(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    raw = read_safe(path, raise_on_error=True)
    try:
        data = json.loads(raw.text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return None


def _derive_github_auth_status(op: dict[str, Any]) -> str:
    auth = op.get("auth_summary")
    if not isinstance(auth, dict):
        return "unknown"
    if auth.get("installation_access_proven"):
        return "working"
    if auth.get("app_installation_configured"):
        return "configured"
    return "unconfigured"


def _derive_github_intake_status(op: dict[str, Any]) -> str:
    intake = op.get("intake_summary")
    if not isinstance(intake, dict):
        return "missing"
    cs = intake.get("code_scanning", {})
    dep = intake.get("dependabot", {})
    if isinstance(cs, dict) and cs.get("status") == "present":
        if isinstance(dep, dict) and dep.get("status") == "refused":
            return "partial"
        return "present"
    return "missing"


def _derive_github_packet_status(op: dict[str, Any]) -> str:
    packet = op.get("packet_summary")
    if not isinstance(packet, dict):
        return "missing"
    if packet.get("packet_index_stale"):
        return "stale"
    if packet.get("packet_count", 0) > 0:
        return "present"
    return "missing"


def _derive_github_surface_status(op: dict[str, Any]) -> str:
    permission = op.get("permission_summary")
    if not isinstance(permission, dict):
        return "missing"
    refused = permission.get("refused_surfaces", [])
    available = permission.get("known_available_surfaces", [])
    if refused and available:
        return "partial"
    if available:
        return "present"
    return "missing"


def _derive_github_next_action(op: dict[str, Any]) -> str:
    actions = op.get("next_recommended_actions", [])
    if isinstance(actions, list) and actions:
        return actions[0]
    summary = op.get("summary")
    if isinstance(summary, dict):
        return summary.get("next_recommended_action", "no_action")
    return "no_action"


def _derive_google_auth_status(op: dict[str, Any]) -> str:
    auth = op.get("auth_summary")
    if not isinstance(auth, dict):
        return "unknown"
    if auth.get("oauth_configured") or auth.get("token_hash_present"):
        return "configured"
    return "unconfigured"


def _derive_google_intake_status(op: dict[str, Any]) -> str:
    surface = op.get("surface_summary")
    if not isinstance(surface, dict):
        return "missing"
    present = sum(
        1
        for s in surface.values()
        if isinstance(s, dict) and s.get("status") == "present"
    )
    refused = sum(
        1
        for s in surface.values()
        if isinstance(s, dict) and s.get("status") == "refused"
    )
    if present > 0 and refused > 0:
        return "partial"
    if present > 0:
        return "present"
    if refused > 0:
        return "refused"
    return "missing"


def _derive_google_packet_status(op: dict[str, Any]) -> str:
    source = op.get("source_artifacts")
    if isinstance(source, list):
        for art in source:
            if isinstance(art, dict) and art.get("artifact_id") == "read_intake":
                if art.get("present"):
                    return "present"
    return "not_implemented"


def _derive_google_next_action(op: dict[str, Any]) -> str:
    actions = op.get("next_recommended_actions", [])
    if isinstance(actions, list) and actions:
        return actions[0]
    return "no_action"


def _derive_meta_auth_status(op: dict[str, Any]) -> str:
    config = op.get("configured_summary")
    if not isinstance(config, dict):
        return "unknown"
    if config.get("access_token_configured"):
        return "configured"
    return "unconfigured"


def _derive_meta_intake_status(op: dict[str, Any]) -> str:
    surface = op.get("surface_summary")
    if not isinstance(surface, dict):
        return "missing"
    has_unconfigured = any(
        v == "unconfigured" for v in surface.values() if isinstance(v, str)
    )
    has_refused = any(v == "refused" for v in surface.values() if isinstance(v, str))
    if has_refused and has_unconfigured:
        return "partial"
    if has_refused:
        return "refused"
    return "not_implemented"


def _derive_meta_packet_status(op: dict[str, Any]) -> str:
    actions = op.get("next_recommended_action", [])
    if isinstance(actions, list) and "build_surface_audit" in actions:
        return "present"
    return "not_implemented"


def _derive_meta_surface_status(op: dict[str, Any]) -> str:
    surface = op.get("surface_summary")
    if not isinstance(surface, dict):
        return "missing"
    unconfigured = sum(
        1 for v in surface.values() if isinstance(v, str) and v == "unconfigured"
    )
    refused = sum(1 for v in surface.values() if isinstance(v, str) and v == "refused")
    if refused > 0 and unconfigured > 0:
        return "partial"
    if unconfigured > 0:
        return "not_implemented"
    return "missing"


def _derive_meta_next_action(op: dict[str, Any]) -> str:
    actions = op.get("next_recommended_action", [])
    if isinstance(actions, list) and actions:
        return actions[0]
    summary = op.get("summary")
    if isinstance(summary, dict):
        return summary.get("next_action", "no_action")
    return "no_action"


def _derive_risk_level(
    refused_count: int, public_release_ready: bool, auth_status: str
) -> str:
    if auth_status == "working" and not public_release_ready:
        return "medium"
    if auth_status == "configured":
        return "medium"
    if refused_count > _HIGH_RISK_REFUSAL_THRESHOLD:
        return "high"
    if refused_count > 0:
        return "medium"
    return "low"


_DERIVE_MAP: dict[str, tuple] = {
    "github": (
        _derive_github_auth_status,
        _derive_github_intake_status,
        _derive_github_packet_status,
        _derive_github_surface_status,
        _derive_github_next_action,
    ),
    "google_workspace": (
        _derive_google_auth_status,
        _derive_google_intake_status,
        _derive_google_packet_status,
        _derive_google_intake_status,
        _derive_google_next_action,
    ),
    "meta": (
        _derive_meta_auth_status,
        _derive_meta_intake_status,
        _derive_meta_packet_status,
        _derive_meta_surface_status,
        _derive_meta_next_action,
    ),
}


def _make_entry_base(
    provider_id: str,
    display_name: str,
    path: Path,
    op_hash: str | None,
    present: bool,
    remote_mutation: bool,
    public_release: bool,
    content_light: bool,
    auth: str,
    intake: str,
    packets: str,
    surface: str,
    action: str,
    risk: str,
    refused: int,
    ready_packets: int | None,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "display_name": display_name,
        "operating_picture_path": str(path),
        "operating_picture_hash": op_hash,
        "operating_picture_present": present,
        "auth_status": auth,
        "intake_status": intake,
        "packet_status": packets,
        "surface_status": surface,
        "remote_mutation": remote_mutation,
        "public_release_ready": public_release,
        "content_light": content_light,
        "next_recommended_action": action,
        "risk_level": risk,
        "refused_surfaces_count": refused,
        "ready_packet_count": ready_packets,
        "evidence_paths": evidence,
        "stale_inputs": [],
    }


def _count_refusals(op_picture: dict[str, Any]) -> int:
    permission = op_picture.get("permission_summary")
    if isinstance(permission, dict):
        refused = permission.get("refused_surfaces", [])
        if isinstance(refused, list):
            return len(refused)
    refusals = op_picture.get("refusals", [])
    if isinstance(refusals, list):
        return len(refusals)
    return 0


def _get_ready_packets(op_picture: dict[str, Any]) -> int | None:
    packet_summary = op_picture.get("packet_summary")
    if isinstance(packet_summary, dict):
        return packet_summary.get("packet_count")
    return None


def _get_evidence(op_picture: dict[str, Any]) -> list[str]:
    evidence = op_picture.get("evidence_paths")
    if isinstance(evidence, list):
        return evidence
    return []


def _build_provider_entry(
    provider_id: str, op_picture: dict[str, Any] | None, path: Path, op_hash: str | None
) -> dict[str, Any]:
    provider_def = _PROVIDER_DEFS[provider_id]
    display_name: str = provider_def["display_name"]

    if op_picture is None:
        return _make_entry_base(
            provider_id,
            display_name,
            path,
            op_hash,
            present=False,
            remote_mutation=False,
            public_release=False,
            content_light=True,
            auth="unknown",
            intake="missing",
            packets="missing",
            surface="missing",
            action="no_action",
            risk="restricted",
            refused=0,
            ready_packets=None,
            evidence=[],
        )

    derivations = _DERIVE_MAP.get(provider_id)
    if derivations is None:
        return _make_entry_base(
            provider_id,
            display_name,
            path,
            op_hash,
            present=True,
            remote_mutation=bool(op_picture.get("remote_mutation")),
            public_release=bool(op_picture.get("public_release_ready")),
            content_light=bool(op_picture.get("content_light", True)),
            auth="unknown",
            intake="not_implemented",
            packets="not_implemented",
            surface="not_implemented",
            action="no_action",
            risk="restricted",
            refused=0,
            ready_packets=None,
            evidence=[],
        )

    auth_fn, intake_fn, packet_fn, surface_fn, action_fn = derivations
    auth_status = auth_fn(op_picture)
    public_release = bool(op_picture.get("public_release_ready") or False)
    refused_count = _count_refusals(op_picture)

    return _make_entry_base(
        provider_id,
        display_name,
        path,
        op_hash,
        present=True,
        remote_mutation=bool(op_picture.get("remote_mutation")),
        public_release=public_release,
        content_light=bool(op_picture.get("content_light", True)),
        auth=auth_status,
        intake=intake_fn(op_picture),
        packets=packet_fn(op_picture),
        surface=surface_fn(op_picture),
        action=action_fn(op_picture),
        risk=_derive_risk_level(refused_count, public_release, auth_status),
        refused=refused_count,
        ready_packets=_get_ready_packets(op_picture),
        evidence=_get_evidence(op_picture),
    )

    derive_map = {
        "github": (
            _derive_github_auth_status,
            _derive_github_intake_status,
            _derive_github_packet_status,
            _derive_github_surface_status,
            _derive_github_next_action,
        ),
        "google_workspace": (
            _derive_google_auth_status,
            _derive_google_intake_status,
            _derive_google_packet_status,
            _derive_google_intake_status,
            _derive_google_next_action,
        ),
        "meta": (
            _derive_meta_auth_status,
            _derive_meta_intake_status,
            _derive_meta_packet_status,
            _derive_meta_surface_status,
            _derive_meta_next_action,
        ),
    }

    derivations = derive_map.get(provider_id)
    if derivations is None:
        return {
            "provider_id": provider_id,
            "display_name": provider_def["display_name"],
            "operating_picture_path": str(path),
            "operating_picture_hash": op_hash,
            "operating_picture_present": True,
            "auth_status": "unknown",
            "intake_status": "not_implemented",
            "packet_status": "not_implemented",
            "surface_status": "not_implemented",
            "remote_mutation": bool(op_picture.get("remote_mutation")),
            "public_release_ready": bool(op_picture.get("public_release_ready")),
            "content_light": bool(op_picture.get("content_light", True)),
            "next_recommended_action": "no_action",
            "risk_level": "restricted",
            "refused_surfaces_count": 0,
            "ready_packet_count": None,
            "evidence_paths": [],
            "stale_inputs": [],
        }

    auth_fn, intake_fn, packet_fn, surface_fn, action_fn = derivations

    auth_status = auth_fn(op_picture)
    intake_status = intake_fn(op_picture)
    packet_status = packet_fn(op_picture)
    surface_status = surface_fn(op_picture)
    next_action = action_fn(op_picture)
    public_release = bool(op_picture.get("public_release_ready") or False)

    refused_count = 0
    permission = op_picture.get("permission_summary")
    if isinstance(permission, dict):
        refused = permission.get("refused_surfaces", [])
        if isinstance(refused, list):
            refused_count = len(refused)
    else:
        refusals = op_picture.get("refusals", [])
        if isinstance(refusals, list):
            refused_count = len(refusals)

    ready_packet_count = None
    packet_summary = op_picture.get("packet_summary")
    if isinstance(packet_summary, dict):
        ready_packet_count = packet_summary.get("packet_count")

    evidence = op_picture.get("evidence_paths")
    if not isinstance(evidence, list):
        evidence = []

    return {
        "provider_id": provider_id,
        "display_name": provider_def["display_name"],
        "operating_picture_path": str(path),
        "operating_picture_hash": op_hash,
        "operating_picture_present": True,
        "auth_status": auth_status,
        "intake_status": intake_status,
        "packet_status": packet_status,
        "surface_status": surface_status,
        "remote_mutation": bool(op_picture.get("remote_mutation")),
        "public_release_ready": public_release,
        "content_light": bool(op_picture.get("content_light", True)),
        "next_recommended_action": next_action,
        "risk_level": _derive_risk_level(refused_count, public_release, auth_status),
        "refused_surfaces_count": refused_count,
        "ready_packet_count": ready_packet_count,
        "evidence_paths": evidence,
        "stale_inputs": [],
    }


def _build_aggregate_summary(
    providers: list[dict[str, Any]], op_pictures: dict[str, dict[str, Any] | None]
) -> dict[str, Any]:
    configured = sum(
        1 for p in providers if p["auth_status"] in {"working", "configured"}
    )
    readonly_ready = sum(
        1 for p in providers if p["intake_status"] in {"present", "partial"}
    )
    public_ready = sum(1 for p in providers if p["public_release_ready"])
    mutation = sum(1 for p in providers if p["remote_mutation"])
    refused = sum(p["refused_surfaces_count"] for p in providers)
    stale = sum(1 for p in providers if p["packet_status"] == "stale")

    next_action = "no_action"
    if configured == 0:
        next_action = "configure_provider_auth"
    elif readonly_ready == 0:
        next_action = "run_provider_intakes"
    elif public_ready == 0:
        next_action = "gate_check: public_release_not_ready"
    elif stale > 0:
        next_action = "regenerate_stale_providers"
    else:
        next_action = "provider_readiness_graduated"

    return {
        "providers_configured_count": configured,
        "providers_readonly_ready_count": readonly_ready,
        "providers_public_release_ready_count": public_ready,
        "remote_mutation_enabled_count": mutation,
        "refused_surface_count": refused,
        "stale_provider_count": stale,
        "next_global_action": next_action,
    }


def _build_readiness_matrix(providers: list[dict[str, Any]]) -> dict[str, Any]:
    matrix: dict[str, Any] = {}
    for p in providers:
        pid = p["provider_id"]
        matrix[pid] = {
            "auth": p["auth_status"],
            "intake": p["intake_status"],
            "packets": p["packet_status"],
            "surface": p["surface_status"],
            "public_release_ready": p["public_release_ready"],
        }
    for required in ("github", "google_workspace", "meta"):
        if required not in matrix:
            matrix[required] = {
                "auth": "unknown",
                "intake": "missing",
                "packets": "missing",
                "surface": "missing",
                "public_release_ready": False,
            }
    return matrix


def _build_release_gate(
    providers: list[dict[str, Any]], op_pictures: dict[str, dict[str, Any] | None]
) -> dict[str, Any]:
    all_public_ready = all(p["public_release_ready"] for p in providers)
    blocking: list[str] = []
    advisory: list[str] = []

    for p in providers:
        pid = p["provider_id"]
        seams: list[str] = []
        if pid in op_pictures and isinstance(op_pictures[pid], dict):
            seams = op_pictures[pid].get("remaining_seams", [])  # type: ignore[union-attr]
            if not isinstance(seams, list):
                seams = []
        if p["risk_level"] in {"high", "restricted"}:
            blocking.append(f"{pid}: risk_level={p['risk_level']}")
        elif p["risk_level"] == "medium":
            advisory.append(f"{pid}: risk_level={p['risk_level']}")
        if seams:
            for seam in seams[:3]:
                advisory.append(f"{pid}: {seam}")

    return {
        "public_release_ready": all_public_ready,
        "blocking_provider_seams": blocking,
        "advisory_provider_seams": advisory,
    }


def _assert_content_light(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_FIELDS:
                raise ValueError(
                    f"forbidden_key_detected: registry contains forbidden field '{key}'"
                )
            _assert_content_light(item)
    elif isinstance(value, list):
        for item in value:
            _assert_content_light(item)


def build_provider_operating_picture_registry(
    *,
    generated_at_utc: str | None = None,
    provider_op_pictures: dict[str, dict[str, Any] | None] | None = None,
    repo_root: Path = _REPO_ROOT,
    provider_filter: list[str] | None = None,
) -> dict[str, Any]:
    if provider_op_pictures is None:
        provider_op_pictures = {}

    branch, head = _load_git_metadata(repo_root)
    generated_at = generated_at_utc or _now_iso()

    providers: list[dict[str, Any]] = []
    for provider_id, provider_def in _PROVIDER_DEFS.items():
        if provider_filter and provider_id not in provider_filter:
            continue

        path = Path(provider_def["op_picture_path"])
        explicitly_provided = provider_id in provider_op_pictures
        op_picture = provider_op_pictures.get(provider_id)
        op_hash = None
        if explicitly_provided and op_picture is not None:
            op_hash = _sha256_file(path) if path.exists() else None
        elif explicitly_provided and op_picture is None:
            op_hash = None
        elif path.exists():
            op_picture = _load_op_picture(path)
            op_hash = _sha256_file(path)
        else:
            op_hash = None

        entry = _build_provider_entry(provider_id, op_picture, path, op_hash)
        providers.append(entry)

        if op_picture is not None:
            provider_op_pictures[provider_id] = op_picture

    aggregate = _build_aggregate_summary(providers, provider_op_pictures)
    matrix = _build_readiness_matrix(providers)
    release_gate = _build_release_gate(providers, provider_op_pictures)

    evidence_paths = []
    for p in providers:
        if p["operating_picture_present"] and p["operating_picture_path"]:
            evidence_paths.append(p["operating_picture_path"])

    report: dict[str, Any] = {
        "schema_version": "rig.provider.operating_picture_registry.v1",
        "generated_at": generated_at,
        "branch": branch,
        "head": head,
        "content_light": True,
        "remote_mutation": False,
        "provider_count": len(providers),
        "providers": providers,
        "aggregate_summary": aggregate,
        "provider_readiness_matrix": matrix,
        "release_gate_implications": release_gate,
        "redaction_status": {
            "content_light": True,
            "forbidden_strings_present": False,
            "redaction_rule_count": len(_FORBIDDEN_FIELDS),
            "checked_artifact_count": len(providers),
        },
        "remaining_seams": [
            "GitHub: dependabot intake refused, secret_scanning gated",
            "Google Workspace: restricted scopes refused, OAuth not configured",
            "Meta: publishing/messaging refused, app review required, business verification required",
        ],
    }

    _assert_content_light(report)
    return report


def build_provider_operating_picture_registry_from_paths(
    *,
    generated_at_utc: str | None = None,
    repo_root: Path = _REPO_ROOT,
    provider_filter: list[str] | None = None,
) -> dict[str, Any]:
    provider_op_pictures: dict[str, dict[str, Any] | None] = {}
    for provider_id, provider_def in _PROVIDER_DEFS.items():
        if provider_filter and provider_id not in provider_filter:
            continue
        path = Path(provider_def["op_picture_path"])
        if path.exists():
            provider_op_pictures[provider_id] = _load_op_picture(path)

    return build_provider_operating_picture_registry(
        generated_at_utc=generated_at_utc,
        provider_op_pictures=provider_op_pictures,
        repo_root=repo_root,
        provider_filter=provider_filter,
    )


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_provider_operating_picture_registry(
    path: Path = _DEFAULT_OUTPUT_JSON,
    *,
    generated_at_utc: str | None = None,
    repo_root: Path = _REPO_ROOT,
    provider_filter: list[str] | None = None,
) -> dict[str, Any]:
    report = build_provider_operating_picture_registry_from_paths(
        generated_at_utc=generated_at_utc,
        repo_root=repo_root,
        provider_filter=provider_filter,
    )
    _write_json(path, report)
    return report


__all__ = [
    "ProviderRegistryError",
    "build_provider_operating_picture_registry",
    "build_provider_operating_picture_registry_from_paths",
    "write_provider_operating_picture_registry",
]

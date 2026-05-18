from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

PROTOCOL = "rig.file_coordination.v1"
STALE_TTL = timedelta(hours=8)


@dataclass(frozen=True, slots=True)
class FileMarker:
    protocol: str
    state: str
    agent_id: str
    session_id: str
    claimed_at: str
    allowed_followup: str
    summary: str
    task_id: str | None = None
    mission_id: str | None = None
    released_at: str | None = None
    head_sha_at_claim: str | None = None
    file_sha256_at_claim: str | None = None
    file_sha256_at_release: str | None = None


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def detect_comment_style(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in {
        ".py",
        ".sh",
        ".bash",
        ".yaml",
        ".yml",
        ".toml",
        ".ts",
        ".js",
        ".css",
    }:
        return (
            "#"
            if suffix in {".py", ".sh", ".bash", ".yaml", ".yml", ".toml"}
            else "block"
        )
    if suffix in {".html", ".md"}:
        return "html"
    return None


def is_generated_or_unsafe_for_inline_marker(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() in {".json", ".svg", ".png", ".jpg", ".jpeg", ".gif"}:
        return True
    return any(
        token in name
        for token in {"render", "manifest", "index", "schema", ".generated."}
    )


def _marker_line(marker: FileMarker, path: Path) -> str:
    payload = json.dumps(asdict(marker), sort_keys=True, separators=(",", ":"))
    style = detect_comment_style(path)
    if style == "#":
        return f"# rig-file-coordination: {payload}\n"
    if style == "html":
        return f"<!-- rig-file-coordination: {payload} -->\n"
    if style == "block":
        return f"/* rig-file-coordination: {payload} */\n"
    raise ValueError("inline marker not supported")


def _parse_marker_line(line: str) -> dict[str, Any] | None:
    prefixes = (
        "# rig-file-coordination: ",
        "<!-- rig-file-coordination: ",
        "/* rig-file-coordination: ",
    )
    for prefix in prefixes:
        if line.startswith(prefix):
            payload = (
                line[len(prefix) :].strip().removesuffix(" -->").removesuffix(" */")
            )
            return json.loads(payload)
    return None


def read_inline_marker(path: Path) -> FileMarker | None:
    if is_generated_or_unsafe_for_inline_marker(path):
        return None
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
    except Exception:
        return None
    payload = _parse_marker_line(first)
    return FileMarker(**payload) if payload else None


def validate_marker(marker: dict[str, Any]) -> None:
    required = {
        "protocol",
        "state",
        "agent_id",
        "session_id",
        "claimed_at",
        "allowed_followup",
        "summary",
    }
    missing = sorted(required - marker.keys())
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")
    if marker["protocol"] != PROTOCOL:
        raise ValueError("unsupported protocol")
    if marker["state"] not in {"active", "released_modified", "released_readonly"}:
        raise ValueError("invalid state")


def write_sidecar_event(event: dict[str, Any]) -> None:
    path = Path.cwd() / ".rig" / "file-coordination" / "claims.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_marker(
    *,
    state: str,
    path: Path,
    agent_id: str,
    session_id: str,
    task_id: str | None,
    summary: str,
    allowed_followup: str,
    head_sha_at_claim: str | None = None,
    file_sha256_at_claim: str | None = None,
    file_sha256_at_release: str | None = None,
    released_at: str | None = None,
    mission_id: str | None = None,
) -> FileMarker:
    return FileMarker(
        protocol=PROTOCOL,
        state=state,
        agent_id=agent_id,
        session_id=session_id,
        task_id=task_id,
        mission_id=mission_id,
        claimed_at=_now(),
        released_at=released_at,
        head_sha_at_claim=head_sha_at_claim,
        file_sha256_at_claim=file_sha256_at_claim,
        file_sha256_at_release=file_sha256_at_release,
        allowed_followup=allowed_followup,
        summary=summary,
    )


def claim_file(
    path: Path,
    agent_id: str,
    session_id: str,
    task_id: str | None,
    allowed_followup: str = "additive_only",
    *,
    override_stale: bool = False,
    summary: str = "claim",
) -> FileMarker:
    current = read_inline_marker(path)
    if current and current.state == "active" and current.session_id != session_id:
        claimed = datetime.fromisoformat(current.claimed_at)
        if datetime.now(tz=UTC) - claimed <= STALE_TTL or not override_stale:
            raise RuntimeError(
                f"stale_active_claim=false active claim owned by {current.session_id} at {current.claimed_at}"
            )
    head_sha = _load_head_sha()
    content_sha = file_sha256(path) if path.exists() else None
    marker = _build_marker(
        state="active",
        path=path,
        agent_id=agent_id,
        session_id=session_id,
        task_id=task_id,
        summary=summary,
        allowed_followup=allowed_followup,
        head_sha_at_claim=head_sha,
        file_sha256_at_claim=content_sha,
    )
    if not is_generated_or_unsafe_for_inline_marker(path):
        text = _load_text(path)
        lines = text.splitlines(True)
        if lines and _parse_marker_line(lines[0]):
            lines[0] = _marker_line(marker, path)
        else:
            lines.insert(0, _marker_line(marker, path))
        _write_text(path, "".join(lines))
    write_sidecar_event({"event": "claim", **asdict(marker), "path": str(path)})
    return marker


def _load_head_sha() -> str | None:
    return None


def release_file(
    path: Path,
    agent_id: str,
    session_id: str,
    state: str,
    summary: str,
    allowed_followup: str = "additive_only",
) -> FileMarker:
    current = read_inline_marker(path)
    released_at = _now()
    marker = _build_marker(
        state=state,
        path=path,
        agent_id=agent_id,
        session_id=session_id,
        task_id=current.task_id if current else None,
        summary=summary,
        allowed_followup=allowed_followup,
        head_sha_at_claim=current.head_sha_at_claim if current else None,
        file_sha256_at_claim=current.file_sha256_at_claim if current else None,
        file_sha256_at_release=file_sha256(path) if path.exists() else None,
        released_at=released_at,
        mission_id=current.mission_id if current else None,
    )
    if not is_generated_or_unsafe_for_inline_marker(path):
        text = _load_text(path)
        lines = text.splitlines(True)
        if lines and _parse_marker_line(lines[0]):
            lines[0] = _marker_line(marker, path)
        else:
            lines.insert(0, _marker_line(marker, path))
        _write_text(path, "".join(lines))
    write_sidecar_event({"event": "release", **asdict(marker), "path": str(path)})
    return marker


def scan_file_claims(paths: list[Path]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in sorted(paths):
        marker = read_inline_marker(path)
        if marker:
            results.append({"path": str(path), "marker": asdict(marker)})
    return results


def scan_session_owned_markers(
    paths: list[Path], session_id: str
) -> list[dict[str, Any]]:
    return [
        item
        for item in scan_file_claims(paths)
        if item["marker"].get("session_id") == session_id
        and item["marker"].get("state") == "active"
    ]

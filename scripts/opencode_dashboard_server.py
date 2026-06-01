from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / ".opencode" / "ops-dashboard"
DRAFT_STATE_PATH = BUILD_ROOT / "draft-state.json"
QUESTION_ARCHIVE_PATH = BUILD_ROOT / "question-archive.jsonl"
ROADMAP_PUBLISHED_ROOT = ROOT / "docs" / "json" / "opencode" / "ops-dashboard" / "published"
ROADMAP_DELTA_ROOT = ROOT / "docs" / "json" / "opencode" / "ops-dashboard" / "deltas"
QUESTION_REPORT_ROOT = ROOT / "docs" / "json" / "opencode" / "ops-dashboard" / "questions"

STATE_LOCK = threading.Lock()
DRAFT_SCHEMA = "opencode.dashboard.draft_state.v1"
ROADMAP_SCHEMA = "opencode.dashboard.roadmap.v1"
DELTA_SCHEMA = "opencode.dashboard.roadmap_delta.v1"
QUESTION_SCHEMA = "opencode.dashboard.question_report.v1"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_dump(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dump(data), encoding="utf-8")


def write_jsonl(path: Path, record: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=False))
        handle.write("\n")


def parse_version(path: Path) -> int:
    match = re.search(r"\.v(\d+)\.json$", path.name)
    return int(match.group(1)) if match else 0


def list_versioned_json(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        (path for path in root.glob("*.json") if path.is_file()),
        key=parse_version,
    )


def default_state() -> dict[str, Any]:
    return {
        "schema_version": DRAFT_SCHEMA,
        "draft_id": "ops-dashboard",
        "draft_source": "local",
        "draft_notes": "",
        "updated_at": now_iso(),
        "roadmap": {
            "title": "Operations Dashboard Roadmap",
            "summary": "Draft roadmap and timeline for the local dashboard. Publish creates a versioned artifact and transition delta.",
            "status": "draft",
            "owner": "ops-dashboard",
            "version_hint": 1,
            "timeline": [
                {
                    "item_id": "roadmap-foundation",
                    "title": "Foundation",
                    "status": "active",
                    "due": "",
                    "owner": "ops-dashboard",
                    "details": "Establish the published roadmap, draft editor, question inbox, and delta artifacts.",
                    "impacted_contexts": [
                        "docs/json/opencode/ops-dashboard/published/",
                        "docs/json/opencode/ops-dashboard/deltas/",
                    ],
                    "notes": "Start from the current published state and keep the draft hidden until publish.",
                },
                {
                    "item_id": "context-delta",
                    "title": "Context delta loop",
                    "status": "planned",
                    "due": "",
                    "owner": "ops-dashboard",
                    "details": "Publish versioned roadmap changes with explicit downstream context files so sessions can adopt the new version without losing the old one.",
                    "impacted_contexts": [
                        "docs/json/opencode/ops-dashboard/published/",
                        "docs/json/opencode/ops-dashboard/deltas/",
                    ],
                    "notes": "Agents should see the superseded version and the transition delta together.",
                },
            ],
        },
        "questions": {
            "pending": [],
            "archived": [],
        },
    }


def normalize_timeline_item(raw: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "item_id": str(raw.get("item_id") or raw.get("id") or f"item-{index + 1}"),
        "title": str(raw.get("title") or ""),
        "status": str(raw.get("status") or "planned"),
        "due": str(raw.get("due") or ""),
        "owner": str(raw.get("owner") or ""),
        "details": str(raw.get("details") or raw.get("description") or ""),
        "impacted_contexts": [
            str(value).strip()
            for value in raw.get("impacted_contexts", [])
            if str(value).strip()
        ],
        "notes": str(raw.get("notes") or ""),
    }


def normalize_question(raw: dict[str, Any], index: int, archived: bool = False) -> dict[str, Any]:
    timestamp = str(raw.get("created_at") or now_iso())
    item = {
        "question_id": str(raw.get("question_id") or raw.get("id") or f"question-{index + 1}"),
        "category": str(raw.get("category") or "general"),
        "question": str(raw.get("question") or ""),
        "linked_contexts": [
            str(value).strip()
            for value in raw.get("linked_contexts", [])
            if str(value).strip()
        ],
        "status": "archived" if archived else str(raw.get("status") or "pending"),
        "created_at": timestamp,
    }
    if archived:
        item["answer"] = str(raw.get("answer") or "")
        item["answered_at"] = str(raw.get("answered_at") or timestamp)
        item["archived_at"] = str(raw.get("archived_at") or timestamp)
    return item


def normalize_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return default_state()
    roadmap = raw.get("roadmap")
    if not isinstance(roadmap, dict):
        roadmap = {}
    questions = raw.get("questions")
    if not isinstance(questions, dict):
        questions = {}
    return {
        "schema_version": DRAFT_SCHEMA,
        "draft_id": str(raw.get("draft_id") or "ops-dashboard"),
        "draft_source": "local",
        "draft_notes": str(raw.get("draft_notes") or ""),
        "updated_at": str(raw.get("updated_at") or now_iso()),
        "roadmap": {
            "title": str(roadmap.get("title") or "Operations Dashboard Roadmap"),
            "summary": str(
                roadmap.get("summary")
                or "Draft roadmap and timeline for the local dashboard."
            ),
            "status": str(roadmap.get("status") or "draft"),
            "owner": str(roadmap.get("owner") or "ops-dashboard"),
            "version_hint": int(roadmap.get("version_hint") or 1),
            "timeline": [
                normalize_timeline_item(item, index)
                for index, item in enumerate(roadmap.get("timeline", []))
                if isinstance(item, dict)
            ],
        },
        "questions": {
            "pending": [
                normalize_question(item, index)
                for index, item in enumerate(questions.get("pending", []))
                if isinstance(item, dict)
            ],
            "archived": [
                normalize_question(item, index, archived=True)
                for index, item in enumerate(questions.get("archived", []))
                if isinstance(item, dict)
            ],
        },
    }


def load_state() -> dict[str, Any]:
    return normalize_state(read_json(DRAFT_STATE_PATH, default_state()))


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_state(state)
    normalized["updated_at"] = now_iso()
    write_json(DRAFT_STATE_PATH, normalized)
    return normalized


def aggregate_contexts(timeline: list[dict[str, Any]]) -> list[str]:
    contexts: list[str] = []
    seen: set[str] = set()
    for item in timeline:
        for context in item.get("impacted_contexts", []):
            if context and context not in seen:
                seen.add(context)
                contexts.append(context)
    return contexts


def latest_published_path() -> Path | None:
    versions = list_versioned_json(ROADMAP_PUBLISHED_ROOT)
    return versions[-1] if versions else None


def build_roadmap(state: dict[str, Any], version: int, previous_version: int | None) -> dict[str, Any]:
    roadmap = state["roadmap"]
    timeline = [normalize_timeline_item(item, index) for index, item in enumerate(roadmap["timeline"])]
    return {
        "schema_version": ROADMAP_SCHEMA,
        "roadmap_id": "ops-dashboard",
        "version": version,
        "publication_state": "published",
        "title": roadmap["title"],
        "summary": roadmap["summary"],
        "status": roadmap["status"],
        "owner": roadmap["owner"],
        "updated_at": state["updated_at"],
        "published_at": now_iso(),
        "supersedes_version": previous_version,
        "source_draft_id": state["draft_id"],
        "transition_delta_path": f"docs/json/opencode/ops-dashboard/deltas/roadmap-delta.v{version:03d}.json",
        "downstream_contexts": aggregate_contexts(timeline),
        "timeline": timeline,
    }


def build_diffs(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    for key in ("title", "summary", "status", "owner"):
        if before.get(key) != after.get(key):
            diffs.append(
                {
                    "path": key,
                    "before": before.get(key, ""),
                    "after": after.get(key, ""),
                    "change_kind": "updated",
                },
            )
    before_timeline = {item.get("item_id"): item for item in before.get("timeline", [])}
    after_timeline = {item.get("item_id"): item for item in after.get("timeline", [])}
    for item_id, item in after_timeline.items():
        previous = before_timeline.get(item_id)
        if previous is None:
            diffs.append(
                {
                    "path": f"timeline.{item_id}",
                    "before": None,
                    "after": item,
                    "change_kind": "added",
                },
            )
        elif previous != item:
            diffs.append(
                {
                    "path": f"timeline.{item_id}",
                    "before": previous,
                    "after": item,
                    "change_kind": "updated",
                },
            )
    for item_id, item in before_timeline.items():
        if item_id not in after_timeline:
            diffs.append(
                {
                    "path": f"timeline.{item_id}",
                    "before": item,
                    "after": None,
                    "change_kind": "removed",
                },
            )
    return diffs


def build_delta(before: dict[str, Any], after: dict[str, Any], version: int) -> dict[str, Any]:
    changed_fields = build_diffs(before, after)
    downstream = [
        {
            "path": path,
            "reason": "Linked from published roadmap timeline",
            "impact": "refresh",
        }
        for path in after.get("downstream_contexts", [])
    ]
    return {
        "schema_version": DELTA_SCHEMA,
        "roadmap_id": "ops-dashboard",
        "from_version": before.get("version", 0),
        "to_version": after["version"],
        "generated_at": now_iso(),
        "before_artifact_path": f"docs/json/opencode/ops-dashboard/published/roadmap.v{before['version']:03d}.json",
        "after_artifact_path": f"docs/json/opencode/ops-dashboard/published/roadmap.v{after['version']:03d}.json",
        "changed_fields": changed_fields,
        "downstream_contexts": downstream,
        "human_summary": f"Roadmap version {version} published with {len(changed_fields)} field change{'s' if len(changed_fields) != 1 else ''} and {len(downstream)} downstream context reference{'s' if len(downstream) != 1 else ''}.",
        "content_light": True,
    }


def build_question_report(
    state: dict[str, Any],
    selected_questions: list[dict[str, Any]],
    answer: str,
    version: int,
) -> dict[str, Any]:
    contexts: list[str] = []
    seen: set[str] = set()
    for question in selected_questions:
        for context in question.get("linked_contexts", []):
            if context and context not in seen:
                seen.add(context)
                contexts.append(context)
    return {
        "schema_version": QUESTION_SCHEMA,
        "report_id": f"question-report-v{version:03d}",
        "generated_at": now_iso(),
        "roadmap_version": version,
        "selected_questions": [
            {
                "question_id": question["question_id"],
                "category": question["category"],
                "question": question["question"],
                "linked_contexts": question["linked_contexts"],
                "answer": answer,
            }
            for question in selected_questions
        ],
        "answer": answer,
        "selection_count": len(selected_questions),
        "summary": f"Answered {len(selected_questions)} question{'s' if len(selected_questions) != 1 else ''}.",
        "archived_question_ids": [question["question_id"] for question in selected_questions],
        "downstream_contexts": contexts,
        "content_light": True,
    }


def emit_json(handler: SimpleHTTPRequestHandler, status: HTTPStatus, payload: Any) -> None:
    encoded = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(encoded)


def read_request_json(handler: SimpleHTTPRequestHandler) -> Any:
    length = int(handler.headers.get("Content-Length", "0"))
    if not length:
        return {}
    payload = handler.rfile.read(length)
    if not payload:
        return {}
    return json.loads(payload.decode("utf-8"))


class OpsDashboardHandler(SimpleHTTPRequestHandler):
    server_version = "OpencodeDashboardServer/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/_ops-dashboard/state":
            draft_state = load_state()
            published_versions = list_versioned_json(ROADMAP_PUBLISHED_ROOT)
            published = read_json(published_versions[-1], None) if published_versions else None
            latest_delta = list_versioned_json(ROADMAP_DELTA_ROOT)
            latest_question = list_versioned_json(QUESTION_REPORT_ROOT)
            emit_json(
                self,
                HTTPStatus.OK,
                {
                    "draft_state": draft_state,
                    "published": published,
                    "published_history": [
                        {
                            "version": parse_version(path),
                            "path": str(path.relative_to(ROOT)),
                        }
                        for path in published_versions
                    ],
                    "latest_delta": read_json(latest_delta[-1], None) if latest_delta else None,
                    "latest_question_report": read_json(latest_question[-1], None) if latest_question else None,
                },
            )
            return
        if parsed.path == "/_ops-dashboard/draft-state":
            emit_json(self, HTTPStatus.OK, load_state())
            return
        super().do_GET()

    def do_PUT(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/_ops-dashboard/draft-state":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return
        state = save_state(read_request_json(self))
        emit_json(self, HTTPStatus.OK, {"status": "saved", "draft_state": state})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/_ops-dashboard/publish-roadmap":
            with STATE_LOCK:
                state = load_state()
                previous_path = latest_published_path()
                previous_version = parse_version(previous_path) if previous_path else None
                version = (previous_version or 0) + 1
                roadmap = build_roadmap(state, version, previous_version)
                published_path = ROADMAP_PUBLISHED_ROOT / f"roadmap.v{version:03d}.json"
                write_json(published_path, roadmap)
                previous = (
                    read_json(previous_path, None)
                    if previous_path is not None
                    else {
                        "version": 0,
                        "title": "",
                        "summary": "",
                        "status": "",
                        "owner": "",
                        "timeline": [],
                    }
                )
                delta = build_delta(previous, roadmap, version)
                delta_path = ROADMAP_DELTA_ROOT / f"roadmap-delta.v{version:03d}.json"
                write_json(delta_path, delta)
                roadmap["transition_delta_path"] = str(delta_path.relative_to(ROOT))
                write_json(published_path, roadmap)
            emit_json(
                self,
                HTTPStatus.OK,
                {
                    "status": "published",
                    "published": roadmap,
                    "published_path": str(published_path.relative_to(ROOT)),
                    "delta": delta,
                    "delta_path": str(delta_path.relative_to(ROOT)),
                },
            )
            return
        if parsed.path == "/_ops-dashboard/submit-answer":
            with STATE_LOCK:
                payload = read_request_json(self)
                selected_ids = [str(value) for value in payload.get("question_ids", []) if str(value)]
                answer = str(payload.get("answer") or "").strip()
                if not selected_ids:
                    self.send_error(HTTPStatus.BAD_REQUEST, "No question_ids selected")
                    return
                if not answer:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Answer cannot be empty")
                    return
                state = load_state()
                pending = state["questions"]["pending"]
                selected = [item for item in pending if item["question_id"] in selected_ids]
                if not selected:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Selected questions not found")
                    return
                timestamp = now_iso()
                state["questions"]["pending"] = [
                    item for item in pending if item["question_id"] not in selected_ids
                ]
                for item in selected:
                    archived = {
                        **item,
                        "status": "archived",
                        "answer": answer,
                        "answered_at": timestamp,
                        "archived_at": timestamp,
                    }
                    state["questions"]["archived"].append(archived)
                    write_jsonl(
                        QUESTION_ARCHIVE_PATH,
                        {
                            "schema_version": QUESTION_SCHEMA,
                            "event": "archived",
                            "question_id": item["question_id"],
                            "category": item["category"],
                            "question": item["question"],
                            "answer": answer,
                            "linked_contexts": item["linked_contexts"],
                            "archived_at": timestamp,
                        },
                    )
                save_state(state)
                published_path = latest_published_path()
                current_version = parse_version(published_path) if published_path else 1
                report_version = current_version + 1
                report = build_question_report(state, selected, answer, report_version)
                report_path = QUESTION_REPORT_ROOT / f"question-report.v{report_version:03d}.json"
                write_json(report_path, report)
            emit_json(
                self,
                HTTPStatus.OK,
                {
                    "status": "submitted",
                    "report": report,
                    "report_path": str(report_path.relative_to(ROOT)),
                    "draft_state": state,
                },
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")


def main() -> None:
    handler = partial(OpsDashboardHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("0.0.0.0", 8000), handler)
    print("Opencode dashboard server listening on http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

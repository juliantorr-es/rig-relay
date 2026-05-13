from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from jsonschema import validate
import pytest

from tests.mock.utils import collect_result
from vibe.core.paths._vibe_home import SESSIONS_ROOT
from vibe.core.tools.base import BaseToolState, InvokeContext
from vibe.core.tools.builtins.grep import Grep, GrepArgs, GrepToolConfig


def _search_results_schema() -> dict:
    schema_path = (
        Path(__file__).parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.artifact.search_results.v1.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _artifact_payload(session_id: str) -> dict:
    artifact_dir = SESSIONS_ROOT.path / session_id / "artifacts" / "tool-results"
    artifacts = sorted(artifact_dir.glob("*search_result*.json"))
    assert artifacts, f"no search_result artifact found in {artifact_dir}"
    return json.loads(artifacts[-1].read_text(encoding="utf-8"))["payload"]


@pytest.fixture
def grep(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = GrepToolConfig()
    return Grep(config_getter=lambda: config, state=BaseToolState())


@pytest.mark.asyncio
async def test_search_artifact_is_deterministically_ordered(grep, tmp_path):
    session_id = f"session-{uuid4().hex}"
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    (tmp_path / "b.py").write_text("match\nmatch\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("match\n", encoding="utf-8")

    ctx = InvokeContext(tool_call_id="call-1", session_dir=session_dir)
    result = await collect_result(grep.run(GrepArgs(pattern="match"), ctx=ctx))

    assert result.match_count == 3
    payload = _artifact_payload(session_id)
    validate(instance=payload, schema=_search_results_schema())
    assert payload["backend"] in {"ripgrep", "gnu_grep"}
    assert payload["ordering_policy"] == "rig_normalized_path_line_offset"
    assert payload["total_match_count"] == 3
    assert payload["returned_match_count"] == 3
    assert payload["matched_file_count"] == 2
    assert payload["returned_file_count"] == 2
    assert payload["truncated"] is False
    assert payload["truncation_reason"] is None
    assert payload["root"] == "."
    assert [item["relative_path"] for item in payload["results"]] == [
        "a.py",
        "b.py",
        "b.py",
    ]
    assert all(item["line_number"] is not None for item in payload["results"])


@pytest.mark.asyncio
async def test_search_artifact_reports_no_match_explicitly(grep, tmp_path):
    session_id = f"session-{uuid4().hex}"
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    (tmp_path / "a.py").write_text("match\n", encoding="utf-8")

    ctx = InvokeContext(tool_call_id="call-2", session_dir=session_dir)
    result = await collect_result(grep.run(GrepArgs(pattern="missing"), ctx=ctx))

    assert result.match_count == 0
    payload = _artifact_payload(session_id)
    assert payload["total_match_count"] == 0
    assert payload["returned_match_count"] == 0
    assert payload["matched_file_count"] == 0
    assert payload["returned_file_count"] == 0
    assert payload["results"] == []
    assert payload["truncated"] is False


@pytest.mark.asyncio
async def test_search_artifact_truncation_preserves_counts(grep, tmp_path):
    session_id = f"session-{uuid4().hex}"
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    (tmp_path / "a.py").write_text(
        "\n".join("match" for _ in range(5)), encoding="utf-8"
    )

    ctx = InvokeContext(tool_call_id="call-3", session_dir=session_dir)
    result = await collect_result(
        grep.run(GrepArgs(pattern="match", max_matches=2), ctx=ctx)
    )

    assert result.match_count == 2
    assert result.was_truncated is True
    payload = _artifact_payload(session_id)
    assert payload["total_match_count"] >= payload["returned_match_count"]
    assert payload["returned_match_count"] == 2
    assert payload["truncated"] is True
    assert payload["truncation_reason"] == "match_or_byte_cap"


@pytest.mark.asyncio
async def test_search_artifact_result_hash_changes_with_content(grep, tmp_path):
    session_one = f"session-{uuid4().hex}"
    session_two = f"session-{uuid4().hex}"
    session_dir_one = tmp_path / session_one
    session_dir_two = tmp_path / session_two
    session_dir_one.mkdir()
    session_dir_two.mkdir()

    (tmp_path / "a.py").write_text("match\n", encoding="utf-8")
    ctx_one = InvokeContext(tool_call_id="call-4", session_dir=session_dir_one)
    await collect_result(grep.run(GrepArgs(pattern="match"), ctx=ctx_one))
    payload_one = _artifact_payload(session_one)

    (tmp_path / "a.py").write_text("match\nmatch\n", encoding="utf-8")
    ctx_two = InvokeContext(tool_call_id="call-5", session_dir=session_dir_two)
    await collect_result(grep.run(GrepArgs(pattern="match"), ctx=ctx_two))
    payload_two = _artifact_payload(session_two)

    assert payload_one["result_set_sha256"] != payload_two["result_set_sha256"]


@pytest.mark.asyncio
async def test_search_artifact_normalizes_repo_relative_paths(grep, tmp_path):
    session_id = f"session-{uuid4().hex}"
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "a.py").write_text("match\n", encoding="utf-8")

    ctx = InvokeContext(tool_call_id="call-6", session_dir=session_dir)
    await collect_result(grep.run(GrepArgs(pattern="match", path="nested"), ctx=ctx))

    payload = _artifact_payload(session_id)
    assert all(
        item["relative_path"].startswith("nested/") for item in payload["results"]
    )

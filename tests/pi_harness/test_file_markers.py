from __future__ import annotations

from pathlib import Path

from rig_relay.coordination.file_markers import (
    claim_file,
    detect_comment_style,
    file_sha256,
    is_generated_or_unsafe_for_inline_marker,
    read_inline_marker,
    release_file,
    scan_file_claims,
    validate_marker,
)


def test_comment_styles(tmp_path: Path) -> None:
    assert detect_comment_style(tmp_path / "a.py") == "#"
    assert detect_comment_style(tmp_path / "a.js") == "block"
    assert detect_comment_style(tmp_path / "a.html") == "html"


def test_json_is_sidecar_only(tmp_path: Path) -> None:
    assert is_generated_or_unsafe_for_inline_marker(tmp_path / "a.json") is True


def test_claim_and_release_inline_marker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "a.py"
    path.write_text("print('x')\n", encoding="utf-8")
    before = file_sha256(path)
    claim_file(path, "agent", "session", "task")
    assert read_inline_marker(path) is not None
    release_file(path, "agent", "session", "released_modified", "done")
    after = file_sha256(path)
    assert before != after


def test_claim_refuses_active_other_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "b.py"
    path.write_text("print('x')\n", encoding="utf-8")
    claim_file(path, "agent1", "session1", "task")
    try:
        claim_file(path, "agent2", "session2", "task")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected refusal")


def test_validate_marker() -> None:
    validate_marker({
        "protocol": "rig.file_coordination.v1",
        "state": "active",
        "agent_id": "a",
        "session_id": "s",
        "claimed_at": "2026-05-17T00:00:00+00:00",
        "allowed_followup": "additive_only",
        "summary": "x",
    })


def test_scan_deterministic(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ["b.py", "a.py"]:
        (tmp_path / name).write_text("print('x')\n", encoding="utf-8")
        claim_file(tmp_path / name, "agent", "session", "task")
        release_file(tmp_path / name, "agent", "session", "released_modified", "done")
    result = scan_file_claims([tmp_path / "b.py", tmp_path / "a.py"])
    assert [item["path"] for item in result] == [str(tmp_path / "a.py"), str(tmp_path / "b.py")]


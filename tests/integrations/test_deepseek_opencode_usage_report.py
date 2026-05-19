from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import jsonschema
import pytest

from scripts.rig_deepseek_opencode_usage_report import (
    _cache_write_visibility,
    build_deepseek_opencode_usage_report,
    build_deepseek_opencode_usage_summary,
    main as report_main,
    validate_deepseek_opencode_usage_report,
    validate_deepseek_opencode_usage_summary,
    write_deepseek_opencode_usage_report,
    write_deepseek_opencode_usage_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"


def _schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMAS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _make_db(path: Path) -> None:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE session (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                parent_id TEXT,
                slug TEXT NOT NULL,
                directory TEXT NOT NULL,
                title TEXT NOT NULL,
                version TEXT NOT NULL,
                share_url TEXT,
                summary_additions INTEGER,
                summary_deletions INTEGER,
                summary_files INTEGER,
                summary_diffs TEXT,
                revert TEXT,
                permission TEXT,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL,
                time_compacting INTEGER,
                time_archived INTEGER,
                workspace_id TEXT,
                path TEXT,
                agent TEXT,
                model TEXT,
                cost REAL NOT NULL DEFAULT 0,
                tokens_input INTEGER NOT NULL DEFAULT 0,
                tokens_output INTEGER NOT NULL DEFAULT 0,
                tokens_reasoning INTEGER NOT NULL DEFAULT 0,
                tokens_cache_read INTEGER NOT NULL DEFAULT 0,
                tokens_cache_write INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            """
        )
        sessions = [
            (
                "session-pro-default",
                "project-1",
                None,
                "pro-default",
                "/Users/user/Developer/GitHub/rig-relay",
                "Pro default",
                "1.14.50",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                1,
                2,
                None,
                None,
                None,
                "/Users/user/Developer/GitHub/rig-relay",
                None,
                json.dumps({
                    "id": "deepseek-v4-pro",
                    "providerID": "deepseek",
                    "variant": "default",
                }),
                0.0,
                1_000,
                200,
                50,
                9_000,
                0,
            ),
            (
                "session-pro-max",
                "project-1",
                None,
                "pro-max",
                "/Users/user/Developer/GitHub/rig-relay",
                "Pro max",
                "1.14.50",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                3,
                4,
                None,
                None,
                None,
                "/Users/user/Developer/GitHub/rig-relay",
                None,
                json.dumps({
                    "id": "deepseek-v4-pro",
                    "providerID": "deepseek",
                    "variant": "max",
                }),
                0.0,
                2_000,
                300,
                100,
                18_000,
                0,
            ),
            (
                "session-flash-default",
                "project-1",
                None,
                "flash-default",
                "/Users/user/Developer/GitHub/rig-relay",
                "Flash default",
                "1.14.50",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                5,
                6,
                None,
                None,
                None,
                "/Users/user/Developer/GitHub/rig-relay",
                None,
                json.dumps({"id": "deepseek-v4-flash", "providerID": "deepseek"}),
                0.0,
                500,
                80,
                20,
                5_000,
                0,
            ),
            (
                "session-non-deepseek",
                "project-1",
                None,
                "other",
                "/Users/user/Developer/GitHub/rig-relay",
                "Other",
                "1.14.50",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                7,
                8,
                None,
                None,
                None,
                "/Users/user/Developer/GitHub/rig-relay",
                None,
                None,
                0.0,
                800,
                120,
                10,
                500,
                0,
            ),
        ]
        conn.executemany(
            """
            INSERT INTO session (
                id, project_id, parent_id, slug, directory, title, version,
                share_url, summary_additions, summary_deletions, summary_files,
                summary_diffs, revert, permission, time_created, time_updated,
                time_compacting, time_archived, workspace_id, path, agent, model,
                cost, tokens_input, tokens_output, tokens_reasoning,
                tokens_cache_read, tokens_cache_write
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sessions,
        )
        messages = [
            (
                "message-pro-default-1",
                "session-pro-default",
                1,
                2,
                json.dumps({
                    "role": "assistant",
                    "providerID": "deepseek",
                    "modelID": "deepseek-v4-pro",
                    "mode": "general",
                    "tokens": {
                        "input": 1_000,
                        "output": 200,
                        "reasoning": 50,
                        "cache": {"read": 9_000, "write": 0},
                    },
                }),
            ),
            (
                "message-pro-default-2",
                "session-pro-default",
                3,
                4,
                json.dumps({
                    "role": "assistant",
                    "providerID": "deepseek",
                    "modelID": "deepseek-v4-pro",
                    "mode": "build",
                    "tokens": {
                        "input": 1_500,
                        "output": 300,
                        "reasoning": 75,
                        "cache": {"read": 12_000, "write": 0},
                    },
                }),
            ),
            (
                "message-pro-max-1",
                "session-pro-max",
                5,
                6,
                json.dumps({
                    "role": "assistant",
                    "providerID": "deepseek",
                    "modelID": "deepseek-v4-pro",
                    "mode": "build",
                    "tokens": {
                        "input": 2_000,
                        "output": 400,
                        "reasoning": 100,
                        "cache": {"read": 18_000, "write": 0},
                    },
                }),
            ),
            (
                "message-flash-1",
                "session-flash-default",
                7,
                8,
                json.dumps({
                    "role": "assistant",
                    "providerID": "deepseek",
                    "modelID": "deepseek-v4-flash",
                    "mode": "explore",
                    "tokens": {
                        "input": 500,
                        "output": 80,
                        "reasoning": 20,
                        "cache": {"read": 5_000, "write": 0},
                    },
                }),
            ),
            (
                "message-other-1",
                "session-non-deepseek",
                9,
                10,
                json.dumps({
                    "role": "assistant",
                    "providerID": "anthropic",
                    "modelID": "claude-3.7",
                    "mode": "general",
                    "tokens": {
                        "input": 900,
                        "output": 120,
                        "reasoning": 0,
                        "cache": {"read": 1_000, "write": 0},
                    },
                }),
            ),
        ]
        conn.executemany(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
            messages,
        )
        parts = [
            (
                "part-1",
                "message-pro-default-1",
                "session-pro-default",
                1,
                2,
                json.dumps({"type": "reasoning", "text": "chain of thought"}),
            ),
            (
                "part-2",
                "message-pro-default-1",
                "session-pro-default",
                1,
                2,
                json.dumps({"type": "tool", "callID": "call-1", "tool": "bash"}),
            ),
            (
                "part-3",
                "message-pro-max-1",
                "session-pro-max",
                5,
                6,
                json.dumps({"type": "reasoning", "text": "chain of thought"}),
            ),
            (
                "part-4",
                "message-pro-max-1",
                "session-pro-max",
                5,
                6,
                json.dumps({"type": "tool", "callID": "call-2", "tool": "read_file"}),
            ),
        ]
        conn.executemany(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            parts,
        )
        conn.commit()
    finally:
        conn.close()


def _make_logs(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "2026-05-19T191120.log").write_text(
        "\n".join([
            "service=llm providerID=deepseek modelID=deepseek-v4-pro",
            "request base_url=https://api.deepseek.com",
            "cache_read_tokens=9000",
            "display_thinking=true reasoning_effort=max",
        ]),
        encoding="utf-8",
    )


def _build_report(
    tmp_path: Path, *, generated_at: str = "2026-05-19T12:00:00Z"
) -> dict[str, object]:
    db_path = tmp_path / "opencode.db"
    logs_dir = tmp_path / "log"
    _make_db(db_path)
    _make_logs(logs_dir)
    return build_deepseek_opencode_usage_report(
        db_path=db_path,
        log_dir=logs_dir,
        opencode_version="1.14.50",
        generated_at=generated_at,
    )


def _build_summary(
    tmp_path: Path, *, generated_at: str = "2026-05-19T12:00:00Z"
) -> dict[str, object]:
    report = _build_report(tmp_path, generated_at=generated_at)
    report_path = tmp_path / "report.json"
    write_deepseek_opencode_usage_report(report, report_path)
    return build_deepseek_opencode_usage_summary(report, source_report_path=report_path)


@pytest.mark.contract
def test_schema_validates() -> None:
    schema = _schema("rig.deepseek_opencode_usage_report.v1")
    jsonschema.Draft7Validator.check_schema(schema)


@pytest.mark.real_artifact
@pytest.mark.contract
def test_report_validates_against_schema(tmp_path: Path) -> None:
    report = _build_report(tmp_path)
    jsonschema.validate(report, _schema("rig.deepseek_opencode_usage_report.v1"))


@pytest.mark.real_artifact
def test_builder_reads_fixture_db_and_logs(tmp_path: Path) -> None:
    report = _build_report(tmp_path)
    assert report["provider"] == "deepseek"
    assert report["opencode_version"] == "1.14.50"
    assert report["session_count"] == 3
    assert report["request_count_if_available"] == 4
    assert report["reasoning_token_total"] == 170
    assert report["cache_read_token_total"] == 32_000
    assert report["cache_write_token_total"] == 0
    assert report["output_token_total_if_available"] == 580
    assert report["model_counts"][0]["model_id"] == "deepseek-v4-flash"


@pytest.mark.contract
def test_cache_ratio_calculation_is_deterministic(tmp_path: Path) -> None:
    report = _build_report(tmp_path)
    expected = 32_000 / (32_000 + 3_500)
    assert report["cache_hit_ratio"] == round(expected, 6)


@pytest.mark.contract
@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (
            [{"cache_write_present": True, "cache_write_token_total": 0}],
            "reported_zero",
        ),
        (
            [{"cache_write_present": False, "cache_write_token_total": 0}],
            "not_reported_by_source",
        ),
        (
            [{"cache_write_present": True, "cache_write_token_total": 12}],
            "reported_nonzero",
        ),
    ],
)
def test_cache_write_visibility_semantics(
    rows: list[dict[str, Any]], expected: str
) -> None:
    visibility, _ = _cache_write_visibility(rows)
    assert visibility == expected


@pytest.mark.substrate
def test_lane_policy_is_deterministic(tmp_path: Path) -> None:
    first = _build_report(tmp_path, generated_at="2026-05-19T12:00:00Z")
    second = _build_report(tmp_path, generated_at="2026-05-19T12:00:00Z")
    assert first["lane_policy_recommendation"] == second["lane_policy_recommendation"]


@pytest.mark.adversarial
def test_secret_like_values_are_not_retained(tmp_path: Path) -> None:
    db_path = tmp_path / "opencode.db"
    logs_dir = tmp_path / "log"
    _make_db(db_path)
    _make_logs(logs_dir)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE session SET model = ? WHERE id = ?",
            (
                json.dumps({
                    "id": "deepseek-v4-pro",
                    "providerID": "deepseek",
                    "variant": "default",
                    "path": "/Users/user/Private/Repo",
                    "access_token": "sk-secret-test-value",
                }),
                "session-pro-default",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    report = build_deepseek_opencode_usage_report(
        db_path=db_path,
        log_dir=logs_dir,
        opencode_version="1.14.50",
        generated_at="2026-05-19T12:00:00Z",
    )
    raw = json.dumps(report)
    assert "/Users/user/Private/Repo" not in raw
    assert "sk-secret-test-value" not in raw


@pytest.mark.contract
def test_feature_status_categories_are_distinguished(tmp_path: Path) -> None:
    report = _build_report(tmp_path)
    already = {item["feature_id"] for item in report["features_already_enabled"]}
    supported = {
        item["feature_id"]
        for item in report["features_not_enabled"]["supported_but_not_enabled"]
    }
    adapter = {
        item["feature_id"]
        for item in report["features_not_enabled"]["adapter_change_required"]
    }
    not_priority = {
        item["feature_id"] for item in report["features_not_worth_prioritizing"]
    }
    assert "thinking_mode" in already
    assert "json_output_mode" in supported
    assert "chat_prefix_completion_beta" in adapter
    assert "fim_completion_beta" in adapter
    assert "thinking_mode_noop_parameters" in not_priority


@pytest.mark.real_artifact
@pytest.mark.contract
def test_summary_validates_against_schema(tmp_path: Path) -> None:
    summary = _build_summary(tmp_path)
    errors = validate_deepseek_opencode_usage_summary(summary)
    assert not errors


@pytest.mark.real_artifact
def test_summary_writer_round_trip(tmp_path: Path) -> None:
    summary = _build_summary(tmp_path)
    output_path = tmp_path / "out" / "deepseek_opencode_usage_summary.v1.json"
    write_deepseek_opencode_usage_summary(summary, output_path)
    parsed = json.loads(output_path.read_text(encoding="utf-8"))
    assert parsed["schema_version"] == "rig.deepseek_opencode_usage_summary.v1"


@pytest.mark.integration
def test_cli_writes_report(tmp_path: Path) -> None:
    db_path = tmp_path / "opencode.db"
    logs_dir = tmp_path / "log"
    _make_db(db_path)
    _make_logs(logs_dir)
    output_path = tmp_path / "report.json"
    summary_output_path = tmp_path / "summary.json"
    exit_code = report_main([
        "--db-path",
        str(db_path),
        "--log-dir",
        str(logs_dir),
        "--output-path",
        str(output_path),
        "--summary-output-path",
        str(summary_output_path),
        "--generated-at",
        "2026-05-19T12:00:00Z",
        "--opencode-version",
        "1.14.50",
        "--fail-on-schema-error",
    ])
    assert exit_code == 0
    assert output_path.is_file()
    assert summary_output_path.is_file()
    jsonschema.validate(
        json.loads(output_path.read_text(encoding="utf-8")),
        _schema("rig.deepseek_opencode_usage_report.v1"),
    )
    jsonschema.validate(
        json.loads(summary_output_path.read_text(encoding="utf-8")),
        _schema("rig.deepseek_opencode_usage_summary.v1"),
    )


@pytest.mark.adversarial
def test_cli_exits_non_zero_on_missing_db(tmp_path: Path) -> None:
    output_path = tmp_path / "report.json"
    summary_output_path = tmp_path / "summary.json"
    exit_code = report_main([
        "--db-path",
        str(tmp_path / "missing.db"),
        "--output-path",
        str(output_path),
        "--summary-output-path",
        str(summary_output_path),
        "--generated-at",
        "2026-05-19T12:00:00Z",
    ])
    assert exit_code == 1
    assert not output_path.exists()
    assert not summary_output_path.exists()


@pytest.mark.integration
@pytest.mark.adversarial
def test_cli_summary_mode_writes_summary_and_redacts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "opencode.db"
    logs_dir = tmp_path / "log"
    _make_db(db_path)
    _make_logs(logs_dir)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE session SET model = ? WHERE id = ?",
            (
                json.dumps({
                    "id": "deepseek-v4-pro",
                    "providerID": "deepseek",
                    "variant": "default",
                    "path": "/Users/user/Private/Repo",
                    "access_token": "sk-secret-test-value",
                }),
                "session-pro-default",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    output_path = tmp_path / "report.json"
    summary_output_path = tmp_path / "summary.json"
    exit_code = report_main([
        "--db-path",
        str(db_path),
        "--log-dir",
        str(logs_dir),
        "--output-path",
        str(output_path),
        "--summary-output-path",
        str(summary_output_path),
        "--generated-at",
        "2026-05-19T12:00:00Z",
        "--opencode-version",
        "1.14.50",
        "--summary",
        "--fail-on-schema-error",
    ])
    captured = capsys.readouterr().out
    assert exit_code == 0
    assert output_path.is_file()
    assert summary_output_path.is_file()
    assert "Cache-hit ratio" in captured
    assert "90.14%" in captured
    assert "0.901408" in captured
    assert "reported_zero" in captured
    assert "/Users/user/Private/Repo" not in captured
    assert "sk-secret-test-value" not in captured
    jsonschema.validate(
        json.loads(summary_output_path.read_text(encoding="utf-8")),
        _schema("rig.deepseek_opencode_usage_summary.v1"),
    )


@pytest.mark.contract
def test_validator_accepts_generated_report(tmp_path: Path) -> None:
    report = _build_report(tmp_path)
    errors = validate_deepseek_opencode_usage_report(report)
    assert not errors


@pytest.mark.real_artifact
def test_writer_round_trip(tmp_path: Path) -> None:
    report = _build_report(tmp_path)
    output_path = tmp_path / "out" / "deepseek_opencode_usage_report.v1.json"
    write_deepseek_opencode_usage_report(report, output_path)
    parsed = json.loads(output_path.read_text(encoding="utf-8"))
    assert parsed["schema_version"] == "rig.deepseek_opencode_usage_report.v1"

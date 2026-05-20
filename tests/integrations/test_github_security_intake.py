"""GitHub security intake integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider import (
    GitHubLiveAuthConfig,
    GitHubSecurityIntakeCollector,
    build_github_security_intake_report,
)
from rig_relay.integrations.github_provider._redaction import hash_identifier
from rig_relay.integrations.github_provider._security_intake import (
    _normalize_code_scanning_alert,
    _normalize_dependabot_alert,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "github_security_intake"
)
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.github.security_intake.v1.schema.json"
)


def _load_fixture(name: str) -> list[dict[str, object]]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_code_scanning_alert_normalization_is_content_light():
    alerts = _load_fixture("code_scanning_alerts.page1.json")

    first = _normalize_code_scanning_alert(alerts[0])
    second = _normalize_code_scanning_alert(alerts[1])

    assert first["classification"] == "code_scanning"
    assert first["suggested_group_kind"] == "codeql_security_fix_needed"
    assert second["suggested_group_kind"] == "workflow_or_ci_fix_needed"
    assert len(first["rule_id_hash"]) == 64
    assert len(first["file_path_hash"]) == 64

    serialized = json.dumps([first, second], sort_keys=True)
    for needle in (
        "js/zipslip",
        "js/unsafe-regex",
        "spec-main/api-session-spec.ts",
        ".github/workflows/codeql.yml",
        "https://github.com/octo-org/octo-repo/code-scanning/4",
        "https://github.com/octo-org/octo-repo/code-scanning/9",
    ):
        assert needle not in serialized


def test_dependabot_alert_normalization_is_content_light():
    alerts = _load_fixture("dependabot_alerts.page1.json")

    first = _normalize_dependabot_alert(alerts[0])
    second = _normalize_dependabot_alert(alerts[1])

    assert first["classification"] == "dependabot"
    assert first["fixed_version_available"] is True
    assert second["fixed_version_available"] is True
    assert len(first["package_coordinate_hash"]) == 64
    assert len(first["ghsa_id_hash"]) == 64

    serialized = json.dumps([first, second], sort_keys=True)
    for needle in (
        "django",
        "serialize-javascript",
        "path/to/requirements.txt",
        "package.json",
        "GHSA-rf4j-j272-fj86",
        "CVE-2018-6188",
        "GHSA-7f8r-5x4h-9w2q",
        "CVE-2024-12345",
        "https://github.com/octo-org/octo-repo/security/dependabot/2",
        "https://github.com/octo-org/octo-repo/security/dependabot/3",
    ):
        assert needle not in serialized


def test_dry_run_report_is_schema_valid_and_refuses_secret_scanning():
    report = build_github_security_intake_report(
        "juliantorr-es", "rig-relay", live=False
    )

    assert report["schema_version"] == "rig.github.security_intake.v1"
    assert report["dry_run"] is True
    assert report["permission_mode"] == "development_debug"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["token_narrowing_requested"] is True
    assert report["token_narrowing_effective"] is False
    assert report["counts"]["code_scanning_total"] == 0
    assert report["counts"]["dependabot_total"] == 0
    assert any(item["surface"] == "secret_scanning" for item in report["refusals"])
    assert {
        "code_scanning",
        "dependabot",
        "secret_scanning",
        "checks_workflow",
    }.issubset({item["surface"] for item in report["source_surfaces"]})
    assert report["summary"]["permission_mode"] == "development_debug"
    assert report["summary"]["token_narrowing_requested"] is True
    assert report["summary"]["token_narrowing_effective"] is False

    serialized = json.dumps(report, sort_keys=True)
    for needle in (
        "token_prefix",
        "access_token",
        "authorization",
        "raw_response",
        "raw_body",
    ):
        assert needle not in serialized

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_live_intake_uses_exchanged_token_and_not_placeholder(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("RIG_LIVE_AUTH_TESTS", "1")

    collector = GitHubSecurityIntakeCollector(timeout=0.1)
    config = GitHubLiveAuthConfig(
        app_id=3774417,
        installation_id=133860977,
        private_key_env="-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----",
    )

    exchanged_token = "ghs_real_token_1234567890abcdef1234567890abcd"
    probe_calls: list[tuple[str, int | None, str | None, list[str] | None]] = []

    def fake_exchange_installation_token(self, *args, **kwargs):
        assert args == ()
        assert kwargs["app_id"] == 3774417
        assert kwargs["installation_id"] == 133860977
        assert kwargs["requested_permissions"] == {
            "metadata": "read",
            "security_events": "read",
            "vulnerability_alerts": "read",
        }
        return (
            {
                "token": exchanged_token,
                "expires_at": "2026-06-19T00:00:00Z",
                "permissions": {
                    "metadata": "read",
                    "security_events": "read",
                    "vulnerability_alerts": "read",
                },
                "repository_selection": "all",
            },
            exchanged_token,
        )

    def fake_probe_installation_access(
        self,
        token: str,
        installation_id: int | None = None,
        repository_selection: str | None = None,
        permission_keys: list[str] | None = None,
    ):
        probe_calls.append((
            token,
            installation_id,
            repository_selection,
            permission_keys,
        ))
        assert token == exchanged_token
        assert token != "__placeholder__"
        assert permission_keys == [
            "metadata",
            "security_events",
            "vulnerability_alerts",
        ]
        return {
            "schema_version": "rig.github.live_auth_result.v1",
            "auth_mode": "app_installation",
            "installation_id_hash": "installation-id-hash",
            "installation_access": "success",
            "accessible_repo_count": 4,
            "accessible_repo_name_hashes": ["a", "b", "c", "d"],
            "permission_keys": [
                "actions",
                "administration",
                "checks",
                "contents",
                "issues",
                "metadata",
                "pull_requests",
                "security_events",
                "vulnerability_alerts",
                "workflows",
            ],
            "repository_selection": repository_selection or "",
        }

    def fake_collect_alert_surface(
        self, surface: str, token: str, path: str, *, params=None
    ):
        assert token == exchanged_token
        assert token != "__placeholder__"
        if surface == "code_scanning":
            alerts = [
                _normalize_code_scanning_alert(
                    _load_fixture("code_scanning_alerts.page1.json")[0]
                )
            ]
        else:
            alerts = [
                _normalize_dependabot_alert(
                    _load_fixture("dependabot_alerts.page1.json")[0]
                )
            ]
        groups = [
            {
                "group_kind": alerts[0]["suggested_group_kind"]
                if surface == "code_scanning"
                else "dependency_update_needed",
                "alert_ref": f"{surface}#{alerts[0]['alert_number']}",
                "severity": "high",
            }
        ]
        pagination_meta = {
            "per_page": 100,
            "pages_collected": 1,
            "items_collected": 1,
            "truncated": 0,
        }
        return alerts, groups, None, pagination_meta

    monkeypatch.setattr(
        "rig_relay.integrations.github_provider._security_intake.GitHubLiveTokenExchanger.exchange_installation_token",
        fake_exchange_installation_token,
    )
    monkeypatch.setattr(
        "rig_relay.integrations.github_provider._security_intake.GitHubLiveReadOnlySmoke.probe_installation_access",
        fake_probe_installation_access,
    )
    monkeypatch.setattr(
        GitHubSecurityIntakeCollector,
        "_collect_alert_surface",
        fake_collect_alert_surface,
    )

    report = collector.collect(
        "juliantorr-es",
        "rig-relay",
        live=True,
        config=config,
        permission_mode="development_debug",
        receipt_id="receipt-1",
        trace_id="trace-1",
    )

    assert probe_calls
    assert report["dry_run"] is False
    assert report["permission_mode"] == "development_debug"
    assert report["token_narrowing_requested"] is True
    assert report["token_narrowing_effective"] is True
    assert report["public_release_ready"] is False
    assert report["unsafe_broad_token_used"] is False
    assert report["requested_token_permissions"] == [
        {"permission_name": "metadata", "level": "read"},
        {"permission_name": "security_events", "level": "read"},
        {"permission_name": "vulnerability_alerts", "level": "read"},
    ]
    assert report["effective_token_permissions"] == [
        {"permission_name": "metadata", "level": "read"},
        {"permission_name": "security_events", "level": "read"},
        {"permission_name": "vulnerability_alerts", "level": "read"},
    ]
    assert "actions" in report["app_granted_permissions"]
    assert "workflows" in report["mutation_permissions_observed"]
    assert report["installation_access"]["installation_access"] == "success"
    assert report["counts"]["code_scanning_total"] == 1
    assert report["counts"]["dependabot_total"] == 1
    assert report["patch_candidate_groups"]

    serialized = json.dumps(report, sort_keys=True)
    assert exchanged_token not in serialized
    assert "__placeholder__" not in serialized
    assert "token_prefix" not in serialized


def test_live_mode_refusal_when_not_gated_does_not_touch_network(
    monkeypatch: pytest.MonkeyPatch,
):
    collector = GitHubSecurityIntakeCollector(timeout=0.1)

    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "network should not be touched when live auth is gated off"
        )

    monkeypatch.delenv("RIG_LIVE_AUTH_TESTS", raising=False)
    monkeypatch.setattr(
        "rig_relay.integrations.github_provider._security_intake.httpx.get",
        fail_if_called,
    )

    report = collector.collect(
        "juliantorr-es",
        "rig-relay",
        live=True,
        config=GitHubLiveAuthConfig(
            app_id=3774417,
            installation_id=133860977,
            private_key_env="-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----",
        ),
        receipt_id="receipt-2",
        trace_id="trace-2",
    )

    assert report["refusals"]
    assert report["refusals"][0]["reason"] == "live_network_disabled"
    assert report["source_surfaces"][0]["status"] == "refused"
    assert report["counts"]["refused_surfaces"] == 3


def test_dependabot_400_becomes_structured_refusal_and_state_all_is_not_sent(
    monkeypatch: pytest.MonkeyPatch,
):
    import httpx

    monkeypatch.setenv("RIG_LIVE_AUTH_TESTS", "1")

    collector = GitHubSecurityIntakeCollector(timeout=0.1)
    config = GitHubLiveAuthConfig(
        app_id=3774417,
        installation_id=133860977,
        private_key_env="-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----",
    )
    exchanged_token = "ghs_real_token_1234567890abcdef1234567890abcd"
    request_params: list[tuple[str, dict[str, str] | None]] = []

    def fake_exchange_installation_token(self, *args, **kwargs):
        return (
            {
                "token": exchanged_token,
                "expires_at": "2026-06-19T00:00:00Z",
                "permissions": {
                    "metadata": "read",
                    "security_events": "read",
                    "vulnerability_alerts": "read",
                },
                "repository_selection": "all",
            },
            exchanged_token,
        )

    def fake_probe_installation_access(
        self,
        token: str,
        installation_id: int | None = None,
        repository_selection: str | None = None,
        permission_keys: list[str] | None = None,
    ):
        return {
            "schema_version": "rig.github.live_auth_result.v1",
            "auth_mode": "app_installation",
            "installation_id_hash": hash_identifier("133860977"),
            "installation_access": "success",
            "accessible_repo_count": 4,
            "accessible_repo_name_hashes": ["a", "b", "c", "d"],
            "permission_keys": sorted(permission_keys or []),
            "repository_selection": repository_selection or "",
        }

    def fake_request_json(self, path: str, token: str, params=None):
        request_params.append((path, dict(params or {})))
        if path.endswith("/code-scanning/alerts"):
            return (
                [
                    _normalize_code_scanning_alert(
                        _load_fixture("code_scanning_alerts.page1.json")[0]
                    )
                ],
                {},
            )
        request = httpx.Request("GET", f"https://api.github.com{path}")
        response = httpx.Response(400, request=request)
        raise httpx.HTTPStatusError("Bad Request", request=request, response=response)

    monkeypatch.setattr(
        "rig_relay.integrations.github_provider._security_intake.GitHubLiveTokenExchanger.exchange_installation_token",
        fake_exchange_installation_token,
    )
    monkeypatch.setattr(
        "rig_relay.integrations.github_provider._security_intake.GitHubLiveReadOnlySmoke.probe_installation_access",
        fake_probe_installation_access,
    )
    monkeypatch.setattr(
        GitHubSecurityIntakeCollector, "_request_json", fake_request_json
    )

    report = collector.collect(
        "juliantorr-es",
        "rig-relay",
        live=True,
        config=config,
        permission_mode="development_debug",
        receipt_id="receipt-2",
        trace_id="trace-2",
    )

    assert report["counts"]["code_scanning_total"] == 1
    assert report["counts"]["dependabot_total"] == 0
    assert any(item["surface"] == "dependabot" for item in report["refusals"])
    assert any(item.get("status_code") == 400 for item in report["refusals"])
    assert report["counts"]["refused_surfaces"] == 2
    assert all("state" not in params for _, params in request_params)
    serialized = json.dumps(report, sort_keys=True)
    assert "state=all" not in serialized

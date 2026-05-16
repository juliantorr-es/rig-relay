"""Governance policy enforcement tests — parse JSON artifacts and verify key booleans.

Ensures the contribution policy, license policy, and repository policy
JSON artifacts are valid and contain the required fields. Also verifies
the CLA text contains the three magic contract concepts.
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_json(path: str) -> dict:
    return json.loads((_REPO_ROOT / path).read_text())


# ── JSON artifact existence and parse ───────────────────────────


class TestPolicyArtifactsExist:
    def test_contribution_policy_exists(self) -> None:
        assert (_REPO_ROOT / "docs/json/contribution_policy.v1.json").is_file()

    def test_license_policy_exists(self) -> None:
        assert (_REPO_ROOT / "docs/json/license_policy.v1.json").is_file()

    def test_repository_policy_exists(self) -> None:
        assert (_REPO_ROOT / "docs/json/repository_policy.v1.json").is_file()


class TestPolicyArtifactsParse:
    def test_contribution_policy_parses(self) -> None:
        data = _load_json("docs/json/contribution_policy.v1.json")
        assert "schema_version" in data

    def test_license_policy_parses(self) -> None:
        data = _load_json("docs/json/license_policy.v1.json")
        assert "schema_version" in data

    def test_repository_policy_parses(self) -> None:
        data = _load_json("docs/json/repository_policy.v1.json")
        assert "schema_version" in data


# ── Contribution policy key booleans ────────────────────────────


class TestContributionPolicyBooleans:
    def test_contributor_keeps_copyright_is_true(self) -> None:
        data = _load_json("docs/json/contribution_policy.v1.json")
        assert data["contributor_keeps_copyright"] is True

    def test_maintainer_relicense_right_is_true(self) -> None:
        data = _load_json("docs/json/contribution_policy.v1.json")
        assert data["maintainer_relicense_right"] is True

    def test_dual_licensing_allowed_is_true(self) -> None:
        data = _load_json("docs/json/contribution_policy.v1.json")
        assert data["dual_licensing_allowed"] is True

    def test_legal_review_required_is_true(self) -> None:
        data = _load_json("docs/json/contribution_policy.v1.json")
        assert data["legal_review_required_before_large_external_intake"] is True


# ── License policy key booleans ─────────────────────────────────


class TestLicensePolicyBooleans:
    def test_public_license_is_agpl(self) -> None:
        data = _load_json("docs/json/license_policy.v1.json")
        assert "AGPL-3.0-or-later" in data["public_license"]

    def test_agpl_section_13_expected(self) -> None:
        data = _load_json("docs/json/license_policy.v1.json")
        nip = data["network_interaction_policy"]
        assert (
            nip[
                "agpl_section_13_expected_to_apply_to_modified_network_interactive_versions"
            ]
            is True
        )
        assert (
            nip[
                "source_offer_required_for_modified_versions_interacting_with_remote_users"
            ]
            is True
        )

    def test_commercial_licensing_available(self) -> None:
        data = _load_json("docs/json/license_policy.v1.json")
        assert data["commercial_licensing"]["available_by_separate_agreement"] is True

    def test_contributor_keeps_copyright_in_license_policy(self) -> None:
        data = _load_json("docs/json/license_policy.v1.json")
        assert data["contributions"]["contributor_keeps_copyright"] is True
        assert data["contributions"]["maintainer_relicense_right_required"] is True

    def test_attribution_policy_present(self) -> None:
        data = _load_json("docs/json/license_policy.v1.json")
        assert data["attribution"]["preserve_git_history"] is True
        assert data["attribution"]["machine_readable_attribution_manifest"] is True


# ── CLA text contract concepts ──────────────────────────────────


class TestCLATextConcepts:
    def test_cla_file_exists(self) -> None:
        assert (_REPO_ROOT / "CONTRIBUTOR_LICENSE_AGREEMENT.md").is_file()

    def test_no_copyright_assignment(self) -> None:
        text = (_REPO_ROOT / "CONTRIBUTOR_LICENSE_AGREEMENT.md").read_text()
        assert "does not transfer copyright ownership" in text, (
            "CLA must explicitly state that copyright is not transferred"
        )

    def test_public_project_license_agpl(self) -> None:
        text = (_REPO_ROOT / "CONTRIBUTOR_LICENSE_AGREEMENT.md").read_text()
        assert "AGPL-3.0-or-later" in text, (
            "CLA must reference the project's public license"
        )

    def test_future_licensing_rights(self) -> None:
        text = (_REPO_ROOT / "CONTRIBUTOR_LICENSE_AGREEMENT.md").read_text()
        assert "relicense" in text, "CLA must grant relicense rights"
        assert "dual-license" in text, "CLA must grant dual-license rights"


# ── CONTRIBUTING.md signoff text ────────────────────────────────


class TestContributingSignoff:
    def test_signoff_text_present(self) -> None:
        text = (_REPO_ROOT / "CONTRIBUTING.md").read_text()
        assert "I agree to the Contributor License Agreement" in text, (
            "CONTRIBUTING.md must contain the contribution signoff text"
        )
        assert "relicensed or dual-licensed" in text, (
            "CONTRIBUTING.md must mention relicensing/dual-licensing rights"
        )

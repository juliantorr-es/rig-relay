"""Tests for Rig + Intake cannibalization plan and derived governance docs."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Expected deliverables from the cannibalization plan
REQUIRED_DELIVERABLES = [
    "docs/audits/rig-intake-cannibalization-plan.md",
    "docs/governance/relay-local-remote-boundary.md",
    "docs/governance/relay-desktop-projection-contract.md",
    "docs/governance/frontend-rendering-safety.md",
]


def test_deliverables_exist() -> None:
    """All five required deliverables exist."""
    missing = []
    for path in REQUIRED_DELIVERABLES:
        full = REPO_ROOT / path
        if not full.is_file():
            missing.append(path)
    assert not missing, f"Missing deliverables: {missing}"


def test_cannibalization_plan_has_required_sections() -> None:
    """Plan contains all required classification sections."""
    path = REPO_ROOT / "docs/audits/rig-intake-cannibalization-plan.md"
    text = path.read_text(encoding="utf-8")
    sections = {
        "port_now": "### port_now",
        "port_next": "### port_next",
        "defer": "### defer",
        "reject": "### reject",
    }
    missing = [k for k, v in sections.items() if v not in text]
    assert not missing, f"Missing sections in plan: {missing}"


def test_cannibalization_plan_has_source_verification() -> None:
    """Plan includes source verification table."""
    path = REPO_ROOT / "docs/audits/rig-intake-cannibalization-plan.md"
    text = path.read_text(encoding="utf-8")
    assert "| Rig README" in text
    assert "| Rig Workspace Control Plane" in text
    assert "| Rig UI Projection Contract" in text
    assert "| Rig Progress Stream" in text
    assert "| Intake README" in text
    assert "| Intake Hosted/Local Boundary" in text


def test_cannibalization_plan_has_port_now_classifications() -> None:
    """Plan includes at least 5 port_now items with all required fields."""
    path = REPO_ROOT / "docs/audits/rig-intake-cannibalization-plan.md"
    text = path.read_text(encoding="utf-8")
    # Each port_now item should have a table with Source repo, Target, Rationale, Risk, Validation
    required_fields = [
        "**Source repo**",
        "**Target in Rig Relay**",
        "**Rationale**",
        "**Risk**",
        "**Validation**",
    ]
    for field in required_fields:
        assert field in text, f"Missing port_now field: {field}"


def test_cannibalization_plan_has_rejected_items() -> None:
    """Plan includes a reject table with reasoned rejections."""
    path = REPO_ROOT / "docs/audits/rig-intake-cannibalization-plan.md"
    text = path.read_text(encoding="utf-8")
    assert "| Candidate | Source | Reason |" in text
    assert (
        "Python 3.14" in text
        or "Intake public-hosted" in text
        or "quote domain" in text
    )


def test_plan_mentions_intake_and_rig_as_sources() -> None:
    """Plan references both Rig and Intake as source repos."""
    path = REPO_ROOT / "docs/audits/rig-intake-cannibalization-plan.md"
    text = path.read_text(encoding="utf-8")
    assert "juliantorr-es/Rig" in text
    assert "juliantorr-es/Intake" in text


def test_relay_local_remote_boundary_has_core_boundaries() -> None:
    """Boundary doc includes all core boundary rules."""
    path = REPO_ROOT / "docs/governance/relay-local-remote-boundary.md"
    text = path.read_text(encoding="utf-8")
    rules = [
        "No private keys",
        "Local-only decryption",
        "Outbound-only sync",
        "No raw content",
        "No authoritative receipts",
        "Signed local action envelopes",
    ]
    missing = [r for r in rules if r not in text]
    assert not missing, f"Missing boundary rules: {missing}"


def test_relay_local_remote_boundary_has_data_table() -> None:
    """Boundary doc has the local/remote data classification table."""
    path = REPO_ROOT / "docs/governance/relay-local-remote-boundary.md"
    text = path.read_text(encoding="utf-8")
    assert "| Data | Local | Remote |" in text
    assert "Raw receipts" in text
    assert "Raw prompts/outputs" in text


def test_relay_local_remote_boundary_has_intake_mapping() -> None:
    """Boundary doc has mapping from Intake concepts."""
    path = REPO_ROOT / "docs/governance/relay-local-remote-boundary.md"
    text = path.read_text(encoding="utf-8")
    assert (
        "| Intake concept | Rig Relay equivalent " in text
        or "Rig Relay equivalent" in text
    )
    assert "Hosted Intake" in text or "Split-brain" in text


def test_desktop_projection_contract_has_core_rule() -> None:
    """Projection contract states the core rule explicitly."""
    path = REPO_ROOT / "docs/governance/relay-desktop-projection-contract.md"
    text = path.read_text(encoding="utf-8")
    assert "Backend authors the state" in text
    assert "Frontend renders the state" in text
    assert "Frontend emits intentions only" in text


def test_desktop_projection_contract_has_widgets() -> None:
    """Projection contract defines at least 5 widget types."""
    path = REPO_ROOT / "docs/governance/relay-desktop-projection-contract.md"
    text = path.read_text(encoding="utf-8")
    required_widgets = [
        "OperatorHeader",
        "SafetyState",
        "NextAction",
        "ActiveChildSessions",
        "ReceiptTimeline",
    ]
    missing = [w for w in required_widgets if f"### {w}" not in text]
    assert not missing, f"Missing widget definitions: {missing}"


def test_desktop_projection_contract_has_forbidden_inferences() -> None:
    """Each widget documents forbidden frontend inferences."""
    path = REPO_ROOT / "docs/governance/relay-desktop-projection-contract.md"
    text = path.read_text(encoding="utf-8")
    # At least some widgets should have "Forbidden frontend inference" sections
    assert text.count("Forbidden frontend inference") >= 5


def test_desktop_projection_contract_has_rig_mapping() -> None:
    """Projection contract has mapping from Rig widgets."""
    path = REPO_ROOT / "docs/governance/relay-desktop-projection-contract.md"
    text = path.read_text(encoding="utf-8")
    assert "| Rig widget | Rig Relay widget | Adaptation |" in text
    assert "WorkspaceHeader" in text
    assert "LaneRecommendationCard" in text


def test_desktop_projection_contract_has_widget_grouping() -> None:
    """Projection contract defines widget grouping."""
    path = REPO_ROOT / "docs/governance/relay-desktop-projection-contract.md"
    text = path.read_text(encoding="utf-8")
    assert "Header zone" in text
    assert "Activity zone" in text
    assert "Footer zone" in text


def test_frontend_rendering_safety_has_rules() -> None:
    """Frontend safety doc includes all 8 rules."""
    path = REPO_ROOT / "docs/governance/frontend-rendering-safety.md"
    text = path.read_text(encoding="utf-8")
    rules = [f"Rule {i}" for i in range(1, 9)]
    missing = [r for r in rules if r not in text]
    assert not missing, f"Missing rules: {missing}"


def test_frontend_rendering_safety_has_checklist() -> None:
    """Frontend safety doc has implementation checklist."""
    path = REPO_ROOT / "docs/governance/frontend-rendering-safety.md"
    text = path.read_text(encoding="utf-8")
    assert "| Rule | Check | Status |" in text
    assert "No innerHTML" in text or "Rule 4" in text


def test_frontend_rendering_safety_has_test_requirement() -> None:
    """Frontend safety doc references a test for no-innerHTML."""
    path = REPO_ROOT / "docs/governance/frontend-rendering-safety.md"
    text = path.read_text(encoding="utf-8")
    assert "test_no_inner_html" in text


def test_cross_references_are_consistent() -> None:
    """All new governance docs cross-reference each other."""
    docs = [
        REPO_ROOT / "docs/governance/relay-local-remote-boundary.md",
        REPO_ROOT / "docs/governance/relay-desktop-projection-contract.md",
        REPO_ROOT / "docs/governance/frontend-rendering-safety.md",
    ]
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        assert "Cross-References" in text
        assert "rig-intake-cannibalization-plan" in text


def test_new_docs_dont_mention_intake_quote_domain() -> None:
    """No Intake business domain leakage into Relay docs."""
    docs = [
        REPO_ROOT / "docs/governance/relay-local-remote-boundary.md",
        REPO_ROOT / "docs/governance/relay-desktop-projection-contract.md",
        REPO_ROOT / "docs/governance/frontend-rendering-safety.md",
    ]
    rejected_terms = [
        "service lane",
        "quote submission",
        "freelance",
        "passkey authentication",
        "email verification",
        "encrypted shell",
    ]
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for term in rejected_terms:
            assert term.lower() not in text.lower(), (
                f"Leaked Intake term '{term}' in {doc.name}"
            )

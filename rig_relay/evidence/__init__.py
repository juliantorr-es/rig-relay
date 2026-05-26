"""rig_relay.evidence — Artifacts, receipts, semantic snippets, telemetry bundles,
GitHub truth persistence, and storage lifecycle services.

Target package for migrating:
  scripts/rig_relay_export_semantic_change_snippets.py
  scripts/rig_relay_export_coordination_datasets.py
  scripts/rig_relay_create_telemetry_bundle.py (future)
"""

from __future__ import annotations

from rig_relay.evidence._storage_audit import DEFAULT_BUDGET, audit_storage
from rig_relay.evidence.github_truth_store import GitHubTruthStore
from rig_relay.evidence.governance_decision_evidence import (
    GovernanceDecisionEvidence,
    should_block_mutation_on_evidence_failure,
)
from rig_relay.evidence.receipt_envelope import (
    ReceiptEnvelope,
    build_governance_decision_envelope,
)
from rig_relay.evidence.receipt_store import (
    FilesystemReceiptStore,
    ManifestDiagnostic,
    ReceiptStore,
)

__all__ = [
    "DEFAULT_BUDGET",
    "FilesystemReceiptStore",
    "GitHubTruthStore",
    "GovernanceDecisionEvidence",
    "ManifestDiagnostic",
    "ReceiptEnvelope",
    "ReceiptStore",
    "audit_storage",
    "build_governance_decision_envelope",
    "should_block_mutation_on_evidence_failure",
]

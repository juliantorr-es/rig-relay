from __future__ import annotations

import json
from pathlib import Path

from rig_relay.review_projection.models import ReviewProjectionPolicy


class PolicyEngine:
    def __init__(self, local_rules_path: Path | None = None):
        self.local_rules_path = local_rules_path
        self.policy = ReviewProjectionPolicy()
        self.confidential_paths: list[str] = []
        self._load_local_rules()

    def _load_local_rules(self) -> None:
        if self.local_rules_path and self.local_rules_path.is_file():
            try:
                data = json.loads(self.local_rules_path.read_text("utf-8"))
                self.policy = ReviewProjectionPolicy.model_validate(
                    data.get("policy", {})
                )
                self.confidential_paths = data.get("confidential_paths", [])
            except Exception:
                # Fail closed if rules file exists but is unreadable/invalid
                self.confidential_paths = ["*"]  # Deny all
        else:
            # Default safe policy
            self.policy.confidential_categories = [
                "execution_authorization_enforcement",
                "context_admissibility_or_enforcement",
                "causal_integrity_or_trace_enforcement",
                "autonomous_mutation_admission",
                "isolated_candidate_validation_and_promotion",
                "evidence_preserving_candidate_or_permutation_logic",
                "runtime_redaction_enforcement_projection",
                "confidential_ip_audit_material",
                "orchestration_instructions",
                "secrets_and_credentials",
            ]

    def is_confidential_path(self, path: Path, repo_root: Path) -> bool:
        try:
            rel = path.resolve().relative_to(repo_root.resolve())
        except ValueError:
            return True  # Outside repo root -> fail closed

        rel_str = str(rel)
        if self.confidential_paths == ["*"]:
            return True

        for cpath in self.confidential_paths:
            if rel_str.startswith(cpath) or cpath in rel_str:
                return True
        return False

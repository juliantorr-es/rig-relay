from __future__ import annotations

import hashlib
from pathlib import Path

from rig_relay.core.paths import is_confidential_artifact_path
from rig_relay.review_projection.models import (
    FileClassification,
    InclusionManifest,
    ProjectionMode,
)
from rig_relay.review_projection.policy import PolicyEngine
from rig_relay.review_projection.public_baseline import PublicBaselineValidator


class ClassificationEngine:
    def __init__(
        self,
        repo_root: Path,
        policy_engine: PolicyEngine,
        manifest: InclusionManifest,
        public_validator: PublicBaselineValidator | None = None,
    ):
        self.repo_root = repo_root.resolve()
        self.policy_engine = policy_engine
        self.manifest = manifest
        self.public_validator = public_validator

    def _hash_file(self, path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            return ""

    def _is_approved_by_manifest(self, rel_path: str) -> bool:
        if rel_path in self.manifest.approved_files:
            return True
        for glob_pat in self.manifest.approved_globs:
            # Basic glob matching check, simplified for v1
            if Path(rel_path).match(glob_pat):
                return True
        return False

    def classify_file(self, file_path: Path) -> FileClassification:
        try:
            rel_path = str(file_path.resolve().relative_to(self.repo_root))
        except ValueError:
            return FileClassification.UNCLASSIFIED_REFUSED

        if is_confidential_artifact_path(file_path, self.repo_root):
            return FileClassification.CONFIDENTIAL_HOLDBACK

        if not file_path.is_file():
            return FileClassification.UNCLASSIFIED_REFUSED

        # 1. Excluded secret or private material (fail closed on credentials)
        if any(part in file_path.parts for part in [".env", ".git", ".github", "secrets", "tokens"]):
            return FileClassification.EXCLUDED_SECRET_OR_PRIVATE_MATERIAL

        # 2. Generated or projection sensitive
        if any(part in file_path.parts for part in [".build", "docs", "artifacts"]):
            return FileClassification.GENERATED_OR_PROJECTION_SENSITIVE

        # 3. Confidential holdback check (Policy)
        if self.policy_engine.is_confidential_path(file_path, self.repo_root):
            return FileClassification.CONFIDENTIAL_HOLDBACK

        # 4. Public baseline check
        if self.manifest.mode == ProjectionMode.PUBLIC_BASELINE_REVIEW:
            if not self.public_validator:
                return FileClassification.UNCLASSIFIED_REFUSED
            file_hash = self._hash_file(file_path)
            if self.public_validator.is_verified_public(rel_path, file_hash):
                return FileClassification.PUBLIC_ALREADY_DISCLOSED
            return FileClassification.UNCLASSIFIED_REFUSED

        # 5. Manifest override exclusion
        if rel_path in self.manifest.exclude_overrides:
            return FileClassification.UNCLASSIFIED_REFUSED

        # 6. Transform allowed
        if file_path.suffix == ".py":
            if self._is_approved_by_manifest(rel_path):
                return FileClassification.TRANSFORM_ALLOWED

        return FileClassification.UNCLASSIFIED_REFUSED

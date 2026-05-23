from __future__ import annotations

import json
from pathlib import Path

from rig_relay.review_projection.models import PublicBaselineAttestation


class PublicBaselineValidator:
    def __init__(self, attestation_path: Path | None = None):
        self.attestation: PublicBaselineAttestation | None = None
        if attestation_path and attestation_path.is_file():
            try:
                data = json.loads(attestation_path.read_text("utf-8"))
                self.attestation = PublicBaselineAttestation.model_validate(data)
            except Exception:
                self.attestation = None

    def is_verified_public(self, rel_path: str, file_hash: str) -> bool:
        """Check if the file is explicitly attested as public with the given blob hash.
        This operates entirely offline using the injected local attestation.
        """
        if not self.attestation:
            return False
        expected_hash = self.attestation.verified_files.get(rel_path)
        if not expected_hash:
            return False
        return expected_hash == file_hash

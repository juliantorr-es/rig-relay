"""Standalone fixture-callable sealed execution coordinator."""
from __future__ import annotations

import subprocess
from typing import Any

from rig_relay.cli._steward._sealed_completion import (
    SealedCompletionPacket,
    build_completion_packet,
)
from rig_relay.cli._steward._sealed_lane import SealedLaneDescriptor, SealedLanePolicy
from rig_relay.context_egress.models import BoundedMissionManifest
from rig_relay.context_egress.sealed_adapter import SealedContextEgressAdapter


class SealedToolRegistry:
    """Strict allowlist-based capability registry."""

    def __init__(self, policy: SealedLanePolicy) -> None:
        self._policy = policy

    def read_file(self, path: str) -> str:
        target = self._policy.validate_read_target(path)
        return target.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        target = self._policy.validate_write_target(path)
        target.write_text(content, encoding="utf-8")

    def search_files(self, keyword: str) -> dict[str, str]:
        # Only search within approved paths
        results = {}
        for p in self._policy.approved_paths:
            if p.exists() and p.is_file():
                try:
                    text = p.read_text(encoding="utf-8")
                    if keyword in text:
                        results[str(p.relative_to(self._policy.lane_root))] = text
                except UnicodeDecodeError:
                    pass
        return results

    def execute_validation_command(self, cmd: list[str]) -> str:
        self._policy.validate_test_command(cmd)
        result = subprocess.run(
            cmd,
            cwd=str(self._policy.lane_root),
            capture_output=True,
            text=True,
            check=False
        )
        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

    def route_context(self, manifest: BoundedMissionManifest, source: str) -> tuple[Any, Any, Any, Any]:
        adapter = SealedContextEgressAdapter(self._policy.completion_output_root, self._policy.lane_root)
        return adapter.route_fixture_context(manifest, source)

    def prohibited_capability(self, name: str) -> None:
        self._policy.refuse_prohibited_capability(name)


class SealedRunner:
    """Standalone coordinator for sealed fixture runs."""

    def __init__(self, descriptor: SealedLaneDescriptor) -> None:
        self.descriptor = descriptor
        self.policy = SealedLanePolicy(descriptor)
        self.tools = SealedToolRegistry(self.policy)
        self.refusal_counts: dict[str, int] = {}
        
    def record_refusal(self, capability: str) -> None:
        self.refusal_counts[capability] = self.refusal_counts.get(capability, 0) + 1

    def generate_completion_packet(
        self,
        baseline_manifest: dict[str, str],
        current_manifest: dict[str, str],
        test_result_status: str,
        context_egress_receipt_id: str | None = None
    ) -> SealedCompletionPacket:
        changed_paths_dict, diff_digest = self.policy.calculate_changed_path_digests(
            baseline_manifest, current_manifest
        )
        changed_paths = list(changed_paths_dict.keys())

        packet = build_completion_packet(
            lane_id=self.descriptor.lane_id,
            baseline_digest=self.descriptor.baseline_digest,
            approved_path_set_digest=self.descriptor.approved_path_set_digest,
            changed_paths=changed_paths,
            diff_digest=diff_digest,
            test_result_status=test_result_status,
            context_egress_receipt_id=context_egress_receipt_id,
            refusal_counts=self.refusal_counts,
        )

        output_path = self.policy.completion_output_root / f"{self.descriptor.lane_id}_completion.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(packet.model_dump_json(indent=2))

        return packet

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Literal

from anyio import Path

from vibe.core.cartographer.models import (
    CartographerReceipt,
    FindingCandidate,
    PatchPlan,
    RegulationDecision,
)
from vibe.core.cartographer.registry import ICartographerRegistry
from vibe.core.cartographer.scoring import Regulator


class CartographerLoop:
    def __init__(self, registry: ICartographerRegistry) -> None:
        self._registry = registry
        self._regulator = Regulator()

    async def run_ralph(
        self, candidates_to_process: list[FindingCandidate]
    ) -> CartographerReceipt:
        # Ralph: Propose, observe, evaluate. Emits FindingCandidate records, no edits.
        accepted = 0
        for candidate in candidates_to_process:
            await self._registry.append_finding(candidate)
            accepted += 1

        receipt = self._build_receipt(
            "cartograph", len(candidates_to_process), accepted, 0, 0
        )
        return receipt

    async def run_srl(
        self, candidates_to_process: list[FindingCandidate]
    ) -> CartographerReceipt:
        # SRL: Self-regulation loop. Each candidate must include self-check notes.
        accepted = 0
        rejected = 0
        for candidate in candidates_to_process:
            if not all([
                candidate.srl_why_real,
                candidate.srl_evidence_support,
                candidate.srl_validation_proof,
            ]):
                rejected += 1
                continue

            await self._registry.append_finding(candidate)
            accepted += 1

        return self._build_receipt(
            "cartograph", len(candidates_to_process), accepted, rejected, 0
        )

    async def run_crdal(
        self, candidates_to_process: list[FindingCandidate]
    ) -> tuple[CartographerReceipt, list[RegulationDecision]]:
        # CRDAL: Co-regulated loop. Scored by regulator.
        accepted = 0
        rejected = 0
        decisions: list[RegulationDecision] = []

        for candidate in candidates_to_process:
            decision = self._regulator.score_and_decide(candidate)
            decisions.append(decision)

            if decision.decision in ("ignore"):
                rejected += 1
            else:
                await self._registry.append_finding(candidate)
                accepted += 1

        receipt = self._build_receipt(
            "cartograph", len(candidates_to_process), accepted, rejected, 0
        )
        return receipt, decisions

    async def run_repair_propose(
        self, plans_to_propose: list[PatchPlan]
    ) -> CartographerReceipt:
        # Does not edit files, just proposes patches
        return self._build_receipt("repair-propose", 0, 0, 0, len(plans_to_propose))

    async def run_repair_lane(
        self, plan: PatchPlan, has_isolated_lane: bool = False
    ) -> CartographerReceipt:
        # Refuses if no isolated lane is available
        if not has_isolated_lane:
            raise RuntimeError(
                "Refusing repair-lane: no isolated lane available. Must not touch main."
            )

        return self._build_receipt("repair-lane", 0, 0, 0, 1)

    def _build_receipt(
        self,
        mode: Literal["cartograph", "repair-propose", "repair-lane"],
        findings_count: int,
        accepted_count: int,
        rejected_count: int,
        patch_plans_count: int,
    ) -> CartographerReceipt:
        receipt_id = f"rcpt_{hashlib.sha256(str(datetime.now(UTC).timestamp()).encode()).hexdigest()[:12]}"

        data = f"{mode}:{findings_count}:{accepted_count}:{rejected_count}:{patch_plans_count}"
        scan_inputs_sha256 = hashlib.sha256(data.encode()).hexdigest()
        receipt_sha256 = hashlib.sha256(
            f"{receipt_id}:{scan_inputs_sha256}".encode()
        ).hexdigest()

        return CartographerReceipt(
            receipt_id=receipt_id,
            loop_mode=mode,
            scan_inputs_sha256=scan_inputs_sha256,
            findings_count=findings_count,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            patch_plans_count=patch_plans_count,
            receipt_sha256=receipt_sha256,
        )

    async def ingest_out_of_scope_findings(self, source_path: Path) -> int:
        count = 0
        if not await source_path.exists():
            return count

        async with await source_path.open("r", encoding="utf-8") as f:
            async for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    # Convert out of scope finding to FindingCandidate seed
                    candidate = FindingCandidate(
                        finding_id=f"oos_{hashlib.sha256(line.encode()).hexdigest()[:8]}",
                        kind="implementation_gap",  # default mapping
                        title=data.get("title", "Ingested Out-of-Scope Finding"),
                        summary=data.get("description", ""),
                        files=data.get("affected_files", []),
                        confidence=0.8,
                        impact="medium",
                        risk="low",
                        blast_radius="local",
                        validation_available=False,
                        suggested_mode="repair-propose",
                        created_at=datetime.now(UTC).isoformat(),
                    )
                    await self._registry.append_finding(candidate)
                    count += 1
                except json.JSONDecodeError:
                    pass
        return count

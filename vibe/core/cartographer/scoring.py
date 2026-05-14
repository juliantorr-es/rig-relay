from __future__ import annotations

from vibe.core.cartographer.models import FindingCandidate, RegulationDecision


class Regulator:
    def score_and_decide(self, candidate: FindingCandidate) -> RegulationDecision:
        # Very simple initial scoring for CRDAL
        MIN_CONFIDENCE = 0.3
        if candidate.confidence < MIN_CONFIDENCE:
            return RegulationDecision(
                finding_id=candidate.finding_id,
                decision="ignore",
                rationale="Confidence too low",
                confidence=candidate.confidence,
                required_user_approval=False,
            )

        if candidate.impact == "high" and candidate.risk == "high":
            return RegulationDecision(
                finding_id=candidate.finding_id,
                decision="ask_user",
                rationale="High impact and high risk requires user approval",
                confidence=candidate.confidence,
                required_user_approval=True,
            )

        if candidate.suggested_mode == "repair-lane":
            return RegulationDecision(
                finding_id=candidate.finding_id,
                decision="open_repair_lane",
                rationale="Safe repair lane candidate",
                confidence=candidate.confidence,
                required_user_approval=False,
                allowed_next_action="open_lane",
            )

        return RegulationDecision(
            finding_id=candidate.finding_id,
            decision="record",
            rationale="Valid finding, recording for later",
            confidence=candidate.confidence,
            required_user_approval=False,
        )

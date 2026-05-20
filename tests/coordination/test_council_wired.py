from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock

import pytest

from rig_relay.coordination.council import (
    Confidence,
    ConsultationReceipt,
    ConsultationRequest,
    NormalizedConsultation,
    ProviderOpinion,
    ProviderSurface,
)
from rig_relay.coordination.council_invoker import (
    consult_council_before_mutation,
    determine_council_recommendation,
)


def _make_opinion(*, provider: str, has_blockers: bool = False) -> ProviderOpinion:
    return ProviderOpinion(
        provider=provider,
        model_label=provider,
        mission_id="test-mission",
        question="test question",
        blockers=["blocker-1"] if has_blockers else [],
        confidence=Confidence.MEDIUM,
    )


def _make_consultation(
    *, request_id: str, provider: str, has_blockers: bool = False
) -> NormalizedConsultation:
    return NormalizedConsultation(
        consultation_id=f"{request_id}-{provider}",
        request_id=request_id,
        provider=provider,
        provider_surface=ProviderSurface.API,
        opinion=_make_opinion(provider=provider, has_blockers=has_blockers),
    )


class TestDetermineCouncilRecommendation:
    def test_allow_when_no_consultations(self) -> None:
        receipt = ConsultationReceipt(
            receipt_id="r-1", request_id="req-1", consultations=[], provider_count=0
        )
        assert determine_council_recommendation(receipt) == "ALLOW"

    def test_allow_when_all_clear(self) -> None:
        receipt = ConsultationReceipt(
            receipt_id="r-1",
            request_id="req-1",
            consultations=[
                _make_consultation(
                    request_id="req-1", provider="deepseek", has_blockers=False
                ),
                _make_consultation(
                    request_id="req-1", provider="claude", has_blockers=False
                ),
            ],
            provider_count=2,
        )
        assert determine_council_recommendation(receipt) == "ALLOW"

    def test_block_when_all_have_blockers(self) -> None:
        receipt = ConsultationReceipt(
            receipt_id="r-1",
            request_id="req-1",
            consultations=[
                _make_consultation(
                    request_id="req-1", provider="deepseek", has_blockers=True
                ),
                _make_consultation(
                    request_id="req-1", provider="claude", has_blockers=True
                ),
            ],
            provider_count=2,
        )
        assert determine_council_recommendation(receipt) == "BLOCK"

    def test_review_when_mixed_opinions(self) -> None:
        receipt = ConsultationReceipt(
            receipt_id="r-1",
            request_id="req-1",
            consultations=[
                _make_consultation(
                    request_id="req-1", provider="deepseek", has_blockers=True
                ),
                _make_consultation(
                    request_id="req-1", provider="claude", has_blockers=False
                ),
            ],
            provider_count=2,
        )
        assert determine_council_recommendation(receipt) == "REVIEW"


class TestConsultCouncilBeforeMutation:
    @pytest.mark.asyncio
    async def test_returns_receipt_when_no_providers(self) -> None:
        receipt = await consult_council_before_mutation(
            tool_name="write_file",
            tool_args={"path": "/tmp/test.py", "content": "x = 1"},
            context_summary="Testing council",
            providers=[],
        )
        assert isinstance(receipt, ConsultationReceipt)
        assert receipt.provider_count == 0
        assert receipt.consultations == []

    @pytest.mark.asyncio
    async def test_content_light_args_are_hashed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_consult = AsyncMock(
            return_value=NormalizedConsultation(
                consultation_id="req-1-deepseek",
                request_id="req-1",
                provider="deepseek",
                provider_surface=ProviderSurface.API,
                opinion=_make_opinion(provider="deepseek", has_blockers=False),
            )
        )

        async def _fake_consult_one_provider(
            request: ConsultationRequest, provider_name: str
        ) -> NormalizedConsultation:
            return await mock_consult(request, provider_name)

        monkeypatch.setattr(
            "rig_relay.coordination.council_invoker._consult_one_provider",
            _fake_consult_one_provider,
        )

        tool_args = {"path": "/tmp/sensitive.py", "content": "password=123"}
        await consult_council_before_mutation(
            tool_name="write_file",
            tool_args=tool_args,
            context_summary="Testing content-light",
            providers=["deepseek"],
        )

        mock_consult.assert_awaited_once()
        request = mock_consult.call_args[0][0]
        expected_hash = hashlib.sha256(
            json.dumps(tool_args, sort_keys=True, default=str).encode()
        ).hexdigest()
        assert request.packet_sha256 == expected_hash
        assert "password" not in request.packet_sha256

    @pytest.mark.asyncio
    async def test_allow_when_all_providers_return_no_blockers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_consult(
            request: ConsultationRequest, provider_name: str
        ) -> NormalizedConsultation:
            return NormalizedConsultation(
                consultation_id=f"{request.request_id}-{provider_name}",
                request_id=request.request_id,
                provider=provider_name,
                provider_surface=ProviderSurface.API,
                opinion=_make_opinion(provider=provider_name, has_blockers=False),
            )

        monkeypatch.setattr(
            "rig_relay.coordination.council_invoker._consult_one_provider",
            _fake_consult,
        )

        receipt = await consult_council_before_mutation(
            tool_name="write_file",
            tool_args={"path": "/tmp/test.py"},
            context_summary="Test allow",
            providers=["deepseek", "claude"],
        )

        assert receipt.provider_count == 2
        assert determine_council_recommendation(receipt) == "ALLOW"

    @pytest.mark.asyncio
    async def test_block_when_all_providers_return_blockers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_consult(
            request: ConsultationRequest, provider_name: str
        ) -> NormalizedConsultation:
            return NormalizedConsultation(
                consultation_id=f"{request.request_id}-{provider_name}",
                request_id=request.request_id,
                provider=provider_name,
                provider_surface=ProviderSurface.API,
                opinion=_make_opinion(provider=provider_name, has_blockers=True),
            )

        monkeypatch.setattr(
            "rig_relay.coordination.council_invoker._consult_one_provider",
            _fake_consult,
        )

        receipt = await consult_council_before_mutation(
            tool_name="bash",
            tool_args={"command": "rm -rf /"},
            context_summary="Test block",
            providers=["deepseek", "claude"],
        )

        assert receipt.provider_count == 2
        assert determine_council_recommendation(receipt) == "BLOCK"

    @pytest.mark.asyncio
    async def test_does_not_call_real_providers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = 0

        async def _fake_consult(
            request: ConsultationRequest, provider_name: str
        ) -> NormalizedConsultation:
            nonlocal call_count
            call_count += 1
            return NormalizedConsultation(
                consultation_id=f"{request.request_id}-{provider_name}",
                request_id=request.request_id,
                provider=provider_name,
                provider_surface=ProviderSurface.API,
            )

        monkeypatch.setattr(
            "rig_relay.coordination.council_invoker._consult_one_provider",
            _fake_consult,
        )

        await consult_council_before_mutation(
            tool_name="write_file",
            tool_args={"path": "/tmp/test.py"},
            context_summary="Test no real providers",
            providers=["deepseek", "claude"],
        )

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_consultation_failure_returns_empty_consult(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _failing_consult(
            request: ConsultationRequest, provider_name: str
        ) -> NormalizedConsultation:
            raise RuntimeError("Simulated API failure")

        monkeypatch.setattr(
            "rig_relay.coordination.council_invoker._consult_one_provider",
            _failing_consult,
        )

        async def _patched_consult(
            request: ConsultationRequest, provider_name: str
        ) -> NormalizedConsultation:
            try:
                return await _failing_consult(request, provider_name)
            except Exception:
                return NormalizedConsultation(
                    consultation_id=f"{request.request_id}-{provider_name}",
                    request_id=request.request_id,
                    provider=provider_name,
                    provider_surface=ProviderSurface.API,
                    transcript_sha256=hashlib.sha256(b"error").hexdigest(),
                )

        monkeypatch.setattr(
            "rig_relay.coordination.council_invoker._consult_one_provider",
            _patched_consult,
        )

        receipt = await consult_council_before_mutation(
            tool_name="bash",
            tool_args={"command": "ls"},
            context_summary="Test failure handling",
            providers=["deepseek"],
        )

        assert receipt.provider_count == 1
        assert receipt.consultations[0].opinion is None
        assert receipt.consultations[0].transcript_sha256 != ""


class TestCouncilIntegrationWithAgentLoop:
    @pytest.mark.asyncio
    async def test_council_is_skipped_when_no_providers_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from rig_relay.coordination.council_invoker import (
            consult_council_before_mutation,
        )

        receipt = await consult_council_before_mutation(
            tool_name="bash",
            tool_args={"command": "ls"},
            context_summary="Test",
            providers=[],
        )

        assert receipt.provider_count == 0
        assert determine_council_recommendation(receipt) == "ALLOW"

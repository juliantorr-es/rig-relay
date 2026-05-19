from __future__ import annotations

import os

import pytest

from rig_relay.sdk import (
    RigCapabilityDecision,
    RigClient,
    RigVerdict,
    evaluate_github_capability,
    evaluate_google_workspace_capability,
)


class TestSDKGitHubProvider:
    def test_github_provider_status_returns_content_light(self):
        c = RigClient()
        r = c.check_github_provider_status_sync()
        assert r.content_light is True
        assert r.operation_kind == "github_provider_read"
        assert r.receipt_ref is not None
        assert r.receipt_ref.content_light is True

    @pytest.mark.asyncio
    async def test_github_live_read_returns_result_with_trace(self):
        c = RigClient()
        r = await c.run_github_live_read("github.repo.metadata.read", trace_id="pt-gh")
        assert r.trace_id == "pt-gh"
        assert r.content_light is True
        assert r.operation_kind == "github_provider_read"
        assert r.receipt_ref is not None

    @pytest.mark.asyncio
    async def test_github_live_read_refuses_mutation_capability(self):
        c = RigClient()
        r = await c.run_github_live_read(
            "github.repo.content.write", trace_id="pt-gh-mut"
        )
        assert r.verdict == RigVerdict.REFUSED

    @pytest.mark.asyncio
    async def test_github_live_read_refuses_without_env_var(self):
        original = os.environ.pop("RIG_LIVE_PROVIDER_TESTS", None)
        try:
            c = RigClient()
            r = await c.run_github_live_read(
                "github.repo.metadata.read", trace_id="pt-gh-no-env"
            )
            assert r.verdict == RigVerdict.REFUSED
            assert r.refusal_code == "live_network_disabled"
        finally:
            if original is not None:
                os.environ["RIG_LIVE_PROVIDER_TESTS"] = original

    @pytest.mark.asyncio
    async def test_github_capability_evaluation_returns_decision(self):
        c = RigClient()
        d = await c.evaluate_github_capability(
            "github.repo.metadata.read", trace_id="pt-gh-eval"
        )
        assert isinstance(d, RigCapabilityDecision)
        assert d.capability_id == "github.repo.metadata.read"

    def test_github_capability_sync_evaluation(self):
        d = evaluate_github_capability("github.repo.commits.read", "pt-ev")
        assert isinstance(d, RigCapabilityDecision)
        assert d.trace_id == "pt-ev"


class TestSDKGoogleWorkspaceProvider:
    def test_google_workspace_status_returns_content_light(self):
        c = RigClient()
        r = c.check_google_workspace_status_sync()
        assert r.content_light is True
        assert r.operation_kind == "google_workspace_provider_read"
        assert r.receipt_ref is not None
        assert r.receipt_ref.content_light is True

    @pytest.mark.asyncio
    async def test_google_workspace_live_read_returns_result_with_trace(self):
        c = RigClient()
        r = await c.run_google_workspace_live_read(
            "google.admin.directory.user.read", trace_id="pt-gw"
        )
        assert r.trace_id == "pt-gw"
        assert r.content_light is True
        assert r.operation_kind == "google_workspace_provider_read"
        assert r.receipt_ref is not None

    @pytest.mark.asyncio
    async def test_google_workspace_live_read_refuses_restricted_scope(self):
        c = RigClient()
        r = await c.run_google_workspace_live_read(
            "google.admin.reports.audit.read", trace_id="pt-gw-restricted"
        )
        assert r.verdict == RigVerdict.REFUSED

    @pytest.mark.asyncio
    async def test_google_workspace_live_read_refuses_without_env_var(self):
        original = os.environ.pop("RIG_LIVE_PROVIDER_TESTS", None)
        try:
            c = RigClient()
            r = await c.run_google_workspace_live_read(
                "google.admin.directory.user.read", trace_id="pt-gw-no-env"
            )
            assert r.verdict == RigVerdict.REFUSED
            assert r.refusal_code == "live_network_disabled"
        finally:
            if original is not None:
                os.environ["RIG_LIVE_PROVIDER_TESTS"] = original

    @pytest.mark.asyncio
    async def test_google_workspace_capability_evaluation_returns_decision(self):
        c = RigClient()
        d = await c.evaluate_google_workspace_capability(
            "google.gmail.messages.read", trace_id="pt-gw-eval"
        )
        assert isinstance(d, RigCapabilityDecision)
        assert d.capability_id == "google.gmail.messages.read"

    def test_google_workspace_capability_sync_evaluation(self):
        d = evaluate_google_workspace_capability("google.drive.files.read", "pt-gw-ev")
        assert isinstance(d, RigCapabilityDecision)
        assert d.trace_id == "pt-gw-ev"


class TestSDKProviderTraceContinuity:
    @pytest.mark.asyncio
    async def test_trace_id_survives_github_read_roundtrip(self):
        c = RigClient()
        r = await c.check_github_provider_status("trace-gh-123")
        assert r.trace_id == "trace-gh-123"
        r2 = await c.run_github_live_read(
            "github.repo.metadata.read", trace_id="trace-gh-456"
        )
        assert r2.trace_id == "trace-gh-456"

    @pytest.mark.asyncio
    async def test_trace_id_survives_google_read_roundtrip(self):
        c = RigClient()
        r = await c.check_google_workspace_status("trace-gw-123")
        assert r.trace_id == "trace-gw-123"
        r2 = await c.run_google_workspace_live_read(
            "google.admin.directory.user.read", trace_id="trace-gw-456"
        )
        assert r2.trace_id == "trace-gw-456"

    @pytest.mark.asyncio
    async def test_receipt_ref_contains_trace_id(self):
        c = RigClient()
        r = await c.check_github_provider_status("trace-receipt")
        assert r.receipt_ref is not None
        assert r.receipt_ref.trace_id == "trace-receipt"
        r2 = await c.check_google_workspace_status("trace-gw-receipt")
        assert r2.receipt_ref is not None
        assert r2.receipt_ref.trace_id == "trace-gw-receipt"

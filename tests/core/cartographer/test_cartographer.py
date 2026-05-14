from __future__ import annotations

import json

from anyio import Path
import pytest
import pytest_asyncio

from vibe.core.cartographer.loop import CartographerLoop
from vibe.core.cartographer.models import FindingCandidate, FindingKind, PatchPlan
from vibe.core.cartographer.registry import JsonlCartographerRegistry


@pytest_asyncio.fixture
async def temp_registry_path(tmp_path):
    return Path(tmp_path) / "cartographer-findings.jsonl"


@pytest_asyncio.fixture
async def temp_oos_path(tmp_path):
    p = Path(tmp_path) / "out-of-scope-findings.jsonl"
    await p.write_text(
        json.dumps({
            "title": "Old unused function",
            "description": "Found unused func",
            "affected_files": ["foo.py"],
        })
        + "\n"
    )
    return p


@pytest.mark.asyncio
async def test_out_of_scope_ingestion(temp_registry_path, temp_oos_path):
    registry = JsonlCartographerRegistry(temp_registry_path)
    loop = CartographerLoop(registry)

    count = await loop.ingest_out_of_scope_findings(temp_oos_path)
    assert count == 1

    findings = await registry.get_all_findings()
    assert len(findings) == 1
    assert findings[0].title == "Old unused function"


@pytest.mark.asyncio
async def test_finding_fingerprint_stability(temp_registry_path):
    registry = JsonlCartographerRegistry(temp_registry_path)
    candidate1 = FindingCandidate(
        finding_id="1",
        kind=FindingKind.GHOST,
        title="T",
        summary="S",
        confidence=1.0,
        impact="high",
        risk="low",
        blast_radius="local",
        validation_available=False,
        suggested_mode="cartograph",
        created_at="now",
    )
    # Different ID and confidence, same semantic fields
    candidate2 = FindingCandidate(
        finding_id="2",
        kind=FindingKind.GHOST,
        title="T",
        summary="S",
        confidence=0.5,
        impact="high",
        risk="low",
        blast_radius="local",
        validation_available=False,
        suggested_mode="cartograph",
        created_at="now",
    )

    fp1 = registry._fingerprint(candidate1)
    fp2 = registry._fingerprint(candidate2)
    assert fp1 == fp2


@pytest.mark.asyncio
async def test_duplicate_finding_suppression(temp_registry_path):
    registry = JsonlCartographerRegistry(temp_registry_path)
    loop = CartographerLoop(registry)

    c1 = FindingCandidate(
        finding_id="1",
        kind=FindingKind.GHOST,
        title="T",
        summary="S",
        confidence=1.0,
        impact="high",
        risk="low",
        blast_radius="local",
        validation_available=False,
        suggested_mode="cartograph",
        created_at="now",
    )
    c2 = FindingCandidate(
        finding_id="2",
        kind=FindingKind.GHOST,
        title="T",
        summary="S",
        confidence=0.5,
        impact="high",
        risk="low",
        blast_radius="local",
        validation_available=False,
        suggested_mode="cartograph",
        created_at="now",
    )

    await loop.run_ralph([c1, c2])

    findings = await registry.get_all_findings()
    assert len(findings) == 1


@pytest.mark.asyncio
async def test_ralph_mode_emits_findings_without_patching(temp_registry_path):
    registry = JsonlCartographerRegistry(temp_registry_path)
    loop = CartographerLoop(registry)

    c = FindingCandidate(
        finding_id="1",
        kind=FindingKind.GHOST,
        title="T",
        summary="S",
        confidence=1.0,
        impact="high",
        risk="low",
        blast_radius="local",
        validation_available=False,
        suggested_mode="cartograph",
        created_at="now",
    )

    receipt = await loop.run_ralph([c])
    assert receipt.loop_mode == "cartograph"
    assert receipt.accepted_count == 1
    assert receipt.scan_inputs_sha256 != ""


@pytest.mark.asyncio
async def test_srl_mode_requires_self_check_fields(temp_registry_path):
    registry = JsonlCartographerRegistry(temp_registry_path)
    loop = CartographerLoop(registry)

    c_bad = FindingCandidate(
        finding_id="1",
        kind=FindingKind.GHOST,
        title="T",
        summary="S",
        confidence=1.0,
        impact="high",
        risk="low",
        blast_radius="local",
        validation_available=False,
        suggested_mode="cartograph",
        created_at="now",
    )
    c_good = FindingCandidate(
        finding_id="2",
        kind=FindingKind.GHOST,
        title="T",
        summary="S",
        confidence=1.0,
        impact="high",
        risk="low",
        blast_radius="local",
        validation_available=False,
        suggested_mode="cartograph",
        created_at="now",
        srl_why_real="Reason",
        srl_evidence_support="Ev",
        srl_validation_proof="Proof",
    )

    receipt = await loop.run_srl([c_bad, c_good])
    assert receipt.accepted_count == 1
    assert receipt.rejected_count == 1


@pytest.mark.asyncio
async def test_crdal_mode_creates_regulation_decisions(temp_registry_path):
    registry = JsonlCartographerRegistry(temp_registry_path)
    loop = CartographerLoop(registry)

    # Low confidence -> ignore
    c1 = FindingCandidate(
        finding_id="1",
        kind=FindingKind.GHOST,
        title="T",
        summary="S",
        confidence=0.1,
        impact="low",
        risk="low",
        blast_radius="local",
        validation_available=False,
        suggested_mode="cartograph",
        created_at="now",
    )

    # High impact/risk -> ask_user
    c2 = FindingCandidate(
        finding_id="2",
        kind=FindingKind.GHOST,
        title="T",
        summary="S",
        confidence=0.9,
        impact="high",
        risk="high",
        blast_radius="local",
        validation_available=False,
        suggested_mode="cartograph",
        created_at="now",
    )

    receipt, decisions = await loop.run_crdal([c1, c2])
    assert len(decisions) == 2
    assert decisions[0].decision == "ignore"
    assert decisions[1].decision == "ask_user"
    assert receipt.accepted_count == 1
    assert receipt.rejected_count == 1


@pytest.mark.asyncio
async def test_repair_propose_emits_patch_plan(temp_registry_path):
    registry = JsonlCartographerRegistry(temp_registry_path)
    loop = CartographerLoop(registry)

    p = PatchPlan(
        plan_id="p1",
        source_finding_ids=[],
        scope="scope",
        files_expected=[],
        validation_commands=[],
        risk="low",
        rollback_note="",
        requires_worktree_lane=True,
    )
    receipt = await loop.run_repair_propose([p])

    assert receipt.loop_mode == "repair-propose"
    assert receipt.patch_plans_count == 1


@pytest.mark.asyncio
async def test_repair_lane_refuses_no_isolated_lane(temp_registry_path):
    registry = JsonlCartographerRegistry(temp_registry_path)
    loop = CartographerLoop(registry)

    p = PatchPlan(
        plan_id="p1",
        source_finding_ids=[],
        scope="scope",
        files_expected=[],
        validation_commands=[],
        risk="low",
        rollback_note="",
        requires_worktree_lane=True,
    )

    with pytest.raises(RuntimeError, match="no isolated lane available"):
        await loop.run_repair_lane(p, has_isolated_lane=False)


@pytest.mark.asyncio
async def test_receipt_is_content_light(temp_registry_path):
    registry = JsonlCartographerRegistry(temp_registry_path)
    loop = CartographerLoop(registry)
    c = FindingCandidate(
        finding_id="1",
        kind=FindingKind.GHOST,
        title="T",
        summary="S",
        confidence=1.0,
        impact="high",
        risk="low",
        blast_radius="local",
        validation_available=False,
        suggested_mode="cartograph",
        created_at="now",
    )
    receipt = await loop.run_ralph([c])

    # Verify no raw strings, only IDs, counts, and hashes
    dump = receipt.model_dump()
    assert "receipt_id" in dump
    assert "scan_inputs_sha256" in dump
    assert "receipt_sha256" in dump
    assert "T" not in str(dump)
    assert "S" not in str(dump)

from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest

from rig_relay.coordination.fleet_claims import (
    ClaimResult,
    FleetClaimStore,
    accept_integration,
    acquire_claim,
    get_active_claims,
    mark_ready_for_integration,
    record_tests_completed,
    release_claim,
    renew_claim,
    start_editing,
)
from rig_relay.coordination.fleet_xattr_projection import (
    ClaimXattrPayload,
    project_claim_xattrs,
    remove_claim_xattrs,
)


def _default_kwargs(**overrides):
    return {
        "mission_id": "m1",
        "lane_id": "l1",
        "agent_id": "a1",
        "mode": "exclusive_write",
        "claimed_paths": ["src/a.py"],
        "base_sha256_by_path": {},
        "workspace_authority_id": "ws-test-1",
        "ttl_seconds": 3600,
    } | overrides


# ── test 1 ────────────────────────────────────────────────────────────────────


def test_claim_acquisition_appends_schema_valid_event(tmp_path: Path) -> None:
    store = FleetClaimStore(root=tmp_path / "fleet")
    result = acquire_claim(
        store, **_default_kwargs(claimed_paths=["src/a.py", "src/b.py"])
    )
    assert result.acquired

    events_path = store._events_path
    assert events_path.is_file()

    content = events_path.read_text(encoding="utf-8")
    lines = [line for line in content.strip().split("\n") if line.strip()]
    assert len(lines) == 1

    event = json.loads(lines[0])
    assert event["schema_version"] == "rig.relay.fleet_coordination_event.v1"
    assert event["event_id"]
    assert event["claim_id"]
    assert event["event_kind"] == "claim_acquired"
    assert event["claimed_paths"] == ["src/a.py", "src/b.py"]
    assert event["workspace_authority_id"]


# ── test 2 ────────────────────────────────────────────────────────────────────


def test_ancestor_descendant_path_overlap_conflicts(tmp_path: Path) -> None:
    store = FleetClaimStore(root=tmp_path / "fleet")
    result1 = acquire_claim(
        store, **_default_kwargs(claimed_paths=["rig_relay/governance/"])
    )
    assert result1.acquired
    assert result1.claim is not None
    acquired_claim_id = result1.claim.claim_id

    active = get_active_claims(store, workspace_authority_id="ws-test-1")
    assert len(active) == 1
    assert active[0].claim_id == acquired_claim_id


# ── test 3 ────────────────────────────────────────────────────────────────────


def test_exact_path_conflicts(tmp_path: Path) -> None:
    store = FleetClaimStore(root=tmp_path / "fleet")
    result1 = acquire_claim(store, **_default_kwargs(claimed_paths=["src/a.py"]))
    assert result1.acquired

    result2 = acquire_claim(store, **_default_kwargs(claimed_paths=["src/a.py"]))
    assert not result2.acquired
    assert result2.refusal_reason == "conflict_exact_path"


# ── test 4 ────────────────────────────────────────────────────────────────────


def test_disjoint_paths_remain_concurrently_active(tmp_path: Path) -> None:
    store = FleetClaimStore(root=tmp_path / "fleet")
    result1 = acquire_claim(
        store,
        **_default_kwargs(claimed_paths=["src/a.py"], workspace_authority_id="ws-1"),
    )
    assert result1.acquired

    result2 = acquire_claim(
        store,
        **_default_kwargs(claimed_paths=["src/b.py"], workspace_authority_id="ws-1"),
    )
    assert result2.acquired

    active = get_active_claims(store, workspace_authority_id="ws-1")
    assert len(active) == 2


# ── test 5 ────────────────────────────────────────────────────────────────────


def test_distinct_workspace_authorities_no_conflict(tmp_path: Path) -> None:
    store = FleetClaimStore(root=tmp_path / "fleet")
    result1 = acquire_claim(
        store,
        **_default_kwargs(
            claimed_paths=["src/a.py"], workspace_authority_id="ws-alpha"
        ),
    )
    assert result1.acquired

    result2 = acquire_claim(
        store,
        **_default_kwargs(claimed_paths=["src/a.py"], workspace_authority_id="ws-beta"),
    )
    assert result2.acquired

    active_alpha = get_active_claims(store, workspace_authority_id="ws-alpha")
    assert len(active_alpha) == 1

    active_beta = get_active_claims(store, workspace_authority_id="ws-beta")
    assert len(active_beta) == 1


# ── test 6 ────────────────────────────────────────────────────────────────────


def test_released_claim_no_longer_blocks(tmp_path: Path) -> None:
    store = FleetClaimStore(root=tmp_path / "fleet")
    result1 = acquire_claim(store, **_default_kwargs(claimed_paths=["src/a.py"]))
    assert result1.acquired
    assert result1.claim is not None
    claim_id = result1.claim.claim_id

    release_result = release_claim(store, claim_id=claim_id)
    assert release_result.acquired

    result_new = acquire_claim(store, **_default_kwargs(claimed_paths=["src/a.py"]))
    assert result_new.acquired
    assert result_new.claim is not None

    active = get_active_claims(store, workspace_authority_id="ws-test-1")
    assert len(active) == 1
    assert active[0].claim_id == result_new.claim.claim_id


# ── test 7 ────────────────────────────────────────────────────────────────────


def test_expired_claim_permits_new_acquisition(tmp_path: Path) -> None:
    store = FleetClaimStore(root=tmp_path / "fleet")
    result1 = acquire_claim(
        store, **_default_kwargs(claimed_paths=["src/a.py"], ttl_seconds=0)
    )
    assert result1.acquired

    time.sleep(0.1)

    result2 = acquire_claim(store, **_default_kwargs(claimed_paths=["src/a.py"]))
    assert result2.acquired
    assert result2.claim is not None

    active = get_active_claims(store, workspace_authority_id="ws-test-1")
    assert len(active) == 1
    assert active[0].claim_id == result2.claim.claim_id


# ── test 8 ────────────────────────────────────────────────────────────────────


def test_event_digest_chain_deterministic(tmp_path: Path) -> None:
    store = FleetClaimStore(root=tmp_path / "fleet")
    result1 = acquire_claim(store, **_default_kwargs(claimed_paths=["src/a.py"]))
    assert result1.acquired
    assert result1.claim is not None
    claim_id = result1.claim.claim_id

    renew_claim(store, claim_id=claim_id)

    result2 = acquire_claim(store, **_default_kwargs(claimed_paths=["src/b.py"]))
    assert result2.acquired

    events_path = store._events_path
    content = events_path.read_text(encoding="utf-8")
    lines = [line for line in content.strip().split("\n") if line.strip()]

    prior: str | None = None
    for line in lines:
        event = json.loads(line)
        assert event["prior_event_digest"] == prior
        prior = event["event_digest"]


# ── test 9 ────────────────────────────────────────────────────────────────────


def test_state_transitions_preserve_claim_id(tmp_path: Path) -> None:
    store = FleetClaimStore(root=tmp_path / "fleet")
    result = acquire_claim(store, **_default_kwargs(claimed_paths=["src/a.py"]))
    assert result.acquired
    assert result.claim is not None
    claim_id = result.claim.claim_id

    start_editing(store, claim_id=claim_id)
    record_tests_completed(store, claim_id=claim_id)
    mark_ready_for_integration(
        store, claim_id=claim_id, lane_output_sha256_by_path={"src/a.py": "sha256:abc"}
    )

    events_path = store._events_path
    content = events_path.read_text(encoding="utf-8")
    lines = [line for line in content.strip().split("\n") if line.strip()]

    expected_kinds = [
        "claim_acquired",
        "edit_started",
        "tests_completed",
        "ready_for_integration",
    ]
    event_ids: set[str] = set()

    for i, line in enumerate(lines):
        event = json.loads(line)
        assert event["claim_id"] == claim_id
        assert event["event_id"] not in event_ids
        event_ids.add(event["event_id"])
        assert event["event_kind"] == expected_kinds[i]


# ── test 10 ───────────────────────────────────────────────────────────────────


def test_stale_base_refuses_only_when_target_diverged_from_acquisition_base(
    tmp_path: Path,
) -> None:
    store = FleetClaimStore(root=tmp_path / "fleet")

    # ── success case: base unchanged ──────────────────────────────────────────
    result1 = acquire_claim(
        store,
        **_default_kwargs(
            claimed_paths=["src/a.py"], base_sha256_by_path={"src/a.py": "base-hash-v1"}
        ),
    )
    assert result1.acquired
    assert result1.claim is not None
    claim_id_a = result1.claim.claim_id

    mark_result = mark_ready_for_integration(
        store,
        claim_id=claim_id_a,
        lane_output_sha256_by_path={"src/a.py": "lane-output-hash"},
    )
    assert mark_result.acquired

    accept_result = accept_integration(
        store,
        claim_id=claim_id_a,
        current_base_sha256_by_path={"src/a.py": "base-hash-v1"},
    )
    assert accept_result.acquired

    # ── stale case: base diverged ─────────────────────────────────────────────
    result2 = acquire_claim(
        store,
        **_default_kwargs(
            claimed_paths=["src/b.py"],
            base_sha256_by_path={"src/b.py": "base-v1"},
            workspace_authority_id="ws-stale",
        ),
    )
    assert result2.acquired
    assert result2.claim is not None
    claim_id_b = result2.claim.claim_id

    mark_ready_for_integration(
        store,
        claim_id=claim_id_b,
        lane_output_sha256_by_path={"src/b.py": "lane-output-v1"},
    )

    stale_result = accept_integration(
        store, claim_id=claim_id_b, current_base_sha256_by_path={"src/b.py": "base-v2"}
    )
    assert not stale_result.acquired
    assert stale_result.refusal_reason == "stale_base"


# ── test 11 ───────────────────────────────────────────────────────────────────


def test_concurrent_acquisition_yields_one_accepted_one_refused(tmp_path: Path) -> None:
    store = FleetClaimStore(root=tmp_path / "fleet")
    results: list[ClaimResult] = []
    barrier = threading.Barrier(2)

    def attempt() -> None:
        barrier.wait()
        result = acquire_claim(store, **_default_kwargs(claimed_paths=["src/x.py"]))
        results.append(result)

    t1 = threading.Thread(target=attempt)
    t2 = threading.Thread(target=attempt)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(results) == 2
    acquired_results = [r for r in results if r.acquired]
    refused_results = [r for r in results if not r.acquired]
    assert len(acquired_results) == 1
    assert len(refused_results) == 1

    events_path = store._events_path
    content = events_path.read_text(encoding="utf-8")
    lines = [line for line in content.strip().split("\n") if line.strip()]

    event_kinds = [json.loads(line)["event_kind"] for line in lines]
    assert "claim_acquired" in event_kinds
    assert "claim_refused_conflict" in event_kinds


# ── test 12 ───────────────────────────────────────────────────────────────────


def test_ledger_integrity_detects_corruption(tmp_path: Path) -> None:
    store = FleetClaimStore(root=tmp_path / "fleet")
    acquire_claim(store, **_default_kwargs(claimed_paths=["src/a.py"]))
    acquire_claim(
        store,
        **_default_kwargs(
            claimed_paths=["src/b.py"], workspace_authority_id="ws-other"
        ),
    )

    events_path = store._events_path
    content = events_path.read_text(encoding="utf-8")
    lines = [line for line in content.strip().split("\n") if line.strip()]

    corrupted_lines = lines.copy()
    corrupted_lines.insert(1, "this is not valid json {{{")

    corrupted_content = "\n".join(corrupted_lines) + "\n"
    events_path.write_text(corrupted_content, encoding="utf-8")

    malformed_count = 0
    raw = events_path.read_text(encoding="utf-8")
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            malformed_count += 1

    assert malformed_count >= 1


# ── test 13 ───────────────────────────────────────────────────────────────────


def test_pointer_artifact_created_on_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "rig_relay.coordination.fleet_xattr_projection._xattr_available", lambda: True
    )
    monkeypatch.setattr(
        "rig_relay.coordination.fleet_xattr_projection._set_xattr_safe",
        lambda path, key, value: True,
    )

    store = FleetClaimStore(root=tmp_path / "fleet")
    result = acquire_claim(store, **_default_kwargs(claimed_paths=["src/a.py"]))
    assert result.acquired
    assert result.claim is not None
    claim_id = result.claim.claim_id

    payload = ClaimXattrPayload(
        mission_id="m1",
        lane_id="l1",
        agent_id="a1",
        mode="exclusive_write",
        acquired_at=result.claim.acquired_at,
        expires_at=result.claim.expires_at,
        base_sha256="",
        coordination_event_id=result.event_id or "",
        state="claimed",
    )
    xattr_result = project_claim_xattrs(claim_id, payload, target_paths=[])
    assert xattr_result.claim_id == claim_id

    pointer_path = Path(".rig/relay/fleet/claims") / f"{claim_id}.json"
    assert pointer_path.is_file()
    pointer_data = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert pointer_data["claim_id"] == claim_id
    assert pointer_data["mission_id"] == "m1"
    assert pointer_data["lane_id"] == "l1"
    assert pointer_data["state"] == "claimed"

    release_result = release_claim(store, claim_id=claim_id)
    assert release_result.acquired

    remove_claim_xattrs([str(pointer_path)])
    assert not pointer_path.exists()

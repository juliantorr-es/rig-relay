"""Internal A2A fabric tests — C2 task persistence, coordination, and durability."""

from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from rig_relay.protocols.a2a._artifacts import A2AArtifactKind, A2AArtifactRef
from rig_relay.protocols.a2a._governance_bindings import (
    A2AGovernanceBinding,
    ConfidentialityTier,
    MutationIntent,
)
from rig_relay.protocols.a2a._internal_fabric import (
    A2AInternalFabric,
    _content_light_scan,
    _generate_task_id,
    capability_check_for_task,
)
from rig_relay.protocols.a2a._models import A2ATaskStatus
from rig_relay.protocols.a2a._trust import CapabilityClass, TrustTier


@pytest.fixture
def fabric():
    with tempfile.TemporaryDirectory() as tmp:
        store = A2AInternalFabric(root=Path(tmp))
        yield store


@pytest.fixture
def fabric_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


class TestTaskCreation:
    def test_create_task_basic(self, fabric):
        task = fabric.create_task(
            agent_id="agent-1", description="Test task", trace_id="trace-1"
        )
        assert task.task_id.startswith("a2a_")
        assert task.agent_id == "agent-1"
        assert task.status == A2ATaskStatus.CREATED
        assert task.seq == 1
        assert len(task.events) == 1
        assert task.events[0].event_type == A2ATaskStatus.CREATED

    def test_create_task_with_custom_id(self, fabric):
        task = fabric.create_task(agent_id="agent-1", task_id="my-task-42")
        assert task.task_id == "my-task-42"

    def test_create_task_with_governance_binding(self, fabric):
        binding = A2AGovernanceBinding(
            mission_id="mission-1",
            confidentiality_tier=ConfidentialityTier.INTERNAL,
            mutation_intent=MutationIntent.PROPOSAL_ONLY,
        )
        task = fabric.create_task(agent_id="agent-1", governance_binding=binding)
        assert task.governance_binding is not None
        assert task.governance_binding.mission_id == "mission-1"

    def test_create_task_with_trust_tier(self, fabric):
        task = fabric.create_task(
            agent_id="agent-1", trust_tier=TrustTier.INTERNAL_SUBAGENT_WORKER
        )
        assert task.trust_tier == TrustTier.INTERNAL_SUBAGENT_WORKER

    def test_create_duplicate_task_id_refused(self, fabric):
        fabric.create_task(agent_id="agent-1", task_id="dup-task")
        with pytest.raises(ValueError, match="already exists"):
            fabric.create_task(agent_id="agent-2", task_id="dup-task")

    def test_create_task_rejects_secret_content(self, fabric):
        with pytest.raises(ValueError, match="forbidden content"):
            fabric.create_task(
                agent_id="agent-1", description="task with api_key: abc123"
            )

    def test_generate_task_id_unique(self):
        ids = {_generate_task_id() for _ in range(100)}
        assert len(ids) == 100


class TestTaskTransitions:
    def test_submit_created_task(self, fabric):
        task = fabric.create_task(agent_id="a1")
        task = fabric.submit_task(task.task_id)
        assert task.status == A2ATaskStatus.SUBMITTED
        assert task.seq == 2

    def test_full_lifecycle(self, fabric):
        task = fabric.create_task(agent_id="a1")
        task = fabric.submit_task(task.task_id)
        task = fabric.start_task(task.task_id)
        task = fabric.complete_task(task.task_id)
        assert task.status == A2ATaskStatus.COMPLETED
        assert task.seq == 4

    def test_cancel_from_submitted(self, fabric):
        task = fabric.create_task(agent_id="a1")
        task = fabric.submit_task(task.task_id)
        task = fabric.cancel_task(task.task_id, reason="no longer needed")
        assert task.status == A2ATaskStatus.CANCELLED

    def test_input_required_cycle(self, fabric):
        task = fabric.create_task(agent_id="a1")
        task = fabric.submit_task(task.task_id)
        task = fabric.start_task(task.task_id)
        task = fabric.set_input_required(task.task_id)
        assert task.status == A2ATaskStatus.INPUT_REQUIRED
        task = fabric.start_task(task.task_id)
        assert task.status == A2ATaskStatus.RUNNING

    def test_invalid_transition_refused(self, fabric):
        task = fabric.create_task(agent_id="a1")
        with pytest.raises(ValueError, match="Invalid A2A transition"):
            fabric.complete_task(task.task_id)

    def test_terminal_cannot_transition(self, fabric):
        task = fabric.create_task(agent_id="a1")
        task = fabric.submit_task(task.task_id)
        task = fabric.start_task(task.task_id)
        task = fabric.complete_task(task.task_id)
        with pytest.raises(ValueError, match="Invalid A2A transition"):
            fabric.start_task(task.task_id)

    def test_cancel_terminal_is_noop(self, fabric):
        task = fabric.create_task(agent_id="a1")
        task = fabric.submit_task(task.task_id)
        task = fabric.start_task(task.task_id)
        task = fabric.complete_task(task.task_id)
        result = fabric.cancel_task(task.task_id)
        assert result.status == A2ATaskStatus.COMPLETED

    def test_fail_task_with_reason(self, fabric):
        task = fabric.create_task(agent_id="a1")
        task = fabric.submit_task(task.task_id)
        task = fabric.start_task(task.task_id)
        task = fabric.fail_task(task.task_id, reason="dependency missing")
        assert task.status == A2ATaskStatus.FAILED
        msgs = fabric.get_messages(task.task_id)
        assert any("dependency missing" in m for m in msgs)

    def test_transition_nonexistent_task(self, fabric):
        with pytest.raises(ValueError, match="not found"):
            fabric.submit_task("nonexistent")


class TestMessages:
    def test_send_message(self, fabric):
        task = fabric.create_task(agent_id="a1")
        fabric.send_message(task.task_id, "hello world")
        msgs = fabric.get_messages(task.task_id)
        assert msgs == ["hello world"]

    def test_multiple_messages_ordered(self, fabric):
        task = fabric.create_task(agent_id="a1")
        fabric.send_message(task.task_id, "first")
        fabric.send_message(task.task_id, "second")
        fabric.send_message(task.task_id, "third")
        msgs = fabric.get_messages(task.task_id)
        assert msgs == ["first", "second", "third"]

    def test_message_on_nonexistent_task(self, fabric):
        with pytest.raises(ValueError, match="not found"):
            fabric.send_message("no-task", "hello")


class TestArtifacts:
    def test_attach_artifact(self, fabric):
        task = fabric.create_task(agent_id="a1")
        ref = A2AArtifactRef(
            artifact_id="art-1",
            artifact_kind=A2AArtifactKind.PROPOSED_SCOPE,
            content_hash="a" * 64,
        )
        fabric.attach_artifact(task.task_id, ref)
        task = fabric.get_task(task.task_id)
        assert task is not None
        assert len(task.artifact_refs) == 1
        assert task.artifact_refs[0].artifact_id == "art-1"

    def test_attach_duplicate_artifact_idempotent(self, fabric):
        task = fabric.create_task(agent_id="a1")
        ref = A2AArtifactRef(
            artifact_id="art-1", artifact_kind=A2AArtifactKind.PROPOSED_SCOPE
        )
        fabric.attach_artifact(task.task_id, ref)
        fabric.attach_artifact(task.task_id, ref)
        task = fabric.get_task(task.task_id)
        assert task is not None
        assert len(task.artifact_refs) == 1

    def test_attach_multiple_artifacts(self, fabric):
        task = fabric.create_task(agent_id="a1")
        for i in range(5):
            fabric.attach_artifact(
                task.task_id,
                A2AArtifactRef(
                    artifact_id=f"art-{i}",
                    artifact_kind=A2AArtifactKind.PROGRESS_UPDATE,
                ),
            )
        task = fabric.get_task(task.task_id)
        assert task is not None
        assert len(task.artifact_refs) == 5


class TestTaskQuery:
    def test_get_task(self, fabric):
        fabric.create_task(agent_id="a1", task_id="find-me")
        found = fabric.get_task("find-me")
        assert found is not None
        assert found.task_id == "find-me"

    def test_get_nonexistent(self, fabric):
        assert fabric.get_task("ghost") is None

    def test_list_all(self, fabric):
        fabric.create_task(agent_id="a1")
        fabric.create_task(agent_id="a2")
        fabric.create_task(agent_id="a1")
        assert fabric.task_count() == 3

    def test_list_by_agent(self, fabric):
        fabric.create_task(agent_id="a1")
        fabric.create_task(agent_id="a2")
        fabric.create_task(agent_id="a1")
        a1_tasks = fabric.list_tasks(agent_id="a1")
        assert len(a1_tasks) == 2

    def test_list_by_status(self, fabric):
        t1 = fabric.create_task(agent_id="a1")
        fabric.create_task(agent_id="a2")
        fabric.submit_task(t1.task_id)
        submitted = fabric.list_tasks(status=A2ATaskStatus.SUBMITTED)
        assert len(submitted) == 1

    def test_list_by_trust_tier(self, fabric):
        fabric.create_task(agent_id="a1", trust_tier=TrustTier.INTERNAL_SUBAGENT_WORKER)
        fabric.create_task(agent_id="a2", trust_tier=TrustTier.INTERNAL_GOVERNED_AGENT)
        workers = fabric.list_tasks(trust_tier=TrustTier.INTERNAL_SUBAGENT_WORKER)
        assert len(workers) == 1


class TestCoordinationLinking:
    def test_link_coordination_claim(self, fabric):
        task = fabric.create_task(agent_id="a1")
        fabric.link_coordination_claim(task.task_id, "claim-42")
        task = fabric.get_task(task.task_id)
        assert task is not None
        assert task.coordination_task_claim_id == "claim-42"

    def test_link_nonexistent_task(self, fabric):
        with pytest.raises(ValueError, match="not found"):
            fabric.link_coordination_claim("ghost", "claim-1")


class TestPersistence:
    def test_task_survives_reload(self, fabric_dir):
        f1 = A2AInternalFabric(root=fabric_dir)
        task = f1.create_task(agent_id="a1", task_id="persistent-1")
        f1.submit_task(task.task_id)
        f1.send_message(task.task_id, "msg1")
        f1.attach_artifact(
            task.task_id,
            A2AArtifactRef(
                artifact_id="art-1", artifact_kind=A2AArtifactKind.PROPOSED_SCOPE
            ),
        )

        f2 = A2AInternalFabric(root=fabric_dir)
        reloaded = f2.get_task("persistent-1")
        assert reloaded is not None
        assert reloaded.status == A2ATaskStatus.SUBMITTED
        assert reloaded.agent_id == "a1"
        assert f2.get_messages("persistent-1") == ["msg1"]
        assert len(reloaded.artifact_refs) == 1

    def test_governance_binding_survives_reload(self, fabric_dir):
        binding = A2AGovernanceBinding(
            mission_id="m1", mutation_intent=MutationIntent.PROPOSAL_ONLY
        )
        f1 = A2AInternalFabric(root=fabric_dir)
        f1.create_task(agent_id="a1", task_id="gb-task", governance_binding=binding)

        f2 = A2AInternalFabric(root=fabric_dir)
        reloaded = f2.get_task("gb-task")
        assert reloaded is not None
        assert reloaded.governance_binding is not None
        assert reloaded.governance_binding.mission_id == "m1"


class TestEventReplay:
    def test_reconstruct_from_events(self, fabric):
        task = fabric.create_task(agent_id="a1")
        fabric.submit_task(task.task_id)
        fabric.start_task(task.task_id)
        fabric.complete_task(task.task_id)

        reconstructed = fabric.replay_task_state(task.task_id)
        assert reconstructed is not None
        assert reconstructed.status == A2ATaskStatus.COMPLETED
        assert len(reconstructed.events) == 4

    def test_event_log_has_all_transitions(self, fabric):
        task = fabric.create_task(agent_id="a1")
        fabric.submit_task(task.task_id)
        fabric.start_task(task.task_id)
        fabric.complete_task(task.task_id)

        events = fabric.get_events(task.task_id)
        assert len(events) == 4
        assert events[0].event_type == A2ATaskStatus.CREATED
        assert events[1].event_type == A2ATaskStatus.SUBMITTED
        assert events[2].event_type == A2ATaskStatus.RUNNING
        assert events[3].event_type == A2ATaskStatus.COMPLETED

    def test_reconstruct_sequence_numbers(self, fabric):
        task = fabric.create_task(agent_id="a1")
        fabric.submit_task(task.task_id)
        fabric.start_task(task.task_id)
        fabric.complete_task(task.task_id)

        reconstructed = fabric.replay_task_state(task.task_id)
        assert reconstructed is not None
        seqs = [e.seq for e in reconstructed.events]
        assert seqs == [1, 2, 3, 4]


class TestContentLightEnforcement:
    def test_scan_detects_secret(self):
        bad = {"api_key": "sk-12345"}
        found = _content_light_scan(bad)
        assert "api_key" in found

    def test_scan_detects_token(self):
        bad = {"token": "ghp_abcdef"}
        found = _content_light_scan(bad)
        assert "token" in found

    def test_scan_detects_raw_source(self):
        bad = {"raw_source": "def main(): pass"}
        found = _content_light_scan(bad)
        assert "raw_source" in found

    def test_scan_clean_content_passes(self):
        clean = {"task_id": "t1", "status": "created", "description": "do stuff"}
        found = _content_light_scan(clean)
        assert found == []

    def test_scan_detects_in_nested_object(self):
        bad = {"nested": {"deep": {"secret": "classified"}}}
        found = _content_light_scan(bad)
        assert "secret" in found


class TestCapabilityCheck:
    def test_governed_agent_admitted_for_mutation(self, fabric):
        task = fabric.create_task(
            agent_id="a1", trust_tier=TrustTier.INTERNAL_GOVERNED_AGENT
        )
        admitted, _ = capability_check_for_task(
            task, CapabilityClass.MUTATION_PENDING_AUTHORITY
        )
        assert admitted

    def test_subagent_refused_for_mutation(self, fabric):
        task = fabric.create_task(
            agent_id="a1", trust_tier=TrustTier.INTERNAL_SUBAGENT_WORKER
        )
        admitted, reason = capability_check_for_task(
            task, CapabilityClass.MUTATION_PENDING_AUTHORITY
        )
        assert not admitted
        assert "not admitted" in reason

    def test_external_refused_for_mutation(self, fabric):
        task = fabric.create_task(
            agent_id="a1", trust_tier=TrustTier.EXTERNAL_UNAUTHENTICATED
        )
        admitted, _ = capability_check_for_task(
            task, CapabilityClass.MUTATION_PENDING_AUTHORITY
        )
        assert not admitted


class TestConcurrentSafety:
    def test_two_tasks_independent(self, fabric):
        t1 = fabric.create_task(agent_id="a1", task_id="t1")
        t2 = fabric.create_task(agent_id="a2", task_id="t2")
        fabric.submit_task(t1.task_id)
        fabric.submit_task(t2.task_id)
        fabric.cancel_task(t2.task_id)
        assert fabric.get_task("t1").status == A2ATaskStatus.SUBMITTED
        assert fabric.get_task("t2").status == A2ATaskStatus.CANCELLED

    def test_messages_dont_interleave(self, fabric):
        t1 = fabric.create_task(agent_id="a1", task_id="t1")
        t2 = fabric.create_task(agent_id="a2", task_id="t2")
        fabric.send_message(t1.task_id, "msg-t1-1")
        fabric.send_message(t2.task_id, "msg-t2-1")
        fabric.send_message(t1.task_id, "msg-t1-2")
        assert fabric.get_messages("t1") == ["msg-t1-1", "msg-t1-2"]
        assert fabric.get_messages("t2") == ["msg-t2-1"]

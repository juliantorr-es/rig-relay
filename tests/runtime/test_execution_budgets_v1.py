from __future__ import annotations

from pydantic import ValidationError
import pytest

from rig_relay.runtime.execution_budgets import (
    AGENT_LOOP_MAX_TOTAL_RUNTIME_SECONDS,
    BASH_MAX_OUTPUT_BYTES,
    BASH_MAX_STDERR_BYTES,
    BASH_MAX_STDOUT_BYTES,
    CONTEXT_MAX_FILES_READ,
    CONTEXT_MAX_PACKET_BYTES,
    NETWORK_DISABLED_BY_DEFAULT,
    RECEIPT_MAX_PAYLOAD_BYTES,
    SUBAGENT_MAX_RUNTIME_SECONDS,
    TOOL_MAX_RUNTIME_SECONDS,
    AgentExecutionBudgets,
)

_ALL_POSITIVE_INT_BUDGETS: list[tuple[str, int]] = [
    ("AGENT_LOOP_MAX_TOTAL_RUNTIME_SECONDS", AGENT_LOOP_MAX_TOTAL_RUNTIME_SECONDS),
    ("SUBAGENT_MAX_RUNTIME_SECONDS", SUBAGENT_MAX_RUNTIME_SECONDS),
    ("TOOL_MAX_RUNTIME_SECONDS", TOOL_MAX_RUNTIME_SECONDS),
    ("BASH_MAX_STDOUT_BYTES", BASH_MAX_STDOUT_BYTES),
    ("BASH_MAX_STDERR_BYTES", BASH_MAX_STDERR_BYTES),
    ("CONTEXT_MAX_PACKET_BYTES", CONTEXT_MAX_PACKET_BYTES),
    ("RECEIPT_MAX_PAYLOAD_BYTES", RECEIPT_MAX_PAYLOAD_BYTES),
    ("CONTEXT_MAX_FILES_READ", CONTEXT_MAX_FILES_READ),
    ("BASH_MAX_OUTPUT_BYTES", BASH_MAX_OUTPUT_BYTES),
]


class TestBudgetConstantsArePositive:
    @pytest.mark.parametrize("name,value", _ALL_POSITIVE_INT_BUDGETS)
    def test_constant_is_positive(self, name: str, value: int) -> None:
        assert value > 0, f"{name} = {value}, expected > 0"


class TestAgentExecutionBudgetsModel:
    def test_default_instantiation(self):
        budgets = AgentExecutionBudgets()
        assert budgets.agent_loop_max_total_runtime_seconds == 1800
        assert budgets.subagent_max_runtime_seconds == 300
        assert budgets.tool_max_runtime_seconds == 120
        assert budgets.bash_max_stdout_bytes == 65536
        assert budgets.bash_max_stderr_bytes == 65536
        assert budgets.context_max_packet_bytes == 5_000_000
        assert budgets.receipt_max_payload_bytes == 1_048_576
        assert budgets.context_max_files_read == 100
        assert budgets.bash_max_output_bytes == 65536
        assert budgets.network_disabled_by_default is True

    def test_defaults_match_module_constants(self):
        budgets = AgentExecutionBudgets()
        assert (
            budgets.agent_loop_max_total_runtime_seconds
            == AGENT_LOOP_MAX_TOTAL_RUNTIME_SECONDS
        )
        assert budgets.subagent_max_runtime_seconds == SUBAGENT_MAX_RUNTIME_SECONDS
        assert budgets.tool_max_runtime_seconds == TOOL_MAX_RUNTIME_SECONDS
        assert budgets.bash_max_stdout_bytes == BASH_MAX_STDOUT_BYTES
        assert budgets.bash_max_stderr_bytes == BASH_MAX_STDERR_BYTES
        assert budgets.context_max_packet_bytes == CONTEXT_MAX_PACKET_BYTES
        assert budgets.receipt_max_payload_bytes == RECEIPT_MAX_PAYLOAD_BYTES
        assert budgets.context_max_files_read == CONTEXT_MAX_FILES_READ
        assert budgets.bash_max_output_bytes == BASH_MAX_OUTPUT_BYTES
        assert budgets.network_disabled_by_default == NETWORK_DISABLED_BY_DEFAULT

    def test_custom_values_valid(self):
        budgets = AgentExecutionBudgets(
            agent_loop_max_total_runtime_seconds=3600,
            tool_max_runtime_seconds=60,
            network_disabled_by_default=False,
        )
        assert budgets.agent_loop_max_total_runtime_seconds == 3600
        assert budgets.tool_max_runtime_seconds == 60
        assert budgets.network_disabled_by_default is False

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            AgentExecutionBudgets(extra_field=123)  # pyright: ignore[reportCallIssue]

    def test_rejects_zero_runtime(self):
        with pytest.raises(ValidationError):
            AgentExecutionBudgets(agent_loop_max_total_runtime_seconds=0)

    def test_rejects_negative_runtime(self):
        with pytest.raises(ValidationError):
            AgentExecutionBudgets(agent_loop_max_total_runtime_seconds=-1)

    def test_rejects_runtime_above_86400(self):
        with pytest.raises(ValidationError):
            AgentExecutionBudgets(agent_loop_max_total_runtime_seconds=86401)

    def test_accepts_runtime_at_86400_boundary(self):
        budgets = AgentExecutionBudgets(agent_loop_max_total_runtime_seconds=86400)
        assert budgets.agent_loop_max_total_runtime_seconds == 86400

    def test_rejects_zero_bytes(self):
        with pytest.raises(ValidationError):
            AgentExecutionBudgets(bash_max_stdout_bytes=0)

    def test_serializes_to_json(self):
        budgets = AgentExecutionBudgets()
        data = budgets.model_dump(mode="json")
        assert data["agent_loop_max_total_runtime_seconds"] == 1800
        assert data["network_disabled_by_default"] is True

    def test_deserializes_from_dict(self):
        data = {
            "agent_loop_max_total_runtime_seconds": 900,
            "subagent_max_runtime_seconds": 150,
            "tool_max_runtime_seconds": 60,
            "bash_max_stdout_bytes": 32768,
            "bash_max_stderr_bytes": 32768,
            "context_max_packet_bytes": 2500000,
            "receipt_max_payload_bytes": 524288,
            "context_max_files_read": 50,
            "bash_max_output_bytes": 32768,
            "network_disabled_by_default": False,
        }
        budgets = AgentExecutionBudgets.model_validate(data)
        assert budgets.agent_loop_max_total_runtime_seconds == 900
        assert budgets.network_disabled_by_default is False

    def test_round_trip_through_json(self):
        original = AgentExecutionBudgets(
            agent_loop_max_total_runtime_seconds=3600, subagent_max_runtime_seconds=600
        )
        raw = original.model_dump(mode="json")
        restored = AgentExecutionBudgets.model_validate(raw)
        assert restored == original


class TestNetworkDisabledByDefault:
    def test_network_disabled_by_default_is_true(self):
        assert NETWORK_DISABLED_BY_DEFAULT is True

    def test_model_default_network_disabled(self):
        budgets = AgentExecutionBudgets()
        assert budgets.network_disabled_by_default is True

    def test_network_can_be_enabled_in_model(self):
        budgets = AgentExecutionBudgets(network_disabled_by_default=False)
        assert budgets.network_disabled_by_default is False

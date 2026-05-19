from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import time

from rig_relay.protocols._transport_budgets import BudgetTracker
from rig_relay.protocols.a2a._lifecycle import (
    build_agent_card,
    build_task_card,
    cancel_task,
    transition_task,
)
from rig_relay.protocols.a2a._models import (
    A2AAgentCard,
    A2ADelegationReceipt,
    A2ATaskCard,
    A2ATaskStatus,
)


async def serve_agent_card(agent_name: str, trace_id: str = "") -> A2AAgentCard:
    return build_agent_card(agent_id=agent_name, name=agent_name)


async def serve_agent_card_json(agent_name: str, trace_id: str = "") -> dict:
    card = await serve_agent_card(agent_name, trace_id)
    return {
        "agent_card": {
            "agent_id": card.agent_id,
            "agent_name": card.name,
            "capabilities": card.capabilities,
            "local_only": card.local_only,
            "remote_federation_supported": card.remote_federation_supported,
            "content_light": card.content_light,
            "schema_version": card.schema_version,
            "trace_id": trace_id,
            "generated_at": card.generated_at,
        }
    }


@dataclass
class A2AServerState:
    agent_card: A2AAgentCard
    tasks: dict[str, A2ATaskCard] = field(default_factory=dict)
    delegations: dict[str, A2ADelegationReceipt] = field(default_factory=dict)

    def add_task(self, card: A2ATaskCard) -> None:
        self.tasks[card.task_id] = card

    def get_task(self, task_id: str) -> A2ATaskCard | None:
        return self.tasks.get(task_id)


class A2AServer:
    def __init__(
        self,
        agent_id: str = "rig-relay-a2a",
        name: str = "Rig Relay A2A Agent",
        description: str = "",
        capabilities: list[str] | None = None,
        supported_task_types: list[str] | None = None,
    ) -> None:
        self._budgets = BudgetTracker()
        self._budgets.connection_start = time.monotonic()
        self._state = A2AServerState(
            agent_card=build_agent_card(
                agent_id=agent_id,
                name=name,
                description=description,
                capabilities=capabilities,
                supported_task_types=supported_task_types,
            )
        )

    @property
    def budget_tracker(self) -> BudgetTracker:
        return self._budgets

    @property
    def agent_card(self) -> A2AAgentCard:
        return self._state.agent_card

    def handle_jsonrpc_request(self, raw_request: str) -> str:
        if not self._budgets.can_accept_request(len(raw_request.encode("utf-8"))):
            return json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32000,
                    "message": "Rate limited: request budget exceeded",
                },
            })

        self._budgets.track_request()
        try:
            try:
                request = json.loads(raw_request)
            except json.JSONDecodeError:
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                })

            method = request.get("method")
            req_id = request.get("id")

            if method == "agent/card":
                card = self._state.agent_card
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "agent_id": card.agent_id,
                        "name": card.name,
                        "description": card.description,
                        "capabilities": card.capabilities,
                        "supported_task_types": card.supported_task_types,
                        "local_only": card.local_only,
                        "remote_federation_supported": card.remote_federation_supported,
                        "content_light": card.content_light,
                    },
                })

            if method == "tasks/send":
                params = request.get("params", {})
                task_id = (
                    params.get("task_id")
                    or f"task_{hashlib.sha256(str(time.monotonic()).encode()).hexdigest()[:12]}"
                )
                card = build_task_card(
                    task_id=task_id,
                    agent_id=self.agent_card.agent_id,
                    description=params.get("description", ""),
                    trace_id=params.get("trace_id", ""),
                )
                submitted = transition_task(card, A2ATaskStatus.SUBMITTED)
                self._state.add_task(submitted)
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "task_id": submitted.task_id,
                        "status": submitted.status.value,
                        "trace_id": submitted.trace_id,
                    },
                })

            if method == "tasks/cancel":
                params = request.get("params", {})
                task_id = params.get("task_id", "")
                task = self._state.get_task(task_id)
                if isinstance(task, A2ATaskCard):
                    cancelled = cancel_task(task)
                    self._state.tasks[task_id] = cancelled
                    return json.dumps({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "task_id": task_id,
                            "status": cancelled.status.value,
                        },
                    })
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"task_id": task_id, "status": "not_found"},
                })

            if method == "tasks/list":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tasks": [
                            {
                                "task_id": t.task_id,
                                "status": t.status.value,
                                "agent_id": t.agent_id,
                            }
                            for t in self._state.tasks.values()
                        ]
                    },
                })

            return json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })
        finally:
            self._budgets.release_request()


__all__ = ["A2AServer", "A2AServerState", "serve_agent_card", "serve_agent_card_json"]

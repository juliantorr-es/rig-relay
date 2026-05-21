from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import Any, cast

from jsonpatch import JsonPatch, JsonPatchException  # type: ignore[import-untyped]
from pydantic import ValidationError

from rig_relay.core.nuage.agent_models import AgentCompletionState
from rig_relay.core.nuage.events import (
    CustomTaskCanceled,
    CustomTaskCompleted,
    CustomTaskFailed,
    CustomTaskInProgress,
    CustomTaskStarted,
    CustomTaskTimedOut,
    JSONPatchAppend,
    JSONPatchPayload,
    JSONPatchReplace,
    JSONPayload,
    WorkflowEvent,
    WorkflowExecutionCanceled,
    WorkflowExecutionCompleted,
    WorkflowExecutionFailed,
)
from rig_relay.core.nuage.remote_workflow_event_models import (
    AssistantMessageState,
    BaseUIState,
    PendingInputRequest,
    RemoteToolArgs,
    RemoteToolResult,
    WaitForInputPayload,
    WorkingState,
    parse_tool_ui_state,
)
from rig_relay.core.nuage.workflow import WorkflowExecutionStatus
from rig_relay.core.tools.base import BaseTool, BaseToolConfig, BaseToolState, ToolError
from rig_relay.core.tools.ui import ToolUIData
from rig_relay.core.types import (
    AgentStats,
    AssistantEvent,
    BaseEvent,
    LLMMessage,
    ReasoningEvent,
    Role,
    ToolResultEvent,
    ToolStreamEvent,
    UserMessageEvent,
    WaitingForInputEvent,
)

_WAIT_FOR_INPUT_TASK_TYPE = "wait_for_input"
_STEER_INPUT_LABEL = "Send a message to steer..."
# These names must match the remote workflow's tool naming convention
_ASK_USER_QUESTION_TOOL = "ask_user_question"
_SEND_USER_MESSAGE_TOOL = "send_user_message"


def _get_value_at_path(path: str, obj: Any) -> Any:
    if not path or path == "/":
        return obj
    parts = path.split("/")[1:]
    current = obj
    for part in parts:
        if current is None:
            return None
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _set_value_at_path(path: str, obj: Any, value: Any) -> None:
    if not path or path == "/":
        return
    parts = path.split("/")[1:]
    current = obj
    for part in parts[:-1]:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return
        else:
            return
    last = parts[-1]
    if isinstance(current, dict):
        current[last] = value
    elif isinstance(current, list):
        try:
            current[int(last)] = value
        except (ValueError, IndexError):
            pass


class _RemoteTool(
    BaseTool[RemoteToolArgs, RemoteToolResult, BaseToolConfig, BaseToolState],
    ToolUIData[RemoteToolArgs, RemoteToolResult],
):
    remote_name = "remote_tool"

    @classmethod
    def get_name(cls) -> str:
        return cls.remote_name

    @classmethod
    def get_status_text(cls) -> str:
        return f"Running {cls.remote_name}"

    @classmethod
    def format_call_display(cls, args: RemoteToolArgs) -> Any:
        from rig_relay.core.tools.ui import ToolCallDisplay

        return ToolCallDisplay(summary=args.summary or cls.remote_name)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> Any:
        from rig_relay.core.tools.ui import ToolResultDisplay

        if event.error:
            return ToolResultDisplay(success=False, message=event.error)
        if isinstance(event.result, RemoteToolResult):
            return ToolResultDisplay(
                success=True, message=event.result.message or cls.remote_name
            )
        return ToolResultDisplay(success=True, message=cls.remote_name)

    async def run(
        self, args: RemoteToolArgs, ctx: Any = None
    ) -> AsyncGenerator[ToolStreamEvent | RemoteToolResult, None]:
        raise ToolError("Remote workflow tools cannot be invoked locally")
        yield  # type: ignore[misc]


_REMOTE_TOOL_CACHE: dict[str, type[_RemoteTool]] = {}


def _remote_tool_class(tool_name: str) -> type[_RemoteTool]:
    cached = _REMOTE_TOOL_CACHE.get(tool_name)
    if cached is not None:
        return cached

    class_name = "".join(
        char if char.isalnum() or char == "_" else "_"
        for char in f"RemoteTool_{tool_name.replace('-', '_')}"
    )
    tool_class = type(
        class_name, (_RemoteTool,), {"remote_name": tool_name, "__module__": __name__}
    )
    _REMOTE_TOOL_CACHE[tool_name] = tool_class
    return tool_class


class RemoteWorkflowEventTranslator:
    def __init__(
        self,
        *,
        available_tools: dict[str, type[BaseTool]],
        stats: AgentStats,
        merge_message: Callable[[LLMMessage], None],
    ) -> None:
        self._available_tools = available_tools
        self._stats = stats
        self._merge_message = merge_message
        self._task_state: dict[str, dict[str, Any]] = {}
        self._completion_message_ids: dict[str, str] = {}
        self._seen_tool_call_ids: set[str] = set()
        self._seen_tool_results: set[str] = set()
        self._open_tool_calls: dict[str, str] = {}
        self._input_snapshots: dict[str, str] = {}
        self._tool_stream_snapshots: dict[str, str] = {}
        self._pending_tool_progress: dict[str, tuple[str, str]] = {}
        self._pending_input_request: PendingInputRequest | None = None
        self._pending_question_prompt: str | None = None
        self._pending_ask_user_question_call_id: str | None = None
        self._steer_task_ids: set[str] = set()
        self._invalid_steer_task_ids: set[str] = set()
        self._last_status: WorkflowExecutionStatus | None = None

    @property
    def pending_input_request(self) -> PendingInputRequest | None:
        return self._pending_input_request

    @pending_input_request.setter
    def pending_input_request(self, value: PendingInputRequest | None) -> None:
        self._pending_input_request = value

    @property
    def last_status(self) -> WorkflowExecutionStatus | None:
        return self._last_status

    @property
    def task_state(self) -> dict[str, dict[str, Any]]:
        return self._task_state

    def consume_workflow_event(self, event: WorkflowEvent) -> list[BaseEvent]:
        if self._consume_workflow_lifecycle_event(event):
            return []

        wait_for_input_events = self._consume_wait_for_input_event(event)
        if wait_for_input_events is not None:
            return wait_for_input_events

        if not isinstance(
            event,
            (
                CustomTaskStarted,
                CustomTaskInProgress,
                CustomTaskCompleted,
                CustomTaskFailed,
                CustomTaskTimedOut,
                CustomTaskCanceled,
            ),
        ):
            return []

        return self._consume_agent_task_event(event)

    def is_idle_boundary(self, event: WorkflowEvent) -> bool:
        if isinstance(
            event,
            (
                WorkflowExecutionCompleted,
                WorkflowExecutionFailed,
                WorkflowExecutionCanceled,
            ),
        ):
            return True

        if isinstance(event, CustomTaskStarted):
            return event.attributes.custom_task_type == _WAIT_FOR_INPUT_TASK_TYPE

        if not isinstance(event, (CustomTaskInProgress, CustomTaskCompleted)):
            return False

        if event.attributes.custom_task_type != "AgentInputState":
            return False

        if self._open_tool_calls:
            return False

        state = self._task_state.get(event.attributes.custom_task_id, {})
        return state.get("input") is None

    def flush_open_tool_calls(self) -> list[BaseEvent]:
        events: list[BaseEvent] = []
        for tool_call_id, tool_name in list(self._open_tool_calls.items()):
            tool_class = self._resolve_tool_class(tool_name)
            events.append(
                ToolResultEvent(
                    tool_name=tool_name,
                    tool_class=tool_class,
                    tool_call_id=tool_call_id,
                )
            )
        self._open_tool_calls.clear()
        return events

    def _consume_workflow_lifecycle_event(self, event: WorkflowEvent) -> bool:
        if isinstance(event, WorkflowExecutionCompleted):
            self._last_status = WorkflowExecutionStatus.COMPLETED
            self._pending_input_request = None
            return True

        if isinstance(event, WorkflowExecutionCanceled):
            self._last_status = WorkflowExecutionStatus.CANCELED
            self._pending_input_request = None
            return True

        if isinstance(event, WorkflowExecutionFailed):
            self._last_status = WorkflowExecutionStatus.FAILED
            self._pending_input_request = None
            return True

        return False

    def _consume_wait_for_input_event(
        self, event: WorkflowEvent
    ) -> list[BaseEvent] | None:
        if isinstance(event, CustomTaskStarted):
            return self._wait_for_input_started_events(event)

        if not isinstance(
            event,
            (
                CustomTaskCompleted,
                CustomTaskCanceled,
                CustomTaskFailed,
                CustomTaskTimedOut,
            ),
        ):
            return None
        return self._wait_for_input_terminal_events(event)

    def _consume_agent_task_event(
        self,
        event: (
            CustomTaskStarted
            | CustomTaskInProgress
            | CustomTaskCompleted
            | CustomTaskFailed
            | CustomTaskTimedOut
            | CustomTaskCanceled
        ),
    ) -> list[BaseEvent]:
        task_type = event.attributes.custom_task_type
        if task_type not in {
            "AgentCompletionState",
            "AgentToolCallState",
            "AgentStepState",
            "AgentInputState",
            "assistant_message",
            "working",
        }:
            return []

        if isinstance(
            event, (CustomTaskFailed, CustomTaskTimedOut, CustomTaskCanceled)
        ):
            return self._agent_task_terminal_events(event)

        previous_state, state = self._get_current_state(event)
        task_id = event.attributes.custom_task_id
        events: list[BaseEvent] = []

        match task_type:
            case "AgentCompletionState":
                events = self._completion_events(task_id, previous_state, state)
            case "assistant_message":
                events = self._assistant_message_events(task_id, previous_state, state)
            case "working":
                events = self._working_events(task_id, previous_state, state, event)
            case "AgentToolCallState":
                events = self._tool_events(task_id, state, event)
            case "AgentInputState":
                self._input_events(task_id, state)
        return events

    def _wait_for_input_started_events(
        self, event: CustomTaskStarted
    ) -> list[BaseEvent] | None:
        if event.attributes.custom_task_type != _WAIT_FOR_INPUT_TASK_TYPE:
            return None

        payload_value = event.attributes.payload.value
        label = self._wait_for_input_label(payload_value)

        if label == _STEER_INPUT_LABEL:
            return self._steer_wait_for_input_started(event, payload_value)

        if isinstance(payload_value, dict):
            self._set_pending_input_request(
                event.attributes.custom_task_id, payload_value
            )

        events: list[BaseEvent] = []
        if label:
            events.extend(self._assistant_question_events(label))

        events.append(
            WaitingForInputEvent(
                task_id=event.attributes.custom_task_id,
                label=label,
                predefined_answers=self._extract_predefined_answers(payload_value),
            )
        )
        return events

    def _steer_wait_for_input_started(
        self, event: CustomTaskStarted, payload_value: Any
    ) -> list[BaseEvent]:
        task_id = event.attributes.custom_task_id
        self._steer_task_ids.add(task_id)
        if self._pending_input_request is None and isinstance(payload_value, dict):
            try:
                self._set_pending_input_request(task_id, payload_value)
            except ValidationError:
                self._invalid_steer_task_ids.add(task_id)
                raise
        return []

    def _steer_wait_for_input_terminal(
        self,
        event: CustomTaskCompleted
        | CustomTaskCanceled
        | CustomTaskFailed
        | CustomTaskTimedOut,
        payload_value: Any,
    ) -> list[BaseEvent]:
        task_id = event.attributes.custom_task_id
        self._steer_task_ids.discard(task_id)
        invalid_steer_task = task_id in self._invalid_steer_task_ids
        self._invalid_steer_task_ids.discard(task_id)
        if (
            self._pending_input_request is not None
            and self._pending_input_request.task_id == task_id
        ):
            self._pending_input_request = None
        if isinstance(event, CustomTaskCompleted) and not invalid_steer_task:
            return self._completed_wait_for_input_events(payload_value)
        return []

    def _set_pending_input_request(
        self, task_id: str, payload_value: dict[str, Any]
    ) -> None:
        self._pending_input_request = PendingInputRequest.model_validate({
            "task_id": task_id,
            **payload_value,
        })

    def _wait_for_input_label(self, payload_value: Any) -> str | None:
        if not isinstance(payload_value, dict):
            return None
        label = payload_value.get("label")
        return label if isinstance(label, str) else None

    def _is_steer_wait_for_input(self, task_id: str, payload_value: Any) -> bool:
        if task_id in self._steer_task_ids:
            return True
        return self._wait_for_input_label(payload_value) == _STEER_INPUT_LABEL

    def _wait_for_input_terminal_events(
        self,
        event: CustomTaskCompleted
        | CustomTaskCanceled
        | CustomTaskFailed
        | CustomTaskTimedOut,
    ) -> list[BaseEvent] | None:
        if event.attributes.custom_task_type != _WAIT_FOR_INPUT_TASK_TYPE:
            return None

        payload_value = (
            event.attributes.payload.value
            if isinstance(event, CustomTaskCompleted)
            else None
        )
        if self._is_steer_wait_for_input(
            event.attributes.custom_task_id, payload_value
        ):
            return self._steer_wait_for_input_terminal(event, payload_value)

        self._pending_input_request = None
        self._pending_question_prompt = None
        ask_user_question_call_id = self._pending_ask_user_question_call_id
        self._pending_ask_user_question_call_id = None

        if not isinstance(event, CustomTaskCompleted):
            if ask_user_question_call_id:
                return self._emit_tool_result_events(
                    tool_name=_ASK_USER_QUESTION_TOOL,
                    tool_call_id=ask_user_question_call_id,
                    output=None,
                    error="Cancelled",
                )
            return []
        events = self._completed_wait_for_input_events(
            event.attributes.payload.value, ask_user_question_call_id
        )
        return events

    def _completed_wait_for_input_events(
        self, payload_value: Any, ask_user_question_call_id: str | None = None
    ) -> list[BaseEvent]:
        if not isinstance(payload_value, dict):
            return []
        payload = WaitForInputPayload.model_validate(payload_value)
        if payload.input is None:
            return []

        textual_input = self._extract_user_text(payload.input.message)
        if not textual_input:
            return []

        events: list[BaseEvent] = []
        if ask_user_question_call_id:
            events.extend(
                self._emit_tool_result_events(
                    tool_name=_ASK_USER_QUESTION_TOOL,
                    tool_call_id=ask_user_question_call_id,
                    output={"answer": textual_input},
                    error=None,
                )
            )

        user_message = LLMMessage(role=Role.user, content=textual_input)
        self._merge_message(user_message)
        if user_message.message_id is None:
            return events

        events.append(
            UserMessageEvent(content=textual_input, message_id=user_message.message_id)
        )
        return events

    def _get_current_state(
        self, event: CustomTaskStarted | CustomTaskInProgress | CustomTaskCompleted
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        task_id = event.attributes.custom_task_id
        previous_state = self._task_state.get(task_id, {})
        if isinstance(event.attributes.payload, JSONPayload):
            new_state = self._normalize_state(event.attributes.payload.value)
        else:
            new_state = self._apply_json_patch(
                previous_state, cast(JSONPatchPayload, event.attributes.payload)
            )
        self._task_state[task_id] = new_state
        return previous_state, new_state

    def _agent_task_terminal_events(
        self, event: CustomTaskFailed | CustomTaskTimedOut | CustomTaskCanceled
    ) -> list[BaseEvent]:
        if event.attributes.custom_task_type != "AgentToolCallState":
            return []

        task_id = event.attributes.custom_task_id
        state = self._task_state.get(task_id, {})
        return self._tool_terminal_events(task_id, state, event)

    def _normalize_state(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        return {}

    def _apply_json_patch(
        self, previous_state: dict[str, Any], payload: JSONPatchPayload
    ) -> dict[str, Any]:
        new_state = cast(dict[str, Any], self._json_safe_value(previous_state))

        for patch in payload.value:
            if isinstance(patch, JSONPatchAppend):
                current = _get_value_at_path(patch.path, new_state)
                _set_value_at_path(
                    patch.path, new_state, f"{current or ''}{patch.value}"
                )
            elif isinstance(patch, JSONPatchReplace) and not patch.path.strip("/"):
                new_state = self._normalize_state(patch.value)
            else:
                try:
                    new_state = JsonPatch([
                        {"op": patch.op, "path": patch.path, "value": patch.value}
                    ]).apply(new_state)
                except JsonPatchException:
                    pass

        return new_state

    def _completion_events(
        self, task_id: str, previous_state: dict[str, Any], state: dict[str, Any]
    ) -> list[BaseEvent]:
        completion_state = AgentCompletionState.model_validate(state)
        previous_completion_state = AgentCompletionState.model_validate(previous_state)
        current_content = completion_state.content
        current_reasoning = completion_state.reasoning_content
        previous_content = previous_completion_state.content
        previous_reasoning = previous_completion_state.reasoning_content

        if not (
            (not current_content or current_content.startswith(previous_content))
            and (
                not current_reasoning
                or current_reasoning.startswith(previous_reasoning)
            )
        ):
            previous_content = ""
            previous_reasoning = ""
            self._completion_message_ids.pop(task_id, None)

        content_delta = current_content[len(previous_content) :]
        reasoning_delta = current_reasoning[len(previous_reasoning) :]
        if not content_delta and not reasoning_delta:
            return []

        message_id = self._completion_message_ids.setdefault(
            task_id, LLMMessage(role=Role.assistant).message_id or task_id
        )

        self._merge_message(
            LLMMessage(
                role=Role.assistant,
                content=content_delta or None,
                reasoning_content=reasoning_delta or None,
                message_id=message_id,
            )
        )

        events: list[BaseEvent] = []
        if reasoning_delta:
            events.append(
                ReasoningEvent(content=reasoning_delta, message_id=message_id)
            )
        if content_delta:
            events.append(AssistantEvent(content=content_delta, message_id=message_id))
        return events

    def _assistant_message_events(
        self, task_id: str, previous_state: dict[str, Any], state: dict[str, Any]
    ) -> list[BaseEvent]:
        current_text = self._extract_content_chunks_text(state)
        previous_text = self._extract_content_chunks_text(previous_state)

        if not (not current_text or current_text.startswith(previous_text)):
            previous_text = ""
            self._completion_message_ids.pop(task_id, None)

        delta = current_text[len(previous_text) :]
        if not delta:
            return []

        message_id = self._completion_message_ids.setdefault(
            task_id, LLMMessage(role=Role.assistant).message_id or task_id
        )
        self._merge_message(
            LLMMessage(role=Role.assistant, content=delta, message_id=message_id)
        )
        return [AssistantEvent(content=delta, message_id=message_id)]

    def _extract_content_chunks_text(self, state: dict[str, Any]) -> str:
        msg = AssistantMessageState.model_validate(state)
        return "".join(
            chunk.text for chunk in msg.contentChunks if chunk.type == "text"
        )

    def _working_events(
        self,
        task_id: str,
        previous_state: dict[str, Any],
        state: dict[str, Any],
        event: CustomTaskStarted | CustomTaskInProgress | CustomTaskCompleted,
    ) -> list[BaseEvent]:
        working = WorkingState.model_validate(state)
        previous_working = WorkingState.model_validate(previous_state)
        parsed_ui_state = (
            parse_tool_ui_state(working.toolUIState) if working.toolUIState else None
        )
        base_ui_state = (
            BaseUIState.model_validate(working.toolUIState)
            if working.toolUIState
            else None
        )
        tool_call_id = base_ui_state.toolCallId if base_ui_state else None

        if not tool_call_id:
            return self._working_events_without_tool_call(
                task_id, working, previous_working, parsed_ui_state, event
            )

        return self._working_events_with_tool_call(
            task_id, working, parsed_ui_state, tool_call_id, event
        )

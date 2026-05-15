"""Remote workflow event translator mixin — input events."""
from __future__ import annotations

from typing import Any



import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from rig_relay.core.logger import logger
from rig_relay.core.nuage.remote_workflow_event_models import (
    WaitForInputPayload,
    PredefinedAnswersState,
)
from rig_relay.core.types import (
    AssistantEvent,
    BaseEvent,
    LLMMessage,
    Role,
    UserMessageEvent,
    WaitingForInputEvent,
)



class InputEventsMixin:
    """Mixin providing input events methods for RemoteWorkflowEventTranslator."""

    def _input_events(self, task_id: str, state: dict[str, Any]) -> None:
        parsed = WaitForInputPayload.model_validate(state)
        if parsed.input is None:
            return

        textual_input = self._extract_user_text(parsed.input.message)
        if not textual_input:
            return

        if self._input_snapshots.get(task_id) == textual_input:
            return

        self._input_snapshots[task_id] = textual_input
        self._pending_question_prompt = None
        self._merge_message(LLMMessage(role=Role.user, content=textual_input))


    def _extract_user_text(self, value: Any) -> str | None:
        if isinstance(value, str):
            return value
        if not isinstance(value, list):
            return None

        parts: list[str] = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])

        if not parts:
            return None
        return "".join(parts)


    def _extract_predefined_answers(self, value: Any) -> list[str] | None:
        if not isinstance(value, dict):
            return None
        parsed = PredefinedAnswersState.model_validate(value)
        if parsed.input_schema is None or parsed.input_schema.properties is None:
            return None
        message = parsed.input_schema.properties.message
        if message is None:
            return None

        answers: list[str] = []
        for example in message.examples:
            answer = self._extract_user_text(example)
            if not answer or answer.lower() == "other" or answer in answers:
                continue
            answers.append(answer)

        return answers or None


    def _ask_user_question_events(
        self, tool_name: str, tool_args: dict[str, Any]
    ) -> list[BaseEvent]:
        if tool_name != _ASK_USER_QUESTION_TOOL:
            return []

        try:
            parsed = AskUserQuestionArgs.model_validate(tool_args)
        except ValidationError:
            logger.warning("Failed to parse ask_user_question args", exc_info=True)
            return []
        prompt = "\n\n".join(q.question for q in parsed.questions)
        if not prompt:
            return []

        return self._assistant_question_events(prompt)


    def _assistant_question_events(self, prompt: str) -> list[BaseEvent]:
        if self._pending_question_prompt == prompt:
            return []

        self._pending_question_prompt = prompt
        message_id = LLMMessage(role=Role.assistant).message_id
        self._merge_message(
            LLMMessage(role=Role.assistant, content=prompt, message_id=message_id)
        )
        return [AssistantEvent(content=prompt, message_id=message_id)]


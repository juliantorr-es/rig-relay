from __future__ import annotations

import asyncio
import concurrent.futures
import typing

from rig_relay.extensions.safari.context import GitHubPageContext
from rig_relay.extensions.safari.models import (
    AcceptedResponse,
    AppUnavailableResponse,
    DeferralReason,
    DeferredResponse,
    GitHubIssueHandoff,
    GitHubPullRequestHandoff,
    GitHubRepositoryHandoff,
    MessageDirection,
    RefusalReason,
    RefusedResponse,
    RepositoryStatus,
    SafariExtensionMessage,
    TriggeredBy,
    UnavailableReason,
    validate_content_light,
)


class NativeMessageContract:
    def __init__(self) -> None:
        self._app_connected: bool = True
        self._repository_statuses: dict[str, RepositoryStatus] = {}
        self._carte_blanche_connected: bool = True
        self._force_unavailable: bool = False
        self._force_defer_all: bool = False
        self._force_defer_reason: DeferralReason | None = None

    def set_app_connected(self, connected: bool) -> None:
        self._app_connected = connected

    def set_repository_status(
        self, owner: str, repo: str, status: RepositoryStatus
    ) -> None:
        self._repository_statuses[f"{owner}/{repo}"] = status

    def set_carte_blanche_connected(self, connected: bool) -> None:
        self._carte_blanche_connected = connected

    async def receive_handoff(
        self, message: SafariExtensionMessage
    ) -> SafariExtensionMessage:
        if message.validate_content_light():
            return self._refuse(
                message.kind, message.message_id, RefusalReason.INVALID_MESSAGE
            )

        if message.direction != MessageDirection.EXTENSION_TO_APP:
            return self._refuse(
                message.kind, message.message_id, RefusalReason.INVALID_MESSAGE
            )

        if self._force_unavailable or not self._app_connected:
            return self._app_unavailable()

        match message.kind:
            case (
                "handoff.github_repository"
                | "handoff.github_pull_request"
                | "handoff.github_issue"
            ):
                return self._handle_repo_handoff(message)
            case "ping":
                return self._ping(message.message_id)
            case _:
                return self._refuse(
                    message.kind, message.message_id, RefusalReason.INVALID_MESSAGE
                )

    def _handle_repo_handoff(
        self, message: SafariExtensionMessage
    ) -> SafariExtensionMessage:
        owner: str
        repo: str
        match message.payload:
            case GitHubRepositoryHandoff(owner=o, repo=r):
                owner = o
                repo = r
            case GitHubPullRequestHandoff(owner=o, repo=r):
                owner = o
                repo = r
            case GitHubIssueHandoff(owner=o, repo=r):
                owner = o
                repo = r
            case _:
                return self._refuse(
                    message.kind, message.message_id, RefusalReason.INVALID_MESSAGE
                )

        if self._force_defer_all:
            return self._defer(
                message.kind,
                message.message_id,
                self._force_defer_reason or DeferralReason.DEFERRED_CAPABILITY,
            )

        if not self._carte_blanche_connected:
            return self._defer(
                message.kind,
                message.message_id,
                DeferralReason.APP_NOT_CONNECTED_TO_CARTE_BLANCHE,
            )

        key = f"{owner}/{repo}"
        status = self._repository_statuses.get(
            key, RepositoryStatus.KNOWN_AND_AVAILABLE
        )

        match status:
            case RepositoryStatus.KNOWN_AND_AVAILABLE:
                return self._accept(message.kind, message.message_id, status)
            case _:
                return self._defer(
                    message.kind,
                    message.message_id,
                    DeferralReason.REQUIRES_SELECTION_OR_IMPORT_IN_MAIN_APP,
                )

    def _accept(
        self, kind: str, message_id: str, repository_status: RepositoryStatus
    ) -> SafariExtensionMessage:
        return SafariExtensionMessage(
            direction=MessageDirection.APP_TO_EXTENSION,
            kind="response.accepted",
            payload=AcceptedResponse(
                in_response_to=message_id,
                action=kind,
                repository_status=repository_status,
            ),
        )

    def _defer(
        self, kind: str, message_id: str, reason: DeferralReason
    ) -> SafariExtensionMessage:
        return SafariExtensionMessage(
            direction=MessageDirection.APP_TO_EXTENSION,
            kind="response.deferred",
            payload=DeferredResponse(
                in_response_to=message_id, action=kind, deferral_reason=reason
            ),
        )

    def _refuse(
        self, kind: str, message_id: str, reason: RefusalReason
    ) -> SafariExtensionMessage:
        return SafariExtensionMessage(
            direction=MessageDirection.APP_TO_EXTENSION,
            kind="response.refused",
            payload=RefusedResponse(
                in_response_to=message_id, action=kind, refusal_reason=reason
            ),
        )

    def _ping(self, message_id: str) -> SafariExtensionMessage:
        return SafariExtensionMessage(
            direction=MessageDirection.APP_TO_EXTENSION,
            kind="response.accepted",
            payload=AcceptedResponse(
                in_response_to=message_id,
                action="ping",
                repository_status=RepositoryStatus.KNOWN_AND_AVAILABLE,
                message="pong",
            ),
        )

    def _app_unavailable(self) -> SafariExtensionMessage:
        return SafariExtensionMessage(
            direction=MessageDirection.APP_TO_EXTENSION,
            kind="response.app_unavailable",
            payload=AppUnavailableResponse(
                message="App is not available", reason=UnavailableReason.APP_NOT_RUNNING
            ),
        )


def create_app_unavailable_contract() -> NativeMessageContract:
    contract = NativeMessageContract()
    contract._force_unavailable = True
    return contract


def create_deferred_contract(reason: DeferralReason) -> NativeMessageContract:
    contract = NativeMessageContract()
    contract._force_defer_all = True
    contract._force_defer_reason = reason
    return contract


def _run_coro(coro: object) -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        result: object = asyncio.run(
            typing.cast(typing.Coroutine[typing.Any, typing.Any, bool], coro)
        )
        return typing.cast(bool, result)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return typing.cast(
            bool,
            executor.submit(
                lambda: asyncio.run(
                    typing.cast(typing.Coroutine[typing.Any, typing.Any, bool], coro)
                )
            ).result(),
        )


def validate_message_roundtrip(
    message: SafariExtensionMessage, contract: NativeMessageContract
) -> bool:
    async def _roundtrip() -> bool:
        response = await contract.receive_handoff(message)
        if response.direction != MessageDirection.APP_TO_EXTENSION:
            return False
        if isinstance(response.payload, (RefusedResponse, AppUnavailableResponse)):
            return False
        return validate_content_light(response)

    return _run_coro(_roundtrip())


def build_handoff_from_context(
    ctx: GitHubPageContext, triggered_by: TriggeredBy
) -> SafariExtensionMessage:
    if ctx.pr_number is not None:
        payload = GitHubPullRequestHandoff(
            url=ctx.url,
            owner=ctx.owner,
            repo=ctx.repo,
            pr_number=ctx.pr_number,
            page_kind=ctx.page_kind,
            triggered_by=triggered_by,
        )
        kind = "handoff.github_pull_request"
    elif ctx.issue_number is not None:
        payload = GitHubIssueHandoff(
            url=ctx.url,
            owner=ctx.owner,
            repo=ctx.repo,
            issue_number=ctx.issue_number,
            triggered_by=triggered_by,
        )
        kind = "handoff.github_issue"
    else:
        payload = GitHubRepositoryHandoff(
            url=ctx.url,
            owner=ctx.owner,
            repo=ctx.repo,
            page_kind=ctx.page_kind,
            triggered_by=triggered_by,
        )
        kind = "handoff.github_repository"

    return SafariExtensionMessage(
        direction=MessageDirection.EXTENSION_TO_APP, kind=kind, payload=payload
    )

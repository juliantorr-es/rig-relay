from __future__ import annotations

from enum import StrEnum
import logging
from os import getenv

from vibe.cli.plan_offer.ports.whoami_gateway import (
    WhoAmIGateway,
    WhoAmIGatewayError,
    WhoAmIGatewayUnauthorized,
    WhoAmIPlanType,
    WhoAmIResponse,
)
from vibe.core.config import ProviderConfig
from vibe.core.types import Backend

logger = logging.getLogger(__name__)

CONSOLE_CLI_URL = ""
UPGRADE_URL = ""
SWITCH_TO_PRO_KEY_URL = ""


class RelayPlanName(StrEnum):
    FREE = "F"
    ENTERPRISE = "E"


class PlanInfo:
    plan_type: WhoAmIPlanType
    plan_name: str
    prompt_switching_to_pro_plan: bool

    def __init__(
        self,
        plan_type: WhoAmIPlanType,
        plan_name: str = "",
        prompt_switching_to_pro_plan: bool = False,
    ) -> None:
        self.plan_type = plan_type
        self.plan_name = plan_name
        self.prompt_switching_to_pro_plan = prompt_switching_to_pro_plan

    @classmethod
    def from_response(cls, response: WhoAmIResponse) -> PlanInfo:
        return cls(
            plan_type=response.plan_type,
            plan_name=response.plan_name,
            prompt_switching_to_pro_plan=response.prompt_switching_to_pro_plan,
        )

    def is_paid_api_plan(self) -> bool:
        return self.plan_type == WhoAmIPlanType.API and not self.is_free_api_plan()

    def is_free_api_plan(self) -> bool:
        return self.plan_type == WhoAmIPlanType.API and "FREE" in self.plan_name.upper()

    def is_chat_pro_plan(self) -> bool:
        return self.plan_type == WhoAmIPlanType.CHAT

    def is_teleport_eligible(self) -> bool:
        return self.is_chat_pro_plan() and not self.prompt_switching_to_pro_plan

    def is_free_relay_plan(self) -> bool:
        return (
            self.plan_type == WhoAmIPlanType.MISTRAL_CODE
            and self.plan_name.upper() == RelayPlanName.FREE
        )

    def is_relay_enterprise_plan(self) -> bool:
        return (
            self.plan_type == WhoAmIPlanType.MISTRAL_CODE
            and self.plan_name.upper() == RelayPlanName.ENTERPRISE
        )


async def decide_plan_offer(api_key: str | None, gateway: WhoAmIGateway) -> PlanInfo:
    if not api_key:
        return PlanInfo(WhoAmIPlanType.UNKNOWN)
    try:
        response = await gateway.whoami(api_key)
        return PlanInfo.from_response(response)
    except WhoAmIGatewayUnauthorized:
        return PlanInfo(WhoAmIPlanType.UNAUTHORIZED)
    except WhoAmIGatewayError:
        logger.warning("Failed to fetch plan status.", exc_info=True)
    return PlanInfo(WhoAmIPlanType.UNKNOWN)


def resolve_api_key_for_plan(provider: ProviderConfig) -> str | None:
    api_env_key = "DEEPSEEK_API_KEY"

    if provider.backend == Backend.MISTRAL:
        api_env_key = provider.api_key_env_var

    return getenv(api_env_key)


def plan_offer_cta(payload: PlanInfo | None) -> str | None:
    return None


def plan_title(payload: PlanInfo | None) -> str | None:  # noqa: PLR0911
    if not payload:
        return None
    if payload.is_chat_pro_plan():
        return "[Subscription] Pro"
    if payload.is_free_api_plan():
        return "[API] Experiment plan"
    if payload.is_paid_api_plan():
        return "[API] Scale plan"
    if payload.is_free_relay_plan():
        return "Rig Relay Free"
    if payload.is_relay_enterprise_plan():
        return "Rig Relay Enterprise"
    return None
    return None

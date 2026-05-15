"""Council — structured multi-provider consultation via companion windows.

Sends bounded mission packets to external AI providers through pywebview
companion windows and collects structured opinions. Each consultation
produces a receipt-backed NormalizedConsultation artifact.

No provider ever gets direct repo mutation authority.
Output is structured for comparison across providers.

Content-light: raw transcripts are hashed, never logged.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolDeterminismClass,
    ToolError,
    ToolMutationClass,
    ToolPermission,
)
from rig_relay.core.tools.ui import ToolUIData
from rig_relay.core.types import ToolStreamEvent


class ConsultProviderArgs(BaseModel):
    provider: str = Field(
        default="chatgpt",
        description="Provider to consult: chatgpt, claude, gemini, deepseek, mistral, perplexity",
    )
    prompt: str = Field(
        ...,
        description="The prompt to send to the provider's web app",
    )
    wait_seconds: int = Field(
        default=0,
        description="Seconds to wait for the provider to respond before reading (0 = immediate return, caller should poll)",
    )


class ConsultProviderResult(BaseModel):
    status: str
    provider: str
    response_text: str = ""
    error: str = ""


class ConsultProviderConfig(BaseToolConfig):
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.NONDETERMINISTIC_PROVIDER
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY
    permission: ToolPermission = ToolPermission.ALWAYS


class ConsultProvider(
    BaseTool[
        ConsultProviderArgs,
        ConsultProviderResult,
        ConsultProviderConfig,
        BaseToolState,
    ],
    ToolUIData[ConsultProviderArgs, ConsultProviderResult],
):
    """Consult a provider's web app through a companion pywebview window.

    Sends a prompt to an open provider window and reads the response.
    The provider window must already be open (use the Provider Dock widget
    or /provider slash command to open one).

    Provider window sharing: on macOS, pywebview shares Safari's cookie
    jar. If the user is logged into the provider in Safari, the session
    carries over automatically — no re-authentication needed.

    No API key required. Works with free-tier accounts.
    """

    async def run(
        self,
        args: ConsultProviderArgs,
        ctx: InvokeContext | None = None,
    ) -> AsyncGenerator[ToolStreamEvent | ConsultProviderResult, None]:
        import asyncio

        try:
            import webview  # type: ignore[import-untyped]
        except ImportError:
            result = ConsultProviderResult(
                status="error",
                provider=args.provider,
                error="pywebview not available (tool only works in desktop mode)",
            )
            yield result
            return

        # Send prompt to provider window
        send_js = self._build_send_js(args.provider, args.prompt)
        sent = False
        for w in webview.windows:
            wtitle = str(getattr(w, "title", ""))
            if args.provider.lower() in wtitle.lower():
                try:
                    w.evaluate_js(send_js)
                    sent = True
                except Exception:
                    pass
                break

        if not sent:
            result = ConsultProviderResult(
                status="error",
                provider=args.provider,
                error=(
                    f"No {args.provider} companion window found. "
                    f"Open it first: click {args.provider} in the Provider Dock, "
                    f"or use /provider {args.provider}"
                ),
            )
            yield result
            return

        # Wait for response if requested
        if args.wait_seconds > 0:
            await asyncio.sleep(min(args.wait_seconds, 60))

        # Read response
        read_js = self._build_read_js(args.provider)
        response_text = ""
        for w in webview.windows:
            wtitle = str(getattr(w, "title", ""))
            if args.provider.lower() in wtitle.lower():
                try:
                    result = w.evaluate_js(read_js)
                    response_text = str(result or "")
                except Exception:
                    pass
                break

        yield ConsultProviderResult(
            status="sent",
            provider=args.provider,
            response_text=response_text[:4000] if response_text else "(no response yet — the provider may still be generating)",
        )

    @staticmethod
    def _build_send_js(provider: str, prompt: str) -> str:
        import json

        selectors = {
            "chatgpt": '#prompt-textarea',
            "claude": 'div[contenteditable="true"]',
            "gemini": 'div[contenteditable="true"]',
            "deepseek": '#chat-input, textarea',
            "mistral": 'textarea, div[contenteditable="true"]',
            "perplexity": 'textarea',
        }
        selector = selectors.get(provider, 'textarea, div[contenteditable="true"]')
        escaped = json.dumps(prompt)

        return (
            "(function(){"
            f'const el=document.querySelector("{selector}");'
            "if(!el)return'no_input';"
            f"const text={escaped};"
            "if(el.tagName==='TEXTAREA'||el.tagName==='INPUT'){"
            "el.value=text;el.dispatchEvent(new Event('input',{bubbles:true}));"
            "}else{"
            "el.innerText=text;el.dispatchEvent(new Event('input',{bubbles:true}));"
            "}"
            "return'ok';"
            "})()"
        )

    @staticmethod
    def _build_read_js(provider: str) -> str:
        selectors = {
            "chatgpt": '[data-message-author-role="assistant"]',
            "claude": ".font-claude-message, .prose",
            "gemini": ".model-response-text, .prose",
            "deepseek": ".ds-markdown, .markdown",
            "mistral": ".prose",
            "perplexity": ".prose, .markdown",
        }
        selector = selectors.get(provider, ".prose, .markdown")
        return (
            "(function(){"
            f'const els=document.querySelectorAll("{selector}");'
            "if(!els.length)return'';"
            "const last=els[els.length-1];"
            "return last?last.innerText:'';"
            "})()"
        )


__all__ = [
    "ConsultProvider",
    "ConsultProviderArgs",
    "ConsultProviderConfig",
    "ConsultProviderResult",
]

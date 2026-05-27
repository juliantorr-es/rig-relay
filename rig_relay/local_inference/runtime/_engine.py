"""Rig-governed MLX-backed inference engine.

Uses mlx-lm Python APIs for model loading, text generation, and streaming.
Returns visible responses for UI consumption. Content-light evidence is
emitted separately by the service layer.

Thread safety: uses a generation lock to serialize all MLX operations.
MLX stream initialized once per process on first use.

Tool-call parsing: detects JSON blocks, function-call XML, and tool-call
XML from model output. Proposals only — never executed directly.

OMLX-informed patterns:
  - MLX stream init: engine_core.py _init_mlx_thread (Apache 2.0)
  - Tool-call detection: api/tool_calling.py multi-family parsing (Apache 2.0)
  - Streaming: mlx-lm.stream_generate() progressive token emission
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import queue
import re
import secrets
import threading
import time
from typing import Any, cast

from rig_relay.core.logger import logger
from rig_relay.local_inference.runtime._models import (
    FinishReason,
    LocalInferenceResponse,
    ToolCallProposal,
)

try:
    import mlx.core as _mlx_core  # noqa: F401
    import mlx.nn.layers.base as mlx_base
    import mlx_lm.tokenizer_utils

    HAS_MLX = True
except ImportError:
    HAS_MLX = False


class MlxNotAvailableError(Exception):
    pass


class ModelNotLoadedError(Exception):
    pass


@dataclass
class LoadedModel:
    model_id_hash: str
    model_path: str
    loaded_at: str
    mlx_model: mlx_base.Module = field(repr=False)
    tokenizer: mlx_lm.tokenizer_utils.TokenizerWrapper = field(repr=False)


class RiggedMlxEngine:
    """MLX-backed inference engine with serialized generation and streaming.

    Delegates model storage to ModelPoolManager when configured.
    Supports cache-augmented generation via RiggedCacheAuthority.
    """

    def __init__(self) -> None:
        self._loaded_models: dict[str, LoadedModel] = {}
        self._mlx_available: bool | None = None
        self._stream_initialized: bool = False
        self._model_lock: threading.Lock = threading.Lock()
        self._gen_lock: threading.Lock = threading.Lock()
        self._cache_authority: Any | None = None
        self._pool: Any | None = None

    def set_cache_authority(self, cache_authority: Any) -> None:
        self._cache_authority = cache_authority

    def set_pool(self, pool: Any) -> None:
        """Delegate model storage to a ModelPoolManager."""
        self._pool = pool

    @property
    def is_mlx_available(self) -> bool:
        if self._mlx_available is None:
            try:
                import mlx.core as _  # noqa: F401

                self._mlx_available = True
            except ImportError:
                self._mlx_available = False
        return self._mlx_available

    @property
    def loaded_model_count(self) -> int:
        return len(self._loaded_models)

    def list_loaded_models(self) -> list[LoadedModel]:
        return list(self._loaded_models.values())

    def load_model(self, model_path: str, model_id: str = "") -> LoadedModel:
        if not self.is_mlx_available:
            raise MlxNotAvailableError("MLX not available")

        model_id_hash = _sha256(model_path)[:16]
        display_id = model_id or model_path

        with self._gen_lock:
            with self._model_lock:
                if model_id_hash in self._loaded_models:
                    return self._loaded_models[model_id_hash]

                logger.info("Loading model via mlx-lm: %s", display_id)
                self._ensure_mlx_stream()

                import mlx_lm as _mlx

                result = _mlx.load(model_path)
                loaded = LoadedModel(
                    model_id_hash=model_id_hash,
                    model_path=model_path,
                    loaded_at=_now_iso(),
                    mlx_model=result[0],
                    tokenizer=result[1],
                )
                self._loaded_models[model_id_hash] = loaded
                logger.info("Model loaded: %s (hash=%s)", display_id, model_id_hash)

                if self._pool is not None:
                    self._pool.load(model_path, model_id_hash, loaded)

                return loaded

    def unload_model(self, model_id_hash: str) -> bool:
        with self._gen_lock:
            with self._model_lock:
                if model_id_hash in self._loaded_models:
                    del self._loaded_models[model_id_hash]
                    return True
        return False

    def generate(
        self, model_id_hash: str, messages: list[dict], max_tokens: int = 4096
    ) -> LocalInferenceResponse:
        """Generate text (non-streaming) via mlx-lm with serialized execution.

        Returns visible LocalInferenceResponse with content, tool proposals,
        and generation metadata. _gen_lock covers the full call including
        model lookup and mlx_lm.generate().
        """
        with self._gen_lock:
            loaded = self._loaded_models.get(model_id_hash)

            if loaded is None:
                return LocalInferenceResponse(
                    content="", finish_reason=FinishReason.ERROR
                )

            self._ensure_mlx_stream()
            tokenizer = loaded.tokenizer
            prompt = _build_prompt_using_chat_template(messages, tokenizer)
            start = time.monotonic()

            try:
                import mlx_lm as _mlx

                cache_hit = False
                cached = None
                prompt_tokens_list: list[int] = []

                if self._cache_authority is not None and hasattr(tokenizer, "encode"):
                    try:
                        prompt_tokens_list = cast(Any, tokenizer).encode(prompt)
                        cached, _ = self._cache_authority.fetch_cache(
                            loaded.mlx_model, prompt_tokens_list
                        )
                        cache_hit = cached is not None
                    except Exception:
                        cached = None

                generate_kwargs: dict = {
                    "model": loaded.mlx_model,
                    "tokenizer": tokenizer,
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                    "verbose": False,
                }
                if cached is not None:
                    generate_kwargs["prompt_cache"] = cached

                response = _mlx.generate(**generate_kwargs)
                elapsed = (time.monotonic() - start) * 1000
                output_text = response if isinstance(response, str) else str(response)
                usage = _estimate_usage(prompt, output_text, tokenizer)
                tool_proposals = _parse_tool_calls(output_text)
                finish = (
                    FinishReason.TOOL_CALLS if tool_proposals else FinishReason.STOP
                )

                return LocalInferenceResponse(
                    content=output_text,
                    finish_reason=finish,
                    tool_call_proposals=tool_proposals,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    latency_ms=int(elapsed),
                    model_id_hash=model_id_hash,
                    cache_hit=cache_hit,
                )

            except Exception as e:
                elapsed = (time.monotonic() - start) * 1000
                logger.error("mlx-lm generation error: %s", e)
                return LocalInferenceResponse(
                    content="",
                    finish_reason=FinishReason.ERROR,
                    latency_ms=int(elapsed),
                    model_id_hash=model_id_hash,
                )

    def stream_generate_sync(
        self,
        model_id_hash: str,
        messages: list[dict],
        max_tokens: int,
        output_queue: queue.Queue,
        cancel_flag: list[bool],
    ) -> None:
        """Synchronous streaming generation intended for a dedicated thread.

        Holds _gen_lock across the entire mlx-lm streaming call. Pushes
        (kind, payload) tuples to the thread-safe output_queue:

            ("token", str)      — next text token
            ("done", dict)      — completion info: content, finish_reason,
                                  tool_call_proposals, completion_tokens,
                                  prompt_tokens (for cache write-back)
            ("error", str)      — error message
            ("cancelled", None) — cancelled via cancel_flag

        Checks cancel_flag[0] before each token yield.
        """
        with self._gen_lock:
            loaded = self._loaded_models.get(model_id_hash)
            if loaded is None:
                output_queue.put(("error", "Model not loaded"))
                return

            self._ensure_mlx_stream()
            tokenizer = loaded.tokenizer
            prompt = _build_prompt_using_chat_template(messages, tokenizer)

            cache_hit = False
            cached = None
            prompt_tokens_for_cache: list[int] = []

            if self._cache_authority is not None and hasattr(tokenizer, "encode"):
                try:
                    prompt_tokens_for_cache = cast(Any, tokenizer).encode(prompt)
                    cached, _ = self._cache_authority.fetch_cache(
                        loaded.mlx_model, prompt_tokens_for_cache
                    )
                    cache_hit = cached is not None
                except Exception:
                    cached = None

            try:
                import mlx_lm as _mlx

                stream_kwargs: dict[str, Any] = {
                    "model": loaded.mlx_model,
                    "tokenizer": tokenizer,
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                }
                if cached is not None:
                    stream_kwargs["prompt_cache"] = cached

                accumulated: list[str] = []
                for token_result in _mlx.stream_generate(**stream_kwargs):
                    if cancel_flag[0]:
                        output_queue.put(("cancelled", None))
                        return
                    text = (
                        token_result
                        if isinstance(token_result, str)
                        else (
                            token_result.text
                            if hasattr(token_result, "text")
                            else str(token_result)
                        )
                    )
                    accumulated.append(text)
                    output_queue.put(("token", text))

                full_text = "".join(accumulated)
                tool_proposals = _parse_tool_calls(full_text)
                finish = (
                    FinishReason.TOOL_CALLS if tool_proposals else FinishReason.STOP
                )
                output_queue.put((
                    "done",
                    {
                        "content": full_text,
                        "finish_reason": finish,
                        "tool_call_proposals": tool_proposals,
                        "completion_tokens": len(accumulated),
                        "cache_hit": cache_hit,
                        "prompt_tokens": prompt_tokens_for_cache,
                    },
                ))

            except Exception as e:
                logger.error("mlx-lm streaming error: %s", e)
                output_queue.put(("error", str(e)))

    def _ensure_mlx_stream(self) -> None:
        if self._stream_initialized:
            return
        self._stream_initialized = True
        if not self.is_mlx_available:
            return
        try:
            import mlx.core as mx
            import mlx_lm.generate as mlx_gen

            if not hasattr(mlx_gen, "generation_stream"):
                mlx_gen.generation_stream = mx.new_stream(mx.default_device())
        except Exception:
            pass


def _build_prompt_using_chat_template(messages: list[dict], tokenizer: object) -> str:
    if hasattr(tokenizer, "apply_chat_template"):
        try:
            formatted = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            if isinstance(formatted, str) and formatted:
                return formatted
        except Exception:
            pass

    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _parse_tool_calls(text: str) -> list[ToolCallProposal]:
    proposals: list[ToolCallProposal] = []

    json_blocks = re.findall(r"```json\s*(.*?)```", text, re.DOTALL)
    for block in json_blocks:
        try:
            data = json.loads(block)
            if isinstance(data, dict) and "name" in data:
                proposals.append(
                    ToolCallProposal(
                        call_id=_make_call_id(),
                        tool_name=str(data.get("name", "")),
                        arguments=json.dumps(
                            data.get("arguments", data.get("parameters", {}))
                        ),
                        rationale=str(data.get("rationale", "")),
                    )
                )
        except (json.JSONDecodeError, TypeError):
            continue

    for tag in ("function_call", "tool_call"):
        pattern = re.findall(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.DOTALL)
        for block in pattern:
            try:
                data = json.loads(block)
                if isinstance(data, dict):
                    proposals.append(
                        ToolCallProposal(
                            call_id=_make_call_id(),
                            tool_name=str(data.get("name", data.get("function", ""))),
                            arguments=json.dumps(
                                data.get("arguments", data.get("parameters", {}))
                            ),
                        )
                    )
            except (json.JSONDecodeError, TypeError):
                continue

    return proposals


def _estimate_usage(
    prompt: str, output: str, tokenizer: object | None
) -> dict[str, int]:
    try:
        if tokenizer is not None and hasattr(tokenizer, "encode"):
            return {
                "prompt_tokens": len(tokenizer.encode(prompt)),
                "completion_tokens": len(tokenizer.encode(output)),
                "total_tokens": len(tokenizer.encode(prompt))
                + len(tokenizer.encode(output)),
            }
    except Exception:
        pass
    return {
        "prompt_tokens": len(prompt) // 4,
        "completion_tokens": len(output) // 4,
        "total_tokens": (len(prompt) + len(output)) // 4,
    }


def _make_call_id() -> str:
    return f"call_{secrets.token_hex(8)}"


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()

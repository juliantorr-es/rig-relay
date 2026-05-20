"""Runtime backend registry for local inference runtimes.

Content-light registry of supported local inference backends.
Never starts servers or downloads models.
"""

from __future__ import annotations

from rig_relay.providers.local_inference.models import RuntimeBackend

REGISTRY: list[RuntimeBackend] = [
    RuntimeBackend(
        backend_id="ollama",
        display_name="Ollama",
        executable_name="ollama",
        default_host="127.0.0.1",
        default_port=11434,
        health_endpoint="/api/tags",
        openai_base_url="http://localhost:11434/v1",
        pull_command_template="ollama pull {model_id}",
        start_command_template="ollama serve",
        stop_strategy="process_sigterm",
        supported_platforms=["macos", "linux", "windows"],
        expected_model_formats=["gguf"],
        risk_level="low",
        content_exposure_notes="Runs locally. No remote exposure unless configured.",
        enabled_default=False,
        auto_start_allowed_default=False,
        auto_download_allowed_default=False,
        raw_retention_allowed_default=False,
    ),
    RuntimeBackend(
        backend_id="llama_cpp_server",
        display_name="llama.cpp Server",
        executable_name="llama-server",
        default_host="127.0.0.1",
        default_port=8080,
        health_endpoint="/health",
        openai_base_url="http://localhost:8080/v1",
        pull_command_template="",
        start_command_template="llama-server -m {model_path} --host 127.0.0.1 --port {port}",
        stop_strategy="process_sigterm",
        supported_platforms=["macos", "linux", "windows"],
        expected_model_formats=["gguf"],
        risk_level="medium",
        content_exposure_notes="Requires explicit model path. No remote exposure.",
        enabled_default=False,
        auto_start_allowed_default=False,
        auto_download_allowed_default=False,
        raw_retention_allowed_default=False,
    ),
    RuntimeBackend(
        backend_id="vllm",
        display_name="vLLM",
        executable_name="vllm",
        default_host="127.0.0.1",
        default_port=8000,
        health_endpoint="/health",
        openai_base_url="http://localhost:8000/v1",
        pull_command_template="",
        start_command_template="vllm serve {model_id} --host 127.0.0.1 --port {port}",
        stop_strategy="process_sigterm",
        supported_platforms=["linux"],
        expected_model_formats=["hf_transformers", "safetensors"],
        risk_level="medium",
        content_exposure_notes="NVIDIA GPU required. High throughput.",
        enabled_default=False,
        auto_start_allowed_default=False,
        auto_download_allowed_default=False,
        raw_retention_allowed_default=False,
    ),
    RuntimeBackend(
        backend_id="custom_openai_compatible",
        display_name="Custom OpenAI-Compatible",
        executable_name="",
        default_host="127.0.0.1",
        default_port=8080,
        health_endpoint="/health",
        openai_base_url="",
        pull_command_template="",
        start_command_template="",
        stop_strategy="none",
        supported_platforms=["macos", "linux", "windows"],
        expected_model_formats=["unknown"],
        risk_level="high",
        content_exposure_notes="User-configured. Rig does not manage lifecycle.",
        enabled_default=True,
        auto_start_allowed_default=False,
        auto_download_allowed_default=False,
        raw_retention_allowed_default=False,
    ),
]


def list_backends() -> list[RuntimeBackend]:
    return list(REGISTRY)


def get_backend(backend_id: str) -> RuntimeBackend | None:
    for b in REGISTRY:
        if b.backend_id == backend_id:
            return b
    return None


__all__ = ["REGISTRY", "get_backend", "list_backends"]

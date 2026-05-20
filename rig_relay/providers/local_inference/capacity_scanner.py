"""Local system capacity scanner — content-light hardware profiling.

Never exposes serial numbers, usernames, absolute user-home paths, secrets,
or raw process lists. Conservative classifier.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import platform
import secrets
import shutil

from rig_relay.providers.local_inference.models import CapacityScan


def scan_capacity(*, now: str | None = None) -> CapacityScan:
    caps = CapacityScan(
        scan_id=f"cs_{secrets.token_hex(8)}",
        collected_at=now or datetime.now(UTC).isoformat(),
    )
    caps.os_name = platform.system()
    caps.cpu_arch = platform.machine()
    caps.cpu_core_count = os.cpu_count() or 0
    caps.python_version = platform.python_version()

    caps.ram_total_mb = _ram_total()
    caps.disk_free_model_path_mb = _disk_free_home()

    caps.metal_available = caps.os_name == "Darwin"
    caps.cuda_available = _check_binary("nvcc") or _check_env("CUDA_VISIBLE_DEVICES")
    caps.rocm_available = _check_binary("rocm-smi")
    caps.gpu_detected = (
        caps.metal_available or caps.cuda_available or caps.rocm_available
    )

    if caps.cuda_available:
        caps.gpu_class = "cuda"
    elif caps.metal_available:
        caps.gpu_class = "metal"

    caps.runtimes_detected = []
    if _check_binary("ollama"):
        caps.runtimes_detected.append("ollama")
    if _check_binary("llama-server") or _check_binary("llama.cpp"):
        caps.runtimes_detected.append("llama_cpp_server")
    if _check_binary("vllm"):
        caps.runtimes_detected.append("vllm")

    caps.capacity_class = _classify(caps)
    return caps


def _ram_total() -> int:
    try:
        return int(
            os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 * 1024)
        )
    except (ValueError, OSError):
        try:
            return int(shutil.disk_usage(Path.home())[0] / (1024 * 1024))
        except Exception:
            return 0


def _disk_free_home() -> int:
    try:
        return int(shutil.disk_usage(Path.home())[2] / (1024 * 1024))
    except Exception:
        return 0


def _check_binary(name: str) -> bool:
    return shutil.which(name) is not None


def _check_env(name: str) -> bool:
    return bool(os.environ.get(name))


def _classify(caps: CapacityScan) -> str:
    if caps.cuda_available:
        if caps.ram_total_mb > 32000:
            return "cuda_heavy"
        if caps.ram_total_mb > 16000:
            return "cuda_medium"
        return "cuda_light"
    if caps.os_name == "Darwin":
        ram = caps.ram_total_mb
        if ram > 32000:
            return "apple_silicon_heavy"
        if ram > 16000:
            return "apple_silicon_medium"
        return "apple_silicon_light"
    if caps.cpu_core_count > 4 and caps.ram_total_mb > 16000:
        return "small_cpu"
    if caps.cpu_core_count > 0:
        return "tiny_cpu"
    return "unknown"


__all__ = ["scan_capacity"]

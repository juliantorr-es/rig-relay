"""Energy and power measurement — read-only OS telemetry.

Collects thermal state and power estimates from the host OS.
Content-light: no serial numbers, battery health, or user data.
"""

from __future__ import annotations

import platform
import subprocess
from typing import Any


def measure_power_estimate() -> dict[str, Any]:
    """Return a content-light power/thermal summary dict.

    On macOS: reads thermal state from pmset.
    On Linux: reads RAPL from /sys/class/powercap/.
    On other platforms: returns nulls.

    Never collects serial numbers, battery health, or user data.

    Returns:
        dict with keys:
          - power_estimate_watts: float | None
          - thermal_state: str
          - platform: str
    """
    plat = platform.system()
    thermal_state = ""
    power_estimate_watts: float | None = None

    if plat == "Darwin":
        thermal_state = _macos_thermal_state()
        power_estimate_watts = None
    elif plat == "Linux":
        thermal_state = ""
        power_estimate_watts = _linux_rapl_watts()

    return {
        "power_estimate_watts": power_estimate_watts,
        "thermal_state": thermal_state,
        "platform": plat,
    }


def _macos_thermal_state() -> str:
    try:
        result = subprocess.run(
            ["pmset", "-g", "therm"], capture_output=True, text=True, timeout=5
        )
        output = result.stdout.lower()
        if "critical" in output:
            return "critical"
        if "serious" in output:
            return "serious"
        if "fair" in output:
            return "fair"
        if "nominal" in output:
            return "nominal"
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.xcpm.cpu_thermal_level"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        level = result.stdout.strip()
        mapping = {"0": "nominal", "1": "fair", "2": "serious", "3": "critical"}
        if level in mapping:
            return mapping[level]
    except Exception:
        pass

    return ""


def _linux_rapl_watts() -> float | None:
    powercap_dir = "/sys/class/powercap"
    try:
        import os

        if not os.path.isdir(powercap_dir):
            return None
        total_uw = 0.0
        count = 0
        for entry in os.listdir(powercap_dir):
            if not entry.startswith("intel-rapl:"):
                continue
            energy_path = os.path.join(powercap_dir, entry, "energy_uj")
            if not os.path.isfile(energy_path):
                continue
            try:
                with open(energy_path) as f:
                    total_uw += float(f.read().strip())
                count += 1
            except Exception:
                continue
        if count == 0:
            return None
        watts = total_uw / 1_000_000.0
        if watts < 0:
            return None
        return round(watts, 6)
    except Exception:
        return None


__all__ = ["measure_power_estimate"]

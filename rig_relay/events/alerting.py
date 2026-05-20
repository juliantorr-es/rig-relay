from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto
import operator as _op
from typing import Any

from rig_relay.events.metrics import EventFabricMetrics


class AlertSeverity(StrEnum):
    INFO = auto()
    WARNING = auto()
    CRITICAL = auto()


@dataclass(slots=True)
class AlertRule:
    rule_name: str
    severity: str
    field: str
    operator: str
    threshold: Any
    description: str = ""


_DEFAULT_RULES: list[AlertRule] = [
    AlertRule(
        rule_name="projection_stale",
        severity="warning",
        field="projection_freshness",
        operator="==",
        threshold="stale",
    ),
    AlertRule(
        rule_name="reconnect_pressure_high",
        severity="warning",
        field="reconnect_pressure",
        operator="==",
        threshold="high",
    ),
    AlertRule(
        rule_name="consumer_error_rate",
        severity="critical",
        field="consumer_error_count",
        operator=">",
        threshold=10,
    ),
    AlertRule(
        rule_name="bridge_disconnected",
        severity="critical",
        field="bridge_backend_health",
        operator="==",
        threshold="disconnected",
    ),
    AlertRule(
        rule_name="wal_overflow",
        severity="critical",
        field="wal_uncommitted_count",
        operator=">",
        threshold=1000,
    ),
]


def evaluate_alerts(
    metrics: EventFabricMetrics, rules: list[AlertRule] | None = None
) -> list[dict[str, Any]]:
    triggered: list[dict[str, Any]] = []
    metrics_dict = metrics.to_json()
    active_rules = rules if rules is not None else _DEFAULT_RULES

    for rule in active_rules:
        current_value = metrics_dict.get(rule.field)
        if current_value is None:
            continue

        if _evaluate_condition(current_value, rule.operator, rule.threshold):
            triggered.append({
                "rule_name": rule.rule_name,
                "severity": rule.severity,
                "current_value": current_value,
                "threshold": rule.threshold,
                "triggered_at": datetime.now(UTC).isoformat(),
            })

    return triggered


def _evaluate_condition(value: Any, operator: str, threshold: Any) -> bool:
    _ops = {
        ">": _op.gt,
        "<": _op.lt,
        "==": _op.eq,
        "!=": _op.ne,
        ">=": _op.ge,
        "<=": _op.le,
    }
    fn = _ops.get(operator)
    return fn(value, threshold) if fn else False


__all__ = ["AlertRule", "AlertSeverity", "evaluate_alerts"]

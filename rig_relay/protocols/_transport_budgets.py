from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TransportBudgets:
    max_request_bytes: int = 65536
    max_response_bytes: int = 65536
    max_stream_event_bytes: int = 65536
    max_pending_requests: int = 64
    max_connection_lifetime_seconds: int = 300
    max_concurrent_sessions: int = 8
    request_timeout_seconds: int = 30
    cancel_timeout_seconds: int = 5
    content_light: bool = True


@dataclass
class BudgetTracker:
    budgets: TransportBudgets = field(default_factory=TransportBudgets)
    pending_requests: int = 0
    active_sessions: int = 0
    connection_start: float = 0.0

    def can_accept_request(self, request_size: int) -> bool:
        if self.pending_requests >= self.budgets.max_pending_requests:
            return False
        if request_size > self.budgets.max_request_bytes:
            return False
        return True

    def track_request(self) -> None:
        self.pending_requests += 1

    def release_request(self) -> None:
        if self.pending_requests > 0:
            self.pending_requests -= 1

    def can_start_session(self) -> bool:
        return self.active_sessions < self.budgets.max_concurrent_sessions

    def track_session(self) -> None:
        self.active_sessions += 1

    def release_session(self) -> None:
        if self.active_sessions > 0:
            self.active_sessions -= 1

    def check_event_size(self, size: int) -> bool:
        return size <= self.budgets.max_stream_event_bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "budgets": {
                "max_request_bytes": self.budgets.max_request_bytes,
                "max_response_bytes": self.budgets.max_response_bytes,
                "max_stream_event_bytes": self.budgets.max_stream_event_bytes,
                "max_pending_requests": self.budgets.max_pending_requests,
                "max_connection_lifetime_seconds": self.budgets.max_connection_lifetime_seconds,
                "max_concurrent_sessions": self.budgets.max_concurrent_sessions,
            },
            "pending_requests": self.pending_requests,
            "active_sessions": self.active_sessions,
        }


__all__ = ["BudgetTracker", "TransportBudgets"]

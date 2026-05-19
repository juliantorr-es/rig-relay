from __future__ import annotations

import json
from pathlib import Path

from rig_relay.protocols._transport_budgets import BudgetTracker, TransportBudgets
from rig_relay.protocols.mcp.server import RigMCPServer

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class TestBudgetTrackerUnit:
    def test_budget_tracker_rejects_over_limit(self):
        budgets = TransportBudgets(max_pending_requests=1)
        tracker = BudgetTracker(budgets=budgets)
        tracker.pending_requests = 1

        assert not tracker.can_accept_request(100)

    def test_budget_tracker_rejects_oversized_request(self):
        budgets = TransportBudgets(max_request_bytes=100)
        tracker = BudgetTracker(budgets=budgets)

        assert not tracker.can_accept_request(200)
        assert tracker.can_accept_request(50)

    def test_budget_tracker_allows_normal_request(self):
        tracker = BudgetTracker()

        assert tracker.can_accept_request(1000)

    def test_budget_tracker_tracks_and_releases(self):
        tracker = BudgetTracker()

        assert tracker.pending_requests == 0
        tracker.track_request()
        assert tracker.pending_requests == 1
        tracker.track_request()
        assert tracker.pending_requests == 2
        tracker.release_request()
        assert tracker.pending_requests == 1
        tracker.release_request()
        assert tracker.pending_requests == 0
        tracker.release_request()
        assert tracker.pending_requests == 0

    def test_budget_tracker_rejects_session_when_full(self):
        budgets = TransportBudgets(max_concurrent_sessions=1)
        tracker = BudgetTracker(budgets=budgets)
        tracker.active_sessions = 1

        assert not tracker.can_start_session()

    def test_budget_tracker_event_size_check(self):
        tracker = BudgetTracker()

        assert tracker.check_event_size(1000)
        assert tracker.check_event_size(65536)
        assert not tracker.check_event_size(65537)

    def test_budget_tracker_dict_serialization(self):
        tracker = BudgetTracker()
        tracker.pending_requests = 3
        tracker.active_sessions = 2

        d = tracker.to_dict()
        assert d["pending_requests"] == 3
        assert d["active_sessions"] == 2
        assert d["budgets"]["max_request_bytes"] == 65536
        assert d["budgets"]["max_concurrent_sessions"] == 8

    def test_budget_tracker_session_tracking(self):
        tracker = BudgetTracker()

        assert tracker.active_sessions == 0
        tracker.track_session()
        assert tracker.active_sessions == 1
        tracker.track_session()
        assert tracker.active_sessions == 2
        tracker.release_session()
        assert tracker.active_sessions == 1
        tracker.release_session()
        assert tracker.active_sessions == 0
        tracker.release_session()
        assert tracker.active_sessions == 0


class TestMCPServerBudgetIntegration:
    def test_mcp_server_applies_budget_checks(self):
        server = RigMCPServer()

        raw = json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
        result = server.process_jsonrpc_sync(raw)
        parsed = json.loads(result)
        assert parsed["id"] == 1
        assert "result" in parsed

    def test_mcp_server_rejects_when_pending_full(self):
        budgets = TransportBudgets(max_pending_requests=0)
        tracker = BudgetTracker(budgets=budgets)
        server = RigMCPServer()
        server._budgets = tracker

        raw = json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
        result = server.process_jsonrpc_sync(raw)
        parsed = json.loads(result)
        assert parsed["error"]["code"] == -32000

    def test_mcp_server_rejects_when_oversized(self):
        budgets = TransportBudgets(max_request_bytes=10)
        tracker = BudgetTracker(budgets=budgets)
        server = RigMCPServer()
        server._budgets = tracker

        raw = json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
        result = server.process_jsonrpc_sync(raw)
        parsed = json.loads(result)
        assert parsed["error"]["code"] == -32000

    def test_mcp_server_budget_tracker_exposed(self):
        server = RigMCPServer()
        tracker = server.budget_tracker
        assert isinstance(tracker, BudgetTracker)
        assert tracker.pending_requests == 0

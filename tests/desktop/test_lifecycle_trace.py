from __future__ import annotations

import json
from pathlib import Path
import secrets

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend" / "desktop"


@pytest.fixture
def bridge_token() -> str:
    return secrets.token_hex(32)


@pytest.fixture
def evidence_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("evidence")
    # Ensure the lifecycle artifact writer can find this dir
    return d


class TestLifecycleStepsModule:
    def test_all_steps_have_order(self):
        from rig_relay.desktop.lifecycle_steps import LifecycleStep, step_order

        for step in LifecycleStep:
            assert step_order(step) > 0 or step_order(step) == 999, (
                f"Step {step} has no order"
            )

    def test_required_steps_are_non_empty(self):
        from rig_relay.desktop.lifecycle_steps import REQUIRED_FOR_READY

        assert len(REQUIRED_FOR_READY) > 0

    def test_frontend_steps_required_for_ready(self):
        from rig_relay.desktop.lifecycle_steps import REQUIRED_FOR_READY, LifecycleStep

        assert LifecycleStep.FRONTEND_PROJECTION_RENDER_OK in REQUIRED_FOR_READY
        assert LifecycleStep.FRONTEND_WIDGETS_MOUNT_OK in REQUIRED_FOR_READY
        assert LifecycleStep.FRONTEND_READY in REQUIRED_FOR_READY

    def test_static_probes_not_sufficient_for_ready(self):
        from rig_relay.desktop.lifecycle_steps import REQUIRED_FOR_READY, LifecycleStep

        # Static probes (bridge:01-bridge:13) are NOT in required-for-ready
        # except bridge_server_bound and bridge_runtime_config_served
        static_probes = {
            LifecycleStep.BRIDGE_FRONTEND_DIR_RESOLVED,
            LifecycleStep.BRIDGE_INDEX_RESOLVED,
            LifecycleStep.BRIDGE_ASSETS_VERIFIED,
            LifecycleStep.BRIDGE_CONFIG_BUILT,
            LifecycleStep.BRIDGE_WEBSOCKET_SERVER_CREATED,
            LifecycleStep.BRIDGE_HEALTH_PROBED,
            LifecycleStep.BRIDGE_INDEX_PROBED,
            LifecycleStep.BRIDGE_MODULE_PROBED,
            LifecycleStep.BRIDGE_ENTRYPOINT_PROBED,
            LifecycleStep.BRIDGE_CSS_PROBED,
            LifecycleStep.BRIDGE_WINDOW_CREATED,
            LifecycleStep.BRIDGE_WINDOW_STARTED,
        }
        for step in static_probes:
            assert step not in REQUIRED_FOR_READY, (
                f"Static probe {step} must not be required for ready"
            )

    def test_missing_required_step_fails(self):
        from rig_relay.desktop.lifecycle_steps import (
            REQUIRED_FOR_READY,
            LifecycleStep,
            validate_lifecycle_completeness,
        )

        # Almost all required steps complete, but missing frontend_ready
        almost = set(REQUIRED_FOR_READY) - {LifecycleStep.FRONTEND_READY}
        is_ready, missing = validate_lifecycle_completeness(almost)
        assert not is_ready
        assert LifecycleStep.FRONTEND_READY in missing

    def test_frontend_failed_prevents_ready(self):
        from rig_relay.desktop.lifecycle_steps import (
            LifecycleStep,
            validate_lifecycle_completeness,
        )

        steps = {LifecycleStep.FRONTEND_FAILED}
        is_ready, _ = validate_lifecycle_completeness(steps)
        assert not is_ready

    def test_lifecycle_step_from_bridge_id(self):
        from rig_relay.desktop.lifecycle_steps import (
            LifecycleStep,
            lifecycle_step_from_bridge_id,
        )

        assert (
            lifecycle_step_from_bridge_id("bridge:01")
            == LifecycleStep.BRIDGE_FRONTEND_DIR_RESOLVED
        )
        assert (
            lifecycle_step_from_bridge_id("bridge:18")
            == LifecycleStep.FRONTEND_PROJECTION_RENDER_OK
        )
        assert lifecycle_step_from_bridge_id("nonexistent") is None


class TestLifecycleArtifactWriter:
    def test_writes_jsonl_with_correct_schema(self, evidence_dir):
        from rig_relay.desktop.lifecycle_artifact import LifecycleArtifactWriter

        writer = LifecycleArtifactWriter(evidence_dir=evidence_dir)
        writer.set_handshake_id("test-handshake")
        writer.write_event(
            step_id="bridge_server_bound",
            status="ok",
            source="backend",
            handshake_id="test-handshake",
        )
        writer.write_event(
            step_id="frontend_ready",
            status="ok",
            source="frontend",
            handshake_id="test-handshake",
        )

        assert writer.artifact_path.is_file()
        lines = writer.artifact_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            event = json.loads(line)
            assert event["schema_version"] == "rig.relay.bridge_lifecycle_event.v1"
            assert event["handshake_id"] == "test-handshake"

    def test_events_correlated_by_handshake(self, evidence_dir):
        from rig_relay.desktop.lifecycle_artifact import LifecycleArtifactWriter

        writer = LifecycleArtifactWriter(evidence_dir=evidence_dir)
        writer.set_handshake_id("corr_abc123")
        for i in range(5):
            writer.write_event(
                step_id=f"test_step_{i}",
                status="ok",
                source="backend" if i % 2 == 0 else "frontend",
                handshake_id="corr_abc123",
            )

        lines = writer.artifact_path.read_text(encoding="utf-8").strip().split("\n")
        for line in lines:
            event = json.loads(line)
            assert event["handshake_id"] == "corr_abc123"
            assert event["sequence"] > 0
            assert event["timestamp"]
            assert event["event_id"]

    def test_summary_marks_incomplete_without_frontend_events(self, evidence_dir):
        from rig_relay.desktop.lifecycle_artifact import LifecycleArtifactWriter

        writer = LifecycleArtifactWriter(evidence_dir=evidence_dir)
        writer.set_handshake_id("test-handshake")

        # Only backend events
        for step in ["bridge_server_bound", "bridge_runtime_config_served"]:
            writer.write_event(
                step_id=step,
                status="ok",
                source="backend",
                handshake_id="test-handshake",
            )

        summary = writer.build_summary()
        assert summary.overall_status != "ready"
        assert len(summary.missing_steps) > 0

    def test_summary_marks_ready_when_all_required_complete(self, evidence_dir):
        from rig_relay.desktop.lifecycle_artifact import LifecycleArtifactWriter

        writer = LifecycleArtifactWriter(evidence_dir=evidence_dir)
        writer.set_handshake_id("test-handshake")

        required = [
            ("bridge_server_bound", "ok", "backend"),
            ("bridge_runtime_config_served", "ok", "backend"),
            ("frontend_runtime_config_loaded", "ok", "frontend"),
            ("frontend_websocket_constructed", "ok", "frontend"),
            ("frontend_auth_ok", "ok", "frontend"),
            ("backend_ws_auth_ok", "ok", "websocket"),
            ("frontend_projection_received", "ok", "frontend"),
            ("frontend_projection_render_ok", "ok", "frontend"),
            ("frontend_widgets_mount_ok", "ok", "frontend"),
            ("frontend_ready", "ok", "frontend"),
        ]
        for step_id, status, source in required:
            writer.write_event(
                step_id=step_id,
                status=status,
                source=source,
                handshake_id="test-handshake",
            )

        summary = writer.build_summary()
        assert summary.overall_status == "ready"
        assert len(summary.missing_steps) == 0

    def test_summary_marks_failed_on_error(self, evidence_dir):
        from rig_relay.desktop.lifecycle_artifact import LifecycleArtifactWriter

        writer = LifecycleArtifactWriter(evidence_dir=evidence_dir)
        writer.set_handshake_id("test-handshake")
        writer.write_event(
            step_id="frontend_projection_render_ok",
            status="failed",
            source="frontend",
            handshake_id="test-handshake",
            error_message="render error",
        )
        writer.write_event(
            step_id="frontend_failed",
            status="ok",
            source="frontend",
            handshake_id="test-handshake",
        )

        summary = writer.build_summary()
        assert summary.overall_status == "failed"
        assert summary.first_failure_step == "frontend_projection_render_ok"
        assert "render error" in summary.first_failure_reason

    def test_safe_details_serialized_without_tokens(self, evidence_dir):
        from rig_relay.desktop.lifecycle_artifact import LifecycleArtifactWriter

        writer = LifecycleArtifactWriter(evidence_dir=evidence_dir)
        writer.set_handshake_id("test-handshake")
        writer.write_event(
            step_id="bridge_server_bound",
            status="ok",
            source="backend",
            handshake_id="test-handshake",
            safe_details={"host": "127.0.0.1", "port": 8765, "token_present": True},
        )

        lines = writer.artifact_path.read_text(encoding="utf-8").strip().split("\n")
        event = json.loads(lines[0])
        details = event.get("safe_details", {})
        assert "token" not in details
        assert "access_token" not in details
        assert "refresh_token" not in details
        assert details.get("token_present") is True

    def test_thread_safety(self, evidence_dir):
        import concurrent.futures

        from rig_relay.desktop.lifecycle_artifact import LifecycleArtifactWriter

        writer = LifecycleArtifactWriter(evidence_dir=evidence_dir)
        writer.set_handshake_id("hs")

        def write_one(i):
            writer.write_event(
                step_id=f"step_{i}", status="ok", source="backend", handshake_id="hs"
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            list(ex.map(write_one, range(20)))

        events = writer.get_events()
        assert len(events) == 20
        sequences = {e.sequence for e in events}
        assert len(sequences) >= 19

    def test_clear_handshake_resets(self, evidence_dir):
        from rig_relay.desktop.lifecycle_artifact import LifecycleArtifactWriter

        writer = LifecycleArtifactWriter(evidence_dir=evidence_dir)
        writer.set_handshake_id("first")
        writer.write_event(step_id="a", status="ok", source="backend")
        writer.clear_for_new_handshake()
        writer.set_handshake_id("second")
        writer.write_event(step_id="b", status="ok", source="frontend")
        events = writer.get_events()
        assert len(events) == 1
        assert events[0].handshake_id == "second"


class TestLifecycleBridgeIntegration:
    @pytest.mark.asyncio
    async def test_bridge_startup_writes_lifecycle_events(
        self, bridge_token, evidence_dir
    ):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        # Minor patch: inject evidence_dir into lifecycle writer
        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=FRONTEND_DIR, auth_token=bridge_token
        )
        server = DesktopBridgeServer(config)
        server._lifecycle_writer.evidence_dir = evidence_dir

        await server.start()
        try:
            # Check that backend lifecycle events were written
            events = server._lifecycle_writer.get_events()
            backend_events = [e for e in events if e.source == "backend"]
            assert len(backend_events) >= 3, (
                f"Expected at least 3 backend lifecycle events, got {len(backend_events)}"
            )

            # Check later events have handshake_id once it's assigned
            hsid = server._golden_handshake_id
            for e in events:
                assert e.schema_version == "rig.relay.bridge_lifecycle_event.v1"
                if e.handshake_id:
                    assert e.handshake_id == hsid

            # Check required backend steps are present
            step_ids = {e.step_id for e in events}
            assert "bridge_server_bound" in step_ids
            assert "bridge_config_built" in step_ids
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_lifecycle_events_are_ordered(self, bridge_token, evidence_dir):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=FRONTEND_DIR, auth_token=bridge_token
        )
        server = DesktopBridgeServer(config)
        server._lifecycle_writer.evidence_dir = evidence_dir

        await server.start()
        try:
            events = server._lifecycle_writer.get_events()
            sequences = [e.sequence for e in events]
            assert sequences == sorted(sequences), (
                "Lifecycle event sequences must be monotonic"
            )
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_lifecycle_summary_written_on_stop(self, bridge_token, evidence_dir):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=FRONTEND_DIR, auth_token=bridge_token
        )
        server = DesktopBridgeServer(config)
        server._lifecycle_writer.evidence_dir = evidence_dir

        await server.start()
        await server.stop()

        # Summary should exist
        summary_path = evidence_dir / "bridge_lifecycle_summary.v1.json"
        assert summary_path.is_file(), f"Summary not found at {summary_path}"
        summary = json.loads(summary_path.read_text())
        assert summary["handshake_id"] == server._golden_handshake_id
        assert summary["overall_status"] in ("incomplete", "failed")
        # Without frontend events, summary should NOT be "ready"
        assert summary["overall_status"] != "ready"

    @pytest.mark.asyncio
    async def test_static_probes_do_not_produce_ready(self, bridge_token, evidence_dir):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=FRONTEND_DIR, auth_token=bridge_token
        )
        server = DesktopBridgeServer(config)
        server._lifecycle_writer.evidence_dir = evidence_dir

        await server.start()
        await server.stop()

        summary = json.loads(
            evidence_dir.joinpath("bridge_lifecycle_summary.v1.json").read_text()
        )
        # Without frontend projection render and widget mount events, must NOT be ready
        assert summary["overall_status"] != "ready", (
            "Static backend probes alone must not produce ready status"
        )

    @pytest.mark.asyncio
    async def test_jsonl_artifact_has_no_markdown(self, bridge_token, evidence_dir):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=FRONTEND_DIR, auth_token=bridge_token
        )
        server = DesktopBridgeServer(config)
        server._lifecycle_writer.evidence_dir = evidence_dir
        await server.start()
        await server.stop()

        artifact_path = evidence_dir / "bridge_lifecycle_trace.v1.jsonl"
        if artifact_path.is_file():
            content = artifact_path.read_text()
            # No markdown headers
            assert "# " not in content
            assert "## " not in content
            # Every line is valid JSON
            for line in content.strip().split("\n"):
                json.loads(line)

    @pytest.mark.asyncio
    async def test_frontend_event_get_endpoint_works(self, bridge_token, evidence_dir):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=FRONTEND_DIR, auth_token=bridge_token
        )
        server = DesktopBridgeServer(config)
        server._lifecycle_writer.evidence_dir = evidence_dir
        await server.start()
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                # GET with query params — the frontend's fallback event delivery
                url = (
                    f"http://127.0.0.1:{server.bound_port}/frontend-event"
                    f"?type=frontend_boot_started"
                    f"&handshake_id={server._golden_handshake_id}"
                )
                resp = await client.get(url)
                assert resp.status_code == 200
        finally:
            await server.stop()

        # Check that the token is NOT in lifecycle artifact
        artifact_path = evidence_dir / "bridge_lifecycle_trace.v1.jsonl"
        if artifact_path.is_file():
            content = artifact_path.read_text()
            assert bridge_token not in content, (
                "Token leaked in lifecycle trace artifact!"
            )
        summary_path = evidence_dir / "bridge_lifecycle_summary.v1.json"
        if summary_path.is_file():
            content = summary_path.read_text()
            assert bridge_token not in content, "Token leaked in lifecycle summary!"

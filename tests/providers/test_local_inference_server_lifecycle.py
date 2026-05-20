"""Server lifecycle executor tests — plan mode, subprocess mock, port collision, health probe."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import httpx
import respx

from rig_relay.providers.local_inference.models import RuntimeBackend
from rig_relay.providers.local_inference.server_lifecycle_executor import (
    _check_port_free,
    probe_server_health,
    start_server,
    stop_server,
)


def _auto_start_backend(backend_id: str = "ollama", **overrides) -> RuntimeBackend:
    base: dict = {
        "backend_id": backend_id,
        "display_name": "Test",
        "executable_name": "test-exec",
        "default_host": "127.0.0.1",
        "default_port": 11434,
        "health_endpoint": "/health",
        "start_command_template": "test-exec --port {port}",
        "auto_start_allowed_default": True,
    }
    base.update(overrides)
    return RuntimeBackend(**base)


class TestStartServerPlanMode:
    def test_plan_mode_does_not_start_process(self) -> None:
        receipt = start_server(backend_id="llama_cpp_server", execute=False)
        assert receipt.pid == 0
        assert receipt.started_by_rig is False
        assert receipt.lifecycle_action == "plan"
        assert "execute_flag_not_set" in receipt.blocked_reasons

    def test_plan_mode_populates_command_hash(self) -> None:
        receipt = start_server(backend_id="llama_cpp_server", execute=False)
        assert receipt.command_hash
        assert len(receipt.command_hash) == 64
        assert receipt.command_safe_preview

    def test_unknown_backend_blocks(self) -> None:
        receipt = start_server(backend_id="nonexistent", execute=False)
        assert any("unknown_backend" in r for r in receipt.blocked_reasons)

    def test_no_template_blocks(self) -> None:
        receipt = start_server(backend_id="custom_openai_compatible", execute=False)
        assert "no_start_command_template" in receipt.blocked_reasons

    def test_non_localhost_host_blocked(self) -> None:
        receipt = start_server(
            backend_id="llama_cpp_server", host="192.168.1.1", execute=False
        )
        assert "host_not_localhost" in receipt.blocked_reasons
        assert receipt.remote_network_exposed is True
        assert receipt.localhost_only is False

    def test_all_zeros_host_blocked(self) -> None:
        receipt = start_server(
            backend_id="llama_cpp_server", host="0.0.0.0", execute=False
        )
        assert "host_not_localhost" in receipt.blocked_reasons
        assert receipt.remote_network_exposed is True
        assert receipt.localhost_only is False

    def test_auto_start_not_allowed_blocks_execute(self) -> None:
        receipt = start_server(backend_id="llama_cpp_server", execute=True)
        assert "auto_start_not_allowed" in receipt.blocked_reasons
        assert receipt.started_by_rig is False


class TestStartServerMockedProcess:
    def test_fake_server_start_launches_subprocess(self) -> None:
        backend = _auto_start_backend("ollama")
        fake_proc = MagicMock(spec=subprocess.Popen)
        fake_proc.pid = 12345

        with (
            patch(
                "rig_relay.providers.local_inference.server_lifecycle_executor.get_backend",
                return_value=backend,
            ),
            patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
            patch(
                "rig_relay.providers.local_inference.server_lifecycle_executor._check_port_free",
                return_value=True,
            ),
            patch("httpx.Client") as mock_httpx_client,
        ):
            mock_instance = mock_httpx_client.return_value.__enter__.return_value
            mock_instance.get.return_value.status_code = 200

            receipt = start_server(
                backend_id="ollama", host="127.0.0.1", port=11434, execute=True
            )

        assert mock_popen.called
        assert receipt.pid == 12345
        assert receipt.started_by_rig is True
        assert receipt.lifecycle_action == "start"
        assert receipt.health_status == "ok"

    def test_start_passes_command_from_template(self) -> None:
        backend = _auto_start_backend(
            "llama_cpp_server",
            executable_name="llama-server",
            start_command_template="llama-server -m {model_path} --host {host} --port {port}",
        )
        fake_proc = MagicMock(spec=subprocess.Popen)
        fake_proc.pid = 99

        with (
            patch(
                "rig_relay.providers.local_inference.server_lifecycle_executor.get_backend",
                return_value=backend,
            ),
            patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
            patch(
                "rig_relay.providers.local_inference.server_lifecycle_executor._check_port_free",
                return_value=True,
            ),
            patch("httpx.Client") as mock_httpx_client,
        ):
            mock_instance = mock_httpx_client.return_value.__enter__.return_value
            mock_instance.get.return_value.status_code = 200

            start_server(
                backend_id="llama_cpp_server",
                host="127.0.0.1",
                port=9090,
                model_path="/models/test.gguf",
                model_id="test-model",
                execute=True,
            )

        call_args = mock_popen.call_args[0][0]
        assert "llama-server" in call_args
        assert "--port" in call_args
        assert "9090" in call_args

    def test_executable_not_found_is_handled(self) -> None:
        backend = _auto_start_backend("ollama")

        with (
            patch(
                "rig_relay.providers.local_inference.server_lifecycle_executor.get_backend",
                return_value=backend,
            ),
            patch("subprocess.Popen", side_effect=FileNotFoundError),
            patch(
                "rig_relay.providers.local_inference.server_lifecycle_executor._check_port_free",
                return_value=True,
            ),
        ):
            receipt = start_server(
                backend_id="ollama", host="127.0.0.1", port=11434, execute=True
            )

        assert receipt.lifecycle_action == "start_failed"
        assert any("executable_not_found" in r for r in receipt.blocked_reasons)
        assert receipt.started_by_rig is False

    def test_health_poll_reports_unhealthy_after_timeout(self) -> None:
        backend = _auto_start_backend("ollama", health_endpoint="/health")
        fake_proc = MagicMock(spec=subprocess.Popen)
        fake_proc.pid = 99

        with (
            patch(
                "rig_relay.providers.local_inference.server_lifecycle_executor.get_backend",
                return_value=backend,
            ),
            patch("subprocess.Popen", return_value=fake_proc),
            patch(
                "rig_relay.providers.local_inference.server_lifecycle_executor._check_port_free",
                return_value=True,
            ),
            patch("httpx.Client") as mock_httpx_client,
        ):
            mock_instance = mock_httpx_client.return_value.__enter__.return_value
            mock_instance.get.side_effect = httpx.ConnectError("refused")

            receipt = start_server(
                backend_id="ollama",
                host="127.0.0.1",
                port=11434,
                execute=True,
                timeout_sec=1,
            )

        assert receipt.health_status == "unhealthy"


class TestPortCollision:
    def test_port_collision_blocks_start(self) -> None:
        backend = _auto_start_backend("ollama")

        with (
            patch(
                "rig_relay.providers.local_inference.server_lifecycle_executor.get_backend",
                return_value=backend,
            ),
            patch(
                "rig_relay.providers.local_inference.server_lifecycle_executor._check_port_free",
                return_value=False,
            ),
        ):
            receipt = start_server(
                backend_id="ollama", host="127.0.0.1", port=11434, execute=True
            )

        assert receipt.port_collision_detected is True
        assert any("port_occupied" in r for r in receipt.blocked_reasons)
        assert receipt.lifecycle_action == "start_blocked"
        assert receipt.started_by_rig is False

    def test_check_port_free_returns_false_when_connectable(self) -> None:
        with patch("socket.create_connection", return_value=MagicMock()):
            result = _check_port_free("127.0.0.1", 19999)
            assert result is False

    def test_check_port_free_returns_true_when_refused(self) -> None:
        with patch("socket.create_connection", side_effect=ConnectionRefusedError):
            result = _check_port_free("127.0.0.1", 19999)
            assert result is True

    def test_ollama_enabled_default_is_false(self) -> None:
        from rig_relay.providers.local_inference.backend_registry import get_backend

        backend = get_backend("ollama")
        assert backend is not None
        assert backend.auto_start_allowed_default is False


class TestHealthProbeRespx:
    def test_health_probe_succeeds_for_reachable_endpoint(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.get("http://127.0.0.1:18080/health").respond(
                200, json={"status": "ok"}
            )

            receipt = probe_server_health("http://127.0.0.1:18080", port=18080)

        assert receipt.health_status == "ok"
        assert receipt.lifecycle_action == "health_probe"

    def test_health_probe_fails_for_unreachable_endpoint(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.get("http://127.0.0.1:19999/health").mock(
                side_effect=httpx.ConnectError("connection refused")
            )

            receipt = probe_server_health("http://127.0.0.1:19999", port=19999)

        assert receipt.health_status == "unreachable"

    def test_health_probe_handles_500_response(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.get("http://127.0.0.1:18081/health").respond(500)

            receipt = probe_server_health("http://127.0.0.1:18081", port=18081)

        assert receipt.health_status == "unhealthy"

    def test_health_probe_strips_trailing_slash(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.get("http://127.0.0.1:18082/health").respond(200)

            receipt = probe_server_health("http://127.0.0.1:18082/", port=18082)

        assert receipt.health_status == "ok"


class TestStopServer:
    def test_stop_plan_mode_does_not_kill(self) -> None:
        receipt = stop_server("ollama", pid=1234, execute=False)
        assert receipt.lifecycle_action == "plan"
        assert receipt.stopped_by_rig is False
        assert "execute_flag_not_set" in receipt.blocked_reasons

    def test_stop_with_pid_kills_process(self) -> None:
        with patch(
            "rig_relay.providers.local_inference.server_lifecycle_executor._kill_process"
        ) as mock_kill:
            receipt = stop_server("ollama", pid=1234, execute=True)

        mock_kill.assert_called_once_with(1234)
        assert receipt.stopped_by_rig is True
        assert receipt.health_status == "stopped"

    def test_stop_no_pid_or_port_blocks(self) -> None:
        receipt = stop_server("ollama", execute=True)
        assert "no_pid_or_port_provided" in receipt.blocked_reasons
        assert receipt.stopped_by_rig is False

    def test_stop_port_no_process_found_reports_stopped(self) -> None:
        with patch(
            "rig_relay.providers.local_inference.server_lifecycle_executor._find_pid_on_port",
            return_value=0,
        ):
            receipt = stop_server("ollama", port=11434, execute=True)

        assert receipt.stopped_by_rig is True
        assert receipt.health_status == "stopped"


class TestNonLocalhostBlocked:
    def test_localhost_is_allowed(self) -> None:
        receipt = start_server(
            backend_id="llama_cpp_server", host="localhost", execute=False
        )
        assert "host_not_localhost" not in receipt.blocked_reasons

    def test_loopback_is_allowed(self) -> None:
        receipt = start_server(
            backend_id="llama_cpp_server", host="127.0.0.1", execute=False
        )
        assert "host_not_localhost" not in receipt.blocked_reasons

    def test_0_0_0_0_is_blocked(self) -> None:
        receipt = start_server(
            backend_id="llama_cpp_server", host="0.0.0.0", execute=False
        )
        assert "host_not_localhost" in receipt.blocked_reasons

    def test_public_ip_is_blocked(self) -> None:
        receipt = start_server(
            backend_id="llama_cpp_server", host="10.0.0.1", execute=False
        )
        assert "host_not_localhost" in receipt.blocked_reasons

from __future__ import annotations

import socket
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import local_platform as supervisor  # noqa: E402


def test_compose_file_is_discovered() -> None:
    assert supervisor.compose_file().name in {
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
    }


def test_environment_overrides_are_applied(monkeypatch) -> None:
    monkeypatch.setenv("PLATFORM_TEST_VALUE", "before")
    result = supervisor.child_environment(
        PLATFORM_TEST_VALUE="after",
        PORT="3100",
    )
    assert result["PLATFORM_TEST_VALUE"] == "after"
    assert result["PORT"] == "3100"


def test_port_detection_reports_bound_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        assert supervisor.port_is_free(port) is False


def test_port_detection_reports_available_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    assert supervisor.port_is_free(port) is True


def test_supervisor_uses_fixed_runtime_ports() -> None:
    assert supervisor.FIXED_API_PORT == 8000
    assert supervisor.FIXED_PORTAL_PORT == 3000
    assert supervisor.API_URL == "http://127.0.0.1:8000"
    assert supervisor.PORTAL_URL == "http://127.0.0.1:3000"


def test_fixed_runtime_environment_uses_authoritative_ports() -> None:
    result = supervisor.fixed_runtime_environment()

    assert result["API_PORT"] == "8000"
    assert result["PORTAL_PORT"] == "3000"
    assert result["API_INTERNAL_BASE_URL"] == "http://api:8000"

from __future__ import annotations

import ast
import importlib.util
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ENTRYPOINT = SCRIPTS / "local_platform.py"
POWERSHELL_LAUNCHER = SCRIPTS / "platform_local.ps1"


def test_local_platform_entrypoint_is_self_contained() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported_from_modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    for obsolete in ("platform_local_runtime", "platform_local_v2", "platform_local_v3"):
        assert obsolete not in imported_modules
        assert obsolete not in imported_from_modules


def test_obsolete_local_supervisor_files_are_removed() -> None:
    obsolete = (
        SCRIPTS / "platform_local_runtime.py",
        SCRIPTS / "platform_local_v2.py",
        SCRIPTS / "platform_local_v3.py",
    )
    assert all(not path.exists() for path in obsolete)


def test_local_platform_uses_fixed_api_and_portal_ports() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "FIXED_API_PORT = 8000" in source
    assert "FIXED_PORTAL_PORT = 3000" in source
    assert '"--api-port"' not in source
    assert '"--portal-port"' not in source
    assert "API_INTERNAL_BASE_URL=API_URL" in source
    assert "PORT=str(FIXED_PORTAL_PORT)" in source


def test_compose_down_includes_every_optional_profile_and_orphan_cleanup() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert 'COMPOSE_PROFILES = ("object-storage", "ai", "ingestion")' in source
    assert 'compose_command("down", "--remove-orphans", include_all_profiles=True)' in source
    assert 'subcommands.add_parser("compose-down"' in source
    assert 'down_parser.add_argument("--volumes"' in source


def test_compose_up_checks_fixed_ports_and_verifies_external_endpoints() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert 'subcommands.add_parser("compose-up"' in source
    assert 'require_free_port(FIXED_API_PORT, "Compose API")' in source
    assert 'require_free_port(FIXED_PORTAL_PORT, "Compose portal")' in source
    assert 'wait_http(f"{API_URL}/health/ready")' in source
    assert 'wait_http(f"{PORTAL_URL}/operations")' in source
    assert "verify_cors()" in source


def test_failed_compose_startup_collects_diagnostics_and_rolls_back() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "def diagnose_compose_failure(" in source
    assert 'compose_command("ps", "--all")' in source
    assert 'compose_command("logs", "--tail", "80", "api", "portal", "scheduler", "migrator")' in source
    assert "def rollback_compose_start(" in source
    assert "if not args.keep_failed:" in source
    assert 'up_parser.add_argument("--keep-failed"' in source


@pytest.mark.parametrize("keep_failed", [False, True])
def test_compose_up_nonzero_exit_handles_partial_stack(monkeypatch, keep_failed: bool) -> None:
    spec = importlib.util.spec_from_file_location("local_platform", ENTRYPOINT)
    assert spec is not None and spec.loader is not None
    platform = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(platform)
    environment = {"API_PORT": "8000", "PORTAL_PORT": "3000"}
    commands = []
    resources = []

    monkeypatch.setattr(platform, "require_free_port", lambda *_args: None)
    monkeypatch.setattr(platform, "executable", lambda name: name)
    monkeypatch.setattr(platform, "fixed_runtime_environment", lambda: environment)

    def fake_run(command, **kwargs):
        assert kwargs["env"] is environment
        commands.append(command)
        if "up" in command:
            resources.extend(["postgres", "api"])
            return subprocess.CompletedProcess(command, 1)
        assert resources == ["postgres", "api"]
        if "down" in command:
            resources.clear()
        return subprocess.CompletedProcess(command, 0)

    def unexpected_http(*_args):
        pytest.fail("HTTP verification must not run after compose up fails")

    monkeypatch.setattr(platform.subprocess, "run", fake_run)
    monkeypatch.setattr(platform, "wait_http", unexpected_http)
    with pytest.raises(RuntimeError, match=r"Command failed \(1\)"):
        platform.compose_up(Namespace(build=True, keep_failed=keep_failed))

    assert commands[0] == platform.compose_command("up", "--build", "-d")
    assert commands[1] == platform.compose_command("ps", "--all")
    assert commands[2] == platform.compose_command("logs", "--tail", "80", "api", "portal", "scheduler", "migrator")
    if keep_failed:
        assert len(commands) == 3
        assert resources == ["postgres", "api"]
    else:
        assert commands[3] == platform.compose_command("down", "--remove-orphans", include_all_profiles=True)
        assert len(commands) == 4
        assert resources == []


def test_status_command_combines_runtime_and_configuration_state() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert 'subcommands.add_parser("status"' in source
    assert 'compose_command("ps", "--all", "--format", "json")' in source
    assert "/health/live" in source
    assert "/health/ready" in source
    assert "/platform/status" in source
    assert "/platform/configuration" in source
    assert '"fixed_ports": {"api": FIXED_API_PORT, "portal": FIXED_PORTAL_PORT}' in source


def test_port_diagnostics_cover_ipv4_ipv6_and_process_ownership() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "def _windows_port_listeners(" in source
    assert "Get-NetTCPConnection" in source
    assert "OwningProcess" in source
    assert "def _unix_port_listeners(" in source
    assert "socket.AF_INET6" in source
    assert "socket.IPV6_V6ONLY" in source
    assert "wslrelay" in source
    assert "Docker Desktop" in source
    assert "Python/Uvicorn" in source


def test_powershell_launcher_removes_api_and_portal_overrides() -> None:
    source = POWERSHELL_LAUNCHER.read_text(encoding="utf-8")
    assert 'ValidateSet("doctor", "port-check", "status", "serve", "compose-up", "compose-down")' in source
    assert "$ApiPort" not in source
    assert "$PortalPort" not in source
    assert "--api-port" not in source
    assert "--portal-port" not in source
    assert "\nelif " not in source

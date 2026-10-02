from __future__ import annotations

import importlib.util
import io
import json
import socket
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

LOCAL_SERVICES_PATH = Path(__file__).resolve().parents[2] / "scripts" / "local_services.py"
LOCAL_SERVICES_MODULE_NAME = "industrial_ai_platform_local_services"
LOCAL_SERVICES_SPEC = importlib.util.spec_from_file_location(
    LOCAL_SERVICES_MODULE_NAME,
    LOCAL_SERVICES_PATH,
)
if LOCAL_SERVICES_SPEC is None or LOCAL_SERVICES_SPEC.loader is None:
    raise ImportError(f"could not load local services module from {LOCAL_SERVICES_PATH}")
services = importlib.util.module_from_spec(LOCAL_SERVICES_SPEC)
sys.modules[LOCAL_SERVICES_MODULE_NAME] = services
LOCAL_SERVICES_SPEC.loader.exec_module(services)


def repository(tmp_path: Path, *, windows: bool = False) -> Path:
    root = tmp_path / "checkout"
    (root / "apps" / "api" / ".venv" / ("Scripts" if windows else "bin")).mkdir(parents=True)
    python = root / "apps" / "api" / ".venv" / ("Scripts/python.exe" if windows else "bin/python")
    python.write_text("", encoding="utf-8")
    python.chmod(0o755)
    (root / "package-lock.json").write_text("{}", encoding="utf-8")
    return root


def specs_for(
    root: Path,
    *,
    windows: bool = False,
    portal_mode: str = "development",
) -> dict[str, services.ServiceSpec]:
    npm = "C:/Program Files/nodejs/npm.cmd" if windows else "/usr/local/bin/npm"
    node = "C:/Program Files/nodejs/node.exe" if windows else "/usr/local/bin/node"
    return services.build_service_specs(
        root,
        "nt" if windows else "posix",
        which=lambda name: node if name.lower().startswith("node") else npm,
        portal_mode=portal_mode,
    )


def metadata_for(spec: services.ServiceSpec, root: Path, runtime: Path, *, pid: int = 321) -> dict[str, object]:
    return {
        "schema_version": services.STATE_SCHEMA_VERSION,
        "service": spec.name,
        "pid": pid,
        "service_pid": pid + 1,
        "checkout": str(root.resolve()),
        "command": list(spec.command),
        "port": spec.port,
        "url": spec.url,
        "health_url": spec.health_url,
        "started_at": "2026-01-01T00:00:00+00:00",
        "identity_token": "a" * 64,
        "control_port": 43210,
        "log": str(services.log_path(spec.name, runtime).resolve()),
        "platform": sys.platform,
    }


def authenticated_response(
    spec: services.ServiceSpec,
    metadata: dict[str, object],
    *,
    action: str = "probe",
    nonce: str = "b" * 32,
) -> dict[str, object]:
    supervisor_pid = int(metadata["pid"])
    return {
        "authenticated": True,
        "action": action,
        "nonce": nonce,
        "service": spec.name,
        "checkout": metadata["checkout"],
        "command": metadata["command"],
        "port": spec.port,
        "platform": metadata["platform"],
        "supervisor_pid": supervisor_pid,
        "service_pid": metadata["service_pid"],
        "service_process_running": True,
        "proof": services.control_proof(
            str(metadata["identity_token"]),
            "response",
            action,
            nonce,
            supervisor_pid,
        ),
    }


def write_metadata(spec: services.ServiceSpec, root: Path, runtime: Path, *, pid: int = 321) -> dict[str, object]:
    metadata = metadata_for(spec, root, runtime, pid=pid)
    services.atomic_write_json(services.state_path(spec.name, runtime), metadata)
    return metadata


def inspection(spec: services.ServiceSpec, state: str) -> services.ServiceInspection:
    managed = state.startswith("running/")
    healthy = state == "running/healthy"
    return services.ServiceInspection(
        spec=spec,
        state=state,
        process_running=managed,
        healthy=healthy,
        managed=managed,
        metadata={"pid": 100, "log": "test.log"} if managed else None,
        detail="test",
        port_busy=managed or state == "foreign port owner",
    )


def test_both_services_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    monkeypatch.setattr(services, "port_is_busy", lambda _port: False)

    states = [services.inspect_service(spec, root, runtime).state for spec in specs_for(root).values()]

    assert states == ["stopped", "stopped"]


def test_both_services_managed_and_healthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    specs = specs_for(root)
    records = {name: write_metadata(spec, root, runtime) for name, spec in specs.items()}
    monkeypatch.setattr(services, "port_is_busy", lambda _port: True)
    monkeypatch.setattr(
        services,
        "control_request",
        lambda metadata, _action: authenticated_response(specs[str(metadata["service"])], metadata),
    )
    monkeypatch.setattr(services, "http_health", lambda _spec: (True, "HTTP 200"))

    inspected = [services.inspect_service(spec, root, runtime) for spec in specs.values()]

    assert all(item.state == "running/healthy" and item.managed for item in inspected)
    assert set(records) == {"api", "portal"}


def test_start_does_not_duplicate_two_healthy_managed_services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = specs_for(repository(tmp_path))
    monkeypatch.setattr(services, "inspect_service", lambda spec: inspection(spec, "running/healthy"))
    monkeypatch.setattr(
        services,
        "launch_service",
        lambda _spec: (_ for _ in ()).throw(AssertionError("service must not be duplicated")),
    )

    assert services.start_services(specs) == 0


def test_only_api_active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    specs = specs_for(root)
    metadata = write_metadata(specs["api"], root, runtime)
    monkeypatch.setattr(services, "port_is_busy", lambda port: port == services.API_PORT)
    monkeypatch.setattr(
        services,
        "control_request",
        lambda _metadata, _action: authenticated_response(specs["api"], metadata),
    )
    monkeypatch.setattr(services, "http_health", lambda _spec: (True, "HTTP 200"))

    assert services.inspect_service(specs["api"], root, runtime).state == "running/healthy"
    assert services.inspect_service(specs["portal"], root, runtime).state == "stopped"


def test_only_portal_active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    specs = specs_for(root)
    metadata = write_metadata(specs["portal"], root, runtime)
    monkeypatch.setattr(services, "port_is_busy", lambda port: port == services.PORTAL_PORT)
    monkeypatch.setattr(
        services, "control_request", lambda _metadata, _action: authenticated_response(specs["portal"], metadata)
    )
    monkeypatch.setattr(services, "http_health", lambda _spec: (True, "HTTP 200"))

    assert services.inspect_service(specs["api"], root, runtime).state == "stopped"
    assert services.inspect_service(specs["portal"], root, runtime).state == "running/healthy"


@pytest.mark.parametrize(("active", "missing"), (("api", "portal"), ("portal", "api")))
def test_start_launches_only_the_missing_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    active: str,
    missing: str,
) -> None:
    specs = specs_for(repository(tmp_path))
    states = {active: "running/healthy", missing: "stopped"}
    launched: list[str] = []

    def inspect(spec: services.ServiceSpec) -> services.ServiceInspection:
        return inspection(spec, states[spec.name])

    def launch(spec: services.ServiceSpec) -> dict[str, object]:
        launched.append(spec.name)
        states[spec.name] = "running/healthy"
        return {"pid": 123, "log": f"{spec.name}.log"}

    monkeypatch.setattr(services, "inspect_service", inspect)
    monkeypatch.setattr(services, "port_is_busy", lambda _port: False)
    monkeypatch.setattr(services, "launch_service", launch)
    monkeypatch.setattr(services, "wait_for_service", lambda spec, _metadata: inspect(spec))

    assert services.start_services(specs) == 0
    assert launched == [missing]


def test_stale_metadata_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    spec = specs_for(root)["api"]
    write_metadata(spec, root, runtime, pid=999)
    monkeypatch.setattr(services, "port_is_busy", lambda _port: False)
    monkeypatch.setattr(services, "control_request", lambda *_args: None)
    monkeypatch.setattr(services, "pid_exists", lambda _pid: False)

    assert services.inspect_service(spec, root, runtime).state == "stale metadata"


def test_reused_pid_is_unknown_and_unverifiable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    spec = specs_for(root)["api"]
    write_metadata(spec, root, runtime, pid=999)
    monkeypatch.setattr(services, "port_is_busy", lambda _port: False)
    monkeypatch.setattr(services, "control_request", lambda *_args: None)
    monkeypatch.setattr(services, "pid_exists", lambda _pid: True)

    assert services.inspect_service(spec, root, runtime).state == "unknown/unverifiable"


@pytest.mark.parametrize(("service", "port"), (("api", services.API_PORT), ("portal", services.PORTAL_PORT)))
def test_foreign_port_owner_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, service: str, port: int
) -> None:
    root = repository(tmp_path)
    spec = specs_for(root)[service]
    monkeypatch.setattr(services, "port_is_busy", lambda candidate: candidate == port)

    assert services.inspect_service(spec, root, root / "runtime" / "local-services").state == "foreign port owner"


def test_managed_process_with_failed_health_is_unhealthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    spec = specs_for(root)["api"]
    metadata = write_metadata(spec, root, runtime)
    monkeypatch.setattr(services, "port_is_busy", lambda _port: True)
    monkeypatch.setattr(services, "control_request", lambda *_args: authenticated_response(spec, metadata))
    monkeypatch.setattr(services, "http_health", lambda _spec: (False, "HTTP 503"))

    assert services.inspect_service(spec, root, runtime).state == "running/unhealthy"


def test_recently_closed_connection_does_not_count_time_wait_as_active_owner() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        port = int(server.getsockname()[1])
        server.listen(1)
        with socket.create_connection(("127.0.0.1", port), timeout=1) as client:
            accepted, _address = server.accept()
            with accepted:
                accepted.shutdown(socket.SHUT_WR)
                client.recv(1)

    assert services.active_listener(port) is False
    assert services.bind_available(port) is True
    assert services.port_is_busy(port) is False


def test_active_tcp_listener_keeps_port_busy() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
        listener.listen(1)

        assert services.active_listener(port) is True
        assert services.port_is_busy(port) is True


def test_free_port_is_reusable() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])

    assert services.active_listener(port) is False
    assert services.bind_available(port) is True
    assert services.port_is_busy(port) is False


def test_bound_socket_without_listener_keeps_port_busy() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])

        assert services.active_listener(port) is False
        assert services.bind_available(port) is False
        assert services.port_is_busy(port) is True


@pytest.mark.parametrize("service", ("api", "portal"))
def test_readiness_timeout_for_each_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, service: str) -> None:
    spec = specs_for(repository(tmp_path))[service]
    monkeypatch.setattr(services, "inspect_service", lambda _spec: inspection(spec, "running/unhealthy"))
    ticks = iter((0.0, 2.0))

    with pytest.raises(services.LocalServicesError, match="readiness timed out"):
        services.wait_for_service(spec, {"log": "service.log"}, timeout=1.0, monotonic=lambda: next(ticks))


def test_stop_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = specs_for(repository(tmp_path))["api"]
    monkeypatch.setattr(services, "inspect_service", lambda _spec: inspection(spec, "stopped"))

    assert services.stop_one(spec) is True
    assert services.stop_one(spec) is True


def test_stop_waits_for_transient_port_occupation_before_removing_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    spec = specs_for(root)["api"]
    metadata = metadata_for(spec, root, runtime)
    managed = services.ServiceInspection(
        spec,
        "running/healthy",
        True,
        True,
        True,
        metadata,
        "HTTP 200",
        True,
    )
    port_states = iter((True, True, False))
    removed: list[str] = []
    monkeypatch.setattr(services, "inspect_service", lambda _spec: managed)
    monkeypatch.setattr(services, "control_request", lambda _metadata, _action: {})
    monkeypatch.setattr(services, "identity_matches", lambda *_args: True)
    monkeypatch.setattr(services, "pid_exists", lambda _pid: False)
    monkeypatch.setattr(services, "port_is_busy", lambda _port: next(port_states))
    monkeypatch.setattr(services.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(services, "remove_stale_metadata", lambda service: removed.append(service))

    assert services.stop_one(spec) is True
    assert removed == ["api"]


def test_stop_timeout_keeps_metadata_when_port_never_releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    spec = specs_for(root)["api"]
    metadata = metadata_for(spec, root, runtime)
    managed = services.ServiceInspection(spec, "running/healthy", True, True, True, metadata, "HTTP 200", True)
    removed: list[str] = []
    monkeypatch.setattr(services, "inspect_service", lambda _spec: managed)
    monkeypatch.setattr(services, "control_request", lambda _metadata, _action: {})
    monkeypatch.setattr(services, "identity_matches", lambda *_args: True)
    monkeypatch.setattr(services, "pid_exists", lambda _pid: False)
    monkeypatch.setattr(services, "wait_for_port_release", lambda _port: False)
    monkeypatch.setattr(services, "remove_stale_metadata", lambda service: removed.append(service))

    assert services.stop_one(spec) is False
    assert removed == []


def test_port_release_polling_uses_monotonic_timeout() -> None:
    ticks = iter((10.0, 10.2, 10.5))
    sleeps: list[float] = []

    released = services.wait_for_port_release(
        services.API_PORT,
        timeout=0.5,
        poll_interval=0.1,
        busy_check=lambda _port: True,
        monotonic=lambda: next(ticks),
        sleep=sleeps.append,
    )

    assert released is False
    assert sleeps == [0.1]


def test_port_reclaimed_by_listener_during_polling_remains_blocked() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
        listener.listen(1)
        ticks = iter((20.0, 20.1, 20.5))

        released = services.wait_for_port_release(
            port,
            timeout=0.5,
            poll_interval=0.1,
            monotonic=lambda: next(ticks),
            sleep=lambda _seconds: None,
        )

        assert released is False
        assert services.port_is_busy(port) is True


def test_stop_never_terminates_foreign_process_that_reclaims_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    spec = specs_for(root)["api"]
    metadata = metadata_for(spec, root, runtime)
    managed = services.ServiceInspection(spec, "running/healthy", True, True, True, metadata, "HTTP 200", True)
    actions: list[str] = []
    removed: list[str] = []
    monkeypatch.setattr(services, "inspect_service", lambda _spec: managed)
    monkeypatch.setattr(
        services,
        "control_request",
        lambda _metadata, action: actions.append(action) or {},
    )
    monkeypatch.setattr(services, "identity_matches", lambda *_args: True)
    monkeypatch.setattr(services, "pid_exists", lambda _pid: False)
    monkeypatch.setattr(services, "wait_for_port_release", lambda _port: False)
    monkeypatch.setattr(services, "remove_stale_metadata", lambda service: removed.append(service))

    assert services.stop_one(spec) is False
    assert actions == ["stop"]
    assert removed == []


def test_restart_starts_only_after_confirmed_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = specs_for(repository(tmp_path))
    starts: list[str] = []
    monkeypatch.setattr(services, "start_services", lambda _specs: starts.append("start") or 0)
    monkeypatch.setattr(services, "stop_services", lambda _specs: 1)

    assert services.restart_services(specs) == 1
    assert starts == []

    monkeypatch.setattr(services, "stop_services", lambda _specs: 0)

    assert services.restart_services(specs) == 0
    assert starts == ["start"]


def test_repository_root_is_independent_from_current_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert Path(services.__file__).resolve().parents[1] == services.REPOSITORY_ROOT


def test_commands_support_repository_paths_with_spaces(tmp_path: Path) -> None:
    root = repository(tmp_path / "repository with spaces")
    specs = specs_for(root)

    assert " " in str(specs["api"].cwd)
    assert specs["api"].command[0] == str((root / "apps/api/.venv/bin/python").resolve())
    assert specs["portal"].cwd == root.resolve()


def test_interruption_during_start_returns_130(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = specs_for(repository(tmp_path))
    monkeypatch.setattr(services, "build_service_specs", lambda **_kwargs: specs)
    monkeypatch.setattr(services, "operation_lock", lambda: nullcontext())
    monkeypatch.setattr(services, "start_services", lambda _specs: (_ for _ in ()).throw(KeyboardInterrupt()))

    assert services.main(["start"]) == 130


def test_partial_start_keeps_first_service_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = specs_for(repository(tmp_path))
    launched: list[str] = []
    removed: list[str] = []
    states = {"api": "stopped", "portal": "stopped"}

    def inspect(spec: services.ServiceSpec) -> services.ServiceInspection:
        return inspection(spec, states[spec.name])

    def launch(spec: services.ServiceSpec) -> dict[str, object]:
        launched.append(spec.name)
        states[spec.name] = "running/healthy" if spec.name == "api" else "running/unhealthy"
        return {"pid": 123, "log": f"{spec.name}.log"}

    def wait(spec: services.ServiceSpec, _metadata: dict[str, object]) -> services.ServiceInspection:
        if spec.name == "portal":
            raise services.LocalServicesError("portal failed")
        return inspect(spec)

    monkeypatch.setattr(services, "inspect_service", inspect)
    monkeypatch.setattr(services, "port_is_busy", lambda _port: False)
    monkeypatch.setattr(services, "launch_service", launch)
    monkeypatch.setattr(services, "wait_for_service", wait)
    monkeypatch.setattr(services, "remove_stale_metadata", lambda service: removed.append(service))

    assert services.start_services(specs) == 1
    assert launched == ["api", "portal"]
    assert inspect(specs["api"]).state == "running/healthy"
    assert inspect(specs["portal"]).state == "running/unhealthy"
    assert removed == []


def test_posix_commands_use_venv_python_and_npm(tmp_path: Path) -> None:
    root = repository(tmp_path)
    specs = specs_for(root)

    assert specs["api"].command == (
        str((root / "apps/api/.venv/bin/python").resolve()),
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    )
    assert specs["portal"].command[1:] == ("run", "dev:portal")


def test_windows_commands_use_venv_python_and_npm_cmd(tmp_path: Path) -> None:
    root = repository(tmp_path, windows=True)
    specs = specs_for(root, windows=True)

    assert specs["api"].command[0].endswith(".venv/Scripts/python.exe")
    assert specs["portal"].command[0].endswith("npm.cmd")
    assert specs["portal"].command[1:] == ("run", "dev:portal")


def test_default_portal_mode_uses_standalone_node_command(tmp_path: Path) -> None:
    root = repository(tmp_path)
    npm = "/usr/local/bin/npm"
    node = "/usr/local/bin/node"

    specs = services.build_service_specs(
        root,
        "posix",
        which=lambda name: node if name == "node" else npm,
    )
    portal = specs["portal"]
    _portal_root, standalone_root, expected_server = services.portal_paths(root.resolve())

    assert portal.mode == "production"
    assert portal.command == (str(Path(node).resolve()), str(expected_server))
    assert portal.cwd == standalone_root
    assert portal.build_command == (str(Path(npm).resolve()), "run", "build:portal")
    assert portal.env_overrides["HOSTNAME"] == "127.0.0.1"
    assert portal.env_overrides["PORT"] == "3000"
    assert portal.env_overrides["API_BASE_URL"] == "http://127.0.0.1:8000"
    assert portal.env_overrides["API_INTERNAL_BASE_URL"] == "http://127.0.0.1:8000"
    assert portal.env_overrides["NEXT_PUBLIC_API_BASE_URL"] == ""


def test_portal_mode_arguments_default_to_production_and_allow_development() -> None:
    assert services.parse_args(["start"]).portal_mode == "production"
    assert services.parse_args(["restart"]).portal_mode == "production"
    assert services.parse_args(["start", "--portal-mode", "development"]).portal_mode == "development"
    assert services.parse_args(["restart", "--portal-mode", "development"]).portal_mode == "development"


def test_standalone_server_resolution_and_asset_copy_follow_monorepo_layout(tmp_path: Path) -> None:
    root = repository(tmp_path)
    portal_root, _standalone_root, expected_server = services.portal_paths(root.resolve())
    expected_server.parent.mkdir(parents=True)
    expected_server.write_text("server", encoding="utf-8")
    static_source = portal_root / ".next" / "static"
    static_source.mkdir(parents=True)
    (static_source / "asset.js").write_text("asset", encoding="utf-8")
    public_source = portal_root / "public"
    public_source.mkdir(parents=True)
    (public_source / "favicon.ico").write_text("icon", encoding="utf-8")

    server = services.resolve_standalone_server(root.resolve())
    copied = services.prepare_standalone_assets(root.resolve(), server)

    assert server == expected_server.absolute()
    assert copied == {"static": True, "public": True}
    assert (server.parent / ".next" / "static" / "asset.js").read_text(encoding="utf-8") == "asset"
    assert (server.parent / "public" / "favicon.ico").read_text(encoding="utf-8") == "icon"

    (public_source / "favicon.ico").unlink()
    public_source.rmdir()

    copied_without_public = services.prepare_standalone_assets(root.resolve(), server)

    assert copied_without_public == {"static": True, "public": False}
    assert not (server.parent / "public").exists()


def test_failed_production_build_never_resolves_or_launches_stale_standalone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repository(tmp_path)
    spec = specs_for(root, portal_mode="production")["portal"]
    runtime = root / "runtime" / "local-services"
    _portal_root, _standalone_root, stale_server = services.portal_paths(root.resolve())
    stale_server.parent.mkdir(parents=True)
    stale_server.write_text("stale", encoding="utf-8")

    def failed_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, stdout="build failed\n")

    monkeypatch.setattr(
        services,
        "resolve_standalone_server",
        lambda _root: pytest.fail("a failed build must not resolve or start stale standalone output"),
    )

    with pytest.raises(services.LocalServicesError, match="stale build output was not started"):
        services.prepare_production_portal(spec, root.resolve(), runtime, runner=failed_runner)

    assert "build failed with exit code 1" in services.log_path("portal", runtime).read_text(encoding="utf-8")


def test_legacy_portal_metadata_without_mode_remains_development_compatible(tmp_path: Path) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    development = specs_for(root)["portal"]
    production = specs_for(root, portal_mode="production")["portal"]
    metadata = metadata_for(development, root, runtime)

    assert "mode" not in metadata
    assert services.metadata_error(metadata, production, root) is None
    assert services.effective_portal_mode(metadata, production) == "development"


def test_detects_posix_virtual_environment_python(tmp_path: Path) -> None:
    root = repository(tmp_path)

    assert services.find_api_python(root, "posix") == (root / "apps/api/.venv/bin/python").resolve()


def test_detects_windows_virtual_environment_python(tmp_path: Path) -> None:
    root = repository(tmp_path, windows=True)

    assert services.find_api_python(root, "nt") == (root / "apps/api/.venv/Scripts/python.exe").resolve()


def test_api_command_preserves_venv_path_when_controller_uses_different_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repository(tmp_path)
    venv_python = root / "apps/api/.venv/bin/python"
    controller_python = tmp_path / "pyenv/versions/3.12.8/bin/python3.12"
    controller_python.parent.mkdir(parents=True)
    controller_python.write_text("", encoding="utf-8")
    controller_python.chmod(0o755)
    venv_python.unlink()
    venv_python.symlink_to(controller_python)
    monkeypatch.setattr(services.sys, "executable", str(controller_python))

    command = specs_for(root)["api"].command

    assert command[0] == str(venv_python.absolute())
    assert command[0] != str(controller_python.resolve())
    assert command[1:] == (
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    )


@pytest.mark.parametrize(
    ("platform_name", "available", "expected"),
    (("posix", {"npm": "/tools/npm"}, "npm"), ("nt", {"npm.cmd": "C:/tools/npm.cmd"}, "npm.cmd")),
)
def test_npm_executable_variants(platform_name: str, available: dict[str, str], expected: str) -> None:
    result = services.find_npm(platform_name, lambda name: available.get(name))

    assert result.name.lower() == expected


def test_stop_refuses_unverifiable_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = specs_for(repository(tmp_path))["api"]
    monkeypatch.setattr(services, "inspect_service", lambda _spec: inspection(spec, "unknown/unverifiable"))
    called = False

    def control(*_args: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(services, "control_request", control)

    assert services.stop_one(spec) is False
    assert called is False


def test_missing_log_returns_no_lines(tmp_path: Path) -> None:
    assert services.tail_lines(tmp_path / "missing.log") == []


def test_log_follow_can_be_interrupted_with_ctrl_c(tmp_path: Path) -> None:
    spec = specs_for(repository(tmp_path))["api"]
    output = io.StringIO()

    services.follow_logs(
        [spec],
        sleep=lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
        output=output,
        runtime_root=tmp_path / "runtime",
    )

    assert "Press Ctrl+C" in output.getvalue()
    assert "Log following stopped" in output.getvalue()


def test_metadata_with_live_pid_but_invalid_identity_is_not_removed_as_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    spec = specs_for(root)["api"]
    metadata = write_metadata(spec, root, runtime)
    metadata["command"] = ["unexpected"]
    services.atomic_write_json(services.state_path("api", runtime), metadata)
    monkeypatch.setattr(services, "port_is_busy", lambda _port: False)
    monkeypatch.setattr(services, "pid_exists", lambda _pid: True)

    assert services.inspect_service(spec, root, runtime).state == "unknown/unverifiable"


def test_persisted_metadata_contains_required_process_identity(tmp_path: Path) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    spec = specs_for(root)["api"]
    metadata = metadata_for(spec, root, runtime)

    assert services.metadata_error(metadata, spec, root) is None
    assert {
        "service",
        "pid",
        "checkout",
        "command",
        "port",
        "started_at",
        "identity_token",
        "log",
        "platform",
    }.issubset(metadata)


def test_state_serialization_does_not_include_environment_or_credentials(tmp_path: Path) -> None:
    root = repository(tmp_path)
    runtime = root / "runtime" / "local-services"
    metadata = metadata_for(specs_for(root)["api"], root, runtime)
    serialized = json.dumps(metadata).lower()

    assert "environment" not in serialized
    assert "database_url" not in serialized
    assert "credential" not in serialized

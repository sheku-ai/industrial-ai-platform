from __future__ import annotations

import argparse
import ctypes
import hashlib
import hmac
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPOSITORY_ROOT / "runtime" / "local-services"
STATE_SCHEMA_VERSION = 1
API_PORT = 8000
PORTAL_PORT = 3000
API_URL = f"http://127.0.0.1:{API_PORT}"
PORTAL_URL = f"http://127.0.0.1:{PORTAL_PORT}"
API_HEALTH_URL = f"{API_URL}/health/ready"
PORTAL_HEALTH_URL = PORTAL_URL
READINESS_TIMEOUT_SECONDS = 90.0
READINESS_POLL_SECONDS = 0.5
CONTROL_TIMEOUT_SECONDS = 2.0
STOP_TIMEOUT_SECONDS = 15.0
GRACEFUL_STOP_SECONDS = 8.0
PORT_RELEASE_TIMEOUT_SECONDS = 5.0
PORT_RELEASE_POLL_SECONDS = 0.1
LOG_TAIL_LINES = 80
MAX_LOG_BYTES = 5 * 1024 * 1024
RETAIN_LOG_BYTES = 2 * 1024 * 1024
CONTROL_TOKEN_ENV = "INDUSTRIAL_AI_LOCAL_SERVICES_CONTROL_TOKEN"
PORTAL_MODES = ("production", "development")
DEFAULT_PORTAL_MODE = "production"


class LocalServicesError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    label: str
    port: int
    url: str
    health_url: str
    cwd: Path
    command: tuple[str, ...]
    env_overrides: dict[str, str]
    mode: str | None = None
    build_command: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServiceInspection:
    spec: ServiceSpec
    state: str
    process_running: bool
    healthy: bool
    managed: bool
    metadata: dict[str, Any] | None
    detail: str
    port_busy: bool


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_path(service: str, root: Path = RUNTIME_ROOT) -> Path:
    return root / f"{service}.json"


def pid_path(service: str, root: Path = RUNTIME_ROOT) -> Path:
    return root / f"{service}.pid"


def log_path(service: str, root: Path = RUNTIME_ROOT) -> Path:
    return root / f"{service}.log"


def find_api_python(repository_root: Path = REPOSITORY_ROOT, platform_name: str | None = None) -> Path:
    platform_name = platform_name or os.name
    venv = repository_root / "apps" / "api" / ".venv"
    candidate = venv / "Scripts" / "python.exe" if platform_name == "nt" else venv / "bin" / "python"
    if not candidate.is_file():
        raise LocalServicesError(f"API virtual environment Python was not found: {candidate}")
    if not os.access(candidate, os.X_OK):
        raise LocalServicesError(f"API virtual environment Python is not executable: {candidate}")
    return candidate.absolute()


def find_npm(platform_name: str | None = None, which: Callable[[str], str | None] = shutil.which) -> Path:
    platform_name = platform_name or os.name
    names = ("npm.cmd", "npm.exe", "npm") if platform_name == "nt" else ("npm",)
    for name in names:
        executable = which(name)
        if executable:
            return Path(executable).resolve()
    raise LocalServicesError(
        "npm was not found on PATH; package-lock.json identifies npm as the portal package manager"
    )


def find_node(platform_name: str | None = None, which: Callable[[str], str | None] = shutil.which) -> Path:
    platform_name = platform_name or os.name
    names = ("node.exe", "node") if platform_name == "nt" else ("node",)
    for name in names:
        executable = which(name)
        if executable:
            return Path(executable).resolve()
    raise LocalServicesError("node was not found on PATH; it is required by the Next.js standalone server")


def portal_paths(repository_root: Path) -> tuple[Path, Path, Path]:
    portal_root = repository_root / "apps" / "admin-portal"
    standalone_root = portal_root / ".next" / "standalone"
    relative_portal_root = portal_root.relative_to(repository_root)
    expected_server = standalone_root / relative_portal_root / "server.js"
    return portal_root, standalone_root, expected_server


def build_service_specs(
    repository_root: Path = REPOSITORY_ROOT,
    platform_name: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    portal_mode: str = DEFAULT_PORTAL_MODE,
) -> dict[str, ServiceSpec]:
    repository_root = repository_root.resolve()
    if portal_mode not in PORTAL_MODES:
        raise LocalServicesError(f"unsupported portal mode: {portal_mode}")
    if not (repository_root / "package-lock.json").is_file():
        raise LocalServicesError(f"npm lockfile was not found in checkout: {repository_root}")
    python = find_api_python(repository_root, platform_name)
    npm = find_npm(platform_name, which)
    portal_root, standalone_root, expected_server = portal_paths(repository_root)
    if portal_mode == "production":
        node = find_node(platform_name, which)
        portal_command = (str(node), str(expected_server))
        portal_cwd = standalone_root
        build_command = (str(npm), "run", "build:portal")
        portal_environment = {
            "NODE_ENV": "production",
            "NEXT_TELEMETRY_DISABLED": "1",
            "HOSTNAME": "127.0.0.1",
            "PORT": str(PORTAL_PORT),
            "API_BASE_URL": API_URL,
            "API_INTERNAL_BASE_URL": API_URL,
            "NEXT_PUBLIC_API_BASE_URL": "",
        }
    else:
        portal_command = (str(npm), "run", "dev:portal")
        portal_cwd = repository_root
        build_command = ()
        portal_environment = {
            "API_BASE_URL": API_URL,
            "API_INTERNAL_BASE_URL": API_URL,
            "NEXT_PUBLIC_API_BASE_URL": "",
            "PORT": str(PORTAL_PORT),
        }
    return {
        "api": ServiceSpec(
            name="api",
            label="API",
            port=API_PORT,
            url=API_URL,
            health_url=API_HEALTH_URL,
            cwd=repository_root / "apps" / "api",
            command=(
                str(python),
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(API_PORT),
            ),
            env_overrides={"PORTAL_PORT": str(PORTAL_PORT)},
        ),
        "portal": ServiceSpec(
            name="portal",
            label="Portal",
            port=PORTAL_PORT,
            url=PORTAL_URL,
            health_url=PORTAL_HEALTH_URL,
            cwd=portal_cwd,
            command=portal_command,
            env_overrides=portal_environment,
            mode=portal_mode,
            build_command=build_command,
        ),
    }


def append_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(f"{message.rstrip()}\n")


def resolve_standalone_server(repository_root: Path) -> Path:
    _portal_root, standalone_root, expected_server = portal_paths(repository_root)
    candidates = (expected_server, standalone_root / "server.js")
    discovered: dict[Path, Path] = {}
    for candidate in candidates:
        if candidate.is_file():
            discovered[candidate.resolve()] = candidate.absolute()
    if not discovered:
        rendered = ", ".join(str(candidate) for candidate in candidates)
        raise LocalServicesError(
            f"Next.js standalone server.js was not found after a successful build; checked: {rendered}"
        )
    if len(discovered) != 1:
        rendered = ", ".join(str(candidate) for candidate in discovered.values())
        raise LocalServicesError(f"Next.js standalone server.js resolution is ambiguous: {rendered}")
    server = next(iter(discovered.values()))
    try:
        server.resolve().relative_to(standalone_root.resolve())
    except ValueError as exc:
        raise LocalServicesError(f"standalone server resolved outside the portal build tree: {server}") from exc
    return server


def replace_asset_tree(source: Path, target: Path, *, required: bool) -> bool:
    if target.exists():
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    if not source.is_dir():
        if required:
            raise LocalServicesError(f"required portal build assets were not generated: {source}")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return True


def prepare_standalone_assets(repository_root: Path, server: Path) -> dict[str, bool]:
    portal_root, _standalone_root, _expected_server = portal_paths(repository_root)
    application_root = server.parent
    static_copied = replace_asset_tree(
        portal_root / ".next" / "static",
        application_root / ".next" / "static",
        required=True,
    )
    public_copied = replace_asset_tree(
        portal_root / "public",
        application_root / "public",
        required=False,
    )
    return {"static": static_copied, "public": public_copied}


def prepare_production_portal(
    spec: ServiceSpec,
    repository_root: Path = REPOSITORY_ROOT,
    runtime_root: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ServiceSpec:
    if spec.name != "portal" or spec.mode != "production" or not spec.build_command:
        raise LocalServicesError("production portal preparation requires a production Portal service specification")
    runtime_root = runtime_root or repository_root / "runtime" / "local-services"
    service_log = log_path("portal", runtime_root)
    prepare_log(service_log)
    append_log(service_log, "[portal] mode: production")
    append_log(service_log, f"[portal] build started: {' '.join(spec.build_command)}")
    environment = os.environ.copy()
    environment.update(spec.env_overrides)
    try:
        result = runner(
            list(spec.build_command),
            cwd=repository_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        append_log(service_log, f"[portal] build could not start: {exc}")
        raise LocalServicesError(f"portal production build could not be started: {exc}") from exc
    build_output = result.stdout or ""
    if build_output:
        append_log(service_log, build_output)
        print(build_output, end="" if build_output.endswith("\n") else "\n")
    if result.returncode != 0:
        append_log(service_log, f"[portal] build failed with exit code {result.returncode}")
        raise LocalServicesError(
            f"portal production build failed with exit code {result.returncode}; stale build output was not started. "
            f"Log: {service_log}"
        )
    append_log(service_log, "[portal] build completed successfully")
    server = resolve_standalone_server(repository_root)
    append_log(service_log, f"[portal] standalone server resolved: {server}")
    append_log(service_log, "[portal] preparing standalone assets")
    assets = prepare_standalone_assets(repository_root, server)
    append_log(
        service_log,
        f"[portal] assets ready: static=yes, public={'yes' if assets['public'] else 'not present'}",
    )
    append_log(service_log, "[portal] standalone launch requested")
    _portal_root, standalone_root, _expected_server = portal_paths(repository_root)
    return replace(spec, command=(spec.command[0], str(server)), cwd=standalone_root)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def portal_mode_from_command(command: Any) -> str | None:
    if not isinstance(command, list) or not command:
        return None
    if command[-2:] == ["run", "dev:portal"]:
        return "development"
    if len(command) == 2 and str(command[-1]).endswith("server.js"):
        return "production"
    return None


def metadata_command_compatible(
    metadata: dict[str, Any], spec: ServiceSpec, repository_root: Path
) -> bool:
    command = metadata.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        return False
    if spec.name == "api":
        return command == list(spec.command)
    command_mode = portal_mode_from_command(command)
    persisted_mode = metadata.get("mode")
    if persisted_mode in PORTAL_MODES and persisted_mode != command_mode:
        return False
    executable_name = Path(command[0]).name.lower()
    if command_mode == "development":
        return executable_name in {"npm", "npm.cmd", "npm.exe"}
    if command_mode == "production":
        if executable_name not in {"node", "node.exe"}:
            return False
        try:
            server = Path(command[1]).resolve()
            _portal_root, standalone_root, expected_server = portal_paths(repository_root)
            allowed_servers = {
                expected_server.resolve(),
                (standalone_root / "server.js").resolve(),
            }
        except (OSError, RuntimeError, ValueError):
            return False
        return server in allowed_servers
    return False


def metadata_error(metadata: dict[str, Any] | None, spec: ServiceSpec, repository_root: Path) -> str | None:
    if metadata is None:
        return "metadata is missing or unreadable"
    required_types: dict[str, type] = {
        "schema_version": int,
        "service": str,
        "pid": int,
        "checkout": str,
        "command": list,
        "port": int,
        "started_at": str,
        "identity_token": str,
        "control_port": int,
        "log": str,
        "platform": str,
    }
    for field, expected_type in required_types.items():
        if not isinstance(metadata.get(field), expected_type):
            return f"metadata field {field!r} is invalid"
    if metadata["schema_version"] != STATE_SCHEMA_VERSION:
        return "metadata schema version does not match"
    if metadata["service"] != spec.name:
        return "metadata service does not match"
    if metadata["platform"] != sys.platform:
        return "metadata platform does not match the current host"
    try:
        checkout = Path(metadata["checkout"]).resolve()
        recorded_log = Path(metadata["log"]).resolve()
    except (OSError, RuntimeError, ValueError):
        return "metadata paths are invalid"
    if checkout != repository_root.resolve():
        return "metadata belongs to another checkout"
    if recorded_log != log_path(spec.name, repository_root / "runtime" / "local-services").resolve():
        return "metadata log path does not match this checkout"
    if not metadata_command_compatible(metadata, spec, repository_root):
        return "metadata command is invalid for this service"
    if "cwd" in metadata:
        if not isinstance(metadata["cwd"], str):
            return "metadata working directory is invalid"
        try:
            Path(metadata["cwd"]).resolve().relative_to(repository_root.resolve())
        except (OSError, RuntimeError, ValueError):
            return "metadata working directory is outside this checkout"
    if "mode" in metadata and metadata["mode"] not in PORTAL_MODES:
        return "metadata portal mode is invalid"
    if metadata["port"] != spec.port:
        return "metadata port does not match"
    if metadata["pid"] <= 0 or not 1 <= metadata["control_port"] <= 65535:
        return "metadata process or control port is invalid"
    if len(metadata["identity_token"]) < 32:
        return "metadata identity token is invalid"
    return None


def pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def active_listener(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def bind_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            candidate.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            candidate.bind(("127.0.0.1", port))
            candidate.listen(1)
        except OSError:
            return False
    return True


def port_is_busy(port: int) -> bool:
    return active_listener(port) or not bind_available(port)


def reserve_control_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def http_health(spec: ServiceSpec) -> tuple[bool, str]:
    try:
        with urlopen(spec.health_url, timeout=CONTROL_TIMEOUT_SECONDS) as response:
            status = int(response.status)
            body = response.read()
    except HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (URLError, OSError, TimeoutError) as exc:
        return False, str(exc)
    if not 200 <= status < 400:
        return False, f"HTTP {status}"
    if spec.name == "api":
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return False, "health response is not valid JSON"
        if not isinstance(payload, dict) or payload.get("status") != "ready":
            return False, f"health status is {payload.get('status') if isinstance(payload, dict) else 'invalid'}"
    if spec.name == "portal":
        try:
            with urlopen(API_HEALTH_URL, timeout=CONTROL_TIMEOUT_SECONDS) as api_response:
                api_status = int(api_response.status)
                api_body = api_response.read()
            api_payload = json.loads(api_body.decode("utf-8"))
        except HTTPError as exc:
            return False, f"Portal HTTP {status}; API dependency HTTP {exc.code}"
        except (URLError, OSError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            return False, f"Portal HTTP {status}; API dependency unhealthy: {exc}"
        if not 200 <= api_status < 400 or not isinstance(api_payload, dict) or api_payload.get("status") != "ready":
            return False, f"Portal HTTP {status}; API dependency is not ready"
    return True, f"HTTP {status}"


def control_proof(token: str, phase: str, action: str, nonce: str, supervisor_pid: int = 0) -> str:
    message = f"{phase}|{action}|{nonce}|{supervisor_pid}".encode("utf-8")
    return hmac.new(token.encode("utf-8"), message, hashlib.sha256).hexdigest()


def control_request(metadata: dict[str, Any], action: str) -> dict[str, Any] | None:
    nonce = secrets.token_hex(16)
    request_payload = {
        "action": action,
        "nonce": nonce,
        "proof": control_proof(metadata["identity_token"], "request", action, nonce),
    }
    request = json.dumps(request_payload).encode("utf-8") + b"\n"
    try:
        with socket.create_connection(
            ("127.0.0.1", int(metadata["control_port"])), timeout=CONTROL_TIMEOUT_SECONDS
        ) as connection:
            connection.settimeout(CONTROL_TIMEOUT_SECONDS)
            connection.sendall(request)
            received = bytearray()
            while b"\n" not in received and len(received) < 65536:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                received.extend(chunk)
    except (OSError, TimeoutError, ValueError):
        return None
    try:
        response = json.loads(bytes(received).split(b"\n", 1)[0].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(response, dict):
        return None
    if response.get("action") != action or response.get("nonce") != nonce:
        return None
    return response


def identity_matches(response: dict[str, Any] | None, metadata: dict[str, Any], spec: ServiceSpec) -> bool:
    if not response:
        return False
    action = str(response.get("action") or "")
    nonce = str(response.get("nonce") or "")
    supervisor_pid = response.get("supervisor_pid")
    if not action or not nonce or not isinstance(supervisor_pid, int):
        return False
    expected_proof = control_proof(
        str(metadata.get("identity_token") or ""),
        "response",
        action,
        nonce,
        supervisor_pid,
    )
    return bool(
        response.get("authenticated") is True
        and hmac.compare_digest(str(response.get("proof") or ""), expected_proof)
        and response.get("service") == spec.name
        and response.get("checkout") == metadata.get("checkout")
        and response.get("command") == metadata.get("command")
        and response.get("port") == spec.port
        and response.get("platform") == metadata.get("platform")
        and response.get("supervisor_pid") == metadata.get("pid")
    )


def inspect_service(
    spec: ServiceSpec,
    repository_root: Path = REPOSITORY_ROOT,
    runtime_root: Path | None = None,
) -> ServiceInspection:
    runtime_root = runtime_root or repository_root / "runtime" / "local-services"
    path = state_path(spec.name, runtime_root)
    path_exists = path.exists()
    metadata = read_json(path)
    busy = port_is_busy(spec.port)
    if not path_exists:
        state = "foreign port owner" if busy else "stopped"
        detail = "fixed port is occupied by a process not managed by this checkout" if busy else "no metadata"
        return ServiceInspection(spec, state, False, False, False, None, detail, busy)
    error = metadata_error(metadata, spec, repository_root)
    if error:
        recorded_pid = metadata.get("pid") if isinstance(metadata, dict) else None
        if isinstance(recorded_pid, int) and pid_exists(recorded_pid):
            return ServiceInspection(
                spec,
                "unknown/unverifiable",
                True,
                False,
                False,
                metadata,
                f"{error}; recorded PID exists and will not be trusted",
                busy,
            )
        return ServiceInspection(spec, "stale metadata", False, False, False, metadata, error, busy)
    assert metadata is not None
    response = control_request(metadata, "probe")
    if identity_matches(response, metadata, spec):
        process_running = bool(response.get("service_process_running"))
        healthy, health_detail = http_health(spec) if process_running else (False, "service process exited")
        state = "running/healthy" if healthy else "running/unhealthy" if process_running else "stale metadata"
        return ServiceInspection(spec, state, process_running, healthy, True, metadata, health_detail, busy)
    if pid_exists(int(metadata["pid"])):
        return ServiceInspection(
            spec,
            "unknown/unverifiable",
            True,
            False,
            False,
            metadata,
            "PID exists but the authenticated process identity could not be verified",
            busy,
        )
    return ServiceInspection(
        spec,
        "stale metadata",
        False,
        False,
        False,
        metadata,
        "recorded supervisor PID is no longer running",
        busy,
    )


def format_inspection(inspection: ServiceInspection) -> str:
    metadata = inspection.metadata or {}
    pid = metadata.get("service_pid") or metadata.get("pid") or "-"
    managed = "yes" if inspection.managed else "no"
    mode_line = (
        (f"  mode: {effective_portal_mode(metadata, inspection.spec)}",)
        if inspection.spec.name == "portal"
        else ()
    )
    return "\n".join(
        (
            inspection.spec.label,
            *mode_line,
            f"  status: {inspection.state}",
            f"  process: {'running' if inspection.process_running else 'stopped'}",
            f"  pid: {pid}",
            f"  port: {inspection.spec.port}",
            f"  url: {inspection.spec.url}",
            f"  health: {'healthy' if inspection.healthy else inspection.detail}",
            f"  log: {metadata.get('log') or log_path(inspection.spec.name)}",
            f"  managed by this checkout: {managed}",
        )
    )


def effective_portal_mode(metadata: dict[str, Any] | None, spec: ServiceSpec | None = None) -> str:
    payload = metadata or {}
    persisted = payload.get("mode")
    if persisted in PORTAL_MODES:
        return str(persisted)
    command_mode = portal_mode_from_command(payload.get("command"))
    if command_mode:
        return command_mode
    if spec is not None and spec.mode in PORTAL_MODES:
        return str(spec.mode)
    return DEFAULT_PORTAL_MODE


def print_status(inspections: list[ServiceInspection]) -> None:
    for index, inspection in enumerate(inspections):
        if index:
            print()
        print(format_inspection(inspection))
    ready = all(item.state == "running/healthy" and item.managed for item in inspections)
    print(f"\nLocal services: {'READY' if ready else 'NOT READY'}")


def remove_stale_metadata(service: str, runtime_root: Path = RUNTIME_ROOT) -> None:
    for path in (state_path(service, runtime_root), pid_path(service, runtime_root)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def prepare_log(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
        with path.open("rb") as source:
            source.seek(-RETAIN_LOG_BYTES, os.SEEK_END)
            retained = source.read()
        path.write_bytes(retained)
    with path.open("a", encoding="utf-8") as output:
        output.write(f"\n=== local services execution {utc_now()} ===\n")


def detached_process_kwargs(log_handle: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    return kwargs


def launch_service(
    spec: ServiceSpec,
    repository_root: Path = REPOSITORY_ROOT,
    runtime_root: Path | None = None,
    popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
) -> dict[str, Any]:
    runtime_root = runtime_root or repository_root / "runtime" / "local-services"
    runtime_root.mkdir(parents=True, exist_ok=True)
    service_log = log_path(spec.name, runtime_root)
    prepare_log(service_log)
    if spec.name == "portal":
        append_log(service_log, f"[portal] mode: {spec.mode or DEFAULT_PORTAL_MODE}")
        append_log(
            service_log,
            "[portal] starting Next.js standalone server"
            if spec.mode == "production"
            else "[portal] starting Next.js development server",
        )
    token = secrets.token_hex(32)
    control_port = reserve_control_port()
    host_command = [
        str(find_api_python(repository_root)),
        str(Path(__file__).resolve()),
        "_host",
        spec.name,
        "--control-port",
        str(control_port),
    ]
    if spec.name == "portal":
        host_command.extend(("--portal-mode", spec.mode or DEFAULT_PORTAL_MODE))
        if spec.mode == "production":
            host_command.extend(("--portal-server", spec.command[-1]))
    environment = os.environ.copy()
    environment[CONTROL_TOKEN_ENV] = token
    with service_log.open("ab", buffering=0) as output:
        process = popen(
            host_command,
            cwd=repository_root,
            env=environment,
            **detached_process_kwargs(output),
        )
    metadata = {
        "schema_version": STATE_SCHEMA_VERSION,
        "service": spec.name,
        "pid": int(process.pid),
        "service_pid": None,
        "checkout": str(repository_root.resolve()),
        "command": list(spec.command),
        "cwd": str(spec.cwd.resolve()),
        "port": spec.port,
        "platform": sys.platform,
        "url": spec.url,
        "health_url": spec.health_url,
        "started_at": utc_now(),
        "identity_token": token,
        "control_port": control_port,
        "log": str(service_log.resolve()),
    }
    if spec.name == "portal":
        metadata["mode"] = spec.mode or DEFAULT_PORTAL_MODE
    atomic_write_json(state_path(spec.name, runtime_root), metadata)
    pid_path(spec.name, runtime_root).write_text(f"{process.pid}\n", encoding="ascii")
    return metadata


def wait_for_service(
    spec: ServiceSpec,
    metadata: dict[str, Any],
    timeout: float = READINESS_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ServiceInspection:
    deadline = monotonic() + timeout
    last = inspect_service(spec)
    while monotonic() < deadline:
        last = inspect_service(spec)
        if last.state == "running/healthy" and last.managed:
            return last
        if last.state == "stale metadata":
            break
        sleep(READINESS_POLL_SECONDS)
    raise LocalServicesError(
        f"{spec.label} readiness timed out on port {spec.port}: {last.detail}. Log: {metadata['log']}"
    )


def start_services(specs: dict[str, ServiceSpec]) -> int:
    failed = False
    for spec in specs.values():
        inspection = inspect_service(spec)
        if (
            spec.name == "portal"
            and inspection.managed
            and effective_portal_mode(inspection.metadata, spec) != spec.mode
        ):
            current_mode = effective_portal_mode(inspection.metadata, spec)
            print(f"Portal is managed in {current_mode} mode; switching to {spec.mode} mode")
            if not stop_one(spec):
                failed = True
                break
            inspection = inspect_service(spec)
        if inspection.state == "running/healthy" and inspection.managed:
            print(f"{spec.label} is already managed and healthy; keeping PID {inspection.metadata.get('pid')}")
            continue
        if inspection.state == "running/unhealthy" and inspection.managed:
            print(
                f"ERROR: {spec.label} is managed but unhealthy on port {spec.port}. "
                f"Inspect {inspection.metadata.get('log')}",
                file=sys.stderr,
            )
            failed = True
            break
        if inspection.state == "unknown/unverifiable":
            print(
                f"ERROR: refusing to start {spec.label}: recorded PID cannot be verified. "
                "Use status and inspect the process manually.",
                file=sys.stderr,
            )
            failed = True
            break
        if inspection.state == "stale metadata":
            remove_stale_metadata(spec.name)
        if port_is_busy(spec.port):
            print(
                f"ERROR: refusing to start {spec.label}: port {spec.port} is occupied by a process "
                "not verifiably managed by this checkout. Stop it manually or free the port.",
                file=sys.stderr,
            )
            failed = True
            break
        launch_spec = spec
        if spec.name == "portal" and spec.mode == "production":
            try:
                launch_spec = prepare_production_portal(spec)
            except LocalServicesError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                failed = True
                break
        try:
            metadata = launch_service(launch_spec)
        except (LocalServicesError, OSError) as exc:
            print(
                f"ERROR: {spec.label} could not be started on port {spec.port}: {exc}. "
                f"Log: {log_path(spec.name)}",
                file=sys.stderr,
            )
            failed = True
            break
        print(f"Started {spec.label} supervisor PID {metadata['pid']}; log: {metadata['log']}")
        try:
            wait_for_service(launch_spec, metadata)
        except LocalServicesError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            failed = True
            break
    inspections = [inspect_service(spec) for spec in specs.values()]
    print_status(inspections)
    return 1 if failed or not all(item.state == "running/healthy" for item in inspections) else 0


def wait_for_port_release(
    port: int,
    timeout: float = PORT_RELEASE_TIMEOUT_SECONDS,
    poll_interval: float = PORT_RELEASE_POLL_SECONDS,
    *,
    busy_check: Callable[[int], bool] | None = None,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> bool:
    busy_check = busy_check or port_is_busy
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    deadline = monotonic() + timeout
    while busy_check(port):
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        sleep(min(poll_interval, remaining))
    return True


def stop_one(spec: ServiceSpec) -> bool:
    inspection = inspect_service(spec)
    if inspection.state == "stopped":
        print(f"{spec.label} is already stopped")
        return True
    if inspection.state == "stale metadata":
        remove_stale_metadata(spec.name)
        owner = " A foreign process still occupies the port." if inspection.port_busy else ""
        print(f"Removed stale {spec.label} metadata without terminating any process.{owner}")
        return True
    if not inspection.managed or inspection.metadata is None:
        print(
            f"ERROR: refusing to stop {spec.label}: {inspection.state}. Process identity is not verifiable.",
            file=sys.stderr,
        )
        return False
    metadata = inspection.metadata
    response = control_request(metadata, "stop")
    if not identity_matches(response, metadata, spec):
        print(f"ERROR: authenticated stop was rejected for {spec.label}; no process was terminated.", file=sys.stderr)
        return False
    deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline and pid_exists(int(metadata["pid"])):
        time.sleep(0.25)
    if pid_exists(int(metadata["pid"])):
        probe = control_request(metadata, "probe")
        if not identity_matches(probe, metadata, spec):
            print(
                f"ERROR: {spec.label} supervisor still exists but its identity is no longer verifiable; "
                "refusing forced termination.",
                file=sys.stderr,
            )
            return False
        forced = control_request(metadata, "force")
        if not identity_matches(forced, metadata, spec):
            print(f"ERROR: verified force request failed for {spec.label}.", file=sys.stderr)
            return False
        force_deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
        while time.monotonic() < force_deadline and pid_exists(int(metadata["pid"])):
            time.sleep(0.25)
        if pid_exists(int(metadata["pid"])):
            print(f"ERROR: verified {spec.label} supervisor did not terminate; metadata was retained.", file=sys.stderr)
            return False
    if not wait_for_port_release(spec.port):
        print(
            f"ERROR: {spec.label} supervisor exited but port {spec.port} remains occupied. "
            "No port owner was terminated; metadata was retained for inspection.",
            file=sys.stderr,
        )
        return False
    remove_stale_metadata(spec.name)
    print(f"Stopped managed {spec.label}")
    return True


def stop_services(specs: dict[str, ServiceSpec]) -> int:
    results = [stop_one(spec) for spec in reversed(tuple(specs.values()))]
    successful = all(results)
    print_status([inspect_service(spec) for spec in specs.values()])
    return 0 if successful else 1


def restart_services(specs: dict[str, ServiceSpec]) -> int:
    if stop_services(specs):
        return 1
    return start_services(specs)


def tail_lines(path: Path, line_count: int = LOG_TAIL_LINES) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-line_count:]
    except FileNotFoundError:
        return []


def print_log_block(spec: ServiceSpec) -> None:
    path = log_path(spec.name)
    print(f"=== {spec.label} ({path}) ===")
    lines = tail_lines(path)
    print("\n".join(lines) if lines else "<log file not found or empty>")


def follow_logs(
    specs: list[ServiceSpec],
    sleep: Callable[[float], None] = time.sleep,
    output: Any = sys.stdout,
    runtime_root: Path = RUNTIME_ROOT,
) -> None:
    positions: dict[Path, int] = {}
    for spec in specs:
        path = log_path(spec.name, runtime_root)
        positions[path] = path.stat().st_size if path.exists() else 0
    print("Following logs. Press Ctrl+C to stop.", file=output)
    try:
        while True:
            for spec in specs:
                path = log_path(spec.name, runtime_root)
                if not path.exists():
                    continue
                size = path.stat().st_size
                if size < positions[path]:
                    positions[path] = 0
                if size > positions[path]:
                    with path.open("r", encoding="utf-8", errors="replace") as source:
                        source.seek(positions[path])
                        content = source.read()
                        positions[path] = source.tell()
                    if content:
                        print(f"[{spec.name}] {content}", end="" if content.endswith("\n") else "\n", file=output)
            sleep(0.5)
    except KeyboardInterrupt:
        print("Log following stopped.", file=output)


def logs_command(specs: dict[str, ServiceSpec], selected: str | None, follow: bool) -> int:
    chosen = [specs[selected]] if selected else list(specs.values())
    for index, spec in enumerate(chosen):
        if index:
            print()
        print_log_block(spec)
    if follow:
        follow_logs(chosen)
    return 0


class WindowsJob:
    def __init__(self, process: subprocess.Popen[Any]) -> None:
        self.handle: int | None = None
        self.kernel32: Any = None
        if os.name != "nt":
            return
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        information = ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(information), ctypes.sizeof(information)):
            kernel32.CloseHandle(handle)
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.AssignProcessToJobObject(handle, wintypes.HANDLE(int(process._handle))):
            kernel32.CloseHandle(handle)
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle = int(handle)
        self.kernel32 = kernel32

    def terminate(self) -> None:
        if self.handle is not None and self.kernel32 is not None:
            self.kernel32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle is not None and self.kernel32 is not None:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


def terminate_service_tree(process: subprocess.Popen[Any], job: WindowsJob, force: bool = False) -> None:
    if os.name == "nt":
        if not force and process.poll() is None:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            except (OSError, ValueError):
                process.terminate()
            try:
                process.wait(timeout=GRACEFUL_STOP_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        job.terminate()
        return
    process_group = process.pid
    try:
        os.killpg(process_group, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        return
    if force:
        return
    try:
        process.wait(timeout=GRACEFUL_STOP_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass


def host_identity(
    metadata: dict[str, Any],
    spec: ServiceSpec,
    process: subprocess.Popen[Any],
    *,
    action: str,
    nonce: str,
    authenticated: bool = True,
) -> dict[str, Any]:
    supervisor_pid = os.getpid()
    payload = {
        "authenticated": authenticated,
        "action": action,
        "nonce": nonce,
        "service": spec.name,
        "checkout": metadata["checkout"],
        "command": list(spec.command),
        "port": spec.port,
        "platform": sys.platform,
        "supervisor_pid": supervisor_pid,
        "service_pid": process.pid,
        "service_process_running": process.poll() is None,
        "proof": (
            control_proof(metadata["identity_token"], "response", action, nonce, supervisor_pid)
            if authenticated
            else None
        ),
    }
    if spec.name == "portal":
        payload["mode"] = metadata.get("mode") or spec.mode or DEFAULT_PORTAL_MODE
    return payload


def service_host(
    service: str,
    control_port: int,
    *,
    portal_mode: str = DEFAULT_PORTAL_MODE,
    portal_server: str | None = None,
) -> int:
    token = os.environ.pop(CONTROL_TOKEN_ENV, "")
    specs = build_service_specs(portal_mode=portal_mode)
    if service not in specs or len(token) < 32:
        return 2
    spec = specs[service]
    if service == "portal" and portal_mode == "production":
        if not portal_server:
            return 2
        requested_server = Path(portal_server).absolute()
        try:
            resolved_server = resolve_standalone_server(REPOSITORY_ROOT)
        except LocalServicesError:
            return 2
        if requested_server.resolve() != resolved_server.resolve():
            return 2
        _portal_root, standalone_root, _expected_server = portal_paths(REPOSITORY_ROOT)
        spec = replace(spec, command=(spec.command[0], str(resolved_server)), cwd=standalone_root)
    elif service == "portal" and portal_server:
        return 2
    metadata_file = state_path(service)
    deadline = time.monotonic() + 5.0
    metadata = read_json(metadata_file)
    while (metadata is None or metadata.get("identity_token") != token) and time.monotonic() < deadline:
        time.sleep(0.05)
        metadata = read_json(metadata_file)
    if metadata_error(metadata, spec, REPOSITORY_ROOT) or metadata is None:
        return 2
    stop_requested = threading.Event()
    force_requested = threading.Event()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("127.0.0.1", control_port))
        server.listen(4)
        server.settimeout(0.25)
    except Exception:
        server.close()
        raise
    environment = os.environ.copy()
    environment.update(spec.env_overrides)
    child_kwargs: dict[str, Any] = {"cwd": spec.cwd, "env": environment, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        child_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        child_kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(list(spec.command), **child_kwargs)
    except Exception:
        server.close()
        raise
    try:
        job = WindowsJob(process)
    except Exception:
        process.terminate()
        process.wait(timeout=2.0)
        server.close()
        raise
    metadata["service_pid"] = process.pid
    atomic_write_json(metadata_file, metadata)

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_requested.set()

    signal.signal(signal.SIGTERM, request_stop)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, request_stop)
    try:
        while process.poll() is None and not stop_requested.is_set() and not force_requested.is_set():
            try:
                connection, _address = server.accept()
            except socket.timeout:
                continue
            with connection:
                connection.settimeout(CONTROL_TIMEOUT_SECONDS)
                try:
                    request = json.loads(connection.makefile("rb").readline(65536).decode("utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    request = {}
                action = str(request.get("action") or "")
                nonce = str(request.get("nonce") or "")
                expected_proof = control_proof(token, "request", action, nonce)
                authenticated = bool(
                    action
                    and nonce
                    and hmac.compare_digest(str(request.get("proof") or ""), expected_proof)
                )
                response = host_identity(
                    metadata,
                    spec,
                    process,
                    action=action,
                    nonce=nonce,
                    authenticated=authenticated,
                )
                if authenticated and action == "stop":
                    stop_requested.set()
                elif authenticated and action == "force":
                    force_requested.set()
                connection.sendall(json.dumps(response).encode("utf-8") + b"\n")
        terminate_service_tree(
            process,
            job,
            force=force_requested.is_set() or process.poll() is not None,
        )
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            terminate_service_tree(process, job, force=True)
            process.wait(timeout=2.0)
        metadata["exit_code"] = process.returncode
        metadata["stopped_at"] = utc_now()
        atomic_write_json(metadata_file, metadata)
        return int(process.returncode or 0)
    finally:
        server.close()
        job.close()


@contextmanager
def operation_lock(runtime_root: Path = RUNTIME_ROOT) -> Iterator[None]:
    runtime_root.mkdir(parents=True, exist_ok=True)
    path = runtime_root / "operation.lock"
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                owner_pid = int(path.read_text(encoding="ascii").strip())
            except (OSError, UnicodeError, ValueError):
                owner_pid = -1
            if owner_pid > 0 and pid_exists(owner_pid):
                raise
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        yield
    except FileExistsError as exc:
        raise LocalServicesError(f"Another local-services operation is active or left a stale lock: {path}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage the local API and portal for this checkout")
    subcommands = parser.add_subparsers(dest="command", required=True)
    start = subcommands.add_parser("start")
    start.add_argument("--portal-mode", choices=PORTAL_MODES, default=DEFAULT_PORTAL_MODE)
    subcommands.add_parser("stop")
    restart = subcommands.add_parser("restart")
    restart.add_argument("--portal-mode", choices=PORTAL_MODES, default=DEFAULT_PORTAL_MODE)
    subcommands.add_parser("status")
    logs = subcommands.add_parser("logs")
    logs.add_argument("service", nargs="?", choices=("api", "portal"))
    logs.add_argument("--follow", action="store_true")
    host = subcommands.add_parser("_host", help=argparse.SUPPRESS)
    host.add_argument("service", choices=("api", "portal"))
    host.add_argument("--control-port", type=int, required=True)
    host.add_argument("--portal-mode", choices=PORTAL_MODES, default=DEFAULT_PORTAL_MODE)
    host.add_argument("--portal-server")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "_host":
        return service_host(
            args.service,
            args.control_port,
            portal_mode=args.portal_mode,
            portal_server=args.portal_server,
        )
    specs = build_service_specs(portal_mode=getattr(args, "portal_mode", DEFAULT_PORTAL_MODE))
    if args.command == "status":
        inspections = [inspect_service(spec) for spec in specs.values()]
        print_status(inspections)
        return 0 if all(item.state == "running/healthy" for item in inspections) else 1
    if args.command == "logs":
        return logs_command(specs, args.service, args.follow)
    try:
        with operation_lock():
            if args.command == "start":
                return start_services(specs)
            if args.command == "stop":
                return stop_services(specs)
            return restart_services(specs)
    except KeyboardInterrupt:
        print(
            "Interrupted. Managed services already started were left running; inspect status and logs.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LocalServicesError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

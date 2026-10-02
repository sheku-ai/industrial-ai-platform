from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
LOG_ROOT = ROOT / "runtime" / "logs"
LOCAL_DATABASE_URL = "postgresql+psycopg://industrial_ai:industrial_ai@127.0.0.1:5432/industrial_ai"
FIXED_API_PORT = 8000
FIXED_PORTAL_PORT = 3000
API_URL = f"http://127.0.0.1:{FIXED_API_PORT}"
PORTAL_URL = f"http://127.0.0.1:{FIXED_PORTAL_PORT}"
COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
COMPOSE_PROFILES = ("object-storage", "ai", "ingestion")
EXPECTED_COMPOSE_SERVICES = ("postgres", "migrator", "api", "scheduler", "portal")
OPTIONAL_COMPOSE_SERVICES = ("minio", "ollama", "ingestion-worker")


def python_executable() -> str:
    for candidate in (
        API_ROOT / ".venv" / "Scripts" / "python.exe",
        API_ROOT / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("API virtual environment was not found under apps/api/.venv")


def executable(name: str) -> str:
    value = shutil.which(name)
    if value:
        return value
    raise RuntimeError(f"Required command was not found on PATH: {name}")


def compose_file() -> Path:
    for name in COMPOSE_NAMES:
        candidate = ROOT / name
        if candidate.exists():
            return candidate
    raise RuntimeError(f"Docker Compose file was not found: {', '.join(COMPOSE_NAMES)}")


def compose_command(*arguments: str, include_all_profiles: bool = False) -> list[str]:
    command = [executable("docker"), "compose", "-f", str(compose_file())]
    if include_all_profiles:
        for profile in COMPOSE_PROFILES:
            command.extend(("--profile", profile))
    command.extend(arguments)
    return command


def child_environment(**values: str) -> dict[str, str]:
    result = os.environ.copy()
    result.update(values)
    return result


def fixed_runtime_environment() -> dict[str, str]:
    return child_environment(
        API_PORT=str(FIXED_API_PORT),
        PORTAL_PORT=str(FIXED_PORTAL_PORT),
        API_INTERNAL_BASE_URL="http://api:8000",
    )


def run(args: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(args))
    completed = subprocess.run(args, cwd=cwd, env=env, check=False)
    if completed.returncode:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(args)}")


def run_best_effort(args: list[str], env: dict[str, str] | None = None) -> None:
    print("+", " ".join(args))
    subprocess.run(args, cwd=ROOT, env=env, check=False)


def capture(args: list[str], env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(args)}\n{message}")
    return completed.stdout


def _windows_port_listeners(port: int) -> list[dict[str, Any]]:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return []
    script = (
        f"$items = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | "
        "ForEach-Object { "
        "$p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; "
        "[PSCustomObject]@{address=$_.LocalAddress; port=$_.LocalPort; pid=$_.OwningProcess; "
        "process=if($p){$p.ProcessName}else{$null}; path=if($p){$p.Path}else{$null}} }; "
        "@($items) | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    payload = completed.stdout.strip()
    if completed.returncode or not payload:
        return []
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else [parsed]


def _unix_port_listeners(port: int) -> list[dict[str, Any]]:
    lsof = shutil.which("lsof")
    if not lsof:
        return []
    completed = subprocess.run(
        [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpcn"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    listeners: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in completed.stdout.splitlines():
        if not line:
            continue
        prefix, value = line[0], line[1:]
        if prefix == "p":
            if current:
                listeners.append(current)
            current = {"pid": int(value), "address": None, "port": port}
        elif prefix == "c":
            current["process"] = value
        elif prefix == "n":
            current["address"] = value
    if current:
        listeners.append(current)
    return listeners


def port_listeners(port: int) -> list[dict[str, Any]]:
    listeners = _windows_port_listeners(port) if os.name == "nt" else _unix_port_listeners(port)
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for item in listeners:
        record = {
            "address": item.get("address"),
            "port": int(item.get("port") or port),
            "pid": item.get("pid"),
            "process": item.get("process"),
            "path": item.get("path"),
        }
        key = (record["address"], record["port"], record["pid"])
        if key not in seen:
            seen.add(key)
            normalized.append(record)
    return normalized


def _bind_available(family: socket.AddressFamily, address: str, port: int) -> bool:
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            try:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            except OSError:
                pass
        try:
            sock.bind((address, port))
            return True
        except OSError:
            return False


def port_is_free(port: int) -> bool:
    if port_listeners(port):
        return False
    return _bind_available(socket.AF_INET, "127.0.0.1", port) and _bind_available(socket.AF_INET6, "::1", port)


def format_port_conflict(port: int, service: str, listeners: list[dict[str, Any]]) -> str:
    lines = [f"Cannot start {service}: fixed port {port} is already in use."]
    if listeners:
        lines.append("Detected listeners:")
        for listener in listeners:
            process = listener.get("process") or "unknown"
            pid = listener.get("pid") or "unknown"
            address = listener.get("address") or "unknown"
            path = listener.get("path")
            detail = f"  - {address}:{port} pid={pid} process={process}"
            if path:
                detail += f" path={path}"
            lines.append(detail)
        names = {str(item.get("process") or "").lower() for item in listeners}
        if any("wslrelay" in name for name in names):
            lines.append("WSL relay is listening on this port; inspect WSL workloads or run 'wsl --shutdown'.")
        if any("docker" in name or "com.docker" in name for name in names):
            lines.append("Docker Desktop is listening on this port; stop the existing platform stack first.")
        if any("python" in name or "uvicorn" in name for name in names):
            lines.append("A local Python/Uvicorn process is listening on this port; stop the previous local runtime.")
    else:
        lines.append("The fixed port could not be bound on IPv4 and IPv6, but the owning process was not discoverable.")
    lines.append("The supported ports are fixed: API 8000 and portal 3000.")
    return "\n".join(lines)


def require_free_port(port: int, service: str) -> None:
    listeners = port_listeners(port)
    if listeners or not port_is_free(port):
        raise RuntimeError(format_port_conflict(port, service, listeners))


def check_port(args: argparse.Namespace) -> None:
    listeners = port_listeners(args.port)
    result = {"port": args.port, "free": not listeners and port_is_free(args.port), "listeners": listeners}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    print(f"Port {args.port}: {'free' if result['free'] else 'in use'}")
    if listeners:
        print(format_port_conflict(args.port, "requested service", listeners))


def wait_tcp(port: int, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"Port did not become available: {port}")


def wait_http(url: str, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=5) as response:
                if 200 <= response.status < 500:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Endpoint did not become available: {url}. Last error: {last_error}")


def fetch_json(url: str) -> tuple[int | None, dict[str, Any] | None, str | None]:
    try:
        with urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload, None
    except Exception as exc:
        return None, None, str(exc)


def verify_cors() -> None:
    origin = PORTAL_URL
    request = Request(
        f"{API_URL}/health/live",
        method="OPTIONS",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            allowed_origin = response.headers.get("Access-Control-Allow-Origin")
            if response.status != 200 or allowed_origin != origin:
                raise RuntimeError(
                    f"CORS verification failed: status={response.status}, "
                    f"allowed_origin={allowed_origin!r}, expected={origin!r}"
                )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"CORS verification failed for {origin}: {exc}") from exc


def tail(path: Path, lines: int = 20) -> str:
    if not path.exists():
        return "<log file not found>"
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:]) or "<log file is empty>"


def start(name: str, args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    stdout_handle = (LOG_ROOT / f"{name}.out.log").open("wb")
    stderr_handle = (LOG_ROOT / f"{name}.err.log").open("wb")
    kwargs: dict[str, object] = {"cwd": cwd, "env": env, "stdout": stdout_handle, "stderr": stderr_handle}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(args, **kwargs)
    print(f"Started {name}: PID {process.pid}")
    return process


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except Exception:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def doctor() -> None:
    checks = {
        "python": Path(python_executable()),
        "repository": ROOT,
        "api": API_ROOT,
        "package.json": ROOT / "package.json",
        "compose": compose_file(),
    }
    failed = False
    for name, path in checks.items():
        ok = path.exists()
        print(f"{name:14} {'ok' if ok else 'missing'}  {path}")
        failed |= not ok
    for name in ("git", "npm", "docker"):
        value = shutil.which(name)
        print(f"{name:14} {'ok' if value else 'missing'}{f'  {value}' if value else ''}")
        failed |= value is None
    docker_ok = False
    if shutil.which("docker"):
        docker_ok = subprocess.run(
            [executable("docker"), "compose", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
    print(f"docker compose {'ok' if docker_ok else 'missing'}")
    print(f"API port       fixed  {FIXED_API_PORT}")
    print(f"Portal port    fixed  {FIXED_PORTAL_PORT}")
    failed |= not docker_ok
    if failed:
        raise RuntimeError("Local platform prerequisites are incomplete")


def compose_down(args: argparse.Namespace) -> None:
    command = compose_command("down", "--remove-orphans", include_all_profiles=True)
    if args.volumes:
        command.append("--volumes")
    run(command, env=fixed_runtime_environment())


def diagnose_compose_failure(environment: dict[str, str]) -> None:
    print("Compose startup verification failed; collecting diagnostics...", file=sys.stderr)
    run_best_effort(compose_command("ps", "--all"), env=environment)
    run_best_effort(compose_command("logs", "--tail", "80", "api", "portal", "scheduler", "migrator"), env=environment)


def rollback_compose_start(environment: dict[str, str]) -> None:
    print("Rolling back failed Compose startup...", file=sys.stderr)
    run_best_effort(compose_command("down", "--remove-orphans", include_all_profiles=True), env=environment)


def compose_up(args: argparse.Namespace) -> None:
    require_free_port(FIXED_API_PORT, "Compose API")
    require_free_port(FIXED_PORTAL_PORT, "Compose portal")
    environment = fixed_runtime_environment()
    command = compose_command("up")
    if args.build:
        command.append("--build")
    command.append("-d")
    try:
        run(command, env=environment)
        wait_http(f"{API_URL}/health/live")
        wait_http(f"{API_URL}/health/ready")
        wait_http(f"{PORTAL_URL}/operations")
        verify_cors()
    except Exception:
        # Compose may create resources before returning a non-zero exit code.
        diagnose_compose_failure(environment)
        if not args.keep_failed:
            rollback_compose_start(environment)
        else:
            print("Keeping failed Compose stack for inspection.", file=sys.stderr)
        raise
    print("Compose platform is running and externally verified")
    print(f"API:    {API_URL}")
    print(f"Portal: {PORTAL_URL}")


def compose_services() -> list[dict[str, Any]]:
    output = capture(compose_command("ps", "--all", "--format", "json"), env=fixed_runtime_environment()).strip()
    if not output:
        return []
    try:
        parsed = json.loads(output)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        records: list[dict[str, Any]] = []
        for line in output.splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records
    return []


def platform_status(args: argparse.Namespace) -> None:
    service_records = compose_services()
    by_service = {record.get("Service", "unknown"): record for record in service_records}
    live_status, live_payload, live_error = fetch_json(f"{API_URL}/health/live")
    ready_status, ready_payload, ready_error = fetch_json(f"{API_URL}/health/ready")
    platform_status_code, platform_payload, platform_error = fetch_json(f"{API_URL}/platform/status")
    configuration_status_code, configuration_payload, configuration_error = fetch_json(
        f"{API_URL}/platform/configuration"
    )
    services: list[dict[str, Any]] = []
    for service in (*EXPECTED_COMPOSE_SERVICES, *OPTIONAL_COMPOSE_SERVICES):
        record = by_service.get(service)
        services.append(
            {
                "service": service,
                "required": service in EXPECTED_COMPOSE_SERVICES,
                "present": record is not None,
                "state": record.get("State") if record else "not-created",
                "health": record.get("Health") if record else None,
                "status": record.get("Status") if record else None,
                "publishers": record.get("Publishers") if record else None,
            }
        )
    summary = {
        "runtime": "compose",
        "api_url": API_URL,
        "portal_url": PORTAL_URL,
        "fixed_ports": {"api": FIXED_API_PORT, "portal": FIXED_PORTAL_PORT},
        "ports": {
            "api": port_listeners(FIXED_API_PORT),
            "portal": port_listeners(FIXED_PORTAL_PORT),
        },
        "services": services,
        "api": {
            "live_http_status": live_status,
            "live": live_payload,
            "live_error": live_error,
            "ready_http_status": ready_status,
            "ready": ready_payload,
            "ready_error": ready_error,
        },
        "platform": platform_payload,
        "platform_http_status": platform_status_code,
        "platform_error": platform_error,
        "configuration": configuration_payload,
        "configuration_http_status": configuration_status_code,
        "configuration_error": configuration_error,
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return
    print("Industrial AI Platform status")
    print(f"API:    {API_URL}")
    print(f"Portal: {PORTAL_URL}")
    print()
    print(f"{'SERVICE':20} {'REQUIRED':9} {'STATE':14} {'HEALTH':12} STATUS")
    for service in services:
        print(
            f"{service['service']:20} {str(service['required']).lower():9} "
            f"{str(service['state']):14} {str(service['health'] or '-'):12} {service['status'] or '-'}"
        )
    print()
    print(f"API live:  {live_status or 'unavailable'}")
    print(f"API ready: {ready_status or 'unavailable'}")
    if ready_payload and isinstance(ready_payload, dict):
        print(f"Readiness: {ready_payload.get('status', 'unknown')}")
    if platform_payload:
        print(f"Version: {platform_payload.get('product_version', 'unknown')}")
        print(f"Stage: {platform_payload.get('release_stage', 'unknown')}")
        print(f"Sprint: {platform_payload.get('current_sprint', 'unknown')}")
        print(f"Work package: {platform_payload.get('current_work_package', 'unknown')}")
        print(f"Build commit: {platform_payload.get('build_commit', 'unknown')}")
        print(f"Database revision: {platform_payload.get('database_revision', 'unknown')}")
        print(f"Configuration revision: {platform_payload.get('configuration_revision', 'unknown')}")
    elif platform_error:
        print(f"Platform metadata: unavailable ({platform_error})")
    if configuration_payload:
        print(f"Effective portal port: {configuration_payload.get('portal_port', 'unknown')}")
        print(f"Effective CORS origins: {', '.join(configuration_payload.get('cors_origins', []))}")


def serve(args: argparse.Namespace) -> None:
    require_free_port(FIXED_API_PORT, "API")
    require_free_port(FIXED_PORTAL_PORT, "portal")
    python = python_executable()
    npm = executable("npm")
    git = executable("git")
    if not args.skip_install:
        run([npm, "install"])
        run([python, "-m", "pip", "install", "-r", "requirements.txt"], API_ROOT)
    if not args.skip_docker:
        run(compose_command("up", "-d", "postgres"), env=fixed_runtime_environment())
        wait_tcp(5432)
    if not args.skip_migrations:
        run(
            [python, "-m", "alembic", "upgrade", "head"],
            API_ROOT,
            child_environment(DATABASE_URL=LOCAL_DATABASE_URL),
        )
    commit = subprocess.check_output([git, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    children: dict[str, subprocess.Popen[bytes]] = {}
    try:
        children["api"] = start(
            "api",
            [python, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(FIXED_API_PORT)],
            API_ROOT,
            child_environment(DATABASE_URL=LOCAL_DATABASE_URL, BUILD_COMMIT=commit, PORTAL_PORT=str(FIXED_PORTAL_PORT)),
        )
        children["portal"] = start(
            "portal",
            [npm, "run", "dev:portal"],
            ROOT,
            child_environment(API_INTERNAL_BASE_URL=API_URL, PORT=str(FIXED_PORTAL_PORT)),
        )
        children["scheduler"] = start(
            "scheduler",
            [python, "scheduler_worker.py"],
            API_ROOT,
            child_environment(
                DATABASE_URL=LOCAL_DATABASE_URL,
                SCHEDULER_POLL_INTERVAL_SECONDS=str(args.scheduler_poll_interval),
                SCHEDULER_BATCH_LIMIT=str(args.scheduler_batch_limit),
                SCHEDULER_OWNER_ID="scheduler-local",
            ),
        )
        for name, process in children.items():
            time.sleep(0.5)
            if process.poll() is not None:
                raise RuntimeError(
                    f"{name} exited during startup with code {process.returncode}\n"
                    f"{tail(LOG_ROOT / f'{name}.err.log')}"
                )
        wait_http(f"{API_URL}/health/live")
        wait_http(f"{PORTAL_URL}/operations")
        wait_http(f"{API_URL}/health/ready")
        verify_cors()
        print("Local platform is running")
        print(f"API:    {API_URL}")
        print(f"Portal: {PORTAL_URL}")
        print("Press Ctrl+C to stop only processes started by this supervisor.")
        while True:
            for name, process in children.items():
                if process.poll() is not None:
                    raise RuntimeError(
                        f"{name} exited with code {process.returncode}\n"
                        f"{tail(LOG_ROOT / f'{name}.err.log')}"
                    )
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping local platform...")
    finally:
        for process in reversed(list(children.values())):
            stop(process)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cross-platform local platform supervisor (fixed API port 8000, portal port 3000)"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("doctor")
    port_parser = subcommands.add_parser("port-check", help="Inspect listeners for a local TCP port")
    port_parser.add_argument("--port", type=int, required=True)
    port_parser.add_argument("--json", action="store_true")
    status_parser = subcommands.add_parser("status", help="Show consolidated Compose and platform status")
    status_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    down_parser = subcommands.add_parser("compose-down", help="Stop all Compose services, including profiled services")
    down_parser.add_argument("--volumes", action="store_true", help="Also remove named volumes")
    up_parser = subcommands.add_parser("compose-up", help="Start and externally verify the Compose platform")
    up_parser.add_argument("--build", action="store_true")
    up_parser.add_argument("--keep-failed", action="store_true", help="Keep a failed stack running for inspection")
    serve_parser = subcommands.add_parser("serve")
    serve_parser.add_argument("--scheduler-poll-interval", type=float, default=5)
    serve_parser.add_argument("--scheduler-batch-limit", type=int, default=100)
    serve_parser.add_argument("--skip-install", action="store_true")
    serve_parser.add_argument("--skip-docker", action="store_true")
    serve_parser.add_argument("--skip-migrations", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "doctor":
        doctor()
    elif args.command == "port-check":
        check_port(args)
    elif args.command == "status":
        platform_status(args)
    elif args.command == "compose-down":
        compose_down(args)
    elif args.command == "compose-up":
        compose_up(args)
    else:
        serve(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

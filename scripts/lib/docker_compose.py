from __future__ import annotations

import shutil
from pathlib import Path
from typing import Mapping, Sequence

from .process_runner import ProcessResult, run_process


class DockerComposeUnavailableError(RuntimeError):
    pass


class DockerCompose:
    def __init__(
        self,
        *,
        project_root: Path,
        compose_files: Sequence[Path],
        profiles: Sequence[str] = (),
        timeout_seconds: int = 900,
    ) -> None:
        self.project_root = project_root.resolve()
        self.compose_files = tuple(path.resolve() for path in compose_files)
        self.profiles = tuple(profiles)
        self.timeout_seconds = timeout_seconds
        self._docker = self._detect()

    @staticmethod
    def _detect() -> str:
        docker = shutil.which("docker")
        if not docker:
            raise DockerComposeUnavailableError(
                "Docker executable was not found in PATH. Install Docker Desktop or Docker Engine."
            )
        result = run_process(
            [docker, "compose", "version"],
            stream=False,
            check=False,
            timeout_seconds=20,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise DockerComposeUnavailableError(
                "Docker Compose v2 is unavailable. Expected 'docker compose'. " + detail
            )
        return docker

    def command(self, arguments: Sequence[str]) -> list[str]:
        command = [self._docker, "compose"]
        for compose_file in self.compose_files:
            command.extend(["-f", str(compose_file)])
        for profile in self.profiles:
            command.extend(["--profile", profile])
        command.extend(str(argument) for argument in arguments)
        return command

    def run(
        self,
        arguments: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout_seconds: int | None = None,
        stream: bool = True,
        check: bool = True,
    ) -> ProcessResult:
        return run_process(
            self.command(arguments),
            cwd=self.project_root,
            env=env,
            timeout_seconds=timeout_seconds or self.timeout_seconds,
            stream=stream,
            check=check,
        )

    def diagnostic_logs(self, services: Sequence[str], *, tail: int = 200) -> None:
        for service in services:
            print(f"\n=== Diagnostic logs: {service} ===", flush=True)
            self.run(
                ["logs", "--no-color", "--tail", str(tail), service],
                timeout_seconds=120,
                check=False,
            )

    def down(self, *, volumes: bool = True, remove_orphans: bool = True) -> ProcessResult:
        arguments = ["down"]
        if volumes:
            arguments.append("--volumes")
        if remove_orphans:
            arguments.append("--remove-orphans")
        return self.run(arguments, timeout_seconds=300, check=False)

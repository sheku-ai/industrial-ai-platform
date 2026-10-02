from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ProcessResult:
    command: tuple[str, ...]
    returncode: int
    duration_seconds: float
    stdout: str
    stderr: str
    timed_out: bool = False


class ProcessExecutionError(RuntimeError):
    def __init__(self, message: str, result: ProcessResult):
        super().__init__(message)
        self.result = result


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGTERM)
        process.wait(timeout=5)
    except Exception:
        process.kill()
        process.wait(timeout=5)


def run_process(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int | float | None = None,
    stream: bool = True,
    check: bool = True,
) -> ProcessResult:
    if not command:
        raise ValueError("command must not be empty")
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    normalized_command = tuple(str(part) for part in command)
    run_env = os.environ.copy()
    if env:
        run_env.update({str(key): str(value) for key, value in env.items()})

    creationflags = 0
    start_new_session = os.name != "nt"
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    capture = not stream
    started = time.monotonic()
    process = subprocess.Popen(
        list(normalized_command),
        cwd=str(cwd) if cwd else None,
        env=run_env,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
        bufsize=1,
        start_new_session=start_new_session,
        creationflags=creationflags,
    )

    stdout_text = ""
    stderr_text = ""
    timed_out = False

    try:
        if capture:
            stdout_text, stderr_text = process.communicate(timeout=timeout_seconds)
            stdout_text = stdout_text or ""
            stderr_text = stderr_text or ""
        else:
            process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process(process)
        if capture:
            stdout_text, stderr_text = process.communicate()
            stdout_text = stdout_text or ""
            stderr_text = stderr_text or ""
    except KeyboardInterrupt:
        _terminate_process(process)
        raise

    result = ProcessResult(
        command=normalized_command,
        returncode=124 if timed_out else int(process.returncode or 0),
        duration_seconds=time.monotonic() - started,
        stdout=stdout_text,
        stderr=stderr_text,
        timed_out=timed_out,
    )

    if check and result.returncode != 0:
        reason = "timed out" if timed_out else f"failed with exit code {result.returncode}"
        raise ProcessExecutionError(f"Command {reason}: {' '.join(normalized_command)}", result)

    return result

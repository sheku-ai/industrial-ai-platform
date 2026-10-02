from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/setup-development.sh"
PRODUCT_INSTALLER = ROOT / "scripts/install-platform.sh"


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _fake_venv(venv: Path, *, valid: bool = True) -> None:
    venv.mkdir(parents=True, exist_ok=True)
    (venv / "pyvenv.cfg").write_text("home = fake-python-3.12\n", encoding="utf-8")
    _write_executable(
        venv / "bin/python",
        f"""#!/usr/bin/env bash
printf 'venv %s\\n' "$*" >> "$SETUP_TEST_LOG"
if [[ "$1" == "--version" ]]; then
  printf 'Python 3.12.8\\n'
  exit 0
fi
if [[ "$1" == "-c" ]]; then
  exit {0 if valid else 1}
fi
if [[ "$1" == "-m" && "$2" == "pip" && "$3" == "--version" ]]; then
  printf 'pip 24.0\\n'
  exit 0
fi
if [[ "$1" == "-m" && "$2" == "pip" && "$3" == "install" ]]; then
  exit 0
fi
exit 1
""",
    )


def _fake_host_python(bin_dir: Path, name: str, version: str) -> None:
    _write_executable(
        bin_dir / name,
        f"""#!/usr/bin/env bash
printf '{name} %s\\n' "$*" >> "$SETUP_TEST_LOG"
if [[ "$1" == "-c" ]]; then
  printf '{version}\\n'
  exit 0
fi
if [[ "$1" == "-m" && "$2" == "venv" ]]; then
  mkdir -p "$3/bin"
  printf 'home = fake-python-3.12\\n' > "$3/pyvenv.cfg"
  cp "$FAKE_VENV_PYTHON" "$3/bin/python"
  chmod +x "$3/bin/python"
  exit 0
fi
exit 1
""",
    )


def _checkout(tmp_path: Path) -> tuple[Path, Path, Path]:
    checkout = tmp_path / "source checkout"
    script = checkout / "scripts/setup-development.sh"
    script.parent.mkdir(parents=True)
    shutil.copyfile(BOOTSTRAP, script)
    requirements = checkout / "apps/api/requirements-dev.txt"
    requirements.parent.mkdir(parents=True)
    requirements.write_text("pytest==8.3.5\n", encoding="utf-8")
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    for command in ("bash", "dirname", "uname", "mkdir", "cp", "chmod"):
        executable = shutil.which(command)
        assert executable is not None
        (bin_dir / command).symlink_to(executable)
    return checkout, script, bin_dir


def _run(script: Path, bin_dir: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    template_venv = tmp_path / "template-venv"
    _fake_venv(template_venv)
    environment = {
        **os.environ,
        "PATH": str(bin_dir),
        "SETUP_TEST_LOG": str(tmp_path / "commands.log"),
        "FAKE_VENV_PYTHON": str(template_venv / "bin/python"),
    }
    return subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_python_312_creates_api_venv_and_installs_development_requirements(tmp_path: Path) -> None:
    checkout, script, bin_dir = _checkout(tmp_path)
    _fake_host_python(bin_dir, "python3.12", "3.12.8")

    result = _run(script, bin_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Development environment: READY" in result.stdout
    assert "Python detected: python3.12 (3.12.8)" in result.stdout
    venv_python = checkout / "apps/api/.venv/bin/python"
    assert venv_python.is_file()
    assert os.access(venv_python, os.X_OK)
    log = (tmp_path / "commands.log").read_text(encoding="utf-8")
    assert f"python3.12 -m venv {checkout}/apps/api/.venv" in log
    assert "python3.12 -m pip" not in log
    assert "venv -m pip --version" in log
    assert f"venv -m pip install -r {checkout}/apps/api/requirements-dev.txt" in log
    assert not (checkout / ".venv").exists()


def test_python_314_without_312_fails_before_creating_venv(tmp_path: Path) -> None:
    checkout, script, bin_dir = _checkout(tmp_path)
    _fake_host_python(bin_dir, "python3", "3.14.4")

    result = _run(script, bin_dir, tmp_path)

    assert result.returncode != 0
    assert "requires Python 3.12" in result.stderr
    assert "3.14.4" in result.stderr
    assert "Product Installer does not require host Python" in result.stderr
    assert not (checkout / "apps/api/.venv").exists()


def test_python_312_takes_priority_over_python3_314(tmp_path: Path) -> None:
    checkout, script, bin_dir = _checkout(tmp_path)
    _fake_host_python(bin_dir, "python3.12", "3.12.8")
    _fake_host_python(bin_dir, "python3", "3.14.4")

    result = _run(script, bin_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Python detected: python3.12 (3.12.8)" in result.stdout
    log = (tmp_path / "commands.log").read_text(encoding="utf-8")
    assert f"python3.12 -m venv {checkout}/apps/api/.venv" in log
    assert "python3 " not in log


def test_existing_valid_venv_is_reused_without_global_pip(tmp_path: Path) -> None:
    checkout, script, bin_dir = _checkout(tmp_path)
    _fake_host_python(bin_dir, "python3.12", "3.12.8")
    venv = checkout / "apps/api/.venv"
    _fake_venv(venv)
    marker = venv / "keep-me"
    marker.write_text("preserved", encoding="utf-8")

    result = _run(script, bin_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "(reused)" in result.stdout
    assert marker.read_text(encoding="utf-8") == "preserved"
    log = (tmp_path / "commands.log").read_text(encoding="utf-8")
    assert "-m venv" not in log
    assert "python3.12 -m pip" not in log
    assert "venv -m pip install -r " in log


def test_existing_incompatible_venv_fails_without_replacement(tmp_path: Path) -> None:
    checkout, script, bin_dir = _checkout(tmp_path)
    _fake_host_python(bin_dir, "python3.12", "3.12.8")
    venv = checkout / "apps/api/.venv"
    _fake_venv(venv, valid=False)
    marker = venv / "keep-me"
    marker.write_text("preserved", encoding="utf-8")

    result = _run(script, bin_dir, tmp_path)

    assert result.returncode != 0
    assert "not a valid Python 3.12 environment" in result.stderr
    assert marker.read_text(encoding="utf-8") == "preserved"
    assert "-m pip install" not in (tmp_path / "commands.log").read_text(encoding="utf-8")


def test_product_installer_remains_independent_of_development_venv() -> None:
    source = PRODUCT_INSTALLER.read_text(encoding="utf-8")

    assert "setup-development.sh" not in source
    assert "apps/api/.venv" not in source
    assert "require_command python" not in source


@pytest.mark.parametrize("launcher", ["platform_local.sh", "platform_local.ps1"])
def test_local_launchers_expect_canonical_api_venv(launcher: str) -> None:
    source = (ROOT / "scripts" / launcher).read_text(encoding="utf-8")

    expected_path = "apps/api/.venv" if launcher.endswith(".sh") else "apps\\api\\.venv"
    assert expected_path in source

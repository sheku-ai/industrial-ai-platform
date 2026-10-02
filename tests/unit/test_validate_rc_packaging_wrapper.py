"""Host database configuration for the RC packaging wrapper."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import URL

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "validate_rc_packaging.sh"
VALIDATOR = """
import json
import os
import sys
from pathlib import Path
from sqlalchemy.engine import make_url

raw = os.environ["DATABASE_URL"]
url = make_url(raw)
Path(os.environ["CAPTURE_PATH"]).write_text(json.dumps({
    "args": sys.argv[1:],
    "host": url.host,
    "port": url.port,
    "dbname": url.query.get("dbname"),
    "credentials_match": (
        url.username == os.environ.get("EXPECTED_USER")
        and url.password == os.environ.get("EXPECTED_PASSWORD")
        and url.query.get("dbname") == os.environ.get("EXPECTED_DB")
    ),
    "existing_url_preserved": raw == os.environ.get("EXPECTED_URL"),
    "special_values_encoded": (
        "%40" in raw and "%2F" in raw and "%23" in raw and "%25" in raw
    ),
}))
print("validator called")
"""


def _workspace(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    wrapper = scripts / WRAPPER.name
    shutil.copy2(WRAPPER, wrapper)
    (scripts / "platform_release_candidate.py").write_text(VALIDATOR)
    python = tmp_path / "apps" / "api" / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    capture = tmp_path / "capture.json"
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("INSTALL_ENV_FILE", None)
    env.pop("POSTGRES_PORT", None)
    env["CAPTURE_PATH"] = str(capture)
    env["PYTHONPATH"] = os.pathsep.join(path for path in sys.path if path)
    return wrapper, capture, env


def _env_file(
    path: Path,
    *,
    user: str = "quality_user",
    password: str = "quality_password",
    database: str = "quality_database",
    port: str | None = None,
) -> bytes:
    lines = [
        f"POSTGRES_USER={user}",
        f"POSTGRES_PASSWORD={password}",
        f"POSTGRES_DB={database}",
    ]
    if port is not None:
        lines.append(f"POSTGRES_PORT={port}")
    content = ("\n".join(lines) + "\n").encode()
    path.write_bytes(content)
    return content


def _run(wrapper: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(wrapper), *args],
        cwd=wrapper.parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_existing_database_url_is_preserved_without_an_env_file(tmp_path: Path) -> None:
    wrapper, capture, env = _workspace(tmp_path)
    env["DATABASE_URL"] = URL.create(
        "postgresql+psycopg",
        username="existing",
        password="existing",
        host="127.0.0.1",
        port=5432,
        database="existing",
    ).render_as_string(hide_password=False)
    env["EXPECTED_URL"] = env["DATABASE_URL"]
    result = _run(wrapper, env, "--release-summary")
    assert result.returncode == 0
    payload = json.loads(capture.read_text())
    assert payload["existing_url_preserved"]
    assert payload["args"] == ["--release-summary"]


def test_default_installer_env_derives_host_url_in_memory(tmp_path: Path) -> None:
    wrapper, capture, env = _workspace(tmp_path)
    env_file = tmp_path / ".env"
    original = _env_file(env_file)
    env.update(
        EXPECTED_USER="quality_user",
        EXPECTED_PASSWORD="quality_password",
        EXPECTED_DB="quality_database",
    )
    result = _run(wrapper, env)
    assert result.returncode == 0
    payload = json.loads(capture.read_text())
    assert payload["credentials_match"]
    assert payload["host"] == "127.0.0.1"
    assert payload["port"] == 5432
    assert payload["args"] == ["--release-contract"]
    assert env_file.read_bytes() == original
    assert b"DATABASE_URL=" not in env_file.read_bytes()


def test_custom_installer_env_and_postgres_port(tmp_path: Path) -> None:
    wrapper, capture, env = _workspace(tmp_path)
    custom = tmp_path / "custom.env"
    _env_file(custom, port="5544")
    env["INSTALL_ENV_FILE"] = str(custom)
    env.update(
        EXPECTED_USER="quality_user",
        EXPECTED_PASSWORD="quality_password",
        EXPECTED_DB="quality_database",
    )
    result = _run(wrapper, env, "--gates")
    assert result.returncode == 0
    payload = json.loads(capture.read_text())
    assert payload["credentials_match"]
    assert payload["port"] == 5544
    assert payload["args"] == ["--gates"]


def test_postgres_port_from_process_matches_installer_override(tmp_path: Path) -> None:
    wrapper, capture, env = _workspace(tmp_path)
    _env_file(tmp_path / ".env", port="5544")
    env["POSTGRES_PORT"] = "5545"
    result = _run(wrapper, env)
    assert result.returncode == 0
    assert json.loads(capture.read_text())["port"] == 5545


def test_special_credentials_and_database_are_encoded(tmp_path: Path) -> None:
    wrapper, capture, env = _workspace(tmp_path)
    user, password, database = "user@:/", "pass@:/?#%", "data@:/?#%"
    env_file = tmp_path / ".env"
    original = _env_file(env_file, user=user, password=password, database=database)
    env.update(EXPECTED_USER=user, EXPECTED_PASSWORD=password, EXPECTED_DB=database)
    result = _run(wrapper, env)
    assert result.returncode == 0
    payload = json.loads(capture.read_text())
    assert payload["credentials_match"]
    assert payload["special_values_encoded"]
    assert env_file.read_bytes() == original
    assert password not in result.stdout + result.stderr


@pytest.mark.parametrize("config", ["missing_file", "missing_password", "invalid_port"])
def test_incomplete_configuration_fails_without_secrets(tmp_path: Path, config: str) -> None:
    wrapper, capture, env = _workspace(tmp_path)
    secret = "do-not-print-this-password"
    if config == "missing_password":
        (tmp_path / ".env").write_text("POSTGRES_USER=user\nPOSTGRES_DB=db\n")
    elif config == "invalid_port":
        _env_file(tmp_path / ".env", password=secret, port="invalid")
    result = _run(wrapper, env)
    assert result.returncode != 0
    assert "RC packaging configuration error:" in result.stderr
    assert secret not in result.stdout + result.stderr
    assert not capture.exists()

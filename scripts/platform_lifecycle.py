#!/usr/bin/env python3
"""
Platform lifecycle operator command.

Sprint 28.1 scope
-----------------
Provide deterministic, non-destructive lifecycle checks for installation,
upgrade readiness and rollback boundary planning.

This command intentionally does not run Alembic upgrades/downgrades itself.
It reports the state an operator needs before applying a deployment action.

Supported commands
------------------
- status
- install-plan
- install-check
- upgrade-check
- pre-upgrade-check
- rollback-check
- rollback-plan
- readiness-check
- operation-instructions
- operation-decision

Output is JSON by default so automation can consume it without parsing logs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEFAULT_ALEMBIC_CONFIG_CANDIDATES = (
    "apps/api/alembic.ini",
    "alembic.ini",
)
DOTENV_CANDIDATES = (".env",)
PLACEHOLDER_MARKERS = (
    "placeholder",
    "change_me",
    "changeme",
    "example",
    "your-",
    "<",
    ">",
)
REQUIRED_OBJECT_STORAGE_KEYS = (
    "OBJECT_STORAGE_ENDPOINT_URL",
    "OBJECT_STORAGE_ACCESS_KEY",
    "OBJECT_STORAGE_SECRET_KEY",
    "OBJECT_STORAGE_BUCKET",
)
OPTIONAL_OBJECT_STORAGE_KEYS = (
    "OBJECT_STORAGE_REGION",
    "OBJECT_STORAGE_SECURE",
)
SUPPORTED_OBJECT_STORAGE_PROVIDERS = {"filesystem", "s3", "minio", "object_storage"}
DEFAULT_OBJECT_STORAGE_PROVIDER = "filesystem"
DEFAULT_FILESYSTEM_STORAGE_ROOT = ".runtime/storage/filesystem"
FILESYSTEM_STORAGE_ROOT_KEYS = (
    "INDUSTRIAL_AI_STORAGE_FILESYSTEM_ROOT",
    "FILESYSTEM_STORAGE_ROOT",
)
REQUIRED_QDRANT_KEYS = ("QDRANT_URL",)
OPTIONAL_AI_KEYS = (
    "FEATURE_EMBEDDINGS_ENABLED",
    "FEATURE_VECTOR_RETRIEVAL_ENABLED",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)
AI_DEGRADED_CAPABILITIES = ("rag", "ai_assistants")
QDRANT_DEGRADED_CAPABILITIES = ("vector_search", "rag")
SUPPORTED_OPERATIONS = ("install", "upgrade", "rollback", "full")


@dataclass(frozen=True)
class CommandResult:
    rc: int
    stdout: str
    stderr: str


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def json_dump(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def run_command(
    args: Sequence[str],
    cwd: Path,
    timeout_s: int,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd),
        env=dict(env) if env is not None else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
    )
    return CommandResult(
        rc=int(completed.returncode),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def load_dotenv_values(root: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for candidate in DOTENV_CANDIDATES:
        path = root / candidate
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key:
                values.setdefault(key, value)
    return values


def runtime_config_value(name: str, dotenv_values: Mapping[str, str]) -> Tuple[str, str]:
    env_value = os.environ.get(name)
    if env_value is not None:
        return env_value.strip(), "environment"
    dotenv_value = dotenv_values.get(name)
    if dotenv_value is not None:
        return dotenv_value.strip(), ".env"
    return "", "missing"


def first_runtime_config_value(
    names: Sequence[str], dotenv_values: Mapping[str, str]
) -> Tuple[str, str, str]:
    for name in names:
        value, source = runtime_config_value(name, dotenv_values)
        if source != "missing":
            return value, source, name
    return "", "missing", names[0]


def contains_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def truthy_config_value(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def redact_url(value: str) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return "<invalid-url>"

    netloc = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:
        port = None
    if port:
        netloc = f"{netloc}:{port}"
    if parts.username or parts.password:
        netloc = f"<credentials>@{netloc}"

    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def normalize_psycopg_url(value: str, connect_timeout_s: int) -> str:
    normalized = value
    if normalized.startswith("postgresql+psycopg://"):
        normalized = normalized.replace("postgresql+psycopg://", "postgresql://", 1)
    elif normalized.startswith("postgres+psycopg://"):
        normalized = normalized.replace("postgres+psycopg://", "postgresql://", 1)

    parts = urlsplit(normalized)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("connect_timeout", str(max(1, connect_timeout_s)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def validate_url_shape(name: str, value: str, allowed_schemes: Iterable[str]) -> Dict[str, Any]:
    allowed = set(allowed_schemes)
    present = bool(value)
    check: Dict[str, Any] = {
        "name": name,
        "present": present,
        "valid": False,
        "non_placeholder": bool(present and not contains_placeholder(value)),
        "redacted": redact_url(value),
        "shape": {
            "database_present": False,
            "host_present": False,
            "scheme": "",
        },
        "issues": [],
    }

    if not present:
        check["issues"].append("missing")
        return check
    if contains_placeholder(value):
        check["issues"].append("placeholder_value")

    try:
        parts = urlsplit(value)
    except ValueError:
        check["issues"].append("invalid_url")
        return check

    check["shape"]["scheme"] = parts.scheme
    check["shape"]["host_present"] = bool(parts.hostname)
    check["shape"]["database_present"] = bool(parts.path and parts.path != "/")

    if parts.scheme not in allowed:
        check["issues"].append("unsupported_scheme")
    if not parts.hostname:
        check["issues"].append("host_missing")

    check["valid"] = bool(not check["issues"])
    return check


def validate_key_presence(name: str, value: str, source: str, secret: bool = False) -> Dict[str, Any]:
    issues: List[str] = []
    if not value:
        issues.append("missing")
    elif contains_placeholder(value):
        issues.append("placeholder_value")

    return {
        "name": name,
        "present": bool(value),
        "source": source,
        "valid": not issues,
        "value": "<redacted>" if secret and value else value,
        "issues": issues,
    }


def build_object_storage_check(dotenv_values: Mapping[str, str]) -> Dict[str, Any]:
    configured_provider, provider_source = runtime_config_value("OBJECT_STORAGE_PROVIDER", dotenv_values)
    provider = (configured_provider or DEFAULT_OBJECT_STORAGE_PROVIDER).strip().lower()
    if provider_source == "missing":
        provider_source = "default"
    provider_check = {
        "name": "OBJECT_STORAGE_PROVIDER",
        "value": provider,
        "source": provider_source,
        "valid": provider in SUPPORTED_OBJECT_STORAGE_PROVIDERS,
        "issues": [] if provider in SUPPORTED_OBJECT_STORAGE_PROVIDERS else ["unsupported_provider"],
    }

    if provider == "filesystem":
        root_value, root_source, root_name = first_runtime_config_value(
            FILESYSTEM_STORAGE_ROOT_KEYS, dotenv_values
        )
        if root_source == "missing":
            root_value = DEFAULT_FILESYSTEM_STORAGE_ROOT
            root_source = "default"
        required = [validate_key_presence(root_name, root_value, root_source)]
        optional: List[Dict[str, Any]] = []
    else:
        required = [
            validate_key_presence(
                name,
                runtime_config_value(name, dotenv_values)[0],
                runtime_config_value(name, dotenv_values)[1],
                secret=name.endswith("_SECRET_KEY") or name.endswith("_ACCESS_KEY"),
            )
            for name in REQUIRED_OBJECT_STORAGE_KEYS
        ]
        optional = [
            validate_key_presence(
                name,
                runtime_config_value(name, dotenv_values)[0],
                runtime_config_value(name, dotenv_values)[1],
            )
            for name in OPTIONAL_OBJECT_STORAGE_KEYS
            if runtime_config_value(name, dotenv_values)[0]
        ]

    return {
        "ready": bool(provider_check["valid"] and all(item["valid"] for item in required)),
        "provider": provider_check,
        "required_configuration": required,
        "optional_configuration": optional,
    }


def document_management_vertical_evidence(database_url: str, timeout_s: int) -> Dict[str, Any]:
    if not database_url:
        return {
            "checked": False,
            "ready": False,
            "reason": "database_url_missing",
            "postgresql_source_of_truth": True,
        }
    engine = None
    try:
        api_path = repo_root() / "apps" / "api"
        if str(api_path) not in sys.path:
            sys.path.insert(0, str(api_path))
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from app.services.platform_read_projections import build_document_management_vertical_evidence

        engine = create_engine(
            database_url,
            connect_args={"connect_timeout": max(1, min(timeout_s, 5))},
            pool_pre_ping=True,
        )
        with Session(engine) as db:
            evidence = build_document_management_vertical_evidence(db)
        return {"checked": True, **evidence}
    except Exception as exc:
        return {
            "checked": True,
            "ready": False,
            "reason": "document_management_evidence_query_failed",
            "error_type": type(exc).__name__,
            "postgresql_source_of_truth": True,
        }
    finally:
        if engine is not None:
            engine.dispose()


def check_postgresql_connectivity(database_url: str, timeout_s: int) -> Dict[str, Any]:
    if not database_url:
        return {
            "checked": False,
            "reachable": False,
            "skipped_reason": "database_url_missing",
        }

    try:
        import psycopg  # type: ignore
    except Exception:
        try:
            parts = urlsplit(database_url)
            host = parts.hostname
            port = parts.port or 5432
            if not host:
                raise ValueError("database_host_missing")
            with socket.create_connection((host, port), timeout=max(1, min(timeout_s, 5))):
                pass
            return {
                "checked": True,
                "method": "tcp_socket",
                "reachable": True,
                "error": None,
            }
        except Exception as exc:
            return {
                "checked": True,
                "method": "tcp_socket",
                "reachable": False,
                "error": "connection_failed",
                "error_type": type(exc).__name__,
            }

    try:
        connect_url = normalize_psycopg_url(database_url, min(timeout_s, 5))
        with psycopg.connect(connect_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
        return {
            "checked": True,
            "method": "psycopg_select_1",
            "reachable": True,
            "error": None,
        }
    except Exception as exc:
        return {
            "checked": True,
            "method": "psycopg_select_1",
            "reachable": False,
            "error": "connection_failed",
            "error_type": type(exc).__name__,
        }


def database_runtime_check(dotenv_values: Mapping[str, str], timeout_s: int) -> Dict[str, Any]:
    database_url, database_source = runtime_config_value("DATABASE_URL", dotenv_values)
    configuration = validate_url_shape(
        "DATABASE_URL",
        database_url,
        ("postgresql", "postgres", "postgresql+psycopg", "postgres+psycopg"),
    )
    configuration["source"] = database_source
    postgresql = check_postgresql_connectivity(database_url, timeout_s)

    return {
        "ready": bool(configuration["valid"] and postgresql["reachable"]),
        "configuration": configuration,
        "postgresql": postgresql,
    }


def resolve_alembic_config(explicit: Optional[str]) -> Path:
    root = repo_root()
    candidates: List[Path] = []

    if explicit:
        candidates.append(Path(explicit))

    env_value = os.environ.get("ALEMBIC_CONFIG")
    if env_value:
        candidates.append(Path(env_value))

    candidates.extend(Path(item) for item in DEFAULT_ALEMBIC_CONFIG_CANDIDATES)

    for candidate in candidates:
        resolved = candidate if candidate.is_absolute() else root / candidate
        if resolved.exists():
            return resolved

    raise RuntimeError(
        "alembic_config_not_found: set ALEMBIC_CONFIG or pass --alembic-config"
    )


def parse_revision_tokens(text: str) -> List[str]:
    tokens: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Alembic commonly renders: "<rev> (head)" or "<rev> -> <next>".
        match = re.match(r"^([0-9A-Za-z_]+)\b", stripped)
        if not match:
            continue

        token = match.group(1)
        if token.lower() in {"rev", "running", "current"}:
            continue
        tokens.append(token)

    return list(dict.fromkeys(tokens))


def alembic_args(config_path: Path, command: str, extra: Sequence[str] = ()) -> List[str]:
    return [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        str(config_path),
        command,
        *extra,
    ]


def alembic_working_directory(config_path: Path) -> Path:
    return config_path.parent


def run_alembic(config_path: Path, command: str, extra: Sequence[str], timeout_s: int) -> CommandResult:
    command_environment = os.environ.copy()
    if not command_environment.get("DATABASE_URL"):
        database_url = load_dotenv_values(repo_root()).get("DATABASE_URL")
        if database_url:
            command_environment["DATABASE_URL"] = database_url
    return run_command(
        alembic_args(config_path, command, extra),
        cwd=alembic_working_directory(config_path),
        env=command_environment,
        timeout_s=timeout_s,
    )


def collect_repository_heads(config_path: Path, timeout_s: int) -> Tuple[List[str], Optional[str]]:
    result = run_alembic(config_path, "heads", (), timeout_s)
    if result.rc != 0:
        return [], (result.stderr or result.stdout).strip()
    return parse_revision_tokens(result.stdout), None


def collect_database_heads(config_path: Path, timeout_s: int) -> Tuple[List[str], Optional[str]]:
    result = run_alembic(config_path, "current", (), timeout_s)
    if result.rc != 0:
        return [], (result.stderr or result.stdout).strip()
    return parse_revision_tokens(result.stdout), None


def collect_history_revisions(config_path: Path, timeout_s: int) -> Tuple[List[str], Optional[str]]:
    result = run_alembic(config_path, "history", ("--verbose",), timeout_s)
    if result.rc != 0:
        return [], (result.stderr or result.stdout).strip()

    revisions: List[str] = []
    for line in result.stdout.splitlines():
        match = re.search(r"^Rev:\s*([0-9A-Za-z_]+)", line.strip())
        if match:
            revisions.append(match.group(1))

    return list(dict.fromkeys(revisions)), None


def lifecycle_status(config_path: Path, timeout_s: int) -> Dict[str, Any]:
    repository_heads, repository_error = collect_repository_heads(config_path, timeout_s)
    database_heads, database_error = collect_database_heads(config_path, timeout_s)

    migration_required = bool(
        repository_heads
        and database_heads
        and set(repository_heads) != set(database_heads)
    )

    compatibility = "unknown"
    startup_compatible = False
    pending_revisions: List[str] = []

    if repository_error or database_error:
        compatibility = "unverified"
    elif not repository_heads:
        compatibility = "repository_heads_missing"
    elif not database_heads:
        compatibility = "database_uninitialized"
        migration_required = True
        pending_revisions = repository_heads
    elif set(database_heads).issubset(set(repository_heads)) and not migration_required:
        compatibility = "compatible"
        startup_compatible = True
    else:
        compatibility = "migration_required"
        pending_revisions = [
            revision for revision in repository_heads if revision not in set(database_heads)
        ]

    return {
        "alembic_config": str(config_path),
        "alembic_cwd": str(alembic_working_directory(config_path)),
        "compatibility": compatibility,
        "database_heads": database_heads,
        "database_error": database_error,
        "migration_required": migration_required,
        "pending_revisions": pending_revisions,
        "repository_heads": repository_heads,
        "repository_error": repository_error,
        "startup_compatible": startup_compatible,
    }


def install_plan(config_path: Path, timeout_s: int) -> Dict[str, Any]:
    status = lifecycle_status(config_path, timeout_s)
    return {
        "plan": "install",
        "safe_to_execute": bool(status["repository_heads"] and not status["repository_error"]),
        "steps": [
            "verify runtime configuration",
            "start required persistence services",
            "run Alembic upgrade to repository head",
            "run lifecycle status until startup_compatible=true",
            "start API and platform workers",
            "run targeted smoke checks",
        ],
        "status": status,
    }


def install_check(config_path: Path, timeout_s: int) -> Dict[str, Any]:
    dotenv_values = load_dotenv_values(repo_root())

    database = database_runtime_check(dotenv_values, timeout_s)
    status = lifecycle_status(config_path, timeout_s)
    object_storage = build_object_storage_check(dotenv_values)

    qdrant_configuration = [
        validate_url_shape(name, runtime_config_value(name, dotenv_values)[0], ("http", "https"))
        for name in REQUIRED_QDRANT_KEYS
    ]
    for check in qdrant_configuration:
        check["source"] = runtime_config_value(check["name"], dotenv_values)[1]

    ai_optional = [
        {
            "name": name,
            "present": bool(runtime_config_value(name, dotenv_values)[0]),
            "source": runtime_config_value(name, dotenv_values)[1],
            "blocking": False,
        }
        for name in OPTIONAL_AI_KEYS
    ]

    embeddings_enabled = truthy_config_value(runtime_config_value("FEATURE_EMBEDDINGS_ENABLED", dotenv_values)[0])
    vector_retrieval_enabled = truthy_config_value(runtime_config_value("FEATURE_VECTOR_RETRIEVAL_ENABLED", dotenv_values)[0])
    llm_configured = any(
        bool(runtime_config_value(name, dotenv_values)[0])
        for name in ("OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    )
    database_url = runtime_config_value("DATABASE_URL", dotenv_values)[0]
    database_ready = bool(database["ready"])
    alembic_ready = bool(status["startup_compatible"] and not status["migration_required"])
    object_storage_ready = bool(object_storage["ready"])
    qdrant_ready = all(item["valid"] for item in qdrant_configuration)
    ai_configured = bool(embeddings_enabled and vector_retrieval_enabled and llm_configured)
    core_ready = bool(database_ready and alembic_ready)
    vertical_evidence = (
        document_management_vertical_evidence(database_url, timeout_s)
        if core_ready
        else {
            "checked": False,
            "ready": False,
            "reason": "core_profile_not_ready",
            "postgresql_source_of_truth": True,
        }
    )
    document_management_ready = bool(core_ready and object_storage_ready and vertical_evidence["ready"])
    ai_services_ready = bool(qdrant_ready and ai_configured)

    degraded_capabilities: List[str] = []
    if not qdrant_ready:
        degraded_capabilities.extend(QDRANT_DEGRADED_CAPABILITIES)
    if not ai_configured:
        degraded_capabilities.extend(AI_DEGRADED_CAPABILITIES)
    degraded_capabilities = list(dict.fromkeys(degraded_capabilities))
    ready = document_management_ready

    return {
        "plan": "install_check",
        "ready": ready,
        "degraded_capabilities": degraded_capabilities,
        "profiles": {
            "core": {
                "ready": core_ready,
                "required": ["postgresql", "alembic"],
                "blocking": True,
            },
            "document_management": {
                "ready": document_management_ready,
                "requires_profile": "core",
                "required": ["object_storage", "postgresql_document_vertical_evidence"],
                "blocking": True,
            },
            "ai_services": {
                "ready": ai_services_ready,
                "required": [],
                "optional": ["qdrant", "embeddings", "llm", "rag", "ai_assistants"],
                "blocking": False,
                "degraded_capabilities": degraded_capabilities,
            },
        },
        "checks": {
            "alembic": {
                "ready": alembic_ready,
                "migration_required": status["migration_required"],
                "startup_compatible": status["startup_compatible"],
            },
            "ai_services": {
                "blocking": False,
                "ready": ai_services_ready,
                "degraded_capabilities": degraded_capabilities,
                "observed_configuration": ai_optional,
            },
            "database": {
                "ready": database_ready,
                "configuration": database["configuration"],
                "postgresql": database["postgresql"],
            },
            "document_management_evidence": vertical_evidence,
            "object_storage": object_storage,
            "qdrant": {
                "ready": qdrant_ready,
                "blocking": False,
                "degraded_capabilities": list(QDRANT_DEGRADED_CAPABILITIES) if not qdrant_ready else [],
                "configuration": qdrant_configuration,
            },
        },
        "status": status,
    }


def upgrade_check(config_path: Path, timeout_s: int) -> Dict[str, Any]:
    dotenv_values = load_dotenv_values(repo_root())
    database = database_runtime_check(dotenv_values, timeout_s)
    status = lifecycle_status(config_path, timeout_s)
    history, history_error = collect_history_revisions(config_path, timeout_s)

    repository_heads = set(status["repository_heads"])
    database_heads = set(status["database_heads"])
    alembic_verifiable = bool(
        status["repository_error"] is None
        and status["database_error"] is None
        and status["repository_heads"]
    )
    database_revision_known = bool(
        status["database_heads"]
        and not history_error
        and database_heads.issubset(set(history))
    )
    upgrade_required = bool(status["migration_required"])
    current_code_startup_safe = bool(status["startup_compatible"])
    upgrade_path_known = bool(
        alembic_verifiable
        and status["repository_heads"]
        and (
            not status["database_heads"]
            or database_revision_known
            or database_heads.issubset(repository_heads)
        )
    )
    ready = bool(database["ready"] and alembic_verifiable and upgrade_path_known)

    if not database["ready"]:
        operator_action = "fix_database_connectivity"
    elif not alembic_verifiable:
        operator_action = "fix_alembic_status"
    elif not upgrade_path_known:
        operator_action = "do_not_upgrade_unknown_revision_path"
    elif upgrade_required:
        operator_action = "backup_then_run_alembic_upgrade"
    else:
        operator_action = "no_schema_upgrade_required"

    return {
        "plan": "upgrade_check",
        "ready": ready,
        "upgrade_required": upgrade_required,
        "safe_to_start_current_code": current_code_startup_safe,
        "safe_to_attempt_upgrade": ready,
        "destructive_action_executed": False,
        "migration_executed": False,
        "operator_action_required": operator_action,
        "checks": {
            "alembic": {
                "ready": alembic_verifiable,
                "database_revision_known": database_revision_known,
                "history_error": history_error,
                "known_revisions_count": len(history),
                "migration_required": status["migration_required"],
                "pending_revisions": status["pending_revisions"],
                "repository_heads": status["repository_heads"],
                "database_heads": status["database_heads"],
            },
            "database": database,
        },
        "status": status,
    }


def pre_upgrade_check(config_path: Path, timeout_s: int) -> Dict[str, Any]:
    payload = upgrade_check(config_path, timeout_s)
    return {
        "plan": "pre_upgrade_check",
        "upgrade_required": payload["upgrade_required"],
        "safe_to_start_current_code": payload["safe_to_start_current_code"],
        "safe_to_attempt_upgrade": payload["safe_to_attempt_upgrade"],
        "status": payload["status"],
    }


def rollback_check(config_path: Path, timeout_s: int, target_revision: Optional[str]) -> Dict[str, Any]:
    dotenv_values = load_dotenv_values(repo_root())
    database = database_runtime_check(dotenv_values, timeout_s)
    status = lifecycle_status(config_path, timeout_s)
    history, history_error = collect_history_revisions(config_path, timeout_s)

    history_set = set(history)
    target_known = bool(target_revision and target_revision in set(history))
    current_known = bool(
        status["database_heads"]
        and all(revision in history_set for revision in status["database_heads"])
    )
    current_at_target = bool(
        target_revision
        and status["database_heads"]
        and set(status["database_heads"]) == {target_revision}
    )

    safe_boundary = bool(
        target_revision
        and target_known
        and current_known
        and not history_error
        and status["database_heads"]
    )

    ready = bool(database["ready"] and safe_boundary and not current_at_target)

    if not target_revision:
        operator_action = "provide_target_revision"
    elif not database["ready"]:
        operator_action = "fix_database_connectivity"
    elif history_error:
        operator_action = "fix_alembic_history"
    elif not target_known:
        operator_action = "do_not_downgrade_unknown_target"
    elif not current_known:
        operator_action = "do_not_downgrade_unknown_current_revision"
    elif current_at_target:
        operator_action = "no_rollback_required"
    else:
        operator_action = "backup_then_manual_alembic_downgrade"

    return {
        "plan": "rollback_check",
        "requested_target_revision": target_revision,
        "ready": ready,
        "safe_boundary_identified": safe_boundary,
        "target_known": target_known,
        "current_known": current_known,
        "current_at_target": current_at_target,
        "destructive_action_executed": False,
        "downgrade_executed": False,
        "operator_action_required": operator_action,
        "checks": {
            "alembic": {
                "ready": bool(safe_boundary),
                "current_known": current_known,
                "history_error": history_error,
                "known_revisions_count": len(history),
                "target_known": target_known,
                "database_heads": status["database_heads"],
            },
            "database": database,
        },
        "history_error": history_error,
        "known_revisions": history,
        "status": status,
    }


def rollback_plan(config_path: Path, timeout_s: int, target_revision: Optional[str]) -> Dict[str, Any]:
    payload = rollback_check(config_path, timeout_s, target_revision)
    operator_action = (
        "manual_alembic_downgrade_after_backup"
        if payload["safe_boundary_identified"] and not payload["current_at_target"]
        else "do_not_downgrade"
    )

    return {
        "plan": "rollback",
        "requested_target_revision": payload["requested_target_revision"],
        "safe_boundary_identified": payload["safe_boundary_identified"],
        "target_known": payload["target_known"],
        "current_known": payload["current_known"],
        "destructive_action_executed": False,
        "operator_action_required": operator_action,
        "history_error": payload["history_error"],
        "known_revisions": payload["known_revisions"],
        "status": payload["status"],
    }


def readiness_check(config_path: Path, timeout_s: int, target_revision: Optional[str]) -> Dict[str, Any]:
    install = install_check(config_path, timeout_s)
    upgrade = upgrade_check(config_path, timeout_s)
    rollback_requested = bool(target_revision)
    rollback = rollback_check(config_path, timeout_s, target_revision) if rollback_requested else None

    ready = bool(
        install["ready"]
        and upgrade["ready"]
        and (rollback is None or rollback["ready"])
    )

    blocking_checks: List[str] = []
    if not install["ready"]:
        blocking_checks.append("install")
    if not upgrade["ready"]:
        blocking_checks.append("upgrade")
    if rollback is not None and not rollback["ready"]:
        blocking_checks.append("rollback")

    if blocking_checks:
        operator_action = "resolve_blocking_lifecycle_checks"
    elif rollback_requested:
        operator_action = "ready_for_install_upgrade_and_rollback_boundary"
    else:
        operator_action = "ready_for_install_and_upgrade_boundary"

    return {
        "plan": "readiness_check",
        "ready": ready,
        "blocking_checks": blocking_checks,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
        "operator_action_required": operator_action,
        "profiles": install["profiles"],
        "degraded_capabilities": install["degraded_capabilities"],
        "checks": {
            "install": {
                "ready": install["ready"],
                "operator_action_required": "start_installation" if install["ready"] else "fix_installation_readiness",
            },
            "upgrade": {
                "ready": upgrade["ready"],
                "operator_action_required": upgrade["operator_action_required"],
                "upgrade_required": upgrade["upgrade_required"],
            },
            "rollback": {
                "requested": rollback_requested,
                "ready": bool(rollback and rollback["ready"]),
                "operator_action_required": rollback["operator_action_required"] if rollback else "provide_target_revision_when_rollback_required",
            },
        },
        "install": install,
        "upgrade": upgrade,
        "rollback": rollback,
    }


def operation_instructions(operation: str, target_revision: Optional[str]) -> Dict[str, Any]:
    target_arg = " --target-revision <revision>"
    concrete_target_arg = f" --target-revision {target_revision}" if target_revision else target_arg
    instructions: Dict[str, List[Dict[str, Any]]] = {
        "install": [
            {
                "phase": "preflight",
                "intent": "verify runtime configuration and required persistence readiness",
                "command": "python scripts/platform_lifecycle.py install-check",
                "required_before_next": True,
            },
            {
                "phase": "schema",
                "intent": "apply repository schema to the configured database after backup policy is satisfied",
                "command": "cd apps/api && python -m alembic upgrade head",
                "required_before_next": True,
                "destructive": False,
                "automatic": False,
            },
            {
                "phase": "verify",
                "intent": "confirm installed schema is startup-compatible with current code",
                "command": "python scripts/platform_lifecycle.py status",
                "required_before_next": True,
            },
            {
                "phase": "start",
                "intent": "start API, workers and UI using deployment-specific process control",
                "command": "<deployment-specific start command>",
                "required_before_next": False,
            },
        ],
        "upgrade": [
            {
                "phase": "preflight",
                "intent": "verify database connectivity and Alembic upgrade boundary",
                "command": "python scripts/platform_lifecycle.py upgrade-check",
                "required_before_next": True,
            },
            {
                "phase": "backup",
                "intent": "capture a restorable database and object storage backup before schema changes",
                "command": "<deployment-specific backup command>",
                "required_before_next": True,
            },
            {
                "phase": "schema",
                "intent": "apply pending Alembic revisions only after preflight and backup pass",
                "command": "cd apps/api && python -m alembic upgrade head",
                "required_before_next": True,
                "destructive": False,
                "automatic": False,
            },
            {
                "phase": "verify",
                "intent": "confirm the upgraded database is compatible before traffic is restored",
                "command": "python scripts/platform_lifecycle.py status",
                "required_before_next": True,
            },
        ],
        "rollback": [
            {
                "phase": "preflight",
                "intent": "verify rollback target and current database revision are known",
                "command": f"python scripts/platform_lifecycle.py rollback-check{concrete_target_arg}",
                "required_before_next": True,
            },
            {
                "phase": "backup",
                "intent": "capture current database and object storage state before downgrade",
                "command": "<deployment-specific backup command>",
                "required_before_next": True,
            },
            {
                "phase": "schema",
                "intent": "perform manual Alembic downgrade only after operator approval",
                "command": "cd apps/api && python -m alembic downgrade <revision>",
                "required_before_next": True,
                "destructive": True,
                "automatic": False,
            },
            {
                "phase": "verify",
                "intent": "confirm rollback boundary and application compatibility",
                "command": "python scripts/platform_lifecycle.py status",
                "required_before_next": True,
            },
        ],
    }

    selected_operations = ("install", "upgrade", "rollback") if operation == "full" else (operation,)
    return {
        "plan": "operation_instructions",
        "operation": operation,
        "target_revision": target_revision,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
        "operator_approval_required": operation in {"rollback", "full"},
        "instructions": [
            {
                "operation": item,
                "steps": instructions[item],
            }
            for item in selected_operations
        ],
    }


def operation_decision(
    config_path: Path,
    timeout_s: int,
    operation: str,
    target_revision: Optional[str],
) -> Dict[str, Any]:
    instructions = operation_instructions(operation, target_revision)

    if operation == "install":
        readiness = install_check(config_path, timeout_s)
        requested_ready = bool(readiness["profiles"]["document_management"]["ready"])
        manual_approval_required = False
        blocking_reasons = [] if requested_ready else ["install_readiness_blocked"]
    elif operation == "upgrade":
        readiness = upgrade_check(config_path, timeout_s)
        requested_ready = bool(readiness["ready"])
        manual_approval_required = bool(readiness["upgrade_required"])
        blocking_reasons = [] if requested_ready else ["upgrade_readiness_blocked"]
    elif operation == "rollback":
        readiness = rollback_check(config_path, timeout_s, target_revision)
        requested_ready = bool(readiness["ready"])
        manual_approval_required = True
        blocking_reasons = [] if requested_ready else ["rollback_readiness_blocked"]
    else:
        readiness = readiness_check(config_path, timeout_s, target_revision)
        requested_ready = bool(readiness["ready"])
        manual_approval_required = bool(target_revision)
        blocking_reasons = list(readiness["blocking_checks"])

    if blocking_reasons:
        decision = "blocked"
    elif manual_approval_required:
        decision = "manual_approval_required"
    else:
        decision = "proceed"

    return {
        "plan": "operation_decision",
        "operation": operation,
        "target_revision": target_revision,
        "decision": decision,
        "ready": requested_ready,
        "blocking_reasons": blocking_reasons,
        "manual_approval_required": manual_approval_required,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
        "next_command": f"python scripts/platform_lifecycle.py operation-instructions --operation {operation}",
        "readiness": readiness,
        "instructions": instructions,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Industrial AI Platform lifecycle command")
    parser.add_argument(
        "command",
        choices=(
            "status",
            "install-plan",
            "install-check",
            "upgrade-check",
            "pre-upgrade-check",
            "rollback-check",
            "rollback-plan",
            "readiness-check",
            "operation-instructions",
            "operation-decision",
        ),
    )
    parser.add_argument("--alembic-config", default=None)
    parser.add_argument("--timeout-s", type=int, default=30)
    parser.add_argument("--target-revision", default=None)
    parser.add_argument("--operation", choices=SUPPORTED_OPERATIONS, default="full")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config_path = resolve_alembic_config(args.alembic_config)

        if args.command == "status":
            payload = lifecycle_status(config_path, args.timeout_s)
        elif args.command == "install-plan":
            payload = install_plan(config_path, args.timeout_s)
        elif args.command == "install-check":
            payload = install_check(config_path, args.timeout_s)
        elif args.command == "upgrade-check":
            payload = upgrade_check(config_path, args.timeout_s)
        elif args.command == "pre-upgrade-check":
            payload = pre_upgrade_check(config_path, args.timeout_s)
        elif args.command == "rollback-check":
            payload = rollback_check(config_path, args.timeout_s, args.target_revision)
        elif args.command == "rollback-plan":
            payload = rollback_plan(config_path, args.timeout_s, args.target_revision)
        elif args.command == "operation-instructions":
            payload = operation_instructions(args.operation, args.target_revision)
        elif args.command == "operation-decision":
            payload = operation_decision(
                config_path,
                args.timeout_s,
                args.operation,
                args.target_revision,
            )
        else:
            payload = readiness_check(config_path, args.timeout_s, args.target_revision)

        print(json_dump(payload))
        return 0
    except subprocess.TimeoutExpired as exc:
        print(json_dump({"error": "command_timeout", "detail": str(exc)}))
        return 2
    except Exception as exc:
        print(json_dump({"error": type(exc).__name__, "detail": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

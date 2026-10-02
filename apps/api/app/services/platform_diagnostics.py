"""Shared platform diagnostics builder for CLI and API surfaces."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

METADATA_FILE = Path("app/core/platform_metadata.py")
DEFAULT_ALEMBIC_CONFIG_CANDIDATES = ("alembic.ini", "apps/api/alembic.ini")
PLACEHOLDER_MARKERS = ("placeholder", "change_me", "changeme", "example", "your-", "<", ">")
REQUIRED_OBJECT_STORAGE_KEYS = (
    "OBJECT_STORAGE_ENDPOINT_URL",
    "OBJECT_STORAGE_ACCESS_KEY",
    "OBJECT_STORAGE_SECRET_KEY",
    "OBJECT_STORAGE_BUCKET",
)
OPTIONAL_OBJECT_STORAGE_KEYS = ("OBJECT_STORAGE_REGION", "OBJECT_STORAGE_SECURE")
SUPPORTED_OBJECT_STORAGE_PROVIDERS = {"filesystem", "s3", "minio", "object_storage"}
DEFAULT_OBJECT_STORAGE_PROVIDER = "filesystem"
DEFAULT_FILESYSTEM_STORAGE_ROOT = ".runtime/storage/filesystem"
FILESYSTEM_STORAGE_ROOT_KEYS = (
    "INDUSTRIAL_AI_STORAGE_FILESYSTEM_ROOT",
    "FILESYSTEM_STORAGE_ROOT",
)
AI_DEGRADED_CAPABILITIES = ("rag", "ai_assistants")
QDRANT_DEGRADED_CAPABILITIES = ("vector_search", "rag")


def repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "apps" / "api").exists() and (parent / "scripts").exists():
            return parent
    return current.parents[3]


def api_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "app").exists() and (parent / "alembic.ini").exists():
            return parent
    return current.parents[2]


def load_dotenv_values(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in (root / ".env", api_root() / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip():
                values.setdefault(key.strip(), value.strip().strip("'\""))
    return values


def config_value(name: str, dotenv_values: Mapping[str, str]) -> tuple[str, str]:
    env_value = os.environ.get(name)
    if env_value is not None:
        return env_value.strip(), "environment"
    dotenv_value = dotenv_values.get(name)
    if dotenv_value is not None:
        return dotenv_value.strip(), ".env"
    return "", "missing"


def mapped_config_value(
    name: str,
    config_values: Mapping[str, str],
    config_sources: Mapping[str, str],
) -> tuple[str, str]:
    value = config_values.get(name)
    if value is None:
        return "", "missing"
    return value.strip(), config_sources.get(name, "mapping")


def first_mapped_config_value(
    names: Sequence[str],
    config_values: Mapping[str, str],
    config_sources: Mapping[str, str],
) -> tuple[str, str, str]:
    for name in names:
        value, source = mapped_config_value(name, config_values, config_sources)
        if source != "missing":
            return value, source, name
    return "", "missing", names[0]


def resolve_object_storage_config(
    dotenv_values: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    names = (
        "OBJECT_STORAGE_PROVIDER",
        *FILESYSTEM_STORAGE_ROOT_KEYS,
        *REQUIRED_OBJECT_STORAGE_KEYS,
        *OPTIONAL_OBJECT_STORAGE_KEYS,
    )
    for name in names:
        value, source = config_value(name, dotenv_values)
        if source != "missing":
            values[name] = value
            sources[name] = source
    return values, sources


def contains_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(normalized and any(marker in normalized for marker in PLACEHOLDER_MARKERS))


def truthy_config_value(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def redact_url(value: str) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return "<invalid-url>"
    netloc = parts.hostname or ""
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


def validate_url_shape(name: str, value: str, allowed_schemes: Sequence[str]) -> dict[str, Any]:
    check: dict[str, Any] = {
        "name": name,
        "present": bool(value),
        "valid": False,
        "non_placeholder": bool(value and not contains_placeholder(value)),
        "redacted": redact_url(value),
        "shape": {"database_present": False, "host_present": False, "scheme": ""},
        "issues": [],
    }
    if not value:
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
    if parts.scheme not in set(allowed_schemes):
        check["issues"].append("unsupported_scheme")
    if not parts.hostname:
        check["issues"].append("host_missing")
    check["valid"] = bool(not check["issues"])
    return check


def validate_key_presence(name: str, value: str, source: str, secret: bool = False) -> dict[str, Any]:
    issues: list[str] = []
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


def build_object_storage_check(
    config_values: Mapping[str, str],
    *,
    config_sources: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    sources = config_sources or {}
    configured_provider, provider_source = mapped_config_value(
        "OBJECT_STORAGE_PROVIDER",
        config_values,
        sources,
    )
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
        root_value, root_source, root_name = first_mapped_config_value(
            FILESYSTEM_STORAGE_ROOT_KEYS,
            config_values,
            sources,
        )
        if root_source == "missing":
            root_value = DEFAULT_FILESYSTEM_STORAGE_ROOT
            root_source = "default"
        required = [validate_key_presence(root_name, root_value, root_source)]
        optional: list[dict[str, Any]] = []
    else:
        required = [
            validate_key_presence(
                name,
                mapped_config_value(name, config_values, sources)[0],
                mapped_config_value(name, config_values, sources)[1],
                secret=name.endswith("_SECRET_KEY") or name.endswith("_ACCESS_KEY"),
            )
            for name in REQUIRED_OBJECT_STORAGE_KEYS
        ]
        optional = [
            validate_key_presence(
                name,
                mapped_config_value(name, config_values, sources)[0],
                mapped_config_value(name, config_values, sources)[1],
            )
            for name in OPTIONAL_OBJECT_STORAGE_KEYS
            if mapped_config_value(name, config_values, sources)[0]
        ]

    return {
        "ready": bool(provider_check["valid"] and all(item["valid"] for item in required)),
        "provider": provider_check,
        "required_configuration": required,
        "optional_configuration": optional,
    }


def build_document_management_evidence(database_url: str, timeout_s: int) -> dict[str, Any]:
    if not database_url:
        return {
            "checked": False,
            "ready": False,
            "reason": "database_url_missing",
            "postgresql_source_of_truth": True,
        }
    engine = None
    try:
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


def check_postgresql_connectivity(database_url: str, timeout_s: int) -> dict[str, Any]:
    if not database_url:
        return {"checked": False, "reachable": False, "skipped_reason": "database_url_missing"}
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
            return {"checked": True, "method": "tcp_socket", "reachable": True, "error": None}
        except Exception as exc:
            return {
                "checked": True,
                "method": "tcp_socket",
                "reachable": False,
                "error": "connection_failed",
                "error_type": type(exc).__name__,
            }

    try:
        with (
            psycopg.connect(normalize_psycopg_url(database_url, min(timeout_s, 5))) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("select 1")
            cursor.fetchone()
        return {"checked": True, "method": "psycopg_select_1", "reachable": True, "error": None}
    except Exception as exc:
        return {
            "checked": True,
            "method": "psycopg_select_1",
            "reachable": False,
            "error": "connection_failed",
            "error_type": type(exc).__name__,
        }


def resolve_alembic_config(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_value = os.environ.get("ALEMBIC_CONFIG")
    if env_value:
        candidates.append(Path(env_value))
    root = repo_root()
    api = api_root()
    candidates.extend(root / item for item in DEFAULT_ALEMBIC_CONFIG_CANDIDATES)
    candidates.append(api / "alembic.ini")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError("alembic_config_not_found")


def parse_revision_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^([0-9A-Za-z_]+)\b", line.strip())
        if match and match.group(1).lower() not in {"rev", "running", "current"}:
            tokens.append(match.group(1))
    return list(dict.fromkeys(tokens))


def run_alembic(config_path: Path, command: str, extra: Sequence[str], timeout_s: int) -> tuple[list[str], str | None]:
    command_environment = os.environ.copy()
    if not command_environment.get("DATABASE_URL"):
        database_url = load_dotenv_values(repo_root()).get("DATABASE_URL")
        if database_url:
            command_environment["DATABASE_URL"] = database_url
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(config_path), command, *extra],
        cwd=str(config_path.parent),
        env=command_environment,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    if completed.returncode != 0:
        return [], (completed.stderr or completed.stdout).strip()
    if command == "history":
        revisions = [
            match.group(1)
            for line in completed.stdout.splitlines()
            if (match := re.search(r"^Rev:\s*([0-9A-Za-z_]+)", line.strip()))
        ]
        return list(dict.fromkeys(revisions)), None
    return parse_revision_tokens(completed.stdout), None


def lifecycle_status(config_path: Path, timeout_s: int) -> dict[str, Any]:
    repository_heads, repository_error = run_alembic(config_path, "heads", (), timeout_s)
    database_heads, database_error = run_alembic(config_path, "current", (), timeout_s)
    migration_required = bool(repository_heads and database_heads and set(repository_heads) != set(database_heads))
    compatibility = "unverified" if repository_error or database_error else "unknown"
    startup_compatible = False
    pending_revisions: list[str] = []
    if not repository_error and not database_error:
        if not repository_heads:
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
            pending_revisions = [revision for revision in repository_heads if revision not in set(database_heads)]
    return {
        "alembic_config": str(config_path),
        "alembic_cwd": str(config_path.parent),
        "compatibility": compatibility,
        "database_heads": database_heads,
        "database_error": database_error,
        "migration_required": migration_required,
        "pending_revisions": pending_revisions,
        "repository_heads": repository_heads,
        "repository_error": repository_error,
        "startup_compatible": startup_compatible,
    }


def read_platform_metadata() -> dict[str, str]:
    metadata_path = api_root() / METADATA_FILE
    metadata = {"name": "Industrial AI Platform", "version": "unknown", "release_stage": "unknown"}
    if metadata_path.exists():
        source = metadata_path.read_text(encoding="utf-8")
        for key, constant in {
            "name": "PRODUCT_NAME",
            "version": "PRODUCT_VERSION",
            "release_stage": "RELEASE_STAGE",
        }.items():
            match = re.search(
                rf'^{constant}[ \t]*(?::[ \t]*[^=\n]+)?[ \t]*=[ \t]*"([^"]+)"',
                source,
                re.MULTILINE,
            )
            if match:
                metadata[key] = match.group(1)
    return metadata


def build_install_profile(config_path: Path, timeout_s: int, dotenv_values: Mapping[str, str]) -> dict[str, Any]:
    database_url, database_source = config_value("DATABASE_URL", dotenv_values)
    database_config = validate_url_shape(
        "DATABASE_URL", database_url, ("postgresql", "postgres", "postgresql+psycopg", "postgres+psycopg")
    )
    database_config["source"] = database_source
    postgresql = check_postgresql_connectivity(database_url, timeout_s)
    database = {
        "ready": bool(database_config["valid"] and postgresql["reachable"]),
        "configuration": database_config,
        "postgresql": postgresql,
    }
    status = lifecycle_status(config_path, timeout_s)
    object_storage_values, object_storage_sources = resolve_object_storage_config(dotenv_values)
    object_storage = build_object_storage_check(
        object_storage_values,
        config_sources=object_storage_sources,
    )
    qdrant_configuration = [
        validate_url_shape("QDRANT_URL", config_value("QDRANT_URL", dotenv_values)[0], ("http", "https"))
    ]
    qdrant_configuration[0]["source"] = config_value("QDRANT_URL", dotenv_values)[1]
    ai_observed = [
        {
            "name": name,
            "present": bool(config_value(name, dotenv_values)[0]),
            "source": config_value(name, dotenv_values)[1],
            "blocking": False,
        }
        for name in (
            "FEATURE_EMBEDDINGS_ENABLED",
            "FEATURE_VECTOR_RETRIEVAL_ENABLED",
            "OPENAI_API_KEY",
            "AZURE_OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        )
    ]
    qdrant_ready = all(item["valid"] for item in qdrant_configuration)
    ai_configured = bool(
        truthy_config_value(config_value("FEATURE_EMBEDDINGS_ENABLED", dotenv_values)[0])
        and truthy_config_value(config_value("FEATURE_VECTOR_RETRIEVAL_ENABLED", dotenv_values)[0])
        and any(
            config_value(name, dotenv_values)[0]
            for name in ("OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "ANTHROPIC_API_KEY")
        )
    )
    alembic_ready = bool(status["startup_compatible"] and not status["migration_required"])
    core_ready = bool(database["ready"] and alembic_ready)
    object_storage_ready = bool(object_storage["ready"])
    document_management_evidence = (
        build_document_management_evidence(database_url, timeout_s)
        if core_ready
        else {
            "checked": False,
            "ready": False,
            "reason": "core_profile_not_ready",
            "postgresql_source_of_truth": True,
        }
    )
    document_ready = bool(core_ready and object_storage_ready and document_management_evidence["ready"])
    degraded_capabilities: list[str] = []
    if not qdrant_ready:
        degraded_capabilities.extend(QDRANT_DEGRADED_CAPABILITIES)
    if not ai_configured:
        degraded_capabilities.extend(AI_DEGRADED_CAPABILITIES)
    degraded_capabilities = list(dict.fromkeys(degraded_capabilities))
    return {
        "status": status,
        "ready": document_ready,
        "profiles": {
            "core": {"ready": core_ready, "required": ["postgresql", "alembic"], "blocking": True},
            "document_management": {
                "ready": document_ready,
                "requires_profile": "core",
                "required": ["object_storage", "postgresql_document_vertical_evidence"],
                "blocking": True,
            },
            "ai_services": {
                "ready": bool(qdrant_ready and ai_configured),
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
                "ready": bool(qdrant_ready and ai_configured),
                "degraded_capabilities": degraded_capabilities,
                "observed_configuration": ai_observed,
            },
            "database": database,
            "document_management_evidence": document_management_evidence,
            "object_storage": object_storage,
            "qdrant": {
                "ready": qdrant_ready,
                "blocking": False,
                "degraded_capabilities": list(QDRANT_DEGRADED_CAPABILITIES) if not qdrant_ready else [],
                "configuration": qdrant_configuration,
            },
        },
        "degraded_capabilities": degraded_capabilities,
    }


def enabled_feature_flags(dotenv_values: Mapping[str, str]) -> dict[str, bool]:
    return {
        "embeddings": truthy_config_value(config_value("FEATURE_EMBEDDINGS_ENABLED", dotenv_values)[0]),
        "vector_retrieval": truthy_config_value(config_value("FEATURE_VECTOR_RETRIEVAL_ENABLED", dotenv_values)[0]),
        "worker": truthy_config_value(config_value("FEATURE_WORKER_ENABLED", dotenv_values)[0]),
        "enterprise_extensions": truthy_config_value(
            config_value("FEATURE_ENTERPRISE_EXTENSIONS_ENABLED", dotenv_values)[0]
        ),
    }


def secret_store_readiness(dotenv_values: Mapping[str, str]) -> dict[str, Any]:
    provider = (config_value("SECRET_STORE_PROVIDER", dotenv_values)[0] or "memory").strip().lower()
    redis_url = config_value("SECRET_STORE_REDIS_URL", dotenv_values)[0]
    if provider == "memory":
        return {
            "ready": True,
            "status": "ready",
            "provider": provider,
            "degraded": False,
            "redis_configured": bool(redis_url),
        }
    if provider == "redis":
        ready = bool(redis_url and not contains_placeholder(redis_url))
        return {
            "ready": ready,
            "status": "ready" if ready else "not_configured",
            "provider": provider,
            "degraded": not ready,
            "redis_configured": bool(redis_url),
        }
    return {
        "ready": False,
        "status": "unsupported_provider",
        "provider": provider,
        "degraded": True,
        "redis_configured": bool(redis_url),
    }


def first_or_unknown(values: Sequence[str]) -> str:
    return values[0] if values else "unknown"


def service_status(ready: bool) -> str:
    return "ready" if ready else "unavailable"


def build_platform_diagnostics(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
) -> dict[str, Any]:
    del target_revision
    dotenv_values = load_dotenv_values(repo_root())
    config_path = resolve_alembic_config(alembic_config)
    install = build_install_profile(config_path, timeout_s, dotenv_values)
    status = install["status"]
    database = install["checks"]["database"]
    object_storage = install["checks"]["object_storage"]
    secret_store = secret_store_readiness(dotenv_values)
    critical_services = {
        "alembic": {
            "ready": install["checks"]["alembic"]["ready"],
            "status": service_status(install["checks"]["alembic"]["ready"]),
            "startup_compatible": status["startup_compatible"],
            "migration_required": status["migration_required"],
        },
        "object_storage": {
            "ready": object_storage["ready"],
            "status": service_status(object_storage["ready"]),
            "required_for": ["document_management"],
        },
        "postgresql": {
            "ready": database["ready"],
            "status": service_status(database["ready"]),
            "connectivity": database["postgresql"],
        },
        "secret_store": secret_store,
    }
    optional_services = {
        "ai_provider": {
            "ready": install["checks"]["ai_services"]["ready"],
            "status": service_status(install["checks"]["ai_services"]["ready"]),
            "blocking": False,
        },
        "vector_store": {
            "ready": install["checks"]["qdrant"]["ready"],
            "status": service_status(install["checks"]["qdrant"]["ready"]),
            "blocking": False,
        },
    }
    degraded_capabilities = list(install["degraded_capabilities"])
    if all(item["ready"] for item in critical_services.values()) and not degraded_capabilities:
        overall_status = "ready"
    elif install["profiles"]["core"]["ready"] and install["profiles"]["document_management"]["ready"]:
        overall_status = "degraded"
    else:
        overall_status = "critical"
    blocking_checks = [] if install["ready"] else ["install"]
    return {
        "plan": "platform_diagnostics",
        "platform": read_platform_metadata(),
        "migrations": {
            "current_revision": first_or_unknown(status["database_heads"]),
            "database_heads": status["database_heads"],
            "repository_head": first_or_unknown(status["repository_heads"]),
            "repository_heads": status["repository_heads"],
            "startup_compatible": status["startup_compatible"],
            "migration_required": status["migration_required"],
        },
        "critical_services": critical_services,
        "optional_services": optional_services,
        "degraded_capabilities": degraded_capabilities,
        "enabled_feature_flags": enabled_feature_flags(dotenv_values),
        "runtime_profiles": install["profiles"],
        "lifecycle_readiness": {
            "ready": install["ready"],
            "blocking_checks": blocking_checks,
            "operator_action_required": "ready" if install["ready"] else "resolve_blocking_lifecycle_checks",
        },
        "overall_status": overall_status,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_diagnostics_summary(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
) -> dict[str, Any]:
    diagnostics = build_platform_diagnostics(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
    )
    return {
        "plan": "platform_diagnostics_summary",
        "platform": diagnostics["platform"],
        "overall_status": diagnostics["overall_status"],
        "critical_services": {
            name: {
                "ready": service["ready"],
                "status": service["status"],
            }
            for name, service in diagnostics["critical_services"].items()
        },
        "optional_services": {
            name: {
                "ready": service["ready"],
                "status": service["status"],
                "blocking": service["blocking"],
            }
            for name, service in diagnostics["optional_services"].items()
        },
        "degraded_capabilities": diagnostics["degraded_capabilities"],
        "runtime_profiles": {
            name: {
                "ready": profile["ready"],
                "blocking": profile["blocking"],
            }
            for name, profile in diagnostics["runtime_profiles"].items()
        },
        "lifecycle_readiness": diagnostics["lifecycle_readiness"],
        "migrations": {
            "current_revision": diagnostics["migrations"]["current_revision"],
            "repository_head": diagnostics["migrations"]["repository_head"],
            "startup_compatible": diagnostics["migrations"]["startup_compatible"],
            "migration_required": diagnostics["migrations"]["migration_required"],
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_diagnostics_issues(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
) -> dict[str, Any]:
    diagnostics = build_platform_diagnostics(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
    )
    issues: list[dict[str, Any]] = []
    for name, service in diagnostics["critical_services"].items():
        if not service["ready"]:
            issues.append(
                {
                    "code": f"critical_service_unavailable:{name}",
                    "severity": "critical",
                    "scope": "critical_services",
                    "name": name,
                    "message": f"Critical service {name} is not ready.",
                }
            )
    for capability in diagnostics["degraded_capabilities"]:
        issues.append(
            {
                "code": f"capability_degraded:{capability}",
                "severity": "degraded",
                "scope": "degraded_capabilities",
                "name": capability,
                "message": f"Optional capability {capability} is degraded.",
            }
        )
    for name, service in diagnostics["optional_services"].items():
        if not service["ready"]:
            issues.append(
                {
                    "code": f"optional_service_unavailable:{name}",
                    "severity": "degraded",
                    "scope": "optional_services",
                    "name": name,
                    "message": f"Optional service {name} is not ready.",
                }
            )

    issues = sorted(issues, key=lambda item: (item["severity"], item["scope"], item["name"], item["code"]))
    return {
        "plan": "platform_diagnostics_issues",
        "overall_status": diagnostics["overall_status"],
        "issue_count": len(issues),
        "issues": issues,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def remediation_for_issue(issue: Mapping[str, Any]) -> dict[str, Any]:
    name = str(issue["name"])
    scope = str(issue["scope"])
    if scope == "critical_services" and name == "postgresql":
        action = "restore_postgresql_connectivity"
        command = "python scripts/platform_diagnostics.py --issues"
    elif scope == "critical_services" and name == "alembic":
        action = "restore_alembic_compatibility"
        command = "python scripts/platform_lifecycle.py status"
    elif scope == "critical_services" and name == "object_storage":
        action = "configure_object_storage"
        command = "python scripts/platform_lifecycle.py install-check"
    elif scope == "critical_services" and name == "secret_store":
        action = "configure_secret_store"
        command = "python scripts/platform_diagnostics.py --issues"
    elif scope == "optional_services" and name == "vector_store":
        action = "configure_optional_vector_store"
        command = "python scripts/platform_diagnostics.py --summary"
    elif scope == "optional_services" and name == "ai_provider":
        action = "configure_optional_ai_provider"
        command = "python scripts/platform_diagnostics.py --summary"
    elif scope == "degraded_capabilities":
        action = f"restore_optional_capability:{name}"
        command = "python scripts/platform_diagnostics.py --summary"
    else:
        action = "inspect_diagnostics"
        command = "python scripts/platform_diagnostics.py"
    return {
        "issue_code": issue["code"],
        "severity": issue["severity"],
        "action": action,
        "safe_to_automate": False,
        "destructive": False,
        "verification_command": command,
    }


def build_platform_diagnostics_remediation(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
) -> dict[str, Any]:
    issues = build_platform_diagnostics_issues(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
    )
    remediation = [remediation_for_issue(issue) for issue in issues["issues"]]
    return {
        "plan": "platform_diagnostics_remediation",
        "overall_status": issues["overall_status"],
        "remediation_count": len(remediation),
        "remediation": remediation,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_diagnostics_catalog() -> dict[str, Any]:
    return {
        "plan": "platform_diagnostics_catalog",
        "critical_services": {
            "alembic": {
                "required_for": ["core"],
                "description": "Database schema compatibility with the current platform code.",
            },
            "object_storage": {
                "required_for": ["document_management"],
                "description": "Storage for original binaries, versions and generated artifacts.",
            },
            "postgresql": {
                "required_for": ["core"],
                "description": "Primary relational persistence for platform state.",
            },
            "secret_store": {
                "required_for": ["runtime_credentials"],
                "description": "Runtime credential and protected document secret handling.",
            },
        },
        "optional_services": {
            "ai_provider": {
                "capabilities": ["llm", "ai_assistants", "rag"],
                "blocking": False,
            },
            "vector_store": {
                "capabilities": ["vector_search", "rag"],
                "blocking": False,
            },
        },
        "runtime_profiles": {
            "core": {
                "required": ["postgresql", "alembic"],
                "blocking": True,
            },
            "document_management": {
                "required": ["core", "object_storage"],
                "blocking": True,
            },
            "ai_services": {
                "required": [],
                "optional": ["qdrant", "embeddings", "llm", "rag", "ai_assistants"],
                "blocking": False,
            },
        },
        "degraded_capabilities": {
            "ai_provider_missing": list(AI_DEGRADED_CAPABILITIES),
            "vector_store_missing": list(QDRANT_DEGRADED_CAPABILITIES),
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }

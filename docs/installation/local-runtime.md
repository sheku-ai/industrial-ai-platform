# Local Runtime Operations

## Release Candidate validation

Run these commands from the repository root after the [canonical installation](installation-guide.md). Keep the same checkout and installed runtime throughout the sequence:

```text
install-platform.sh → run-quality-gate.sh → Product Acceptance
→ validate_rc_packaging.sh → git status and evidence review
```

| Script | Purpose | When to use it | Evidence/output |
|---|---|---|---|
| `scripts/install-platform.sh` | Preflight, persistent configuration, production Compose build, migrations and healthy runtime | First installation or compatible rerun | Installer status, `/health/ready`, `/setup/status` |
| `scripts/run-quality-gate.sh` | Builds production images and validates migrations, backend, security, portal and dependencies | After installation or an RC code change | `runtime/quality-reports/<commit>.json`, Markdown and stage logs |
| `apps/api/scripts/run_local_product_acceptance.py` | Validates product journeys through public APIs | After the Quality Gate on the intended runtime | Terminal gate totals and RC eligibility |
| `scripts/validate_rc_packaging.sh` | Projects the release contract, migration head, Community/Enterprise editions, blockers and optional degradations | After Product Acceptance | JSON release contract on stdout |

```bash
./scripts/install-platform.sh
bash scripts/run-quality-gate.sh
# Load ACCEPTANCE_AUTH_EMAIL and ACCEPTANCE_AUTH_PASSWORD from a protected file outside the repository.
PYTHONPATH=apps/api apps/api/.venv/bin/python \
  apps/api/scripts/run_local_product_acceptance.py --verbose
bash scripts/validate_rc_packaging.sh
git status --short
```

The installer runs host and Docker/Compose preflight, checks ports, prepares persistent paths and local secrets, combines `docker-compose.yml` with the `docker-compose.production.yml` override, builds images, starts both PostgreSQL services, applies both migration chains, then starts API, scheduler and portal. A new installation opens `/setup`; a completed installation reuses its persisted completion evidence. PostgreSQL remains authoritative for installation and runtime state. The production Compose file must not be run alone.

The Quality Gate's report distinguishes `blocking=true` and `blocking=false` stages. Its overall result depends on blocking stages; failed informational stages remain visible as evidence and debt. Never change a gate to hide a defect. Review the report and logs for the current commit in `runtime/quality-reports/`.

Product Acceptance defaults to `http://127.0.0.1:8000/api`. It requires `ACCEPTANCE_AUTH_EMAIL` and `ACCEPTANCE_AUTH_PASSWORD` in the process environment; store them outside the repository. For this RC, the expected result is `23/23 PASSED`, zero failures, blocked gates, missing capabilities and warnings, and `RC eligible: YES`.

RC packaging respects an existing `DATABASE_URL`. Otherwise it reads the installer's `INSTALL_ENV_FILE` (default: repository `.env`) and derives a host PostgreSQL connection in memory using `127.0.0.1` and the configured `POSTGRES_PORT` or default `5432`. It does not write the derived URL to `.env` or print credential-bearing DSNs. For this RC, `ready_with_optional_degradation` with zero blocking gates is valid when the listed degradations are optional under the release contract; the platform migration head is `20260930_2870`.

Keep `.env`, passwords, Product Acceptance credentials and credential-bearing DSNs out of commits and logs. `INSTALL_ENV_FILE` can point outside the repository. If packaging reports PostgreSQL or Alembic unavailable after a healthy installation, verify the selected installer env file and published PostgreSQL port without displaying credentials. Docker image/cache storage is distinct from the SHEKU persistence paths set by the installer; changing `INSTALL_DATA_ROOT` on an existing installation requires a deliberate data migration. Filesystem storage is the default; AI, embeddings, vector databases, Ollama and MinIO are optional for the core.

## Supported network contract

The supported local runtime uses fixed ports:

```text
API:    http://127.0.0.1:8000
Portal: http://127.0.0.1:3000
```

These ports are part of the local development and Compose operating contract. The supported supervisor and PowerShell wrapper do not accept alternate API or portal ports.

Historical examples using `8100`, `3100`, `--api-port` or `--portal-port` are obsolete.

## Supported entrypoints

```text
scripts/local_platform.py
scripts/platform_local.ps1
```

## Diagnostics

```powershell
python scripts/local_platform.py doctor
python scripts/local_platform.py port-check --port 8000
python scripts/local_platform.py port-check --port 3000
```

Machine-readable port output:

```powershell
python scripts/local_platform.py port-check --port 8000 --json
```

The diagnostic identifies IPv4 and IPv6 listeners, owning PID, process name and executable path when available.

## Consolidated status

```powershell
python scripts/local_platform.py status
```

Machine-readable output:

```powershell
python scripts/local_platform.py status --json
```

The command always inspects:

```text
API port: 8000
Portal port: 3000
```

It reports Compose services, health, published ports, API readiness, platform metadata and effective non-secret configuration.

## Local process runtime

```powershell
python scripts/local_platform.py serve
```

Optional development switches:

```text
--skip-install
--skip-docker
--skip-migrations
```

The supervisor starts:

- API on `127.0.0.1:8000`;
- portal on `127.0.0.1:3000`;
- scheduler as a managed local process.

It verifies API liveness, readiness, portal availability and CORS before declaring success.

## Verified Compose runtime

```powershell
python scripts/local_platform.py compose-up --build
```

The command performs:

1. API port `8000` preflight;
2. portal port `3000` preflight;
3. Compose startup;
4. API liveness and readiness verification;
5. portal verification;
6. external CORS verification.

Failed verification collects bounded diagnostics and rolls the stack back unless explicitly retained:

```powershell
python scripts/local_platform.py compose-up --build --keep-failed
```

## Complete shutdown

```powershell
python scripts/local_platform.py compose-down
```

This includes default services, optional profiles and orphan cleanup.

To remove named volumes:

```powershell
python scripts/local_platform.py compose-down --volumes
```

## PowerShell wrapper

```powershell
.\scripts\platform_local.ps1 -Command doctor
.\scripts\platform_local.ps1 -Command status
.\scripts\platform_local.ps1 -Command status -Json
.\scripts\platform_local.ps1 -Command compose-up -Build
.\scripts\platform_local.ps1 -Command compose-up -Build -KeepFailed
.\scripts\platform_local.ps1 -Command compose-down
```

`-ApiPort` and `-PortalPort` are no longer supported.

## CORS

The default local origins are fixed to:

```text
http://localhost:3000
http://127.0.0.1:3000
```

Explicit `CORS_ALLOWED_ORIGINS` remains available for non-local deployment configuration, but it does not redefine the supported local portal port.

## Port conflicts

If `8000` or `3000` is occupied, startup fails before build or recreation.

The supported response is to stop the conflicting process or existing stack. Automatic fallback to another port is not supported.

## Optional services

Object storage, inference, embeddings, vector retrieval and ingestion workers remain optional. Their absence must not prevent the core platform from operating.

## Governed identity and session deployment

Before applying Identity migration `20260811_1030`, create and validate a custom-format backup of Identity PostgreSQL. Apply the independent `identity-migrator`, then recreate API and Portal from the built images. Do not use the disposable test Compose file as a substitute for pre-production validation.

For a reverse-proxy deployment, configure the exact immediate proxy addresses or CIDRs:

```bash
export AUTH_TRUSTED_PROXY_NETWORKS='192.0.2.10/32'
export AUTH_FORWARDED_IP_HEADERS='forwarded,x-forwarded-for'
```

Never trust an entire private range merely because it is private. Container addresses may change after recreation; re-resolve the immediate proxy and recreate the API whenever the trusted peer changes. See [`session-lifecycle-runbook.md`](../operations/session-lifecycle-runbook.md).

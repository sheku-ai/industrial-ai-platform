# SHEKU Installation Guide

This is the canonical first-install procedure for SHEKU 1.6.0.

The supported installation flow is:

```text
Host prerequisites
→ git clone
→ scripts/install-platform.sh
→ preflight
→ container build
→ PostgreSQL + Identity PostgreSQL
→ migrations
→ runtime services
→ /setup
→ Organization
→ Administrator
→ Preferences
→ Installation Completion Evidence
→ Login
```

The installer is intentionally responsible for runtime preparation. A normal user does not need to install Python, Node.js, PostgreSQL, Alembic, Redis or MinIO directly on the host.

Before starting, read [System Requirements](system-requirements.md).

## 1. Prepare the host

Install the required host software:

```text
Bash
Git
curl
OpenSSL
Docker
Docker Compose v2
```

Docker must be running and accessible to the current user:

```bash
docker info
docker compose version
```

On Windows 11, use WSL2 with a supported Ubuntu or Debian distribution and enable that distribution under Docker Desktop WSL integration.

Do not run the SHEKU installer directly from PowerShell or Command Prompt.

## 2. Clone the repository

For the 1.6.0 release line:

```bash
git clone https://github.com/sheku-ai/industrial-ai-platform.git
cd industrial-ai-platform
git checkout 1.6.0
```

The repository is private unless distribution policy states otherwise, so Git authentication must already be configured.

Confirm the checkout:

```bash
git branch --show-current
git status
```

Expected branch:

```text
1.6.0
```

## 3. Run the installer

From the repository root:

```bash
./scripts/install-platform.sh
```

Do not create databases, run Alembic manually or start individual services before the installer.

The installer first performs a non-destructive preflight. A successful preflight reports the detected operating system, architecture, required commands, Docker/Compose availability, Docker daemon access, port availability and persistent-storage compatibility.

The installer combines `docker-compose.yml` with `docker-compose.production.yml` for the installed runtime. The production file is an override; do not run it alone.

Example:

```text
SHEKU installation preflight

Operating system: Ubuntu 26.04.1 LTS (WSL2)
Architecture: amd64
Bash: available
Git: available
curl: available
OpenSSL: available
Docker: available
Docker Compose: available
Docker daemon: reachable
Ports: available
Existing storage: compatible

Preflight: PASSED
```

If preflight fails, correct the reported host prerequisite and rerun the same installer command. Preflight failures are designed to occur before installation changes are made.

## 4. What the installer creates

After preflight succeeds, the installer:

1. creates or reuses its protected environment file;
2. creates the persistent data directories;
3. generates PostgreSQL, Identity PostgreSQL and setup secrets when absent;
4. configures filesystem object storage by default;
5. keeps AI, embeddings, vector retrieval and optional workers disabled by default;
6. validates the final Compose configuration;
7. builds the API, migrators, scheduler and portal images;
8. starts Platform PostgreSQL and Identity PostgreSQL;
9. executes the platform and identity migrators through Compose dependencies;
10. initializes filesystem storage;
11. starts API, scheduler and portal;
12. waits for API readiness and Portal availability;
13. reads authoritative installation state from `GET /setup/status`.

PostgreSQL remains authoritative for installation lifecycle and completion evidence.

Docker image storage holds built images and cache; SHEKU's database and file persistence use the paths configured by the installer. An existing `INSTALL_DATA_ROOT` must not be changed without a deliberate storage migration. Filesystem storage is valid by default; AI providers, embeddings, vector databases, Ollama and MinIO are not required for the core.

## 5. Complete first-run setup

For a new installation the installer finishes with:

```text
SHEKU infrastructure is ready.

Portal: http://127.0.0.1:3000/setup
API health: http://127.0.0.1:8000/health/ready
Setup access code: <secret>

Complete the first-run setup in the browser.
```

Open:

```text
http://127.0.0.1:3000/setup
```

Complete the wizard in order:

```text
Access
→ Organization
→ Administrator
→ Preferences
→ Complete
```

### Access

Enter the setup access code printed by the installer.

The code is an authorization secret only. It is not installation state and is not the completion authority.

### Organization

Create the initial organization root.

The installer does not create a hardcoded customer, plant, site or organizational hierarchy.

### Administrator

Create the initial organization administrator.

The default password policy is:

- minimum 15 characters;
- maximum 128 characters;
- passwords derived from the email, display name, organization or SHEKU are rejected;
- common passwords are rejected;
- long passphrases are supported;
- rigid uppercase/lowercase/number/symbol composition rules are not required.

The backend Identity domain is authoritative for validation and hashing.

### Preferences

Set the initial language and timezone.

### Complete

SHEKU verifies that the required persisted evidence exists and writes Installation Completion Evidence. Completion is not represented by a temporary flag.

Once completion succeeds, setup is closed and normal authentication becomes the entry path.

## 6. Verify installation

Check API readiness:

```bash
curl -fsS http://127.0.0.1:8000/health/ready
echo
```

Check installation state:

```bash
curl -fsS http://127.0.0.1:8000/setup/status
echo
```

A completed installation should report:

```json
{
  "state": "COMPLETED",
  "setup_available": false,
  "steps": {
    "organization_configured": true,
    "administrator_configured": true,
    "preferences_configured": true
  }
}
```

The response also publishes the effective non-secret password-policy contract.

## 7. Login

After completion, open:

```text
http://127.0.0.1:3000
```

The installation boundary routes a completed installation into the normal login flow.

After authentication, the Home page Getting Started state is based on persisted platform evidence rather than temporary setup flags.

## Rerunning the installer

The installer is designed to be resumable and idempotent for a compatible installation.

Run the same command again:

```bash
./scripts/install-platform.sh
```

Existing generated secrets and configured paths are preserved.

If installation is already complete, the installer does not print the setup access code and reports the normal Portal endpoint instead of reopening setup.

After installation, follow the [Release Candidate validation workflow](local-runtime.md#release-candidate-validation) for Quality Gate, Product Acceptance and RC packaging.

## Custom data location

Before the first installation:

```bash
export INSTALL_DATA_ROOT=/srv/sheku
./scripts/install-platform.sh
```

The installer persists the resulting paths in its environment file.

Do not point an existing Compose project at a different data root without a deliberate storage migration. If existing Docker volumes do not match the requested bind paths, the installer stops to protect the existing data.

## Custom environment file

To keep installer configuration outside the repository:

```bash
export INSTALL_ENV_FILE=/etc/sheku/sheku.env
./scripts/install-platform.sh
```

The selected location must be writable by the installation user.

## Optional MinIO object storage

Filesystem storage is the default.

To enable the MinIO profile during installation:

```bash
INSTALL_OBJECT_STORAGE=true ./scripts/install-platform.sh
```

This is optional. SHEKU core does not require MinIO.

## Common preflight failures

### Docker daemon permission denied

Symptom:

```text
Docker is installed, but the current user cannot access the Docker daemon.
```

Confirm:

```bash
docker info
```

On WSL2, verify Docker Desktop integration and that the Linux user has effective Docker socket access. If group membership was just changed, start a new login session or restart WSL before retrying.

### Docker daemon not reachable

Start Docker Engine or Docker Desktop and confirm:

```bash
docker info
```

### Port already in use

The core ports are `3000`, `8000`, `5432` and `5433`.

Stop the conflicting process or existing stack. The installer does not silently select a different port.

### Existing storage is incompatible

The installer may report:

```text
existing SHEKU Docker volumes use a legacy or incompatible storage configuration
```

This protection is intentional. The installer does not automatically delete, recreate or migrate existing persisted storage.

For an existing installation, inspect or migrate the data deliberately before retrying.

For a disposable test installation, remove only the confirmed SHEKU containers and volumes after verifying that their data is no longer required.

## Security notes

- Never commit the generated installer environment file.
- Keep Product Acceptance credentials outside the repository; never log passwords or credential-bearing DSNs.
- `INSTALL_ENV_FILE` can keep installer configuration outside the repository.
- Do not publish the setup access code.
- Do not log administrator passwords.
- Do not replace the normal installer with direct SQL bootstrap steps.
- Do not weaken Product Acceptance or migration gates to bypass an installation defect.
- Preserve PostgreSQL and Identity PostgreSQL data according to the backup and recovery policy.

## Related documentation

- [System Requirements](system-requirements.md)
- [Local Runtime Operations](local-runtime.md)
- [Production Readiness](../deployment/PRODUCTION_READINESS.md)
- [Documentation Index](../README.md)

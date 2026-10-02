# SHEKU System Requirements

This document defines the supported host requirements for the SHEKU 1.6.0 installation path implemented by `scripts/install-platform.sh`.

The installer validates these requirements before creating directories, secrets, volumes, images, databases or runtime services. If preflight fails, installation stops without making installation changes.

## Supported operating systems

| Host | Supported configuration |
|---|---|
| Ubuntu | 22.04 LTS, 24.04 LTS, 26.04 LTS |
| Debian | 12, 13 |
| Windows | Windows 11 with WSL2 running a supported Ubuntu or Debian release |
| macOS | Supported by the installer on Docker Desktop-compatible macOS hosts |

WSL1 is not supported. Running the installer directly from Windows Command Prompt, PowerShell, MSYS, MinGW or Cygwin is not supported. On Windows, run the installer from the Linux shell inside WSL2.

For macOS, the installer currently detects Darwin but does not enforce a specific macOS version. Docker Desktop support remains the practical platform boundary.

## Supported architectures

The installer accepts:

- `amd64` / `x86_64`
- `arm64` / `aarch64`

Other architectures fail preflight.

## Required host software

These commands must be available on `PATH`:

- Bash
- Git
- curl
- OpenSSL
- Docker CLI
- Docker Compose v2

The Docker daemon must be running and the current user must be able to access it.

SHEKU does **not** require these application runtimes to be installed directly on the host:

- Python
- pip or virtualenv
- Node.js
- npm
- PostgreSQL
- Alembic
- Redis
- MinIO
- Ollama

Those components are provided by the container runtime when required by the selected SHEKU topology.

## Docker access

The following command must succeed before installation:

```bash
docker info
```

On Windows with Docker Desktop, enable WSL integration for the selected distribution.

If Docker reports permission denied for `/var/run/docker.sock`, correct Docker permissions or Docker Desktop integration before retrying. The SHEKU installer will stop safely and will not attempt to modify host permissions.

## Required ports

The standard single-host installation requires these host ports to be available:

| Port | Service |
|---:|---|
| 3000 | SHEKU Portal |
| 8000 | SHEKU API |
| 5432 | Platform PostgreSQL |
| 5433 | Identity PostgreSQL |

If object storage is explicitly enabled, the standard MinIO profile additionally uses:

| Port | Service |
|---:|---|
| 9000 | MinIO API |
| 9001 | MinIO Console |

The installer validates the core ports before making installation changes. It does not automatically select alternate ports when a conflict exists.

## Persistent storage

By default, installer-managed persistent data is stored under:

```text
${XDG_DATA_HOME:-$HOME/.local/share}/sheku
```

The default layout is:

```text
sheku/
├── postgres/
├── identity-postgres/
├── filesystem/
├── minio/
├── runtime/
└── backups/
```

The data root can be overridden before installation:

```bash
export INSTALL_DATA_ROOT=/path/to/sheku-data
```

The generated environment file defaults to:

```text
<repository>/.env
```

and can be changed with:

```bash
export INSTALL_ENV_FILE=/path/to/sheku.env
```

The installer creates the environment file with mode `600` and the default data root with restrictive permissions.

Existing Docker volumes are inspected before startup. If their bind-backed storage configuration does not match the requested persistent paths, installation stops rather than recreating or deleting persisted data.

## Filesystem requirements

The installation user must be able to:

- read the cloned repository;
- write the installer environment file;
- create and write the selected data root;
- access the Docker daemon.

Do not place authoritative PostgreSQL data on ephemeral storage for a persistent deployment.

## Network requirements

A normal first installation requires network access sufficient to:

- clone or fetch the SHEKU repository;
- pull required Docker base images;
- resolve container build dependencies when they are not already cached.

Private repository access must be configured using an appropriate Git authentication method such as SSH, a GitHub token or an authenticated Git credential helper.

SHEKU core operation does not require an external AI provider, embeddings service or vector database.

## Resource sizing

SHEKU 1.6.0 does not currently define or enforce a certified CPU, RAM or disk minimum in the installer.

Resource requirements vary with document volume, ingestion workload, optional services and retention. Production sizing must therefore be established for the target workload rather than inferred from a development workstation.

At minimum, allocate enough resources for the enabled containers and for an image build to complete without memory or disk pressure. Persistent disk sizing must account for both PostgreSQL databases, source/derived document storage and backups.

## Default security requirements

The initial administrator password policy defaults to:

```text
minimum length: 15
maximum length: 128
context-derived passwords: blocked
common passwords: blocked
```

The canonical policy is enforced by the Identity backend. The setup UI reads the effective policy from the API and performs only preventive client-side checks.

The installer also generates a one-time setup access token and stores it in the installation environment file. Treat it as a secret. After Installation Completion Evidence exists, setup mutation endpoints are no longer available.

## Optional capabilities

The standard installer keeps these capabilities disabled unless explicitly configured:

- embeddings;
- vector retrieval;
- ingestion worker;
- Enterprise extensions;
- external AI/model providers.

Filesystem object storage is the default. MinIO is opt-in:

```bash
INSTALL_OBJECT_STORAGE=true ./scripts/install-platform.sh
```

## Production deployments

The installer provides the supported single-host Compose installation path. Production deployment still requires the controls defined in:

- [Production Readiness](../deployment/PRODUCTION_READINESS.md)
- [Local Runtime Operations](local-runtime.md)

Reverse proxies, backup strategy, TLS, external identity integrations, monitoring and production capacity planning remain deployment responsibilities outside the basic first-run installer.

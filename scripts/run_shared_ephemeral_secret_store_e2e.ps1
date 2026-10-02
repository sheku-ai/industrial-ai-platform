param(
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

try {
    if (-not $NoBuild) {
        docker compose build api
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to build API image."
        }
    }

    docker compose --profile ingestion up -d --wait postgres redis
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start PostgreSQL and Redis."
    }

    docker compose run --rm migrator
    if ($LASTEXITCODE -ne 0) {
        throw "Database migration failed."
    }

    docker compose --profile ingestion run --rm --no-deps `
        -e PYTHONPATH=/app `
        api `
        python scripts/smoke_shared_ephemeral_secret_store_e2e.py
    if ($LASTEXITCODE -ne 0) {
        throw "Shared ephemeral secret store E2E failed."
    }
}
finally {
    Pop-Location
}

param(
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

try {
    $upArgs = @(
        "compose",
        "--profile", "object-storage",
        "--profile", "ingestion",
        "up", "-d", "--wait"
    )
    if (-not $NoBuild) {
        $upArgs += "--build"
    }
    $upArgs += @("postgres", "redis", "minio", "api", "ingestion-worker")

    & docker @upArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start protected PDF retry runtime."
    }

    docker compose --profile object-storage --profile ingestion run --rm --no-deps `
        -e PYTHONPATH=/app `
        -e SMOKE_API_BASE_URL=http://api:8000/api `
        api `
        python scripts/smoke_protected_pdf_retry_e2e.py
    if ($LASTEXITCODE -ne 0) {
        throw "Protected PDF retry E2E failed."
    }
}
finally {
    Pop-Location
}

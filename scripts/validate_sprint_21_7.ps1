param(
    [switch]$IncludeS3,
    [switch]$SkipFullSuite
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "=== $Name ==="
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ApiRoot = Join-Path $RepositoryRoot "apps\api"
Set-Location $ApiRoot

if (-not $env:DATABASE_URL) {
    throw "DATABASE_URL must be configured explicitly"
}

$unitTests = @(
    "tests/test_artifact_reconciliation.py",
    "tests/test_artifact_unregistered_object.py",
    "tests/test_artifact_publication_retry.py",
    "tests/test_deterministic_chunk_identity.py",
    "tests/test_workspace_cleanup_terminal_paths.py",
    "tests/test_s3_environment.py",
    "tests/test_s3_object_store_integration_support.py"
)

$postgreSqlTests = @(
    "tests/test_postgresql_same_checksum_publication_retry.py",
    "tests/test_postgresql_artifact_publication_tenant_isolation.py",
    "tests/test_postgresql_processing_revision_chunk_identity.py"
)

$s3Tests = @(
    "tests/test_s3_compatible_integration_smoke.py"
)

$combinedTests = @(
    "tests/test_postgresql_s3_artifact_publication_integration.py",
    "tests/test_postgresql_s3_missing_object_reconciliation.py",
    "tests/test_postgresql_s3_checksum_conflict_reconciliation.py",
    "tests/test_postgresql_s3_unregistered_object_reconciliation.py"
)

Invoke-Step "21.7 unit contract tests" {
    python -m pytest @unitTests -q
}

Invoke-Step "21.7 PostgreSQL integration tests" {
    python -m pytest @postgreSqlTests -q
}

if ($IncludeS3) {
    $requiredS3Variables = @(
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "S3_BUCKET"
    )

    foreach ($name in $requiredS3Variables) {
        if (-not [Environment]::GetEnvironmentVariable($name)) {
            throw "$name must be configured when -IncludeS3 is used"
        }
    }

    Invoke-Step "21.7 S3-compatible smoke" {
        python -m pytest @s3Tests -q
    }

    Invoke-Step "21.7 PostgreSQL plus S3 integration tests" {
        python -m pytest @combinedTests -q
    }
}
else {
    Write-Host ""
    Write-Host "=== S3 scenarios skipped by script option ==="
    Write-Host "Run with -IncludeS3 after setting the explicit S3 environment variables."
}

if (-not $SkipFullSuite) {
    Invoke-Step "Full API regression suite" {
        python -m pytest -q
    }
}

Invoke-Step "Alembic current" {
    python -m alembic current
}

Invoke-Step "Alembic heads" {
    python -m alembic heads
}

Write-Host ""
Write-Host "Sprint 21.7 validation set completed successfully."

param(
    [Parameter(Mandatory = $true)]
    [string]$TestDatabaseUrl,

    [switch]$IncludeS3,
    [switch]$KeepDatabase,
    [switch]$SkipPortal,
    [switch]$SkipFullSuite
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
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
$WindowsVenvPython = Join-Path $ApiRoot ".venv\Scripts\python.exe"
$UnixVenvPython = Join-Path $ApiRoot ".venv/bin/python"

if (Test-Path $WindowsVenvPython) {
    $PythonExecutable = $WindowsVenvPython
}
elseif (Test-Path $UnixVenvPython) {
    $PythonExecutable = $UnixVenvPython
}
else {
    throw "Project virtual environment Python was not found under apps/api/.venv"
}

$env:SPRINT_23_5_TEST_DATABASE_URL = $TestDatabaseUrl

$databaseGuard = @'
import os
from sqlalchemy.engine import make_url

url = make_url(os.environ["SPRINT_23_5_TEST_DATABASE_URL"])
name = url.database or ""
if not (name.startswith("test_") or name.endswith("_test")):
    raise SystemExit(
        "Refusing destructive validation: database name must start with 'test_' or end with '_test'"
    )
print(name)
'@

$DatabaseName = ($databaseGuard | & $PythonExecutable -).Trim()
if ($LASTEXITCODE -ne 0 -or -not $DatabaseName) {
    throw "Disposable database safety validation failed"
}

Write-Host "Disposable validation database: $DatabaseName"

$databaseLifecycle = @'
import os
import psycopg
from sqlalchemy.engine import make_url

url = make_url(os.environ["SPRINT_23_5_TEST_DATABASE_URL"])
database = url.database
maintenance = url.set(drivername="postgresql", database="postgres")
conninfo = maintenance.render_as_string(hide_password=False)

with psycopg.connect(conninfo, autocommit=True) as conn:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (database,),
        )
        cursor.execute(f'DROP DATABASE IF EXISTS "{database}"')
        cursor.execute(f'CREATE DATABASE "{database}"')

print(f"Recreated disposable database: {database}")
'@

Invoke-Step "Recreate disposable PostgreSQL database" {
    $databaseLifecycle | & $PythonExecutable -
}

$previousDatabaseUrl = $env:DATABASE_URL
$previousRuntimeTestFlag = $env:RUN_POSTGRES_RUNTIME_TESTS
$previousRuntimeTestUrl = $env:RUNTIME_POSTGRES_TEST_DATABASE_URL

try {
    $env:DATABASE_URL = $TestDatabaseUrl
    $env:RUN_POSTGRES_RUNTIME_TESTS = "1"
    $env:RUNTIME_POSTGRES_TEST_DATABASE_URL = $TestDatabaseUrl

    Set-Location $ApiRoot

    Invoke-Step "Python dependency integrity" {
        & $PythonExecutable -m pip check
    }

    Invoke-Step "Clean Alembic reconstruction" {
        & $PythonExecutable -m alembic upgrade head
    }

    Invoke-Step "Alembic current" {
        & $PythonExecutable -m alembic current
    }

    Invoke-Step "Alembic heads" {
        & $PythonExecutable -m alembic heads
    }

    Invoke-Step "SQLAlchemy and Alembic parity" {
        & $PythonExecutable -m alembic check
    }

    Invoke-Step "PostgreSQL runtime concurrency validation" {
        & $PythonExecutable -m pytest tests/test_runtime_postgresql_concurrency.py -q
    }

    if ($IncludeS3) {
        Set-Location $RepositoryRoot
        Invoke-Step "Bootstrap S3-compatible integration environment" {
            & (Join-Path $RepositoryRoot "scripts\bootstrap_sprint_21_7_s3.ps1")
        }

        Set-Location $ApiRoot
        $s3Tests = @(
            "tests/test_s3_compatible_integration_smoke.py",
            "tests/test_postgresql_s3_artifact_publication_integration.py",
            "tests/test_postgresql_s3_checksum_conflict_reconciliation.py",
            "tests/test_postgresql_s3_missing_object_reconciliation.py",
            "tests/test_postgresql_s3_reconciliation_batch_integration.py",
            "tests/test_postgresql_s3_unregistered_object_reconciliation.py"
        )

        Invoke-Step "PostgreSQL and S3-compatible integration validation" {
            & $PythonExecutable -m pytest @s3Tests -q
        }
    }
    else {
        Write-Host ""
        Write-Host "=== S3-compatible scenarios skipped by script option ==="
        Write-Host "Run with -IncludeS3 to execute the explicit MinIO/S3 integration set."
    }

    if (-not $SkipFullSuite) {
        Invoke-Step "Full API regression suite" {
            & $PythonExecutable -m pytest -q
        }
    }

    if (-not $SkipPortal) {
        Set-Location $RepositoryRoot

        Invoke-Step "Admin Portal lint" {
            npm run lint:portal
        }

        Invoke-Step "Admin Portal production build" {
            npm run build:portal
        }
    }

    Write-Host ""
    Write-Host "Sprint 23.5 validation gates completed successfully."
}
finally {
    if ($null -eq $previousDatabaseUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
    else { $env:DATABASE_URL = $previousDatabaseUrl }

    if ($null -eq $previousRuntimeTestFlag) { Remove-Item Env:RUN_POSTGRES_RUNTIME_TESTS -ErrorAction SilentlyContinue }
    else { $env:RUN_POSTGRES_RUNTIME_TESTS = $previousRuntimeTestFlag }

    if ($null -eq $previousRuntimeTestUrl) { Remove-Item Env:RUNTIME_POSTGRES_TEST_DATABASE_URL -ErrorAction SilentlyContinue }
    else { $env:RUNTIME_POSTGRES_TEST_DATABASE_URL = $previousRuntimeTestUrl }

    if (-not $KeepDatabase) {
        $dropDatabase = @'
import os
import psycopg
from sqlalchemy.engine import make_url

url = make_url(os.environ["SPRINT_23_5_TEST_DATABASE_URL"])
database = url.database
maintenance = url.set(drivername="postgresql", database="postgres")
conninfo = maintenance.render_as_string(hide_password=False)

with psycopg.connect(conninfo, autocommit=True) as conn:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (database,),
        )
        cursor.execute(f'DROP DATABASE IF EXISTS "{database}"')

print(f"Dropped disposable database: {database}")
'@
        $dropDatabase | & $PythonExecutable -
    }

    Remove-Item Env:SPRINT_23_5_TEST_DATABASE_URL -ErrorAction SilentlyContinue
    Set-Location $RepositoryRoot
}

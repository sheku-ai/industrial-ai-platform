param(
    [string]$ApiUrl = "http://127.0.0.1:8000",
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$EvidenceDir = "runtime/evidence/ingestion-smoke",
    [string]$Stages = "infrastructure,migrations,composition,database_integrity",
    [string]$ExecutionId = "",
    [string]$ExpectedStatus = "succeeded",
    [int]$TimeoutSeconds = 180,
    [switch]$StartContainers,
    [switch]$Build,
    [switch]$GenerateFixtures,
    [string]$SourcePdf = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $DatabaseUrl) {
    throw "DatabaseUrl is required. Set DATABASE_URL or pass -DatabaseUrl."
}

$PsycopgDatabaseUrl = $DatabaseUrl
if ($PsycopgDatabaseUrl.StartsWith("postgresql+psycopg://")) {
    $PsycopgDatabaseUrl = $PsycopgDatabaseUrl.Replace("postgresql+psycopg://", "postgresql://")
}
elseif ($PsycopgDatabaseUrl.StartsWith("postgres+psycopg://")) {
    $PsycopgDatabaseUrl = $PsycopgDatabaseUrl.Replace("postgres+psycopg://", "postgresql://")
}

if ($GenerateFixtures) {
    $fixtureArgs = @(
        "scripts/generate_ingestion_smoke_fixtures.py",
        "--output-dir", "tests/fixtures/ingestion"
    )
    if ($SourcePdf) {
        $fixtureArgs += @("--source-pdf", $SourcePdf)
    }
    python @fixtureArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Fixture generation failed."
    }
}

if ($StartContainers) {
    $composeArgs = @("compose", "--profile", "object-storage", "--profile", "ingestion", "up", "-d")
    if ($Build) {
        $composeArgs += "--build"
    }
    docker @composeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose startup failed."
    }
}

$arguments = @(
    "scripts/smoke_ingestion_platform.py",
    "--api-url", $ApiUrl,
    "--database-url", $PsycopgDatabaseUrl,
    "--evidence-dir", $EvidenceDir,
    "--stages", $Stages,
    "--expected-status", $ExpectedStatus,
    "--timeout-seconds", $TimeoutSeconds
)

if ($ExecutionId) {
    $arguments += @("--execution-id", $ExecutionId)
}

python @arguments
if ($LASTEXITCODE -ne 0) {
    Write-Host "Ingestion smoke failed. Review $EvidenceDir" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Ingestion smoke passed. Evidence: $EvidenceDir" -ForegroundColor Green

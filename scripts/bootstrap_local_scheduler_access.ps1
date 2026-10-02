param(
    [string]$ActorReference = "admin-portal"
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ApiRoot = Join-Path $RepositoryRoot "apps\api"
$PythonExecutable = Join-Path $ApiRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExecutable)) {
    throw "Project virtual environment Python was not found at $PythonExecutable"
}

$previousDatabaseUrl = $env:DATABASE_URL
$previousActorReference = $env:NEXT_PUBLIC_ACTOR_REFERENCE

try {
    $env:DATABASE_URL = "postgresql+psycopg://industrial_ai:industrial_ai@localhost:5432/industrial_ai"
    $env:NEXT_PUBLIC_ACTOR_REFERENCE = $ActorReference
    Push-Location $ApiRoot
    & $PythonExecutable bootstrap_local_scheduler_access.py
    if ($LASTEXITCODE -ne 0) {
        throw "Local scheduler access bootstrap failed"
    }
}
finally {
    Pop-Location
    if ($null -eq $previousDatabaseUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
    else { $env:DATABASE_URL = $previousDatabaseUrl }
    if ($null -eq $previousActorReference) { Remove-Item Env:NEXT_PUBLIC_ACTOR_REFERENCE -ErrorAction SilentlyContinue }
    else { $env:NEXT_PUBLIC_ACTOR_REFERENCE = $previousActorReference }
}

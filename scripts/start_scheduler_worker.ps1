param(
    [double]$PollIntervalSeconds = 5,
    [int]$BatchLimit = 100,
    [string]$OwnerId = "scheduler-local"
)

$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ApiRoot = Join-Path $RepositoryRoot "apps\api"
$PythonExecutable = Join-Path $ApiRoot ".venv\Scripts\python.exe"
$DatabaseUrl = "postgresql+psycopg://industrial_ai:industrial_ai@localhost:5432/industrial_ai"

if (-not (Test-Path $PythonExecutable)) {
    throw "Project virtual environment Python was not found at $PythonExecutable"
}

Set-Location $ApiRoot
$env:DATABASE_URL = $DatabaseUrl
$env:SCHEDULER_POLL_INTERVAL_SECONDS = [string]$PollIntervalSeconds
$env:SCHEDULER_BATCH_LIMIT = [string]$BatchLimit
$env:SCHEDULER_OWNER_ID = $OwnerId

& $PythonExecutable scheduler_worker.py

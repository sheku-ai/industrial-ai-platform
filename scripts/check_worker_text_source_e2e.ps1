$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
docker compose --profile object-storage --profile ingestion up -d --build minio postgres api ingestion-worker
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$resultText = docker compose --profile object-storage --profile ingestion exec -T -e PYTHONPATH=/app api python /app/scripts/check_worker_text_source_e2e.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$result = $resultText | ConvertFrom-Json
$result | ConvertTo-Json -Depth 8
if (-not $result.passed) { exit 1 }

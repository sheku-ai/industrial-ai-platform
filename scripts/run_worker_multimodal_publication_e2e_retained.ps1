$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
docker compose --profile object-storage --profile ingestion up -d --build minio postgres api ingestion-worker
$output = docker compose --profile object-storage --profile ingestion exec -T -e PYTHONPATH=/app api python /app/scripts/check_worker_multimodal_publication_e2e.py
$result = $output | ConvertFrom-Json
$result | ConvertTo-Json -Depth 8
if (-not $result.passed) { exit 1 }
exit 0

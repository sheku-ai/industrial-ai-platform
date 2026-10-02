$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
docker compose --profile object-storage --profile ingestion up -d minio postgres api
$resultText = docker compose --profile object-storage --profile ingestion exec -T -e PYTHONPATH=/app api python /app/scripts/check_runtime_multimodal_publication_e2e.py
$ErrorActionPreference = "Stop"
docker compose --profile object-storage --profile ingestion exec -T -e PYTHONPATH=/app api python /app/scripts/cleanup_runtime_multimodal_e2e.py
$result = $resultText | Where-Object { $_ -notmatch '^Traceback' } | Out-String | ConvertFrom-Json
$result | ConvertTo-Json -Depth 8
if (-not $result.passed) { exit 1 }

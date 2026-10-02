$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

docker compose --profile object-storage --profile ingestion up -d minio api
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$output = docker compose --profile object-storage --profile ingestion exec -T -e PYTHONPATH=/app api python /app/scripts/check_multimodal_knowledge_artifact_e2e.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$result = $output | ConvertFrom-Json
$result | ConvertTo-Json -Depth 8
if (-not $result.passed) { exit 1 }

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$output = docker compose --profile ingestion exec -T -e PYTHONPATH=/app api python /app/scripts/check_knowledge_artifact_publisher.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$result = $output | ConvertFrom-Json
$result | ConvertTo-Json -Depth 8
if (-not $result.passed) { exit 1 }

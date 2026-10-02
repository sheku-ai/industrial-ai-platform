$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$output = docker compose --profile ingestion exec -T -e PYTHONPATH=/app api python /app/scripts/check_multiformat_embedded_images.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$result = $output | ConvertFrom-Json
$result | ConvertTo-Json -Depth 6
if (-not $result.passed) { exit 1 }

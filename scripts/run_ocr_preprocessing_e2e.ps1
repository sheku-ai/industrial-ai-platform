$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$output = docker compose --profile ingestion exec -T -e PYTHONPATH=/app api python /app/scripts/check_ocr_preprocessing.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$result = $output | ConvertFrom-Json
$result | ConvertTo-Json -Depth 5
if (-not $result.passed) { exit 1 }

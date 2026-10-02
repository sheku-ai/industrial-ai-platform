$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$resultText = docker compose --profile ingestion exec -T -e PYTHONPATH=/app api python /app/scripts/check_s3_visual_record_source.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$result = $resultText | ConvertFrom-Json
$result | ConvertTo-Json -Depth 8
if (-not $result.passed) { exit 1 }

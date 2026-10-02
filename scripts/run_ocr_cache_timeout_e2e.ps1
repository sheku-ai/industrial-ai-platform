$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$output = & docker compose --profile ingestion exec -T -e PYTHONPATH=/app api python /app/scripts/check_ocr_cache_timeout.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$result = $output | ConvertFrom-Json
$result | ConvertTo-Json -Depth 5
if ($result.passed -ne $true) { exit 1 }

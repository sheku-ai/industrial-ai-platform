param([int]$TimeoutSeconds = 180, [string]$EvidenceDir = "runtime/evidence/ingestion-smoke")
$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$evidenceFile = Join-Path $EvidenceDir "07-protected-pdf-detection.json"
$output = & docker compose --profile ingestion --profile object-storage exec -T -e PYTHONPATH=/app -e SMOKE_TIMEOUT_SECONDS=$TimeoutSeconds api python /app/scripts/smoke_protected_pdf_detection_e2e.py 2>&1
$exitCode = $LASTEXITCODE
$outputText = ($output | Out-String).TrimEnd()
$outputText | Set-Content -Path $evidenceFile -Encoding utf8
Write-Host $outputText
if ($exitCode -ne 0) {
    Write-Host "Protected PDF detection E2E failed. Evidence: $evidenceFile" -ForegroundColor Red
    & docker compose --profile ingestion logs ingestion-worker --no-color --tail 200
    exit $exitCode
}
Write-Host "Protected PDF detection E2E passed. Evidence: $evidenceFile" -ForegroundColor Green

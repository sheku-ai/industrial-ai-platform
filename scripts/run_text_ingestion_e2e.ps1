param(
    [int]$TimeoutSeconds = 180,
    [string]$EvidenceDir = "runtime/evidence/ingestion-smoke"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$evidenceFile = Join-Path $EvidenceDir "05-text-e2e.json"

$previousNativePreference = $null
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $previousNativePreference = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
}

$previousErrorPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $output = & docker compose --profile ingestion --profile object-storage exec -T `
        -e PYTHONPATH=/app `
        -e SMOKE_TIMEOUT_SECONDS=$TimeoutSeconds `
        api `
        python /app/scripts/smoke_text_ingestion_e2e.py 2>&1
    $exitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorPreference
    if ($null -ne $previousNativePreference) {
        $PSNativeCommandUseErrorActionPreference = $previousNativePreference
    }
}

$outputText = ($output | Out-String).TrimEnd()
$outputText | Set-Content -Path $evidenceFile -Encoding utf8
Write-Host $outputText

if ($exitCode -ne 0) {
    Write-Host "Text ingestion E2E failed. Evidence: $evidenceFile" -ForegroundColor Red
    & docker compose --profile ingestion logs ingestion-worker --no-color --tail 200
    exit $exitCode
}

Write-Host "Text ingestion E2E passed. Evidence: $evidenceFile" -ForegroundColor Green

param(
    [int]$TimeoutSeconds = 180,
    [string]$EvidenceDir = "runtime/evidence/ingestion-smoke"
)

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$evidenceFile = Join-Path $EvidenceDir "07-pdf-multisegment-resume-e2e.json"

$output = & docker compose --profile ingestion --profile object-storage exec -T `
    -e PYTHONPATH=/app `
    -e SMOKE_TIMEOUT_SECONDS=$TimeoutSeconds `
    api python /app/scripts/smoke_pdf_multisegment_resume.py 2>&1
$exitCode = $LASTEXITCODE
$outputText = ($output | Out-String).TrimEnd()
$jsonStart = $outputText.IndexOf("{")

if ($jsonStart -ge 0) {
    try {
        $result = $outputText.Substring($jsonStart) | ConvertFrom-Json
        $functionalPass = (
            $result.passed -eq $true -and
            $result.execution_status -eq "succeeded" -and
            $result.document_version_status -eq "indexed" -and
            $result.runtime_attempt_count -eq 2 -and
            @($result.segment_attempt_counts).Count -eq 2 -and
            $result.segment_attempt_counts[0] -eq 1 -and
            $result.segment_attempt_counts[1] -eq 1 -and
            @($result.chunk_indexes).Count -eq 2 -and
            $result.chunk_indexes[0] -eq 0 -and
            $result.chunk_indexes[1] -eq 1 -and
            $result.fts_ready -eq $true
        )
        if (-not $functionalPass) { $exitCode = 1 }
        $outputText = $result | ConvertTo-Json -Depth 10
    }
    catch { $exitCode = 1 }
}

$outputText | Set-Content -Path $evidenceFile -Encoding utf8
Write-Host $outputText

if ($exitCode -ne 0) {
    Write-Host "PDF multisegment resume E2E failed. Evidence: $evidenceFile" -ForegroundColor Red
    & docker compose --profile ingestion logs ingestion-worker --no-color --tail 250
    exit $exitCode
}

Write-Host "PDF multisegment resume E2E passed. Evidence: $evidenceFile" -ForegroundColor Green

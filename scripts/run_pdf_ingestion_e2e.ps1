param([int]$TimeoutSeconds = 180, [string]$EvidenceDir = "runtime/evidence/ingestion-smoke")
$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$evidenceFile = Join-Path $EvidenceDir "06-pdf-e2e.json"
$output = & docker compose --profile ingestion --profile object-storage exec -T -e PYTHONPATH=/app -e SMOKE_TIMEOUT_SECONDS=$TimeoutSeconds api python /app/scripts/smoke_pdf_ingestion_e2e.py 2>&1
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
            $result.chunk_count -eq 2 -and
            $result.fts_ready -eq $true -and
            $result.page_1_sentinel_found -eq $true -and
            $result.page_2_sentinel_found -eq $true -and
            @($result.page_numbers).Count -eq 2 -and
            $result.page_numbers[0] -eq 1 -and
            $result.page_numbers[1] -eq 2 -and
            $result.metrics.adapter_key -eq "platform.pdf.text_layer" -and
            $result.adapter_metrics_propagated -eq $true -and
            $result.page_count -eq 2 -and
            $result.encrypted -eq $false -and
            $result.ocr_used -eq $false -and
            $result.metrics.semantic_publication_connected -eq $true -and
            $result.metrics.semantic_publication_enabled -eq $false -and
            $result.metrics.semantic_documents_published -eq 0 -and
            $result.metrics.semantic_publication_provider -eq "disabled" -and
            $result.metrics.partial_availability_connected -eq $true -and
            $result.metrics.document_availability -eq "complete"
        )
        if (-not $functionalPass) { $exitCode = 1 }
        $outputText = $result | ConvertTo-Json -Depth 10
    }
    catch { $exitCode = 1 }
}
$outputText | Set-Content -Path $evidenceFile -Encoding utf8
Write-Host $outputText
if ($exitCode -ne 0) {
    Write-Host "PDF ingestion E2E failed. Evidence: $evidenceFile" -ForegroundColor Red
    & docker compose --profile ingestion logs ingestion-worker --no-color --tail 200
    exit $exitCode
}
Write-Host "PDF ingestion E2E passed. Evidence: $evidenceFile" -ForegroundColor Green

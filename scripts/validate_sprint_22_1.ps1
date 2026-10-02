param(
    [switch]$FullRegression
)

$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ApiRoot = Join-Path $RepositoryRoot "apps\api"
$WindowsPython = Join-Path $ApiRoot ".venv\Scripts\python.exe"
$UnixPython = Join-Path $ApiRoot ".venv/bin/python"

if (Test-Path $WindowsPython) {
    $Python = $WindowsPython
}
elseif (Test-Path $UnixPython) {
    $Python = $UnixPython
}
else {
    throw "Project virtual environment Python was not found under apps/api/.venv"
}

function Invoke-TestSet {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    Write-Host ""
    Write-Host "=== $Name ==="
    Push-Location $ApiRoot
    try {
        & $Python -m pytest @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

Invoke-TestSet "22.1 deterministic chunk identity" @(
    "tests/test_deterministic_chunk_identity.py",
    "-q"
)

Invoke-TestSet "22.1 cancellation and lease publication boundaries" @(
    "tests/test_document_ingestion_fault_boundaries.py",
    "-q"
)

if ($FullRegression) {
    Invoke-TestSet "Full API regression suite" @(
        "tests",
        "-q"
    )
}

Write-Host ""
Write-Host "Sprint 22.1 validation set completed successfully."

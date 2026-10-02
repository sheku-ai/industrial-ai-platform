param(
    [switch]$SkipBuild,
    [switch]$SkipPortalBuild,
    [int]$HealthTimeoutSeconds = 120
)

Write-Warning "run_sprint_26_2_gate.ps1 is deprecated. Use run_sprint_26_3_gate.ps1."

& "$PSScriptRoot\run_sprint_26_3_gate.ps1" `
    -SkipBuild:$SkipBuild `
    -SkipPortalBuild:$SkipPortalBuild `
    -HealthTimeoutSeconds $HealthTimeoutSeconds

exit $LASTEXITCODE

param([switch]$SkipBuild, [switch]$SkipPortalBuild, [int]$HealthTimeoutSeconds = 120, [int]$TimeoutSeconds = 1200)
$ErrorActionPreference = "Stop"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3 was not found in PATH." }
$forward = @("$PSScriptRoot/run_sprint_26_3_gate.py", "--health-timeout-seconds", "$HealthTimeoutSeconds", "--timeout-seconds", "$TimeoutSeconds")
if ($SkipBuild) { $forward += "--skip-build" }
if ($SkipPortalBuild) { $forward += "--skip-portal-build" }
& $python.Source @forward
exit $LASTEXITCODE

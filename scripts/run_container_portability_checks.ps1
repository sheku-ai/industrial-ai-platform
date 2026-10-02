param([switch]$SkipBuild, [switch]$SkipPortal, [int]$TimeoutSeconds = 1800)
$ErrorActionPreference = "Stop"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3 was not found in PATH." }
$forward = @("$PSScriptRoot/run_container_portability_checks.py", "--timeout-seconds", "$TimeoutSeconds")
if ($SkipBuild) { $forward += "--skip-build" }
if ($SkipPortal) { $forward += "--skip-portal" }
& $python.Source @forward
exit $LASTEXITCODE

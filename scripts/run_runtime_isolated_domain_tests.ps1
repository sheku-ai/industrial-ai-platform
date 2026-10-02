param([switch]$SkipBuild, [switch]$SkipPortalBuild, [int]$TimeoutSeconds = 900)
$ErrorActionPreference = "Stop"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3 was not found in PATH." }
$forward = @("$PSScriptRoot/run_runtime_isolated_domain_tests.py", "--timeout-seconds", "$TimeoutSeconds")
if ($SkipBuild) { $forward += "--skip-build" }
if ($SkipPortalBuild) { $forward += "--skip-portal-build" }
& $python.Source @forward
exit $LASTEXITCODE

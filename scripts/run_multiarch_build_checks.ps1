param([string]$Platforms = "linux/amd64,linux/arm64", [switch]$SkipApi, [switch]$SkipPortal, [int]$TimeoutSeconds = 3600)
$ErrorActionPreference = "Stop"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3 was not found in PATH." }
$forward = @("$PSScriptRoot/run_multiarch_build_checks.py", "--platforms", $Platforms, "--timeout-seconds", "$TimeoutSeconds")
if ($SkipApi) { $forward += "--skip-api" }
if ($SkipPortal) { $forward += "--skip-portal" }
& $python.Source @forward
exit $LASTEXITCODE

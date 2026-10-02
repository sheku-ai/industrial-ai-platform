param([string]$Version = "1.3.1", [string]$Revision = "local", [string]$OutputDir = "runtime/release-artifacts", [switch]$SkipApi, [switch]$SkipPortal, [int]$TimeoutSeconds = 7200)
$ErrorActionPreference = "Stop"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3 was not found in PATH." }
$forward = @("$PSScriptRoot/run_local_oci_artifact_build.py", "--version", $Version, "--revision", $Revision, "--output-dir", $OutputDir, "--timeout-seconds", "$TimeoutSeconds")
if ($SkipApi) { $forward += "--skip-api" }
if ($SkipPortal) { $forward += "--skip-portal" }
& $python.Source @forward
exit $LASTEXITCODE

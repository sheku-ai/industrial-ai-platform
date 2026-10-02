param([switch]$SkipBuild, [int]$StartupDelaySeconds = 8, [int]$TimeoutSeconds = 1200)
$ErrorActionPreference = "Stop"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3 was not found in PATH." }
$forward = @("$PSScriptRoot/run_ingestion_multimodal_isolated_tests.py", "--startup-delay-seconds", "$StartupDelaySeconds", "--timeout-seconds", "$TimeoutSeconds")
if ($SkipBuild) { $forward += "--skip-build" }
& $python.Source @forward
exit $LASTEXITCODE

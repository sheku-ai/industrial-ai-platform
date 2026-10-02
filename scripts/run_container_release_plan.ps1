param([string]$Registry = "ghcr.io", [string]$Namespace = "industrial-ai-platform", [string]$Version = "1.6.0", [string]$Revision = "local", [int]$TimeoutSeconds = 300)
$ErrorActionPreference = "Stop"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3 was not found in PATH." }
$forward = @("$PSScriptRoot/run_container_release_plan.py", "--registry", $Registry, "--namespace", $Namespace, "--version", $Version, "--revision", $Revision, "--timeout-seconds", "$TimeoutSeconds")
& $python.Source @forward
exit $LASTEXITCODE

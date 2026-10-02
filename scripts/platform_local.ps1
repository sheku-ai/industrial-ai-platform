param(
    [ValidateSet("doctor", "port-check", "status", "serve", "compose-up", "compose-down")]
    [string]$Command = "serve",
    [switch]$SkipInstall,
    [switch]$SkipDocker,
    [switch]$SkipMigrations,
    [switch]$Build,
    [switch]$KeepFailed,
    [switch]$Volumes,
    [switch]$Json,
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$Python = @(
    (Join-Path $RepositoryRoot "apps\api\.venv\Scripts\python.exe"),
    (Join-Path $RepositoryRoot "apps\api\.venv\bin\python")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Python) { throw "API virtual environment was not found under apps/api/.venv" }

$arguments = @((Join-Path $PSScriptRoot "local_platform.py"), $Command)
if ($Command -eq "port-check") {
    if ($Port -le 0) { throw "-Port is required for port-check" }
    $arguments += @("--port", $Port)
    if ($Json) { $arguments += "--json" }
}
elseif ($Command -eq "status") {
    if ($Json) { $arguments += "--json" }
}
elseif ($Command -eq "serve") {
    if ($SkipInstall) { $arguments += "--skip-install" }
    if ($SkipDocker) { $arguments += "--skip-docker" }
    if ($SkipMigrations) { $arguments += "--skip-migrations" }
}
elseif ($Command -eq "compose-up") {
    if ($Build) { $arguments += "--build" }
    if ($KeepFailed) { $arguments += "--keep-failed" }
}
elseif ($Command -eq "compose-down" -and $Volumes) {
    $arguments += "--volumes"
}

& $Python @arguments
exit $LASTEXITCODE

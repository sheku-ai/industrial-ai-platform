param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status", "logs")]
    [string]$Command = "status",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArguments
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepositoryRoot "apps\api\.venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "API virtual environment Python was not found: $Python"
}

$Arguments = @((Join-Path $PSScriptRoot "local_services.py"), $Command) + $RemainingArguments
& $Python @Arguments
exit $LASTEXITCODE

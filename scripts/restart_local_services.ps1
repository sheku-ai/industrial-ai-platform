param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArguments
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "local_services.ps1") restart @RemainingArguments
exit $LASTEXITCODE

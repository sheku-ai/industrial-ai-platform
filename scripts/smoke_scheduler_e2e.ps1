param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$ActorReference = "admin-portal",
    [string]$OrganizationId = "",
    [int]$TimeoutSeconds = 30,
    [switch]$KeepData
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ApiRoot = Join-Path $RepositoryRoot "apps\api"
$PythonExecutable = Join-Path $ApiRoot ".venv\Scripts\python.exe"
$DatabaseUrl = "postgresql+psycopg://industrial_ai:industrial_ai@localhost:5432/industrial_ai"

function Invoke-Api($Method, $Path, $Headers = @{}, $Body = $null) {
    $args = @{ Method = $Method; Uri = "$ApiBaseUrl$Path"; Headers = $Headers; TimeoutSec = 15 }
    if ($null -ne $Body) {
        $args.ContentType = "application/json"
        $args.Body = $Body | ConvertTo-Json -Depth 10
    }
    Invoke-RestMethod @args
}

Write-Host "=== Scheduler E2E smoke ==="
$status = Invoke-Api GET "/platform/status"
if (-not $status.no_ai_ready) { throw "Platform status is not no-AI ready" }

$organizationResponse = Invoke-Api GET "/api/core/organizations"
$organizations = @($organizationResponse | ForEach-Object { $_ })
if ($organizations.Count -eq 0) { throw "No organization is available" }

if ($OrganizationId) {
    $organization = $organizations | Where-Object { [string]$_.id -eq $OrganizationId } | Select-Object -First 1
    if (-not $organization) { throw "OrganizationId was not found: $OrganizationId" }
}
else {
    $organization = $organizations | Select-Object -First 1
}

$resolvedOrganizationId = [string]$organization.id
$parsed = [guid]::Empty
if (-not [guid]::TryParse($resolvedOrganizationId, [ref]$parsed)) {
    throw "Resolved organization id is not a UUID: $resolvedOrganizationId"
}

$headers = @{
    "X-Organization-ID" = $resolvedOrganizationId
    "X-Actor-Reference" = $ActorReference
}
$stamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$job = $null

try {
    Write-Host "Organization: $($organization.name) [$resolvedOrganizationId]"
    $job = Invoke-Api POST "/api/control-plane/scheduler/jobs" $headers @{
        code = "scheduler-smoke-$stamp"
        name = "Scheduler Smoke $stamp"
        description = "Automated scheduler end-to-end validation"
        operation_type = "platform.smoke"
        parameters = @{ smoke_id = $stamp }
        enabled = $false
        concurrency_policy = "forbid_overlap"
        misfire_policy = "run_once"
        max_concurrent_runs = 1
        max_runtime_seconds = 60
    }
    if ($job.enabled) { throw "New job must be disabled" }

    $job = Invoke-Api PATCH "/api/control-plane/scheduler/jobs/$($job.id)" $headers @{ enabled = $true }
    if (-not $job.enabled) { throw "Job was not enabled" }

    $schedule = Invoke-Api POST "/api/control-plane/scheduler/schedules" $headers @{
        operational_job_id = $job.id
        schedule_expression = "0 0 1 1 *"
        timezone = "UTC"
        enabled = $false
        start_at = $null
        end_at = $null
    }
    if ($schedule.enabled) { throw "New schedule must be disabled" }

    $schedule = Invoke-Api PATCH "/api/control-plane/scheduler/schedules/$($schedule.id)" $headers @{ enabled = $true }
    if (-not $schedule.enabled -or -not $schedule.next_run_at) { throw "Schedule activation failed" }

    $idempotencyKey = "smoke-$stamp"
    $payload = @{
        idempotency_key = $idempotencyKey
        correlation_id = "scheduler-smoke-$stamp"
        parameters_override = @{ source = "smoke_scheduler_e2e" }
    }
    $run = Invoke-Api POST "/api/control-plane/scheduler/jobs/$($job.id)/runs" $headers $payload
    $duplicate = Invoke-Api POST "/api/control-plane/scheduler/jobs/$($job.id)/runs" $headers $payload
    if ($duplicate.id -ne $run.id) { throw "Manual trigger idempotency failed" }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $resolved = $null
    while ((Get-Date) -lt $deadline) {
        $runResponse = Invoke-Api GET "/api/control-plane/scheduler/runs?limit=500" $headers
        $runItems = @($runResponse | ForEach-Object { $_ })
        $resolved = $runItems | Where-Object { [string]$_.id -eq [string]$run.id } | Select-Object -First 1
        if ($resolved -and $resolved.runtime_execution_id) { break }
        Start-Sleep -Milliseconds 500
    }

    if (-not $resolved) { throw "Scheduler run was not returned" }
    if (-not $resolved.runtime_execution_id) { throw "Scheduler run was not dispatched in time" }
    if ($resolved.status -ne "dispatched") { throw "Unexpected scheduler run status: $($resolved.status)" }

    Write-Host "Scheduler E2E smoke passed."
    Write-Host "Job ID: $($job.id)"
    Write-Host "Schedule ID: $($schedule.id)"
    Write-Host "Scheduler run ID: $($resolved.id)"
    Write-Host "Runtime execution ID: $($resolved.runtime_execution_id)"
    Write-Host "Provider execution enabled: $($status.provider_execution_enabled)"
}
finally {
    if ($job -and -not $KeepData) {
        Write-Host "Cleanup scheduler smoke fixtures"
        $previousDatabaseUrl = $env:DATABASE_URL
        try {
            $env:DATABASE_URL = $DatabaseUrl
            Push-Location $ApiRoot
            & $PythonExecutable detach_scheduler_smoke.py $job.id
            if ($LASTEXITCODE -ne 0) { Write-Warning "Scheduler smoke detach failed" }
            & $PythonExecutable cleanup_scheduler_smoke.py $job.id
            if ($LASTEXITCODE -ne 0) { Write-Warning "Scheduler smoke cleanup failed" }
        }
        finally {
            Pop-Location
            if ($null -eq $previousDatabaseUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
            else { $env:DATABASE_URL = $previousDatabaseUrl }
        }
    }
}

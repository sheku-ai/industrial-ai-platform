param(
    [switch]$SkipPull,
    [switch]$SkipInstall,
    [switch]$SkipDocker,
    [switch]$SkipMigrations,
    [switch]$NoBrowser,
    [switch]$VisibleServices,
    [int]$ApiPort = 8000,
    [int]$PortalPort = 3000,
    [double]$SchedulerPollIntervalSeconds = 5,
    [int]$SchedulerBatchLimit = 100
)

$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ApiRoot = Join-Path $RepositoryRoot "apps\api"
$PythonExecutable = Join-Path $ApiRoot ".venv\Scripts\python.exe"
$DatabaseUrl = "postgresql+psycopg://industrial_ai:industrial_ai@localhost:5432/industrial_ai"
$RuntimeRoot = Join-Path $RepositoryRoot "runtime"
$LogRoot = Join-Path $RuntimeRoot "logs"
$RepositoryPattern = [regex]::Escape($RepositoryRoot)
$ProtectedProcessNames = @(
    "csrss", "smss", "wininit", "winlogon", "services", "lsass",
    "system", "registry", "memory compression", "secure system"
)

if (-not (Test-Path $PythonExecutable)) {
    throw "Project virtual environment Python was not found at $PythonExecutable"
}

New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

function Get-ProcessInfo {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    return Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
}

function Test-ProtectedProcess {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $native = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $native) { return $false }
    return $native.ProcessName.ToLowerInvariant() -in $ProtectedProcessNames
}

function Test-ManagedProcess {
    param(
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)][ValidateSet("api", "portal", "scheduler")][string]$Service
    )

    if (-not $Process) { return $false }
    if (Test-ProtectedProcess -ProcessId ([int]$Process.ProcessId)) { return $false }

    $command = [string]$Process.CommandLine
    $executable = [string]$Process.ExecutablePath
    $name = [string]$Process.Name

    if ($Service -eq "api") {
        return [bool](
            $command -and
            $command -match "uvicorn" -and
            $command -match "main:app" -and
            ($command -match $RepositoryPattern -or $executable -eq $PythonExecutable)
        )
    }

    if ($Service -eq "scheduler") {
        return [bool](
            $command -and
            $command -match "scheduler_worker\.py" -and
            ($command -match $RepositoryPattern -or $executable -eq $PythonExecutable)
        )
    }

    return [bool](
        $name -match "^(node|node\.exe|npm|npm\.cmd|cmd|cmd\.exe|powershell|powershell\.exe)$" -and
        $command -and
        $command -match $RepositoryPattern -and
        ($command -match "next" -or $command -match "dev:portal")
    )
}

function Stop-ManagedProcess {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][ValidateSet("api", "portal", "scheduler")][string]$Service
    )

    $process = Get-ProcessInfo -ProcessId $ProcessId
    if (-not $process) { return }

    if (-not (Test-ManagedProcess -Process $process -Service $Service)) {
        throw "Refusing to terminate unrecognized or protected process PID $ProcessId ($($process.Name))."
    }

    Write-Host "Stopping managed $Service process PID $ProcessId"
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
}

function Stop-AllManagedServiceProcesses {
    param([Parameter(Mandatory = $true)][ValidateSet("api", "portal", "scheduler")][string]$Service)

    $managed = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        Test-ManagedProcess -Process $_ -Service $Service
    })

    foreach ($process in $managed) {
        Stop-ManagedProcess -ProcessId ([int]$process.ProcessId) -Service $Service
    }

    if ($managed.Count -gt 0) { Start-Sleep -Milliseconds 750 }
}

function Test-PlatformApiEndpoint {
    param([Parameter(Mandatory = $true)][int]$Port)
    try {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/platform/status" -TimeoutSec 2
        return [bool](
            $status -and
            $status.current_work_package -and
            $status.current_objective -and
            $null -ne $status.provider_execution_enabled
        )
    }
    catch { return $false }
}

function Get-FreeTcpPort {
    param([Parameter(Mandatory = $true)][int]$StartPort)
    for ($candidate = $StartPort; $candidate -le 65535; $candidate++) {
        if (-not (Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue)) {
            return $candidate
        }
    }
    throw "No free TCP port was found from $StartPort to 65535"
}

function Stop-ManagedListener {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("api", "portal")][string]$Service,
        [Parameter(Mandatory = $true)][int]$Port
    )

    for ($attempt = 1; $attempt -le 20; $attempt++) {
        $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        if ($listeners.Count -eq 0) {
            Write-Host "$Service port $Port released"
            return $true
        }

        $ownerIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
        foreach ($ownerId in $ownerIds) {
            $process = Get-ProcessInfo -ProcessId ([int]$ownerId)
            if (-not $process) {
                if ($Service -eq "api" -and (Test-PlatformApiEndpoint -Port $Port)) {
                    Write-Warning "Verified platform API listener PID $ownerId cannot be inspected. Port will not be force-terminated."
                    return $false
                }
                throw "Port $Port reports PID $ownerId, but Windows cannot inspect it."
            }

            if (-not (Test-ManagedProcess -Process $process -Service $Service)) {
                throw "Port $Port is owned by an unrecognized process. PID $ownerId, name '$($process.Name)', executable '$($process.ExecutablePath)', command '$($process.CommandLine)'."
            }

            Stop-ManagedProcess -ProcessId ([int]$ownerId) -Service $Service
        }

        Start-Sleep -Milliseconds 500
    }

    return $false
}

function Wait-Http {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [int]$Attempts = 45
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return }
        }
        catch { Start-Sleep -Seconds 1 }
    }
    throw "Service did not become ready at $Uri"
}

function Wait-SchedulerWorker {
    param([int]$Attempts = 30)

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $worker = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            Test-ManagedProcess -Process $_ -Service scheduler
        } | Select-Object -First 1
        if ($worker) { return [int]$worker.ProcessId }
        Start-Sleep -Milliseconds 500
    }
    throw "Scheduler worker did not remain active after startup"
}

function Start-ManagedServiceProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Command
    )

    if ($VisibleServices) {
        return Start-Process powershell.exe -PassThru -ArgumentList @(
            "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Command
        )
    }

    $stdoutPath = Join-Path $LogRoot "$Name.out.log"
    $stderrPath = Join-Path $LogRoot "$Name.err.log"
    Remove-Item $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue

    return Start-Process powershell.exe `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Command)
}

Set-Location $RepositoryRoot

if (-not $SkipPull) {
    Write-Host "=== Update repository ==="
    git pull origin main
    if ($LASTEXITCODE -ne 0) { throw "git pull failed" }
}

if (-not $SkipInstall) {
    Write-Host "=== Synchronize Node dependencies ==="
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }

    Write-Host "=== Synchronize Python dependencies ==="
    Push-Location $ApiRoot
    try {
        & $PythonExecutable -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw "Python dependency synchronization failed" }
    }
    finally { Pop-Location }
}

if (-not $SkipDocker) {
    Write-Host "=== Start platform infrastructure ==="
    docker compose up -d postgres minio ollama
    if ($LASTEXITCODE -ne 0) { throw "docker compose infrastructure startup failed" }

    $postgresReady = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $test = Test-NetConnection 127.0.0.1 -Port 5432 -WarningAction SilentlyContinue
        if ($test.TcpTestSucceeded) { $postgresReady = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $postgresReady) { throw "PostgreSQL did not become reachable on port 5432" }
}

if (-not $SkipMigrations) {
    Write-Host "=== Apply database migrations ==="
    $previousDatabaseUrl = $env:DATABASE_URL
    try {
        $env:DATABASE_URL = $DatabaseUrl
        Push-Location $ApiRoot
        & $PythonExecutable -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed" }
    }
    finally {
        Pop-Location
        if ($null -eq $previousDatabaseUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
        else { $env:DATABASE_URL = $previousDatabaseUrl }
    }
}

$commit = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $commit) { throw "Unable to resolve current Git commit" }

Write-Host "=== Stop stale local services ==="
Stop-AllManagedServiceProcesses -Service api
Stop-AllManagedServiceProcesses -Service portal
Stop-AllManagedServiceProcesses -Service scheduler

$apiPortReleased = Stop-ManagedListener -Service api -Port $ApiPort
if (-not $apiPortReleased) {
    $requestedApiPort = $ApiPort
    $ApiPort = Get-FreeTcpPort -StartPort ($requestedApiPort + 1)
    Write-Warning "Port $requestedApiPort remains attached to an orphaned listener. Starting API on port $ApiPort."
}

$portalPortReleased = Stop-ManagedListener -Service portal -Port $PortalPort
if (-not $portalPortReleased) { throw "Portal port $PortalPort could not be released" }

$apiCommand = @"
Set-Location '$ApiRoot'
`$env:DATABASE_URL = '$DatabaseUrl'
`$env:BUILD_COMMIT = '$commit'
& '$PythonExecutable' -m uvicorn main:app --host 127.0.0.1 --port $ApiPort
"@

$portalCommand = @"
Set-Location '$RepositoryRoot'
`$env:API_INTERNAL_BASE_URL = 'http://127.0.0.1:$ApiPort'
npm run dev:portal
"@

$schedulerCommand = @"
Set-Location '$ApiRoot'
`$env:DATABASE_URL = '$DatabaseUrl'
`$env:SCHEDULER_POLL_INTERVAL_SECONDS = '$SchedulerPollIntervalSeconds'
`$env:SCHEDULER_BATCH_LIMIT = '$SchedulerBatchLimit'
`$env:SCHEDULER_OWNER_ID = 'scheduler-local'
& '$PythonExecutable' scheduler_worker.py
"@

Write-Host "=== Start API from commit $commit on port $ApiPort ==="
$apiProcess = Start-ManagedServiceProcess -Name "api" -Command $apiCommand

Write-Host "=== Start Admin Portal from commit $commit ==="
$portalProcess = Start-ManagedServiceProcess -Name "portal" -Command $portalCommand

Write-Host "=== Start Scheduler Worker ==="
$schedulerHostProcess = Start-ManagedServiceProcess -Name "scheduler" -Command $schedulerCommand

Write-Host "=== Verify restarted services ==="
Wait-Http -Uri "http://127.0.0.1:$ApiPort/platform/status"
Wait-Http -Uri "http://127.0.0.1:$PortalPort/operations"
$schedulerPid = Wait-SchedulerWorker
$status = Invoke-RestMethod "http://127.0.0.1:$ApiPort/platform/status"

if ($status.build_commit -ne "unknown" -and $status.build_commit -ne $commit) {
    throw "API build commit '$($status.build_commit)' does not match repository commit '$commit'"
}

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$PortalPort/operations"
}

Write-Host ""
Write-Host "Local platform restart completed."
Write-Host "Commit: $commit"
Write-Host "API: http://127.0.0.1:$ApiPort"
Write-Host "Portal: http://127.0.0.1:$PortalPort"
Write-Host "API host PID: $($apiProcess.Id)"
Write-Host "Portal host PID: $($portalProcess.Id)"
Write-Host "Scheduler host PID: $($schedulerHostProcess.Id)"
Write-Host "Scheduler worker PID: $schedulerPid"
Write-Host "Service mode: $(if ($VisibleServices) { 'visible' } else { 'silent' })"
Write-Host "Logs: $LogRoot"
Write-Host "Scheduler poll interval: $SchedulerPollIntervalSeconds seconds"
Write-Host "Scheduler batch limit: $SchedulerBatchLimit"
Write-Host "Work package: $($status.current_work_package)"
Write-Host "Objective: $($status.current_objective)"
Write-Host "Provider execution enabled: $($status.provider_execution_enabled)"

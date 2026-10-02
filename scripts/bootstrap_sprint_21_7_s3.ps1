param(
    [string]$Bucket = "industrial-ai-integration"
)

$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepositoryRoot

$ExpectedContainer = "industrial-ai-minio"
$DefaultEndpoint = "http://127.0.0.1:9000"
$HealthEndpoint = "http://127.0.0.1:9000/minio/health/ready"
$WindowsVenvPython = Join-Path $RepositoryRoot "apps\api\.venv\Scripts\python.exe"
$UnixVenvPython = Join-Path $RepositoryRoot "apps/api/.venv/bin/python"

if (Test-Path $WindowsVenvPython) {
    $PythonExecutable = $WindowsVenvPython
}
elseif (Test-Path $UnixVenvPython) {
    $PythonExecutable = $UnixVenvPython
}
else {
    throw "Project virtual environment Python was not found under apps/api/.venv"
}

$runningState = docker inspect --format "{{.State.Running}}" $ExpectedContainer 2>$null
$expectedMinioRunning = $LASTEXITCODE -eq 0 -and $runningState -eq "true"

if (-not $expectedMinioRunning) {
    $portOwners = @(docker ps --filter "publish=9000" --format "{{.Names}}" 2>$null)
    $portOwners = @($portOwners | Where-Object { $_ -and $_.Trim() })

    if ($portOwners.Count -gt 0) {
        $owners = $portOwners -join ", "
        throw "Port 9000 is owned by another running container: $owners. The expected container '$ExpectedContainer' is not running. Inspect or stop the conflicting container before continuing."
    }

    Write-Host "Starting expected local MinIO container: $ExpectedContainer"
    docker compose up -d minio
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start expected MinIO container"
    }
}
else {
    Write-Host "Expected MinIO container is running: $ExpectedContainer"
}

$ready = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri $HealthEndpoint -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $ready) {
    throw "MinIO container is running but did not become ready at $HealthEndpoint"
}

Write-Host "MinIO readiness probe passed."

if (-not $env:S3_ENDPOINT_URL) { $env:S3_ENDPOINT_URL = $DefaultEndpoint }
if (-not $env:S3_ACCESS_KEY_ID) { $env:S3_ACCESS_KEY_ID = "minioadmin" }
if (-not $env:S3_SECRET_ACCESS_KEY) { $env:S3_SECRET_ACCESS_KEY = "minioadmin" }
$env:S3_BUCKET = $Bucket
if (-not $env:S3_REGION) { $env:S3_REGION = "us-east-1" }
if (-not $env:S3_USE_SSL) { $env:S3_USE_SSL = "false" }

$python = @'
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

endpoint = os.environ["S3_ENDPOINT_URL"]
bucket = os.environ["S3_BUCKET"]
client = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
    region_name=os.environ.get("S3_REGION", "us-east-1"),
    use_ssl=os.environ.get("S3_USE_SSL", "false").lower() == "true",
    config=Config(
        signature_version="s3v4",
        connect_timeout=3,
        read_timeout=3,
        retries={"max_attempts": 1},
    ),
)

client.list_buckets()

try:
    client.head_bucket(Bucket=bucket)
    print(f"S3 integration bucket already exists: {bucket}")
except ClientError as exc:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    if code not in {"404", "NoSuchBucket", "NotFound"}:
        raise
    client.create_bucket(Bucket=bucket)
    print(f"Created S3 integration bucket: {bucket}")
'@

$python | & $PythonExecutable -
if ($LASTEXITCODE -ne 0) {
    throw "Expected MinIO container is ready, but S3 authentication or bucket bootstrap failed"
}

Write-Host ""
Write-Host "Local S3 integration environment is ready."
Write-Host "Run: .\scripts\validate_sprint_21_7.ps1 -IncludeS3"

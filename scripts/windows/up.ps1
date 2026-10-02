$ErrorActionPreference = "Stop"
Write-Host "Starting Industrial AI Platform runtime"
docker compose up -d --build
Write-Host "Runtime status"
docker compose ps

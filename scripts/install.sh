#!/usr/bin/env bash
set -euo pipefail

printf "\nIndustrial AI Platform - installer\n"
printf "================================\n\n"

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

if ! command_exists docker; then
  echo "Docker is required. Install Docker Desktop or Docker Engine first."
  exit 1
fi

if ! command_exists npm; then
  echo "Node.js and npm are required for the Admin Portal. Install Node.js 20+."
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

npm install

docker compose up -d --build

printf "\nInstallation completed.\n\n"
printf "API:          http://localhost:8000/health\n"
printf "Admin Portal: run 'npm run dev:portal' and open http://localhost:3000\n"
printf "Ollama:       http://localhost:11434\n"
printf "MinIO:        http://localhost:9001\n\n"

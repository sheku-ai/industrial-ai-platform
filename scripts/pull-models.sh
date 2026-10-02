#!/usr/bin/env bash
set -euo pipefail

MODEL=${1:-mistral}

echo "Pulling Ollama model: ${MODEL}"
docker compose up -d ollama
sleep 3
docker exec industrial-ai-ollama ollama pull "${MODEL}"

echo "Model ready: ${MODEL}"

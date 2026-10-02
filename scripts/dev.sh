#!/usr/bin/env bash
set -euo pipefail

docker compose up -d
npm run dev:portal

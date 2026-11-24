#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
docker compose up -d --wait neo4j
docker compose --profile tools build app
printf '\nNeo4j disponível em http://localhost:7474\n'

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p output
arquivo_temporario=$(mktemp output/resultados.XXXXXX)
trap 'rm -f "$arquivo_temporario"' EXIT
docker compose --profile tools run --build --rm -T --entrypoint python app - < scripts/executar_analises.py > "$arquivo_temporario"
mv "$arquivo_temporario" output/resultados.json
printf 'Resultados salvos em output/resultados.json\n'

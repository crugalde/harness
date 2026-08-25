#!/usr/bin/env bash
# credenciales_map.sh — Vuelca id/nombre/tipo de las credenciales del VPS como JSON.
#
#   bash scripts/credenciales_map.sh > map.json
#
# Alimenta a remap_credentials.py. Solo lee metadatos: NO toca ni imprime el campo
# 'data' (que contiene los secretos cifrados).
set -euo pipefail

STACK_DIR="${STACK_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../deploy" && pwd)}"
cd "$STACK_DIR"

if [ ! -f .env ]; then
  echo "ERROR: falta $STACK_DIR/.env" >&2
  exit 2
fi
# shellcheck disable=SC1091
set -a; . ./.env; set +a

docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c \
  "SELECT COALESCE(json_agg(json_build_object('id', id, 'name', name, 'type', type))::text, '[]')
     FROM credentials_entity;"

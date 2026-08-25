#!/usr/bin/env bash
# restore.sh — Restaura un respaldo hecho con backup.sh en una instancia LIMPIA.
#
#   bash scripts/restore.sh backups/2026-08-25_031500
#
# Requisito no negociable: el .env de destino debe tener el MISMO N8N_ENCRYPTION_KEY
# que tenía la instancia de origen. Con otra clave, la BD restaura pero cada credencial
# falla con "Credentials could not be decrypted".
#
# Sobrescribe la base de datos de destino: pide confirmación explícita.
set -euo pipefail

SRC="${1:-}"
STACK_DIR="${STACK_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../deploy" && pwd)}"

if [ -z "$SRC" ] || [ ! -f "$SRC/db.sql.gz" ]; then
  echo "Uso: bash scripts/restore.sh <directorio de respaldo con db.sql.gz>" >&2
  exit 2
fi

cd "$STACK_DIR"
if [ ! -f .env ]; then
  echo "ERROR: falta $STACK_DIR/.env — sin él no sé a qué base restaurar." >&2
  exit 2
fi
# shellcheck disable=SC1091
set -a; . ./.env; set +a
: "${POSTGRES_USER:?falta POSTGRES_USER en .env}"
: "${POSTGRES_DB:?falta POSTGRES_DB en .env}"
if [ -z "${N8N_ENCRYPTION_KEY:-}" ]; then
  echo "AVISO: .env no define N8N_ENCRYPTION_KEY. Si este respaldo viene de otra" >&2
  echo "       instancia, sus credenciales NO se van a poder descifrar." >&2
fi

echo "Vas a SOBRESCRIBIR la base '$POSTGRES_DB' de este stack con $SRC/db.sql.gz."
read -r -p "Escribe 'restaurar' para continuar: " ANSWER
[ "$ANSWER" = "restaurar" ] || { echo "Cancelado."; exit 1; }

echo "[1/4] Deteniendo n8n (Postgres sigue arriba)…"
docker compose stop n8n

echo "[2/4] Recreando la base…"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres \
  -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";" \
  -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"

echo "[3/4] Cargando el dump…"
gunzip -c "$SRC/db.sql.gz" | docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null

echo "[4/4] Levantando n8n…"
docker compose up -d n8n
docker compose logs --tail 30 n8n

echo
echo "Verifica en la UI que los workflows estén y que una credencial abra sin error."
echo "Si ves 'Credentials could not be decrypted': el N8N_ENCRYPTION_KEY no es el del origen."

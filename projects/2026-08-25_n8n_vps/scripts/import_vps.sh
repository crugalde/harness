#!/usr/bin/env bash
# import_vps.sh — Importa workflows JSON en el n8n del VPS usando el CLI del contenedor.
#
#   bash scripts/import_vps.sh /ruta/a/export/workflows
#
# El import es un upsert por ID: reimportar el mismo archivo actualiza el workflow,
# no lo duplica. NO activa nada: los workflows quedan inactivos hasta que los
# actives en la UI, uno a uno.
set -euo pipefail

SRC="${1:-}"
STACK_DIR="${STACK_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../deploy" && pwd)}"

if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then
  echo "Uso: bash scripts/import_vps.sh <directorio con los .json>" >&2
  exit 2
fi

COUNT=$(find "$SRC" -maxdepth 1 -name '*.json' | wc -l | tr -d ' ')
if [ "$COUNT" -eq 0 ]; then
  echo "ERROR: no hay archivos .json en $SRC" >&2
  exit 2
fi

cd "$STACK_DIR"
if ! docker compose ps --status running --services 2>/dev/null | grep -qx n8n; then
  echo "ERROR: el servicio n8n no está corriendo. Levántalo con: docker compose up -d" >&2
  exit 1
fi

mkdir -p backup/workflows
rm -f backup/workflows/*.json
cp "$SRC"/*.json backup/workflows/
# El contenedor corre como el usuario 'node' (uid 1000): que pueda leer lo copiado.
chown -R 1000:1000 backup 2>/dev/null || true

echo "Importando $COUNT workflows…"
docker compose exec -T -u node n8n n8n import:workflow --separate --input=/backup/workflows

DOMAIN=""
if [ -f .env ]; then DOMAIN=$(grep -E "^N8N_DOMAIN=" .env | cut -d= -f2-); fi
echo
echo "Hecho. Siguiente: abre https://${DOMAIN:-TU-DOMINIO}/home/workflows y revisa que estén todos."
echo "Los nodos mostrarán 'credential not found' hasta que crees las credenciales y corras"
echo "credenciales_map.sh + remap_credentials.py (o las reselecciones a mano)."

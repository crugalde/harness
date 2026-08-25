#!/usr/bin/env bash
# backup.sh — Respaldo del n8n del VPS: base de datos + workflows.
#
#   bash scripts/backup.sh                      # db + workflows
#   bash scripts/backup.sh --with-credentials   # además, credenciales DESCIFRADAS (ver aviso)
#   bash scripts/backup.sh --retention 30       # días a conservar (default: 14)
#
# Cron diario a las 03:15 (crontab -e):
#   15 3 * * * /usr/bin/bash /opt/n8n/scripts/backup.sh >> /var/log/n8n-backup.log 2>&1
#
# AVISO SOBRE LA CLAVE: este script NO respalda N8N_ENCRYPTION_KEY, y un dump de la BD
# sin esa clave deja las credenciales indescifrables. La clave va en tu gestor de
# contraseñas, no junto al respaldo (quien tenga ambos tiene todos tus secretos).
set -euo pipefail

STACK_DIR="${STACK_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../deploy" && pwd)}"
RETENTION=14
WITH_CREDS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --with-credentials) WITH_CREDS=1; shift ;;
    --retention) RETENTION="${2:?falta el número de días}"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; exit 2 ;;
  esac
done

cd "$STACK_DIR"
if [ ! -f .env ]; then
  echo "ERROR: falta $STACK_DIR/.env" >&2
  exit 2
fi
# shellcheck disable=SC1091
set -a; . ./.env; set +a

if [ -z "${N8N_ENCRYPTION_KEY:-}" ]; then
  echo "AVISO: N8N_ENCRYPTION_KEY no está en .env; n8n usó una clave autogenerada dentro" >&2
  echo "       del volumen n8n_data (/home/node/.n8n/config). Fíjala antes de confiar en" >&2
  echo "       este respaldo, o restaurar en otra máquina no descifrará nada." >&2
fi

TS=$(date +%Y-%m-%d_%H%M%S)
DEST="backups/$TS"
mkdir -p "$DEST" "backup/export_$TS"
chown -R 1000:1000 backup 2>/dev/null || true

echo "[1/3] Dump de Postgres…"
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  | gzip -9 > "$DEST/db.sql.gz"
# Un .gz truncado o de 20 bytes se ve como respaldo hasta el día que lo necesitas.
BYTES=$(wc -c < "$DEST/db.sql.gz")
if ! gzip -t "$DEST/db.sql.gz" 2>/dev/null || [ "$BYTES" -lt 1000 ]; then
  echo "ERROR: el dump salió corrupto o vacío ($BYTES bytes). Se descarta." >&2
  rm -rf "$DEST"
  exit 1
fi
echo "      $(du -h "$DEST/db.sql.gz" | cut -f1)"

echo "[2/3] Export de workflows (JSON legible, sirve para revisar diffs en git)…"
docker compose exec -T -u node n8n n8n export:workflow --backup --output="/backup/export_$TS/" >/dev/null
echo "      $(find "backup/export_$TS" -name '*.json' | wc -l | tr -d ' ') workflows"
tar -czf "$DEST/workflows.tar.gz" -C "backup/export_$TS" .
rm -rf "backup/export_$TS"

if [ "$WITH_CREDS" -eq 1 ]; then
  echo "[3/3] Export de credenciales DESCIFRADAS (secretos en texto plano)…"
  docker compose exec -T -u node n8n n8n export:credentials --all --decrypted \
    --output=/backup/credentials_decrypted.json >/dev/null
  mv backup/credentials_decrypted.json "$DEST/credentials_decrypted.json"
  chmod 600 "$DEST/credentials_decrypted.json"
  echo "      ⚠  $DEST/credentials_decrypted.json contiene tokens en claro."
  echo "      ⚠  Cífralo antes de moverlo fuera del VPS:  gpg -c $DEST/credentials_decrypted.json"
else
  echo "[3/3] Credenciales: omitidas (--with-credentials para incluirlas descifradas)."
fi

chmod 700 "$DEST"

echo "Retención: eliminando respaldos de más de $RETENTION días…"
while IFS= read -r old; do
  echo "  - rm $old"
  rm -rf "$old"
done < <(find backups -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime "+$RETENTION")

echo "Listo: $STACK_DIR/$DEST"

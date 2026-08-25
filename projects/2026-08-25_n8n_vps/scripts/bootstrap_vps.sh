#!/usr/bin/env bash
# bootstrap_vps.sh — Deja n8n corriendo en el VPS de una sola pasada.
#
#   bash scripts/bootstrap_vps.sh --domain n8n.tudominio.cl --email tu@correo.cl
#
# Qué hace (idempotente: puedes correrlo de nuevo sin romper nada):
#   1. verifica docker + compose y corre el preflight
#   2. genera N8N_ENCRYPTION_KEY y POSTGRES_PASSWORD, y escribe deploy/.env
#      (si ya existe .env, lo respeta y NO regenera secretos)
#   3. levanta el stack y espera a que n8n esté healthy
#   4. imprime la URL y la clave de cifrado UNA vez para que la guardes
set -euo pipefail

DOMAIN=""
EMAIL=""
TZ_VALUE="America/Santiago"
SKIP_PREFLIGHT=0
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="${STACK_DIR:-$(cd "$HERE/../deploy" && pwd)}"

usage() { sed -n '2,14p' "$0"; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:?falta el dominio}"; shift 2 ;;
    --email)  EMAIL="${2:?falta el correo}"; shift 2 ;;
    --tz)     TZ_VALUE="${2:?falta la zona horaria}"; shift 2 ;;
    --skip-preflight) SKIP_PREFLIGHT=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Opción desconocida: $1" >&2; usage 2 ;;
  esac
done

[ -n "$DOMAIN" ] || { echo "ERROR: falta --domain" >&2; usage 2; }
[ -n "$EMAIL" ]  || { echo "ERROR: falta --email (lo usa Let's Encrypt para avisarte)" >&2; usage 2; }

echo "== 1/4 Verificaciones =="
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker no está instalado." >&2
  echo "  Instálalo con:  curl -fsSL https://get.docker.com | sh" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: falta el plugin 'docker compose' v2." >&2
  echo "  Instálalo con:  apt-get install -y docker-compose-plugin" >&2; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "ERROR: falta openssl (apt-get install -y openssl)." >&2; exit 1; }

if [ "$SKIP_PREFLIGHT" -eq 0 ]; then
  bash "$HERE/preflight.sh" "$DOMAIN" || {
    echo >&2
    echo "El preflight encontró problemas. Arréglalos y vuelve a correr esto," >&2
    echo "o usa --skip-preflight si sabes lo que haces (el certificado puede fallar)." >&2
    exit 1
  }
fi

echo
echo "== 2/4 Configuración =="
cd "$STACK_DIR"
if [ -f .env ]; then
  echo "  .env ya existe: lo respeto (no regenero secretos)."
  # shellcheck disable=SC1091
  set -a; . ./.env; set +a
else
  ENC_KEY="$(openssl rand -hex 32)"
  PG_PASS="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)"
  sed -e "s|^N8N_DOMAIN=.*|N8N_DOMAIN=$DOMAIN|" \
      -e "s|^ACME_EMAIL=.*|ACME_EMAIL=$EMAIL|" \
      -e "s|^N8N_ENCRYPTION_KEY=.*|N8N_ENCRYPTION_KEY=$ENC_KEY|" \
      -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$PG_PASS|" \
      -e "s|^TZ=.*|TZ=$TZ_VALUE|" \
      .env.example > .env
  chmod 600 .env
  N8N_ENCRYPTION_KEY="$ENC_KEY"
  echo "  .env creado (chmod 600) con secretos nuevos."
fi

echo
echo "== 3/4 Levantando el stack =="
mkdir -p backup
docker compose pull --quiet
docker compose up -d

CID="$(docker compose ps -q n8n)"
printf '  esperando a que n8n esté healthy'
for _ in $(seq 1 60); do
  STATUS="$(docker inspect --format '{{.State.Health.Status}}' "$CID" 2>/dev/null || echo starting)"
  [ "$STATUS" = "healthy" ] && break
  printf '.'
  sleep 5
done
echo
if [ "${STATUS:-}" != "healthy" ]; then
  echo "  ⚠ n8n no llegó a 'healthy'. Revisa:  docker compose logs --tail 50 n8n" >&2
  exit 1
fi
echo "  n8n healthy."

echo
echo "== 4/4 Listo =="
cat <<EOF

  Editor:   https://$DOMAIN
  Webhooks: https://$DOMAIN/webhook/<path>

  1) Abre la URL y crea la cuenta de owner (email + contraseña). Hazlo AHORA:
     el import por CLI necesita que exista un usuario dueño.
  2) GUARDA ESTA CLAVE en tu gestor de contraseñas. Sin ella, las credenciales
     de este n8n son irrecuperables aunque tengas el respaldo de la base:

     N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY:-(ya estaba en .env, míralo ahí)}

  3) Instala el respaldo diario:
     (crontab -l 2>/dev/null; echo "15 3 * * * /usr/bin/bash $HERE/backup.sh >> /var/log/n8n-backup.log 2>&1") | crontab -

  Si el certificado no sale: docker compose logs caddy  (casi siempre es DNS
  sin propagar o el puerto 80 cerrado).

EOF

#!/usr/bin/env bash
# preflight.sh — Verifica que el VPS esté listo para levantar n8n. Solo lectura.
#
#   bash scripts/preflight.sh n8n.tudominio.cl
#
# Salida 0 = listo (puede haber avisos), 1 = hay algo que arreglar antes de seguir.
set -euo pipefail

DOMAIN="${1:-${N8N_DOMAIN:-}}"
FAIL=0
WARN=0

# Color solo si la salida va a una terminal. Al redirigir a un archivo o pipe
# (p. ej. `ssh vps 'preflight.sh …' > salida.txt`) sale texto plano, copiable tal cual.
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_BAD=$'\033[31m'; C_OFF=$'\033[0m'
else
  C_OK=""; C_WARN=""; C_BAD=""; C_OFF=""
fi

ok()   { printf '  %s✓%s %s\n' "$C_OK" "$C_OFF" "$1"; }
warn() { printf '  %s!%s %s\n' "$C_WARN" "$C_OFF" "$1"; WARN=$((WARN+1)); }
bad()  { printf '  %s✗%s %s\n' "$C_BAD" "$C_OFF" "$1"; FAIL=$((FAIL+1)); }

echo "== Docker =="
if command -v docker >/dev/null 2>&1; then
  ok "docker $(docker --version | awk '{print $3}' | tr -d ,)"
  if docker compose version >/dev/null 2>&1; then
    ok "docker compose $(docker compose version --short)"
  else
    bad "falta el plugin 'docker compose' (v2). Instala docker-compose-plugin."
  fi
  docker info >/dev/null 2>&1 && ok "el daemon responde" || bad "el daemon no responde (¿sudo? ¿servicio caído?)"
else
  bad "docker no está instalado"
fi

echo "== Recursos =="
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
[ "$MEM_MB" -ge 3800 ] && ok "RAM: ${MEM_MB} MB" || \
  { [ "$MEM_MB" -ge 1800 ] && warn "RAM: ${MEM_MB} MB (n8n + Postgres van justos; 4 GB recomendado)" \
    || bad "RAM: ${MEM_MB} MB (insuficiente para n8n + Postgres)"; }

DISK_GB=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
[ "$DISK_GB" -ge 10 ] && ok "disco libre en /: ${DISK_GB} GB" || bad "disco libre en /: ${DISK_GB} GB (mínimo ~10 GB)"

if [ -f /proc/swaps ] && [ "$(wc -l < /proc/swaps)" -gt 1 ]; then
  ok "swap activa"
else
  warn "sin swap: con 4 GB conviene 2 GB de swap (fallocate -l 2G /swapfile …)"
fi

echo "== Puertos 80/443 =="
if command -v ss >/dev/null 2>&1; then
  for p in 80 443; do
    if ss -lntH "sport = :$p" | grep -q .; then
      bad "puerto $p ocupado por: $(ss -lntpH "sport = :$p" | head -1)"
    else
      ok "puerto $p libre"
    fi
  done
else
  warn "no hay 'ss' para verificar puertos (instala iproute2)"
fi

echo "== Firewall =="
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw status | grep -qE '(^|[[:space:]])80(/tcp)?[[:space:]]+ALLOW' && ok "ufw permite 80" || warn "ufw activo pero 80 no aparece permitido (ufw allow 80/tcp)"
  ufw status | grep -qE '(^|[[:space:]])443(/tcp)?[[:space:]]+ALLOW' && ok "ufw permite 443" || warn "ufw activo pero 443 no aparece permitido (ufw allow 443/tcp)"
else
  warn "ufw inactivo o ausente: el VPS queda con todos los puertos según el proveedor"
fi

echo "== DNS =="
if [ -z "$DOMAIN" ]; then
  warn "no pasaste dominio: bash scripts/preflight.sh n8n.neuromuscular.cloud"
else
  PUBIP=$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || echo "")
  # '|| true': si el nombre no existe, getent sale 2 y con pipefail+set -e el script
  # moriría en silencio justo en el caso más común (registro A todavía sin crear).
  RESOLVED=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1; exit}' || true)
  if [ -z "$RESOLVED" ]; then
    bad "$DOMAIN no resuelve. Crea el registro A antes de levantar Caddy (o el certificado falla)."
  elif [ -n "$PUBIP" ] && [ "$RESOLVED" != "$PUBIP" ]; then
    bad "$DOMAIN → $RESOLVED, pero la IP pública del VPS es $PUBIP"
  else
    ok "$DOMAIN → $RESOLVED"
  fi
fi

echo
if [ "$FAIL" -gt 0 ]; then
  echo "Resultado: $FAIL problema(s) y $WARN aviso(s). Arregla lo marcado con ✗ antes de 'docker compose up -d'."
  exit 1
fi
echo "Resultado: listo ($WARN aviso(s))."

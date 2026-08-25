# Estado — Migración de n8n Cloud al VPS

**Última actualización:** 2026-08-25
**Objetivo:** correr n8n self-hosted en `srv1314177` (Hostinger, Ubuntu, Docker) y mover
todos los workflows desde n8n Cloud, sin ejecuciones duplicadas ni credenciales rotas.

## Decisiones tomadas

- **Stack:** n8n **2.36.7** (versión a la que apuntan los tags `latest`/`stable` al
  2026-08-25; la línea 2.37.x es pre-release) + **Postgres 16** + **Caddy 2**.
  - Postgres y no el SQLite por defecto: con volumen de ejecuciones real, SQLite es el
    cuello de botella y la causa nº 1 de bases corruptas tras un reinicio sucio.
  - Caddy y no Traefik: TLS automático con 6 líneas de config; no hay más servicios que
    enrutar en este VPS.
  - Versión **pineada**: `latest` cambia de versión en un `docker compose pull`.
- **Modo regular**, no queue mode (Redis + workers). Se justifica recién con ejecuciones
  concurrentes pesadas; es un cambio de compose, no una migración.
- **Solo Caddy publica puertos** (80/443). n8n y Postgres quedan en la red interna de Docker.
- Retención de ejecuciones a 14 días (`EXECUTIONS_DATA_MAX_AGE=336`): es lo que más crece
  en disco.

## Hechos clave de la migración (verificados)

- **Las credenciales NO se pueden exportar desde n8n Cloud**: se cifran con una clave que no
  controlas. Se recrean a mano, sin excepción. Es el cuello de botella real del proyecto.
- **`N8N_ENCRYPTION_KEY` es el punto de no retorno**: sin ella, un dump de Postgres no sirve
  de nada (todas las credenciales quedan indescifrables). Va al gestor de contraseñas, no
  junto al respaldo.
- Al recrear una credencial, n8n le da **ID nuevo** → los workflows importados apuntan al ID
  viejo y muestran "credential not found". Resuelto con `credenciales_map.sh` +
  `remap_credentials.py` (emparejan por tipo + nombre).
- **El historial de ejecuciones no migra** y **las URLs de webhook cambian de dominio**: hay
  que reapuntar cada sistema emisor externo.
- **El import por CLI no activa workflows** (upsert por ID, quedan inactivos): bueno, porque
  evita que corran en Cloud y en el VPS al mismo tiempo.
- La API pública de n8n **no existe en el trial**; sin ella, el export es a mano desde la UI.
- En n8n 2.x los task runners ya vienen activos y `N8N_RUNNERS_ENABLED` está deprecado;
  además `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` por defecto (los nodos Code ya no leen
  `process.env`).

## Hecho hasta ahora

- [x] `README.md` — runbook completo (decisión, preflight, levantar, exportar, credenciales,
      importar, corte, respaldos, definición de "hecho", qué no se migra).
- [x] `deploy/docker-compose.yml` + `Caddyfile` + `.env.example` — stack completo.
- [x] `scripts/preflight.sh` — verifica DNS/puertos/RAM/disco/firewall en el VPS (solo lectura).
- [x] `scripts/export_cloud.py` — exporta workflows vía API pública + genera
      `inventario_credenciales.md` y `resumen.md` (tabla webhook viejo→nuevo, schedules).
- [x] `scripts/credenciales_map.sh` + `scripts/remap_credentials.py` — reapuntan los IDs de
      credenciales de Cloud a los del VPS.
- [x] `scripts/import_vps.sh` — import por CLI dentro del contenedor.
- [x] `scripts/backup.sh` + `scripts/restore.sh` — pg_dump + export de workflows, retención,
      restauración con confirmación explícita.
- [x] `scripts/bootstrap_vps.sh` — despliegue de una pasada (preflight → secretos → `.env` →
      `up -d` → espera healthy → imprime URL y clave). Idempotente: respeta un `.env` existente.
- [x] `.gitattributes` en la raíz — fuerza LF en `*.sh`/`*.py`/`*.yml`/`Caddyfile`, porque el
      escritorio del usuario es **Windows** y un checkout con CRLF rompe los scripts en el VPS.
- [x] Sección 3.bis del runbook con la ruta Windows (PowerShell, `scp` en vez de `rsync`, las
      tres trampas de CRLF, alternativa WSL).
- [x] **Skill `skills/n8n/`** (el harness como copiloto de diseño): `n8n_workflows`,
      `n8n_workflow_get`, `n8n_executions` (lectura) + `n8n_workflow_create`,
      `n8n_workflow_update`, `n8n_workflow_activate` (escritura, en `GATED_TOOLS`).
      `SKILL.md` lleva las reglas de diseño de workflows.
- [x] `tools/n8n_setup.py` — wizard setup/status (valida la API key, la guarda en
      `~/.config/harness/.env` chmod 600, y diagnostica: workflows, activos, últimos errores).

### Validado en esta sesión

- `docker compose config` → OK (compose válido, variables resueltas).
- Tag `2.36.7` existe en Docker Hub y es a donde apuntan `latest`/`stable` (mismo digest).
- `export_cloud.py` contra una API n8n falsa: paginación por cursor, un JSON por workflow,
  ambos informes, y los errores 401 / 404 / sin-API-key con mensaje accionable.
- `remap_credentials.py` con fixture: reescribe los IDs que calzan, lista los que no y sale
  con código 1 cuando queda trabajo manual.
- `ruff check` limpio en todo lo nuevo; `bash -n` limpio en los seis `.sh`.
- Skill `n8n` contra una API n8n falsa: listado con paginación, resumen de nodos, ejecuciones
  con error, create/update/activate/deactivate — y el servidor de prueba **rechaza** la
  petición si se envían campos de solo lectura (`id`, `active`, `versionId`), que es
  justamente lo que `_clean()` evita.
- `tools/registry.py` descubre la skill: las 6 herramientas quedan registradas.
- `tools/n8n_setup.py setup/status` end-to-end contra la API falsa; `.env` queda en 0600 y un
  401 devuelve mensaje accionable.
- `evals`: 19 OK, 0 fallos (3 casos nuevos cubren el gate de escritura de n8n). `pytest`: 5 OK.

### NO validado (declarado)

- **El stack no se levantó de verdad**: este contenedor de sesión tiene CLI de Docker pero no
  daemon. La primera corrida real (certificado de Caddy, arranque de n8n contra Postgres,
  `import:workflow` dentro del contenedor) queda para el VPS.

## Pendiente (retomar aquí)

1. **Único dato que bloquea el arranque:** el subdominio para el VPS (`n8n.???`) con su
   registro A. Sin dominio propio se puede partir con `sslip.io` sobre la IP, pero entonces
   no hay que reapuntar webhooks de producción hasta tener el definitivo.
   - Instancia de origen **confirmada**: `https://cristianub.app.n8n.cloud`.
   - Si el plan de Cloud tiene API pública se sabe corriendo `export_cloud.py`: un 403
     significa trial/API apagada y el export pasa a ser manual desde la UI.
   - Escritorio del usuario: **Windows** (los pasos locales van en PowerShell; el VPS no cambia).
2. Correr `preflight.sh` en el VPS y arreglar lo que marque.
3. Levantar el stack, crear la cuenta de owner, exportar de Cloud.
4. Recrear credenciales (aprovechar de **rotar** los tokens viejos), importar, remapear.
5. Corte: desactivar en Cloud → reapuntar webhooks → activar en el VPS uno a uno.
6. Instalar el cron de `backup.sh` y probar `restore.sh` una vez en limpio antes de
   cancelar el plan de Cloud.

## Siguiente acción

Confirmar el subdominio del VPS y correr en `srv1314177`:
`bash /opt/n8n/scripts/bootstrap_vps.sh --domain <dominio> --email <correo>`.

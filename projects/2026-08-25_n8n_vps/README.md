# Correr n8n en tu VPS y migrar los workflows desde n8n Cloud

Runbook completo para mover tu cuenta de n8n Cloud a **self-hosted** en el VPS que ya
tienes (`srv1314177`, Hostinger, Ubuntu, Docker), con el stack y los scripts de este
directorio. Tiempo real de trabajo: **1–2 h** si tienes pocas credenciales; el cuello de
botella no es técnico, es **recrear las credenciales a mano** (n8n Cloud no las exporta).

---

## 0. Antes de decidir: qué ganas y qué pierdes

| | n8n Cloud | Self-hosted en tu VPS |
|---|---|---|
| Costo | plan mensual por instancia | ~0 marginal (el VPS ya está pagado) |
| Ejecuciones | limitadas por plan | limitadas por tu CPU/RAM |
| Actualizaciones, TLS, backups, uptime | de n8n | **tuyos** |
| Datos (credenciales, ejecuciones) | en infra de n8n | en tu disco |
| SSO, variables de entorno por proyecto, git ops, log streaming | según plan | son features de pago (Enterprise); la edición Community no las trae |
| Licencia | — | Sustainable Use License: self-hosting para uso interno propio está permitido; revender n8n como servicio, no |

Si lo que te mueve es el costo y el control del dato, el cambio se justifica. Si dependes
de SSO o de features Enterprise, revisa esa fila antes de cancelar el plan.

**Regla de oro de esta migración:** `N8N_ENCRYPTION_KEY`. Es la clave con la que n8n cifra
las credenciales en la base de datos. Si la pierdes, ninguna credencial se recupera —ni con
el dump de Postgres en la mano—. Genérala tú, guárdala en tu gestor de contraseñas **antes**
de crear nada.

---

## 1. Arquitectura del stack

```
Internet ──443──► Caddy (TLS automático, Let's Encrypt)
                    └──► n8n:5678        (contenedor, sin puertos publicados)
                            └──► Postgres:5432 (contenedor, sin puertos publicados)
```

- `deploy/docker-compose.yml` — n8n 2.36.7 + Postgres 16 + Caddy 2.
- `deploy/Caddyfile` — proxy y certificado automático.
- `deploy/.env.example` — todas las variables, con cómo generar cada secreto.

Postgres en vez del SQLite por defecto: con volumen de ejecuciones real, SQLite se convierte
en el cuello de botella y en la causa nº 1 de bases corruptas tras un reinicio sucio.

---

## 2. Prerrequisitos

1. **Subdominio** apuntando al VPS: registro `A` de `n8n.neuromuscular.cloud` → IP del VPS.
2. **Puertos 80 y 443 abiertos** (Caddy los necesita para el desafío ACME).
3. **Docker + plugin compose v2** en el VPS.
4. RAM: 4 GB cómodo, 2 GB al límite. Disco: ≥10 GB libres.

Verifícalo todo de una (solo lectura, no cambia nada):

```bash
ssh root@srv1314177
bash scripts/preflight.sh n8n.neuromuscular.cloud
```

### De dónde sale el subdominio

No es un dato que exista en alguna parte: **lo eliges tú** y lo creas como registro DNS.
Tres casos:

**a) Ya tienes un dominio.** Revísalo en hPanel de Hostinger → **Dominios** (o en el
registrador donde lo compraste; en Chile, NIC Chile para los `.cl`). Eliges cualquier
subdominio libre —`n8n.neuromuscular.cloud`— y creas el registro:

- hPanel → **Dominios → tu dominio → DNS / Nameservers → Zona DNS → Añadir registro**
- Tipo `A` · Nombre `n8n` · Apunta a la IP del VPS · TTL `300`

El nombre se pone **solo** (`n8n`), no el dominio completo: el panel le agrega el resto.

Antes de buscar el panel, confirma **quién administra el DNS** de ese dominio — no siempre es
donde lo compraste:

```bash
nslookup -type=NS neuromuscular.cloud      # Windows
dig +short NS neuromuscular.cloud          # Linux/macOS
```

- `ns1.dns-parking.com` / `ns2.dns-parking.com` → Hostinger: el registro va en hPanel.
- `*.ns.cloudflare.com` → Cloudflare: el registro va en su panel, y **con el proxy apagado**
  (la nubecita en gris, "DNS only"). Con el proxy naranja encendido, Cloudflare termina el
  TLS por su cuenta y el certificado de Caddy nunca se emite o entras en bucle de redirección.
  Puedes encenderlo después, ya con el certificado emitido, si sabes lo que buscas.
- Otros nameservers → el panel de ese proveedor.

**b) No tienes dominio.** Compra uno (~US$10–15/año) en Hostinger, Namecheap o Cloudflare, o
un `.cl` en NIC Chile. Si lo compras en Hostinger, la zona DNS ya queda en el mismo panel.

**c) No quieres comprar nada hoy.** Usa `sslip.io`: es un DNS público que resuelve la IP que
lleva escrita en el nombre, sin configurar nada. Con la IP del VPS:

```bash
ssh root@srv1314177 'curl -s https://api.ipify.org'   # ej. 203.0.113.45
# tu dominio pasa a ser:  n8n.203-0-113-45.sslip.io
bash /opt/n8n/scripts/bootstrap_vps.sh --domain n8n.203-0-113-45.sslip.io --email tu@correo.cl
```

Caddy le emite certificado igual y funciona hoy mismo. **Pero no muevas los webhooks de
producción a esa URL:** cambiar de dominio después obliga a reapuntar cada sistema emisor
otra vez, y ese es justo el paso caro del corte. `sslip.io` sirve para ver el editor andando;
para el corte definitivo, dominio propio.

---

## 3. Paso 1 — Levantar n8n en el VPS

**Camino rápido (una sola pasada).** Copia el proyecto al VPS y corre el bootstrap: verifica
docker y el preflight, genera los secretos, escribe el `.env`, levanta el stack y espera a que
n8n esté sano. Es idempotente: si algo falla, lo arreglas y lo vuelves a correr.

```bash
# Desde tu máquina
rsync -av projects/2026-08-25_n8n_vps/ root@srv1314177:/opt/n8n/
#   Windows:  scp -r projects\2026-08-25_n8n_vps\* root@srv1314177:/opt/n8n/

# En el VPS
ssh root@srv1314177
bash /opt/n8n/scripts/bootstrap_vps.sh --domain n8n.neuromuscular.cloud --email tu@correo.cl
```

Al terminar te imprime la URL y **la clave de cifrado, una sola vez**: guárdala en tu gestor
de contraseñas antes de cerrar la terminal.

<details>
<summary>Camino manual, si prefieres ver cada paso</summary>

```bash
# En el VPS
mkdir -p /opt/n8n && cd /opt/n8n
# copia aquí projects/2026-08-25_n8n_vps/{deploy,scripts} desde tu máquina:
#   rsync -av projects/2026-08-25_n8n_vps/ root@srv1314177:/opt/n8n/
#   Windows:  scp -r projects\2026-08-25_n8n_vps\* root@srv1314177:/opt/n8n/

cd /opt/n8n/deploy
cp .env.example .env && chmod 600 .env

openssl rand -hex 32      # → N8N_ENCRYPTION_KEY (guárdala en tu gestor de contraseñas)
openssl rand -base64 24   # → POSTGRES_PASSWORD
nano .env                 # completa N8N_DOMAIN, ACME_EMAIL y los dos secretos

docker compose up -d
docker compose logs -f n8n     # espera "Editor is now accessible via ..."
```

</details>

Abre `https://n8n.neuromuscular.cloud` y **crea la cuenta de owner** (email + contraseña). Hazlo
ahora: el import por CLI necesita que exista un usuario dueño al que asignar los workflows.

Si el certificado no sale: `docker compose logs caddy` — casi siempre es el DNS aún sin
propagar o el puerto 80 cerrado.

---

## 3.bis Si tu máquina es Windows

Todo lo que corre **en el VPS** es igual (es Ubuntu). Solo cambian los pasos locales:

| En el runbook | En Windows (PowerShell) |
|---|---|
| `python3 script.py` | `python script.py` (o `py -3 script.py`) |
| `export N8N_API_KEY=...` | `$env:N8N_API_KEY = "n8n_api_..."` |
| `rsync -av origen/ root@srv:/destino/` | `scp -r origen\* root@srv:/destino/` |
| `~/.config/harness/.env` | `$HOME\.config\harness\.env` (misma ruta, la resuelve Python) |
| `openssl rand -hex 32` | genérala **en el VPS**, ahí sí hay openssl |

Requisitos: **Python 3** (`winget install Python.Python.3.12`) y el cliente **OpenSSH**, que
Windows 10/11 ya trae (`ssh` y `scp` funcionan en PowerShell sin instalar nada).

Tres trampas concretas:

1. **Finales de línea.** El repo trae `.gitattributes` que fuerza LF en `*.sh`, `*.py`,
   `*.yml` y el `Caddyfile`, así que un `git clone` en Windows ya viene sano. Si copias
   archivos por otra vía y en el VPS ves `$'\r': command not found`:
   `sed -i 's/\r$//' /opt/n8n/scripts/*.sh`
2. **El `.env` créalo en el VPS** (`nano .env`), no en Windows. Un `.env` con CRLF le mete
   un `\r` invisible al final de cada valor y Postgres rechaza la contraseña.
3. **Nada de Notepad** para editar `.sh` o `.env`: usa `nano` por SSH, o VS Code con el
   indicador de la esquina inferior derecha en **LF**.

**Alternativa más cómoda:** `wsl --install` te deja Ubuntu dentro de Windows y el runbook
corre tal cual, con `rsync`, `bash` y `openssl` incluidos.

---

## 4. Paso 2 — Exportar los workflows desde n8n Cloud

En Cloud: **Settings → n8n API → Create an API key**. (La API pública no existe en el trial;
si ese es tu caso, salta a la alternativa manual más abajo.)

```bash
# En tu máquina, desde la raíz del repo (Windows: ver 3.bis)
export N8N_API_KEY='n8n_api_...'
python3 projects/2026-08-25_n8n_vps/scripts/export_cloud.py \
    --base-url https://cristianub.app.n8n.cloud \
    --out ~/n8n_export \
    --new-domain n8n.neuromuscular.cloud
```

Deja tres cosas en `~/n8n_export/`:

- `workflows/*.json` — un archivo por workflow, listo para el import por CLI.
- `inventario_credenciales.md` — **la checklist real de la migración**: cada credencial, su
  tipo y en qué nodos se usa.
- `resumen.md` — workflows activos, tabla de **webhooks viejo → nuevo** y lista de triggers
  por reloj.

> **Alternativa sin API** (plan trial o API deshabilitada): en cada workflow, menú `⋯` →
> *Download*. Guarda todos los `.json` en una carpeta y sigue igual desde el paso 4.

---

## 5. Paso 3 — Recrear las credenciales (la parte manual)

n8n Cloud **no exporta credenciales**: están cifradas con una clave que no controlas. No hay
truco que lo evite. Con `inventario_credenciales.md` al lado, en el VPS:
*Credentials → Add credential*, una por una.

**Usa exactamente el mismo nombre** que tenía en Cloud. Eso permite que el paso siguiente
reconecte los nodos solo; si cambias los nombres, tendrás que reseleccionar credencial en
cada nodo a mano.

Aprovecha y **rota** los tokens que llevan mucho tiempo activos: vas a tocarlos todos igual.

---

## 6. Paso 4 — Importar los workflows y reapuntar las credenciales

Al recrear una credencial, n8n le asigna un **ID nuevo**. Los workflows exportados apuntan al
ID viejo de Cloud, así que cada nodo aparecería con *"credential not found"*. `remap_credentials.py`
reescribe esos IDs emparejando por (tipo, nombre):

```bash
# 1) Copia los JSON al VPS
rsync -av ~/n8n_export/workflows/ root@srv1314177:/opt/n8n/export_workflows/
#    Windows:  scp -r $HOME\n8n_export\workflows\* root@srv1314177:/opt/n8n/export_workflows/

# 2) En el VPS: mapa de las credenciales que acabas de crear (solo metadatos, sin secretos)
cd /opt/n8n
bash scripts/credenciales_map.sh > map.json

# 3) Reescribe los IDs
python3 scripts/remap_credentials.py --dir export_workflows --map map.json
#    → deja export_workflows_remap/ y lista lo que no encontró equivalente

# 4) Importa
bash scripts/import_vps.sh export_workflows_remap
```

El import es un **upsert por ID**: volver a correrlo actualiza los workflows, no los duplica.
Y **no activa nada** — quedan inactivos a propósito.

Si usas proyectos (n8n 2.x), el CLI acepta `--projectId` para importar dentro de uno; por
defecto todo queda en el proyecto personal del owner.

---

## 7. Paso 5 — El corte (cutover)

El orden importa: mal hecho, te quedan dos instancias ejecutando los mismos cron y webhooks.

1. **Desactiva en Cloud** los workflows con trigger por reloj (`resumen.md` los lista). Si
   quedan activos en ambos lados, todo se ejecuta dos veces: correos duplicados, escrituras
   duplicadas.
2. **Reapunta los webhooks externos.** La URL cambia de
   `https://cristianub.app.n8n.cloud/webhook/<path>` a `https://n8n.neuromuscular.cloud/webhook/<path>`.
   La tabla ya está armada en `resumen.md`: tócala en cada servicio emisor (Stripe, GitHub,
   Telegram, formularios, CRM…).
3. **Activa en el VPS uno a uno**, del más crítico al menos, verificando cada ejecución en
   *Executions* antes de pasar al siguiente.
4. **Deja Cloud pagado ~1–2 semanas** con todo desactivado, como red de seguridad. Cancela
   recién cuando el VPS haya corrido un ciclo completo (incluidos los workflows mensuales).

---

## 8. Paso 6 — Operación: respaldos y actualizaciones

```bash
# Respaldo (BD + workflows). Cron diario 03:15:
#   15 3 * * * /usr/bin/bash /opt/n8n/scripts/backup.sh >> /var/log/n8n-backup.log 2>&1
bash scripts/backup.sh
bash scripts/backup.sh --with-credentials   # además, credenciales descifradas (cífralas)

# Restaurar en una instancia limpia (exige el MISMO N8N_ENCRYPTION_KEY)
bash scripts/restore.sh backups/2026-08-25_031500

# Actualizar de versión: sube N8N_IMAGE_TAG en .env, luego
cd /opt/n8n/deploy && docker compose pull && docker compose up -d
```

Reglas de operación:

- **Respalda antes de cada update** y lee las notas de versión si cruzas un major.
- **La clave de cifrado vive en tu gestor de contraseñas**, no en la misma carpeta que el
  dump. Quien tenga ambos tiene todos tus secretos.
- Ejecuciones podadas a 14 días (`EXECUTIONS_DATA_MAX_AGE=336`). Súbelo solo si el disco lo
  aguanta: es lo que más crece.
- Deja la instancia detrás de Caddy y **no publiques el puerto 5678** al exterior.

---

## 8.bis Conectar el harness: diseñar los próximos workflows con Claude Code

Con n8n ya operativo, el harness se conecta a su API pública y pasa a ser copiloto de diseño:

```bash
# En tu máquina, una sola vez (crea la API key en Settings → n8n API del VPS)
python tools/n8n_setup.py
python tools/n8n_setup.py status     # workflows, activos y últimas ejecuciones con error

# A partir de ahí
python tools/loop.py "lista mis workflows activos de n8n"
python tools/loop.py "por qué falló el workflow abc123"
python tools/loop.py "diseña un workflow que me avise por Telegram de papers nuevos de NMUS"
```

La skill `skills/n8n/` expone seis herramientas: tres de **lectura** (`n8n_workflows`,
`n8n_workflow_get`, `n8n_executions`) y tres de **escritura** —crear, modificar y activar—
que están en `GATED_TOOLS`: cada una exige confirmación humana por turno, porque un workflow
activo dispara acciones reales. Los workflows que crea el harness **nacen inactivos** a
propósito: se revisan en el editor, se corren una vez a mano y recién ahí se activan.

`skills/n8n/SKILL.md` lleva además las reglas de diseño que el agente sigue al proponer nodos
(idempotencia, manejo de error, nombres útiles, nada de secretos en parámetros, y que en
n8n 2.x el nodo Code ya no lee `process.env`).

---

## 9. Definición de "hecho"

- [ ] `https://n8n.neuromuscular.cloud` carga con certificado válido y cuenta de owner creada.
- [ ] Nº de workflows en el VPS == nº en Cloud.
- [ ] Cero nodos con *"credential not found"*.
- [ ] Cada webhook externo reapuntado y probado con un evento real.
- [ ] Workflows por reloj: desactivados en Cloud, activos en el VPS, una ejecución correcta
      observada.
- [ ] `bash scripts/backup.sh` corre y deja `backups/<fecha>/db.sql.gz`.
- [ ] `N8N_ENCRYPTION_KEY` guardada en el gestor de contraseñas.
- [ ] Cron de respaldo instalado.
- [ ] `python tools/n8n_setup.py status` responde desde tu máquina (harness conectado).

---

## 10. Lo que NO se migra (declarado por si duele después)

- **Credenciales**: imposible exportarlas desde Cloud. Se recrean a mano (paso 3).
- **Historial de ejecuciones**: se queda en Cloud. Exporta a mano lo que necesites como
  evidencia antes de cancelar.
- **URLs de webhook**: cambian de dominio sí o sí; no hay redirección desde Cloud.
- **Features Enterprise** (SSO, variables por entorno, git ops, log streaming): no están en
  la edición Community.
- **Uptime**: pasa a depender de tu VPS. Sin réplica, un reinicio del host = ventana de
  workflows caídos.

## 11. Si el volumen crece

El stack de este directorio corre en **modo regular** (un solo proceso ejecuta todo), que es
lo correcto para uso personal o de equipo chico. Si llegas a ejecuciones concurrentes pesadas
o webhooks con ráfagas, el siguiente escalón es **queue mode**: Redis + N worker containers
+ webhook processes. Es un cambio de compose, no una migración: la BD y las credenciales
siguen igual.

---

## Fuentes

- [Migrating from cloud to self-hosted — n8n Help Center](https://support.n8n.io/article/migrating-from-cloud-to-self-hosted)
- [CLI commands — n8n Docs](https://docs.n8n.io/hosting/cli-commands/)
- [Export and import workflows — n8n Docs](https://docs.n8n.io/workflows/export-import/)
- [n8n public API: authentication — n8n Docs](https://docs.n8n.io/api/authentication/)
- [Docker Compose — n8n Docs](https://docs.n8n.io/hosting/installation/server-setups/docker-compose/)
- [v2.0 breaking changes — n8n Docs](https://docs.n8n.io/release-notes/v20-breaking-changes)
- [Task runners — n8n Docs](https://docs.n8n.io/hosting/configuration/task-runners/)
- [n8nio/n8n en Docker Hub (versiones)](https://hub.docker.com/r/n8nio/n8n/tags)

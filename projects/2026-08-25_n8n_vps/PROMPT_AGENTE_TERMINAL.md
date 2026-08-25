# Brief para un agente de terminal (Warp AI u otro)

Pégale todo lo que está entre las líneas de guiones. Está escrito para que un agente que
vive en tu terminal continúe la instalación sin adivinar nada.

---

## Contexto

Estoy migrando mi n8n desde la nube a un VPS propio. Todo el código y los scripts ya existen;
tu trabajo es **ejecutarlos y diagnosticar**, no escribir nada nuevo salvo que un paso falle.

- **VPS:** `root@srv1314177` (Hostinger, Ubuntu, Docker ya instalado). Acceso por SSH con clave.
- **Dominio destino:** `n8n.neuromuscular.cloud` (DNS en Hostinger, nameservers `ns1/ns2.dns-parking.com`).
- **Instancia de origen:** `https://cristianub.app.n8n.cloud` (n8n Cloud).
- **Repo local:** el proyecto vive en `projects/2026-08-25_n8n_vps/` dentro del repo `harness`,
  rama `claude/n8n-vps-migration-da12m6`. Si no lo tengo clonado:
  `git clone -b claude/n8n-vps-migration-da12m6 https://github.com/crugalde/harness`
- **Mi máquina es Windows** (PowerShell). Los pasos del servidor se ejecutan por SSH.
- **Directorio en el VPS:** `/opt/n8n`

## Reglas que no puedes romper

1. **Nada destructivo sin preguntarme antes.** Ni `rm -rf`, ni borrar volúmenes de Docker, ni
   `docker system prune`, ni tocar nada fuera de `/opt/n8n`. Si un paso parece exigirlo, para y
   pregunta.
2. **Secretos nunca en pantalla.** La `N8N_ENCRYPTION_KEY` y la API key de n8n no se imprimen,
   no se copian a archivos de log ni se repiten en el chat. Cuando el bootstrap imprima la clave,
   dime solo *"la clave se imprimió, guárdala en tu gestor de contraseñas"*.
3. **No actives workflows.** El import los deja inactivos a propósito. Activarlos es decisión mía,
   uno a uno.
4. **Un paso a la vez.** Ejecuta, muéstrame la salida, dime si pasó o falló y qué significa.
   No encadenes pasos si el anterior no cumplió su criterio de éxito.
5. **No inventes valores.** Si te falta un dato (IP, correo, API key), pídemelo.

## Estado actual

- El stack todavía **no está levantado**.
- El registro DNS `n8n` (tipo A) **puede que aún no exista**. Verifícalo en el paso 1.
- La IP del VPS hay que confirmarla: hubo confusión entre la IP del servidor y la de mi PC.

---

## Paso 1 — Confirmar la IP del VPS y el DNS

```powershell
ssh root@srv1314177 "hostname -I; echo '---'; curl -s https://api.ipify.org; echo"
nslookup n8n.neuromuscular.cloud
```

**Criterio de éxito:** `hostname -I` y `api.ipify.org` devuelven la **misma** IP, y `nslookup`
resuelve `n8n.neuromuscular.cloud` a esa misma IP.

- Si las dos IP del VPS no coinciden → repórtamelo y detente (puede haber NAT o proxy).
- Si `nslookup` no resuelve → el registro A no existe todavía. Dime exactamente qué falta:
  *Tipo A · Nombre `n8n` · Apunta a `<IP>` · TTL 300*, en hPanel → Dominios →
  neuromuscular.cloud → Zona DNS. Detente hasta que yo lo cree y te avise.

## Paso 2 — Copiar el proyecto al VPS

Desde la raíz del repo, en PowerShell:

```powershell
cd projects\2026-08-25_n8n_vps\scripts\windows
.\n8n.ps1 sync
```

Si PowerShell bloquea la ejecución de scripts:
`powershell -ExecutionPolicy Bypass -File .\n8n.ps1 sync`

**Criterio de éxito:** termina sin error y `ssh root@srv1314177 "ls /opt/n8n/scripts"` lista los
`.sh` y `.py`.

## Paso 3 — Preflight

```powershell
.\n8n.ps1 preflight
```

**Criterio de éxito:** termina con `Resultado: listo` o solo con avisos (`!`).

- Cualquier línea con `✗` es bloqueante. Interprétala y propón el arreglo **antes** de seguir.
- Si dice *puerto 80 ocupado*: averigua qué escucha (`ss -lntp | grep ':80'`) y repórtamelo. No
  mates procesos por tu cuenta.
- Si dice *no resuelve*: vuelve al paso 1.

## Paso 4 — Levantar el stack

Necesitas mi correo para los avisos del certificado. Pídemelo si no te lo di.

```powershell
.\n8n.ps1 deploy -Email <MI-CORREO>
```

Esto corre `bootstrap_vps.sh` en el VPS: genera secretos, escribe `/opt/n8n/deploy/.env` en 600,
levanta n8n + Postgres + Caddy y espera a que n8n esté `healthy`.

**Criterio de éxito:** imprime `n8n healthy` y la URL.

- Si n8n no llega a healthy: `ssh root@srv1314177 "cd /opt/n8n/deploy && docker compose logs --tail 50 n8n"`.
- Si el certificado falla: `... docker compose logs --tail 50 caddy`. Casi siempre es DNS sin
  propagar o el puerto 80 cerrado. Repórtame el error, no cambies el Caddyfile.
- **La clave de cifrado que imprime: avísame que salió, no la copies a ningún lado.**

## Paso 5 — Verificar y esperar mi confirmación

```powershell
.\n8n.ps1 status
```

**Criterio de éxito:** los tres contenedores en `running` y el health de n8n responde `HTTP 200`.

Luego dime que abra `https://n8n.neuromuscular.cloud` y cree la cuenta de owner. **Espera a que
te confirme que la creé** antes de seguir: el import necesita que exista un usuario dueño.

## Paso 6 — Exportar los workflows desde n8n Cloud

Pídeme la API key (Settings → n8n API en la instancia de Cloud). Yo la pego en la variable;
no la guardes en ningún archivo.

```powershell
$env:N8N_API_KEY = "<la pego yo>"
.\n8n.ps1 export
```

**Criterio de éxito:** dice cuántos workflows bajó y deja `inventario_credenciales.md` y
`resumen.md` en `$HOME\n8n_export`.

- Si devuelve `403`: mi plan no incluye la API pública. Dímelo y detente; el export lo haré a
  mano desde la UI.
- Cuando termine, muéstrame el resumen: cuántos workflows, cuántas credenciales hay que recrear,
  cuántos webhooks y cuántos triggers por reloj.

## Paso 7 — Esperar a que yo recree las credenciales

n8n Cloud no exporta credenciales. Las creo yo a mano en el VPS, con los **mismos nombres** que
aparecen en `inventario_credenciales.md`. **No sigas hasta que te confirme que terminé.**

## Paso 8 — Subir e importar

```powershell
.\n8n.ps1 upload
.\n8n.ps1 import
```

**Criterio de éxito:** el import lista los workflows importados. Si `remap_credentials.py`
reporta credenciales sin equivalente, muéstrame esa lista: son las que quedaron con distinto
nombre y hay que reseleccionar a mano.

Recuérdame que los workflows quedan **inactivos** y que activarlos es decisión mía.

## Paso 9 — Respaldo automático

```powershell
ssh root@srv1314177
(crontab -l 2>/dev/null; echo "15 3 * * * /usr/bin/bash /opt/n8n/scripts/backup.sh >> /var/log/n8n-backup.log 2>&1") | crontab -
crontab -l
exit
```

**Criterio de éxito:** `crontab -l` muestra la línea.

Después corre un respaldo de prueba: `.\n8n.ps1 backup` y verifica que quedó
`/opt/n8n/deploy/backups/<fecha>/db.sql.gz` con tamaño razonable.

---

## Qué reportarme al final

1. URL del editor y si el certificado es válido.
2. Cuántos workflows quedaron importados vs. cuántos había en Cloud.
3. Credenciales sin reconectar, si quedó alguna.
4. Que la clave de cifrado fue mostrada y guardada.
5. Cualquier `✗` del preflight que quedó sin resolver.

## Lo que NO tienes que hacer

- Activar workflows.
- Reapuntar webhooks en servicios externos (Stripe, Telegram, etc.): eso lo hago yo.
- Cancelar el plan de n8n Cloud.
- Tocar el sitio que ya exista en el hosting de `neuromuscular.cloud`.

---
name: uc-library-fetcher
description: >-
  Automatiza el acceso a papers con paywall mediante las credenciales de la
  Universidad Católica de Chile (CAS UC). Usa Playwright para abrir un navegador,
  pasar por el proxy institucional e inyectar las credenciales de forma segura.
---

# UC Library Fetcher (CAS)

Este skill permite al agente ayudar al usuario a evadir paywalls de revistas científicas (Elsevier, Springer, Wiley, etc.) automatizando el inicio de sesión a través del sistema Single Sign-On (CAS) de la Pontificia Universidad Católica de Chile usando sus credenciales institucionales.

## Requisitos Previos

1.  **`uv`**: Debes asegurarte de que `uv` esté instalado en el sistema.
2.  **Dependencias**: El script utiliza `playwright`. Se debe ejecutar con el flag `--with playwright` si no está en un entorno virtual global. También requiere instalar los navegadores de playwright (`playwright install chromium`).
3.  **Variables de Entorno**: El script requiere `UC_USER` y `UC_PASSWORD`. El script carga automáticamente el `.env` local desde `~/.config/harness/.env` (override con `HARNESS_ENV_FILE`).

> [!WARNING]
> **Seguridad de Credenciales**
> Si el agente nota que faltan las credenciales, **NUNCA** debe pedirle al usuario que las escriba en el chat. Debe entregarle los siguientes comandos al usuario para que las guarde localmente en su `.env` (fuera de iCloud):
> 
> ```bash
> ENV_FILE="${HARNESS_ENV_FILE:-$HOME/.config/harness/.env}"
> mkdir -p "$(dirname "$ENV_FILE")" && touch "$ENV_FILE" && chmod 600 "$ENV_FILE"
> printf "Ingresa tu usuario UC: " && read user && echo "UC_USER=$user" >> "$ENV_FILE"
> printf "Ingresa tu clave UC (oculta): " && read -s key && echo && echo "UC_PASSWORD=$key" >> "$ENV_FILE"
> ```

## Uso del CLI

El script se encuentra en `scripts/fetch_uc_paper.py`. Recibe un DOI (ej. `10.1056/NEJMoa1800410`) o una URL completa, y una ruta de salida donde el usuario deberá guardar el PDF.

```bash
uv run --with playwright scripts/fetch_uc_paper.py "10.1016/j.neuro.2023.01.001" "/ruta/al/proyecto/paper_descargado.pdf"
```

## Flujo de Trabajo

1. El script carga `~/.config/harness/.env` vía `tools/env_loader.py` y lee `UC_USER` /
   `UC_PASSWORD`. **No basta con que el `.env` exista**: si el script no lo carga, `os.getenv`
   devuelve `None` aunque las credenciales estén guardadas.
2. Abre Chromium con **`headless=False`** — es decir, **la ventana del navegador es visible**.
   Es deliberado: si las heurísticas no encuentran el PDF, el usuario puede terminar la
   descarga a mano en esa misma ventana.
3. Resuelve el DOI con el navegador real (doi.org responde 403 a clientes automatizados) y
   reescribe el dominio al formato EZproxy de la UC
   (`www.nejm.org` → `www-nejm-org.pucdechile.idm.oclc.org`).
4. Detecta el formulario CAS e inyecta las credenciales.
5. Busca el botón de PDF con una lista de selectores comunes e intercepta la descarga.
6. **Si no lo encuentra, deja la ventana abierta 2 minutos** para que el usuario descargue
   manualmente a la ruta indicada, y luego cierra. No es un fallo silencioso: hay que estar
   presente frente al computador.

> **Requisito no obvio:** además de la librería, hay que instalar el navegador una vez:
> `uv run --with playwright playwright install chromium` (~150 MB). Sin eso, el script falla
> al lanzar el browser aunque las credenciales estén correctas.

### Comportamiento por editorial (probado 06-08-2026)

| Editorial | Resultado | Detalle |
|---|---|---|
| **Springer** (`link.springer.com`) | **Automático** | Selector `a:has-text('Download PDF')` acierta al primer intento |
| **Elsevier** (`linkinghub.elsevier.com` → ScienceDirect) | **Falla la descarga** | Encuentra tres selectores de PDF pero las tres descargas expiran a los 15 s. ScienceDirect sirve el PDF tras una página intermedia con protección antibot, no como descarga directa |

Cómo distinguir un fallo de login de un fallo de heurística, leyendo el log:

- `[+] Login detectado. Inyectando credenciales` seguido **inmediatamente** de
  `[!] No se detectó login o ya estaba autenticado` → el envío del formulario **falló**
  (el selector del botón submit no coincidió o `networkidle` expiró). Pasó con Elsevier.
- `[+] Login detectado. Inyectando credenciales` y luego directo a `[*] Analizando la página`
  → login correcto. Pasó con Springer.

**Para Elsevier/ScienceDirect, usa el fallback manual**: deja que el script abra la ventana ya
autenticada y descarga el PDF a mano a la ruta que imprime. El proxy sí funciona; lo que no
funciona es la automatización del último clic.

### Límites conocidos

- Requiere sesión interactiva y una pantalla: no sirve en cron ni en un agente desatendido.
- Si la UC exige 2FA, el script no puede completarlo solo.
- `uv run --with playwright` instala siempre la versión más nueva de Playwright, que puede
  pedir un Chromium que no tienes. Si el error dice `Executable doesn't exist at ...chromium-<n>`,
  corre `uv run --with playwright playwright install chromium` (~95 MB) y reintenta.

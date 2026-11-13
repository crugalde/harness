---
name: acceso-uc
description: Descarga el PDF de un paper tras paywall usando el proxy institucional de la Pontificia Universidad Católica de Chile (CAS UC) con Playwright. Úsala solo cuando un estudio necesario no está en acceso abierto ni en la biblioteca local, y siempre con confirmación previa del usuario.
---

# Acceso a texto completo vía proxy UC

Script: `scripts/fetch_uc_paper.py`. Es un **Gate de acción**: usa credenciales
institucionales, así que el orquestador pide confirmación explícita por cada lote de DOIs.

## Requisitos

- `pip install playwright && python3 -m playwright install chromium`
- `UC_USER` y `UC_PASSWORD` en `~/.config/harness/.env` (o la ruta en `HARNESS_ENV_FILE`).

Si faltan las credenciales, **nunca** las pidas por chat. Entrega al usuario estos comandos
para que las guarde localmente (fuera de iCloud):

```bash
ENV_FILE="${HARNESS_ENV_FILE:-$HOME/.config/harness/.env}"
mkdir -p "$(dirname "$ENV_FILE")" && touch "$ENV_FILE" && chmod 600 "$ENV_FILE"
printf "Usuario UC: " && read user && echo "UC_USER=$user" >> "$ENV_FILE"
printf "Clave UC (oculta): " && read -s clave && echo && echo "UC_PASSWORD=$clave" >> "$ENV_FILE"
```

## Uso

```bash
python3 scripts/fetch_uc_paper.py "10.1056/NEJMoa1800410" workspace/papers_locales/autor-anio.pdf
```

- Abre un navegador **visible** a propósito: si no encuentra el botón del PDF, el usuario
  termina la descarga a mano en esa ventana (2 minutos de margen).
- Funciona en el computador del usuario, no en entornos sin pantalla.
- Uso personal académico, dentro de las condiciones de la licencia institucional.

Tras descargar, el PDF queda en `workspace/papers_locales/` (no se versiona en git) y el
`resumidor` puede trabajarlo.

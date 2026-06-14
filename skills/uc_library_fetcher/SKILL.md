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

## Flujo de Trabajo (Automatización Completa)

1. El script correrá en modo invisible (`headless=True`) utilizando la librería de Playwright de forma asincrónica.
2. Tras pasar el login CAS institucional de la UC en segundo plano, el script utilizará heurísticas avanzadas para escanear el sitio de la revista médica.
3. Localizará e interceptará los botones de descarga de PDF comunes.
4. El PDF se guardará localmente en la ruta designada de forma 100% silenciosa.
5. Si las heurísticas fallan (sitio no estándar o la UC exige validación 2FA externa), el script devolverá un código de error, momento en el cual el agente debe comunicar la limitación técnica al usuario.

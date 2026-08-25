#!/usr/bin/env python3
"""export_cloud.py — Exporta los workflows de n8n (Cloud o self-hosted) vía API pública.

Baja todos los workflows a JSON, uno por archivo, en el formato que come
`n8n import:workflow --separate`, y genera dos informes que son el verdadero
trabajo de la migración:

  - `inventario_credenciales.md` — qué credencial usa cada nodo. n8n Cloud **no**
    permite exportar credenciales (se cifran con una clave que no controlas), así
    que hay que recrearlas a mano en el VPS: esta es la checklist.
  - `resumen.md` — workflows activos, triggers de webhook (hay que reapuntar el
    sistema externo) y triggers de schedule (hay que reactivarlos y evitar que
    corran en dos instancias a la vez).

Sin dependencias externas (urllib de la stdlib).

Uso:
  export N8N_API_KEY=...        # Settings → n8n API → Create an API key
  python scripts/export_cloud.py --base-url https://TU-SUB.app.n8n.cloud --out export/
  python scripts/export_cloud.py --base-url https://TU-SUB.app.n8n.cloud --out export/ \
      --new-domain n8n.tudominio.cl          # añade la tabla de webhooks viejo → nuevo

La API key también se lee de ~/.config/harness/.env (N8N_API_KEY o N8N_CLOUD_API_KEY).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# Reutiliza el cargador de .env del harness si el script vive dentro del repo.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
    from env_loader import load_env

    load_env()
except Exception:  # noqa: BLE001 — también debe correr copiado fuera del repo
    pass

TIMEOUT = 30
PAGE_SIZE = 100

# Tipos de trigger que exponen una URL pública (hay que reapuntar el emisor externo).
WEBHOOK_TRIGGERS = (
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.formTrigger",
    "@n8n/n8n-nodes-langchain.chatTrigger",
)
# Tipos de trigger que corren solos por reloj (riesgo de ejecución duplicada).
SCHEDULE_TRIGGERS = (
    "n8n-nodes-base.scheduleTrigger",
    "n8n-nodes-base.cron",
    "n8n-nodes-base.interval",
)


class ApiError(RuntimeError):
    """Error de la API de n8n con mensaje accionable."""


def _request(base_url: str, path: str, api_key: str, params: dict[str, Any] | None = None) -> dict:
    """GET a la API pública de n8n. Devuelve el JSON decodificado."""
    qs = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{base_url.rstrip('/')}/api/v1{path}{qs}"
    req = urllib.request.Request(
        url,
        headers={"X-N8N-API-KEY": api_key, "accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 401:
            raise ApiError(
                "401: API key inválida o expirada. Regenérala en Settings → n8n API."
            ) from exc
        if exc.code == 403:
            raise ApiError(
                "403: la API pública no está disponible en tu plan (no existe en el trial) "
                "o está deshabilitada. Alternativa: descargar cada workflow desde la UI "
                "(⋯ → Download) y saltarse este script."
            ) from exc
        if exc.code == 404:
            raise ApiError(
                f"404 en {url}. Revisa --base-url: debe ser la raíz de la instancia "
                "(ej. https://tu-sub.app.n8n.cloud), sin /api/v1 al final."
            ) from exc
        raise ApiError(f"HTTP {exc.code} en {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"No se pudo conectar a {url}: {exc.reason}") from exc


def fetch_workflows(base_url: str, api_key: str) -> list[dict]:
    """Descarga todos los workflows paginando con el cursor de la API."""
    out: list[dict] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        payload = _request(base_url, "/workflows", api_key, params)
        batch = payload.get("data", [])
        out.extend(batch)
        cursor = payload.get("nextCursor")
        print(f"  … {len(out)} workflows", file=sys.stderr)
        if not cursor or not batch:
            break
    return out


def slugify(name: str, fallback: str = "workflow") -> str:
    """Nombre de archivo seguro a partir del nombre del workflow."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return slug[:60] or fallback


def analyze(workflows: list[dict]) -> dict[str, Any]:
    """Extrae credenciales, triggers y rutas de webhook de los workflows."""
    creds: dict[tuple[str, str], dict[str, Any]] = {}
    webhooks: list[dict[str, str]] = []
    schedules: list[dict[str, str]] = []
    for wf in workflows:
        wf_name = wf.get("name", "(sin nombre)")
        for node in wf.get("nodes", []) or []:
            node_type = node.get("type", "")
            for cred_type, ref in (node.get("credentials") or {}).items():
                ref = ref if isinstance(ref, dict) else {}
                key = (cred_type, ref.get("name", "(sin nombre)"))
                entry = creds.setdefault(
                    key,
                    {"type": cred_type, "name": key[1], "old_id": ref.get("id"), "usos": []},
                )
                entry["usos"].append(f"{wf_name} → {node.get('name', node_type)}")
            if node_type in WEBHOOK_TRIGGERS:
                params = node.get("parameters") or {}
                webhooks.append(
                    {
                        "workflow": wf_name,
                        "nodo": node.get("name", node_type),
                        "path": str(params.get("path", "")) or f"(webhookId {node.get('webhookId', '?')})",
                        "metodo": str(params.get("httpMethod", "GET")),
                    }
                )
            if node_type in SCHEDULE_TRIGGERS:
                schedules.append({"workflow": wf_name, "nodo": node.get("name", node_type)})
    return {"credenciales": list(creds.values()), "webhooks": webhooks, "schedules": schedules}


def write_reports(out: Path, workflows: list[dict], info: dict, base_url: str, new_domain: str | None) -> None:
    """Escribe inventario_credenciales.md y resumen.md."""
    activos = [w for w in workflows if w.get("active")]

    lines = ["# Inventario de credenciales (recrear a mano en el VPS)", ""]
    lines += [
        "n8n Cloud no exporta credenciales: se cifran con una clave que no controlas.",
        "Crea cada una en el VPS **con el mismo nombre exacto** (así `remap_credentials.py`",
        "puede reapuntar los workflows automáticamente).",
        "",
        "| Tipo | Nombre | ID en origen | Nº de usos |",
        "|------|--------|--------------|------------|",
    ]
    for c in sorted(info["credenciales"], key=lambda x: (x["type"], x["name"])):
        lines.append(f"| `{c['type']}` | {c['name']} | `{c['old_id']}` | {len(c['usos'])} |")
    lines += ["", "## Dónde se usa cada una", ""]
    for c in sorted(info["credenciales"], key=lambda x: (x["type"], x["name"])):
        lines.append(f"- **{c['name']}** (`{c['type']}`)")
        lines += [f"  - {u}" for u in c["usos"]]
    (out / "inventario_credenciales.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    old_host = base_url.rstrip("/")
    new_host = f"https://{new_domain}" if new_domain else "https://TU-DOMINIO"
    lines = [
        "# Resumen de la exportación",
        "",
        f"- Origen: `{old_host}`",
        f"- Workflows exportados: **{len(workflows)}**",
        f"- Activos en el origen: **{len(activos)}**",
        f"- Credenciales distintas a recrear: **{len(info['credenciales'])}**",
        "",
        "## Webhooks (hay que reapuntar el sistema externo)",
        "",
    ]
    if info["webhooks"]:
        lines += ["| Workflow | Nodo | Método | URL antigua | URL nueva |", "|---|---|---|---|---|"]
        for w in info["webhooks"]:
            lines.append(
                f"| {w['workflow']} | {w['nodo']} | {w['metodo']} | "
                f"`{old_host}/webhook/{w['path']}` | `{new_host}/webhook/{w['path']}` |"
            )
    else:
        lines.append("_Ninguno._")
    lines += ["", "## Triggers por reloj (desactívalos en el origen antes de activarlos aquí)", ""]
    if info["schedules"]:
        lines += [f"- {s['workflow']} → {s['nodo']}" for s in info["schedules"]]
    else:
        lines.append("_Ninguno._")
    lines += [
        "",
        "## Workflows activos en el origen",
        "",
        *[f"- [ ] {w.get('name', '(sin nombre)')} (`{w.get('id')}`)" for w in activos],
        "",
        "> El import por CLI **no** activa workflows: quedan inactivos hasta que los",
        "> actives en la UI del VPS, uno a uno.",
    ]
    (out / "resumen.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Exporta workflows de n8n vía API pública.")
    ap.add_argument("--base-url", required=True, help="Raíz de la instancia (https://tu-sub.app.n8n.cloud)")
    ap.add_argument("--api-key", default=None, help="API key; por defecto N8N_API_KEY del entorno/.env")
    ap.add_argument("--out", default="export", help="Directorio de salida (default: export/)")
    ap.add_argument("--new-domain", default=None, help="Dominio del VPS, para la tabla de webhooks")
    args = ap.parse_args()

    api_key = args.api_key or os.environ.get("N8N_API_KEY") or os.environ.get("N8N_CLOUD_API_KEY")
    if not api_key:
        print(
            "ERROR: falta la API key. Créala en Settings → n8n API y expórtala:\n"
            "  export N8N_API_KEY=...      (o guárdala en ~/.config/harness/.env)",
            file=sys.stderr,
        )
        return 2

    out = Path(args.out).expanduser().resolve()
    wf_dir = out / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)

    print(f"Descargando workflows de {args.base_url} …", file=sys.stderr)
    try:
        workflows = fetch_workflows(args.base_url, api_key)
    except ApiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not workflows:
        print("No se encontró ningún workflow. ¿API key de la instancia correcta?", file=sys.stderr)
        return 1

    seen: set[str] = set()
    for wf in workflows:
        stem = f"{slugify(wf.get('name', ''))}__{wf.get('id', 'sin_id')}"
        while stem in seen:  # colisión improbable, pero no pisamos archivos
            stem += "_x"
        seen.add(stem)
        path = wf_dir / f"{stem}.json"
        path.write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)

    info = analyze(workflows)
    write_reports(out, workflows, info, args.base_url, args.new_domain)

    print(
        f"\nListo: {len(workflows)} workflows en {wf_dir}\n"
        f"  - {out / 'inventario_credenciales.md'}  ({len(info['credenciales'])} credenciales a recrear)\n"
        f"  - {out / 'resumen.md'}  ({len(info['webhooks'])} webhooks, {len(info['schedules'])} schedules)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

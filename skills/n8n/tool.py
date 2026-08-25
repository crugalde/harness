"""Skill n8n — cliente de la API pública de n8n self-hosted (diseño y operación de workflows).

Sin dependencias externas: usa urllib de la stdlib. Lee credenciales del entorno
(N8N_BASE_URL, N8N_API_KEY), cargadas desde ~/.config/harness/.env por env_loader.

Expone register_skill(reg) para que tools/registry.py la descubra. Las funciones
públicas (ping/list_workflows/...) las reutiliza el wizard tools/n8n_setup.py, así el
cliente HTTP vive en un único lugar.

Frontera de seguridad (AGENTS.md §7): leer workflows y ejecuciones es libre; crear,
modificar o (des)activar un workflow tiene efecto externo —dispara automatizaciones
reales— y va en GATED_TOOLS de loop.py, exigiendo confirmación humana por turno.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

_TIMEOUT = 20
# Campos que la API rechaza o ignora al crear/actualizar: se descartan antes de enviar.
_READ_ONLY = {"id", "active", "createdAt", "updatedAt", "versionId", "tags", "meta",
              "shared", "homeProject", "triggerCount", "isArchived"}
_MAX_CHARS = 6000  # tope de salida por llamada; el modelo no necesita 200 KB de JSON


# --------------------------------------------------------------------------- #
# Cliente HTTP (única fuente de verdad; lo reutiliza el wizard)
# --------------------------------------------------------------------------- #
def config() -> tuple[str, str]:
    """Devuelve (base_url, api_key) desde el entorno; base sin barra final."""
    base = os.environ.get("N8N_BASE_URL", "").strip().rstrip("/")
    key = os.environ.get("N8N_API_KEY", "").strip()
    return base, key


def request(method: str, path: str, payload: dict | None = None,
            *, params: dict | None = None, base: str | None = None,
            key: str | None = None, timeout: int = _TIMEOUT):
    """Llama a la API pública de n8n. Lanza RuntimeError con causa legible si falla.

    base/key explícitos permiten al wizard validar credenciales que aún no están
    en el entorno. Si se omiten, se leen de config().
    """
    cfg_base, cfg_key = config()
    base = (base or cfg_base).rstrip("/")
    key = key or cfg_key
    if not base or not key:
        raise RuntimeError(
            "Faltan credenciales de n8n. Ejecuta el wizard:\n"
            "  python tools/n8n_setup.py\n"
            "o define N8N_BASE_URL y N8N_API_KEY en ~/.config/harness/.env"
        )
    qs = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{base}/api/v1/{path.lstrip('/')}{qs}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-N8N-API-KEY", key)
    req.add_header("accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        if e.code == 401:
            raise RuntimeError("n8n 401: API key inválida o expirada. Regenérala en "
                               "Settings → n8n API y corre el wizard.") from e
        if e.code == 403:
            raise RuntimeError("n8n 403: la API pública está deshabilitada en esa "
                               "instancia (N8N_PUBLIC_API_DISABLED) o el plan no la "
                               "incluye.") from e
        raise RuntimeError(f"n8n HTTP {e.code} en {path}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"No se pudo conectar a {base} ({e.reason}). "
                           "¿Está levantado el stack y el dominio resuelve?") from e
    return json.loads(body) if body.strip() else {}


def ping(*, base: str | None = None, key: str | None = None) -> dict:
    """GET /workflows?limit=1 — verifica conectividad y autenticación."""
    return request("GET", "workflows", params={"limit": 1}, base=base, key=key)


def list_workflows(*, active: bool | None = None, limit: int = 100,
                   base: str | None = None, key: str | None = None) -> list[dict]:
    """Todos los workflows, paginando con el cursor de la API."""
    out: list[dict] = []
    cursor: str | None = None
    while True:
        params: dict[str, object] = {"limit": min(limit, 100)}
        if active is not None:
            params["active"] = "true" if active else "false"
        if cursor:
            params["cursor"] = cursor
        payload = request("GET", "workflows", params=params, base=base, key=key)
        out.extend(payload.get("data", []))
        cursor = payload.get("nextCursor")
        if not cursor or len(out) >= limit:
            break
    return out[:limit]


def get_workflow(wf_id: str) -> dict:
    """GET /workflows/{id} — el JSON completo del workflow."""
    return request("GET", f"workflows/{wf_id}")


def _clean(wf: dict) -> dict:
    """Quita los campos de solo lectura antes de crear/actualizar."""
    return {k: v for k, v in wf.items() if k not in _READ_ONLY}


# --------------------------------------------------------------------------- #
# Tools (firma: dict -> str)
# --------------------------------------------------------------------------- #
def n8n_workflows(args: dict) -> str:
    """Lista workflows con su id, nombre, estado y triggers."""
    active = args.get("active")
    contains = (args.get("name_contains") or "").lower()
    wfs = list_workflows(active=active, limit=int(args.get("limit", 100)))
    if contains:
        wfs = [w for w in wfs if contains in (w.get("name", "").lower())]
    if not wfs:
        return "Sin workflows que cumplan el filtro."
    lines = [f"{len(wfs)} workflow(s):"]
    for w in wfs:
        trig = [n.get("type", "").split(".")[-1] for n in (w.get("nodes") or [])
                if "rigger" in n.get("type", "") or n.get("type", "").endswith("webhook")]
        estado = "activo" if w.get("active") else "inactivo"
        lines.append(f"- [{w.get('id')}] {w.get('name')} — {estado}"
                     + (f" · triggers: {', '.join(sorted(set(trig)))}" if trig else ""))
    return "\n".join(lines)[:_MAX_CHARS]


def n8n_workflow_get(args: dict) -> str:
    """Devuelve un workflow: resumen de nodos por defecto, JSON completo con full=true."""
    wf_id = args.get("id")
    if not wf_id:
        return "ERROR: falta 'id'."
    wf = get_workflow(str(wf_id))
    if args.get("full"):
        body = json.dumps(_clean(wf), ensure_ascii=False, indent=2)
        return body[:_MAX_CHARS] + ("\n… (truncado)" if len(body) > _MAX_CHARS else "")
    nodes = wf.get("nodes") or []
    lines = [f"{wf.get('name')} [{wf.get('id')}] — "
             f"{'activo' if wf.get('active') else 'inactivo'} · {len(nodes)} nodos"]
    for n in nodes:
        creds = ", ".join(f"{t}:{(r or {}).get('name', '?')}"
                          for t, r in (n.get("credentials") or {}).items())
        lines.append(f"- {n.get('name')} ({n.get('type')})" + (f" · cred: {creds}" if creds else ""))
    conns = wf.get("connections") or {}
    lines.append(f"conexiones desde {len(conns)} nodo(s). Usa full=true para el JSON completo.")
    return "\n".join(lines)[:_MAX_CHARS]


def n8n_executions(args: dict) -> str:
    """Últimas ejecuciones, para depurar por qué falló un workflow."""
    params: dict[str, object] = {"limit": int(args.get("limit", 10))}
    if args.get("workflow_id"):
        params["workflowId"] = str(args["workflow_id"])
    if args.get("status"):
        params["status"] = args["status"]          # error | success | waiting
    payload = request("GET", "executions", params=params)
    rows = payload.get("data", [])
    if not rows:
        return "Sin ejecuciones para ese filtro."
    lines = [f"{len(rows)} ejecución(es):"]
    for e in rows:
        lines.append(f"- [{e.get('id')}] wf {e.get('workflowId')} · {e.get('status')} · "
                     f"inicio {e.get('startedAt')} · modo {e.get('mode')}")
    return "\n".join(lines)[:_MAX_CHARS]


def n8n_workflow_create(args: dict) -> str:
    """Crea un workflow. EFECTO EXTERNO: gated. Nace inactivo a propósito."""
    name = args.get("name")
    nodes = args.get("nodes")
    if not name or nodes is None:
        return "ERROR: 'name' y 'nodes' son obligatorios."
    body = _clean({
        "name": name,
        "nodes": nodes,
        "connections": args.get("connections") or {},
        "settings": args.get("settings") or {},
    })
    wf = request("POST", "workflows", body)
    return (f"Workflow creado: [{wf.get('id')}] {wf.get('name')} (inactivo).\n"
            f"Revísalo en el editor antes de activarlo.")


def n8n_workflow_update(args: dict) -> str:
    """Actualiza un workflow existente. EFECTO EXTERNO: gated."""
    wf_id = args.get("id")
    if not wf_id:
        return "ERROR: falta 'id'."
    actual = get_workflow(str(wf_id))
    body = _clean(actual)
    for campo in ("name", "nodes", "connections", "settings"):
        if args.get(campo) is not None:
            body[campo] = args[campo]
    wf = request("PUT", f"workflows/{wf_id}", body)
    return f"Workflow actualizado: [{wf.get('id')}] {wf.get('name')}."


def n8n_workflow_activate(args: dict) -> str:
    """Activa o desactiva un workflow. EFECTO EXTERNO: gated."""
    wf_id = args.get("id")
    if not wf_id:
        return "ERROR: falta 'id'."
    activar = bool(args.get("active", True))
    accion = "activate" if activar else "deactivate"
    wf = request("POST", f"workflows/{wf_id}/{accion}")
    estado = "activo" if wf.get("active") else "inactivo"
    return f"Workflow [{wf.get('id')}] {wf.get('name')} quedó {estado}."


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #
def register_skill(reg) -> None:
    reg.register(
        "n8n_workflows",
        "Lista los workflows de n8n (id, nombre, activo, triggers). Solo lectura.",
        {"type": "object",
         "properties": {"active": {"type": "boolean"},
                        "name_contains": {"type": "string"},
                        "limit": {"type": "integer"}}},
        n8n_workflows,
    )
    reg.register(
        "n8n_workflow_get",
        "Lee un workflow de n8n: resumen de nodos, o JSON completo con full=true. Solo lectura.",
        {"type": "object",
         "properties": {"id": {"type": "string"}, "full": {"type": "boolean"}},
         "required": ["id"]},
        n8n_workflow_get,
    )
    reg.register(
        "n8n_executions",
        "Últimas ejecuciones de n8n (para depurar fallos). Solo lectura.",
        {"type": "object",
         "properties": {"workflow_id": {"type": "string"},
                        "status": {"type": "string", "description": "error | success | waiting"},
                        "limit": {"type": "integer"}}},
        n8n_executions,
    )
    reg.register(
        "n8n_workflow_create",
        "Crea un workflow en n8n (nace inactivo). EFECTO EXTERNO: gated.",
        {"type": "object",
         "properties": {"name": {"type": "string"},
                        "nodes": {"type": "array", "items": {"type": "object"}},
                        "connections": {"type": "object"},
                        "settings": {"type": "object"}},
         "required": ["name", "nodes"]},
        n8n_workflow_create,
    )
    reg.register(
        "n8n_workflow_update",
        "Modifica un workflow existente de n8n. EFECTO EXTERNO: gated.",
        {"type": "object",
         "properties": {"id": {"type": "string"},
                        "name": {"type": "string"},
                        "nodes": {"type": "array", "items": {"type": "object"}},
                        "connections": {"type": "object"},
                        "settings": {"type": "object"}},
         "required": ["id"]},
        n8n_workflow_update,
    )
    reg.register(
        "n8n_workflow_activate",
        "Activa o desactiva un workflow de n8n. EFECTO EXTERNO: gated.",
        {"type": "object",
         "properties": {"id": {"type": "string"}, "active": {"type": "boolean"}},
         "required": ["id"]},
        n8n_workflow_activate,
    )

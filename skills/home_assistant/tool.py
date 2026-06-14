"""Skill home_assistant — cliente REST de Home Assistant (subagente `home`).

Sin dependencias externas: usa urllib de la stdlib. Lee credenciales del entorno
(HA_BASE_URL, HA_TOKEN), cargadas desde ~/.config/harness/.env por env_loader.

Expone register_skill(reg) para que tools/registry.py la descubra. Las funciones
públicas (ping/states/services/call_service) también las reutiliza el wizard
tools/ha_setup.py, así el cliente HTTP vive en un único lugar.

Frontera de seguridad (AGENTS.md §7): la lectura de estados es libre; cualquier
llamada que cambie estado (ha_call_service) tiene efecto externo y va en
GATED_TOOLS de loop.py, exigiendo confirmación humana por turno.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

# Timeout corto: HA está en la LAN; si no responde, falla rápido con mensaje claro.
_TIMEOUT = 15


# --------------------------------------------------------------------------- #
# Cliente HTTP (única fuente de verdad; lo reutiliza el wizard)
# --------------------------------------------------------------------------- #
def config() -> tuple[str, str]:
    """Devuelve (base_url, token) desde el entorno; base sin barra final."""
    base = os.environ.get("HA_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("HA_TOKEN", "").strip()
    return base, token


def request(method: str, path: str, payload: dict | None = None,
            *, base: str | None = None, token: str | None = None,
            timeout: int = _TIMEOUT):
    """Llama a la API REST de HA. Lanza RuntimeError con causa legible si falla.

    base/token explícitos permiten al wizard validar credenciales que aún no
    están en el entorno. Si se omiten, se leen de config().
    """
    cfg_base, cfg_token = config()
    base = (base or cfg_base).rstrip("/")
    token = token or cfg_token
    if not base or not token:
        raise RuntimeError(
            "Faltan credenciales de Home Assistant. Ejecuta el wizard:\n"
            "  python tools/ha_setup.py\n"
            "o define HA_BASE_URL y HA_TOKEN en ~/.config/harness/.env"
        )
    url = f"{base}/api/{path.lstrip('/')}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        if e.code == 401:
            raise RuntimeError("HA 401: token inválido o expirado. Regenera el "
                               "Long-Lived Access Token y corre el wizard.") from e
        raise RuntimeError(f"HA HTTP {e.code} en {path}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"No se pudo conectar a {base} ({e.reason}). "
                           "¿Está encendido HA y estás en la misma red?") from e
    return json.loads(body) if body.strip() else {}


def ping(*, base: str | None = None, token: str | None = None) -> dict:
    """GET /api/ — verifica conectividad y autenticación. {'message': 'API running.'}"""
    return request("GET", "/", base=base, token=token)


def states(entity_id: str | None = None):
    """GET /api/states[/<entity_id>]."""
    return request("GET", f"states/{entity_id}" if entity_id else "states")


def services():
    """GET /api/services — dominios y servicios disponibles."""
    return request("GET", "services")


def call_service(domain: str, service: str, data: dict | None = None):
    """POST /api/services/<domain>/<service> — EFECTO EXTERNO (gated)."""
    return request("POST", f"services/{domain}/{service}", payload=data or {})


# --------------------------------------------------------------------------- #
# Herramientas registradas (devuelven texto para el ToolRegistry)
# --------------------------------------------------------------------------- #
def ha_states(args: dict) -> str:
    """Lee estados. Filtra por entity_id exacto o por domain (p.ej. 'light')."""
    entity_id = (args.get("entity_id") or "").strip()
    domain = (args.get("domain") or "").strip()
    try:
        if entity_id:
            st = states(entity_id)
            return _fmt_state(st)
        data = states()
    except RuntimeError as e:
        return f"ERROR: {e}"
    if domain:
        data = [s for s in data if s.get("entity_id", "").startswith(f"{domain}.")]
    if not data:
        return "Sin entidades para ese filtro."
    # Resumen compacto por dominio para no inundar el contexto.
    by_domain: dict[str, list[str]] = {}
    for s in data:
        eid = s.get("entity_id", "")
        dom = eid.split(".", 1)[0] if "." in eid else "otros"
        by_domain.setdefault(dom, []).append(f"{eid} = {s.get('state', '?')}")
    out = []
    for dom in sorted(by_domain):
        lines = by_domain[dom]
        out.append(f"## {dom} ({len(lines)})\n" + "\n".join(lines))
    return "\n\n".join(out)


def ha_services(args: dict) -> str:
    """Lista servicios; opcionalmente filtra por domain."""
    domain = (args.get("domain") or "").strip()
    try:
        data = services()
    except RuntimeError as e:
        return f"ERROR: {e}"
    out = []
    for block in data:
        dom = block.get("domain", "")
        if domain and dom != domain:
            continue
        svcs = sorted(block.get("services", {}).keys())
        out.append(f"{dom}: {', '.join(svcs)}")
    return "\n".join(out) or "Sin servicios para ese filtro."


def ha_call_service(args: dict) -> str:
    """Ejecuta un servicio (encender, apagar, etc.). EFECTO EXTERNO (gated).

    Nota de campo (instalación de Cristian, 2026-06-14): las luces son entidades
    'switch' (interruptores Zigbee vía Zigbee2MQTT), NO hay dominio 'light'. Y el
    REST de HA suele responder [] ("sin cambios") aunque la acción sí se aplique;
    por eso, si hay entity_id, releemos el estado real y lo reportamos (D4).
    """
    domain = (args.get("domain") or "").strip()
    service = (args.get("service") or "").strip()
    if not domain or not service:
        return "ERROR: faltan 'domain' y 'service' (p.ej. domain='switch', service='turn_off')."
    data = args.get("data") or {}
    entity_id = args.get("entity_id")
    if entity_id and "entity_id" not in data:
        data = {**data, "entity_id": entity_id}
    try:
        result = call_service(domain, service, data)
    except RuntimeError as e:
        return f"ERROR: {e}"
    # Verificación por re-lectura: el endpoint REST puede no listar cambios aunque
    # el estado físico sí cambie. Releemos la entidad objetivo para reportar la verdad.
    verify = ""
    eid = data.get("entity_id")
    if isinstance(eid, str):
        try:
            verify = f" Estado verificado: {eid} = {states(eid).get('state', '?')}."
        except RuntimeError:
            pass
    changed = [s.get("entity_id") for s in result] if isinstance(result, list) else []
    extra = (f" Afectadas: {', '.join(filter(None, changed))}" if changed else "")
    return f"OK: {domain}.{service} ejecutado.{verify}{extra}"


# --------------------------------------------------------------------------- #
# Luces: en esta instalación son entidades 'switch' (Zigbee2MQTT), no 'light'.
# Distinguimos luces de enchufes/entidades de bridge por entity_id + friendly_name.
# --------------------------------------------------------------------------- #
# Estrategia de EXCLUSIÓN: en esta instalación todo 'switch' controlable es una luz,
# salvo enchufes, el bridge de Zigbee2MQTT y sub-entidades de diagnóstico. Es más
# fiable que buscar "luz" en el nombre, porque varios interruptores Zigbee tienen
# nombres sin esa palabra (p.ej. "cocina...", "pasillo..."). Si algún día agregas un
# switch que NO sea luz (bomba, ventilador), añádelo a _NOT_LIGHT o usa 'keep'.
_NOT_LIGHT = ("enchufe", "network_indicator", "outlet_control", "permit_join",
              "zigbee2mqtt_bridge", "power_on_behavior", "backlight")


def _is_light(entity_id: str, friendly_name: str) -> bool:
    if not entity_id.startswith("switch."):
        return False
    blob = f"{entity_id} {friendly_name}".lower()
    return not any(n in blob for n in _NOT_LIGHT)


def lights() -> list[dict]:
    """Estados de las entidades clasificadas como luz (heurística por nombre)."""
    return [s for s in states()
            if _is_light(s.get("entity_id", ""),
                         (s.get("attributes") or {}).get("friendly_name", ""))]


def ha_lights(args: dict) -> str:
    """Lista las luces detectadas y su estado (solo lectura)."""
    try:
        ls = lights()
    except RuntimeError as e:
        return f"ERROR: {e}"
    if not ls:
        return "No se detectaron luces (switch)."
    rows = []
    for s in sorted(ls, key=lambda x: x.get("entity_id", "")):
        fn = (s.get("attributes") or {}).get("friendly_name", "")
        rows.append(f"  {s.get('entity_id', ''):<44} {s.get('state', '?'):<8} {fn}")
    on = sum(1 for s in ls if s.get("state") == "on")
    return f"{len(ls)} luces ({on} encendidas):\n" + "\n".join(rows)


def ha_lights_off(args: dict) -> str:
    """Apaga TODAS las luces encendidas salvo las de 'keep'. EFECTO EXTERNO (gated).

    keep: lista (o csv) de entity_id a mantener encendidos, p.ej.
          ['switch.0xa4c138a5bf2c0a9f']  (luces exterior).
    """
    keep = args.get("keep") or []
    if isinstance(keep, str):
        keep = [k.strip() for k in keep.split(",") if k.strip()]
    keep = set(keep)
    try:
        targets = [s for s in lights()
                   if s.get("entity_id") not in keep and s.get("state") == "on"]
    except RuntimeError as e:
        return f"ERROR: {e}"
    if not targets:
        return "No hay luces encendidas para apagar (o todas están en 'keep')."
    done, errors = [], []
    for s in targets:
        eid = s["entity_id"]
        try:
            call_service("switch", "turn_off", {"entity_id": eid})
            done.append(eid)
        except RuntimeError as e:
            errors.append(f"{eid} ({e})")
    # Verificación tras la ronda de apagado.
    import time
    time.sleep(1.0)
    still_on = []
    try:
        still_on = [s["entity_id"] for s in lights()
                    if s.get("entity_id") not in keep and s.get("state") == "on"]
    except RuntimeError:
        pass
    msg = (f"Apagadas {len(done)} luces. "
           f"Mantenidas (keep): {', '.join(sorted(keep)) or '(ninguna)'}.")
    if errors:
        msg += f" ERRORES: {'; '.join(errors)}."
    if still_on:
        msg += f" ⚠️ Siguen encendidas: {', '.join(still_on)}."
    return msg


def _fmt_state(s: dict) -> str:
    eid = s.get("entity_id", "?")
    state = s.get("state", "?")
    attrs = s.get("attributes", {}) or {}
    name = attrs.get("friendly_name", eid)
    extra = {k: v for k, v in attrs.items() if k != "friendly_name"}
    head = f"{eid} ({name}) = {state}"
    return head + (f"\n  attrs: {json.dumps(extra, ensure_ascii=False)[:400]}" if extra else "")


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #
def register_skill(reg) -> None:
    reg.register(
        "ha_states",
        "Lee estados de Home Assistant (solo lectura). Filtra por entity_id o domain.",
        {"type": "object",
         "properties": {"entity_id": {"type": "string"}, "domain": {"type": "string"}}},
        ha_states,
    )
    reg.register(
        "ha_services",
        "Lista servicios disponibles en Home Assistant. Filtra por domain.",
        {"type": "object", "properties": {"domain": {"type": "string"}}},
        ha_services,
    )
    reg.register(
        "ha_lights",
        "Lista las luces (entidades switch en esta instalación) y su estado. Solo lectura.",
        {"type": "object", "properties": {}},
        ha_lights,
    )
    reg.register(
        "ha_lights_off",
        "Apaga TODAS las luces encendidas salvo las de 'keep'. EFECTO EXTERNO: gated.",
        {"type": "object",
         "properties": {"keep": {"type": "array", "items": {"type": "string"},
                                 "description": "entity_id a mantener encendidos"}}},
        ha_lights_off,
    )
    reg.register(
        "ha_call_service",
        "Ejecuta un servicio de Home Assistant (turn_on/turn_off/etc.). EFECTO EXTERNO: gated.",
        {"type": "object",
         "properties": {
             "domain": {"type": "string", "description": "p.ej. light, switch, climate"},
             "service": {"type": "string", "description": "p.ej. turn_on, turn_off, set_temperature"},
             "entity_id": {"type": "string", "description": "entidad objetivo, p.ej. light.salon"},
             "data": {"type": "object", "description": "datos extra del servicio (brightness, etc.)"}},
         "required": ["domain", "service"]},
        ha_call_service,
    )

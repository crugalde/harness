#!/usr/bin/env python3
"""ha_setup.py — Wizard de conexión y diagnóstico de Home Assistant (subagente `home`).

La "app en tu computador" para conectar y configurar HA. Te guía a crear el
Long-Lived Access Token, valida la conexión contra la API, guarda las credenciales
en ~/.config/harness/.env (chmod 600, fuera de iCloud) y te muestra qué tienes
conectado (entidades agrupadas por dominio).

Sin dependencias externas (urllib de la stdlib). Reutiliza el cliente HTTP de la
skill skills/home_assistant/tool.py, así no se duplica lógica de red.

Uso:
  python tools/ha_setup.py            # wizard interactivo (setup)
  python tools/ha_setup.py status     # solo diagnóstico con las credenciales guardadas
  python tools/ha_setup.py setup --url http://192.168.4.60:8123 --token XXXX  # no interactivo
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "http://192.168.4.60:8123"

# Carga el .env local para precargar valores existentes y permitir 'status'.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from env_loader import env_path, load_env

    load_env()
except Exception:  # noqa: BLE001 — el wizard debe correr aun sin env previo
    def env_path() -> Path:
        return Path.home() / ".config" / "harness" / ".env"


def _ha():
    """Carga el cliente de la skill como módulo (patrón de compose.py)."""
    path = ROOT / "skills" / "home_assistant" / "tool.py"
    spec = importlib.util.spec_from_file_location("ha_skill_tool", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _save_env(updates: dict[str, str]) -> Path:
    """Escribe/actualiza claves en ~/.config/harness/.env sin tocar las demás. chmod 600."""
    path = env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, str] = {}
    order: list[str] = []
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k not in existing:
                order.append(k)
            existing[k] = v.strip()
    for k, v in updates.items():
        if k not in existing:
            order.append(k)
        existing[k] = v
    body = "\n".join(f"{k}={existing[k]}" for k in order) + "\n"
    path.write_text(body, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _print_inventory(ha) -> None:
    """Muestra el inventario del hogar agrupado por dominio."""
    data = ha.states()
    if not isinstance(data, list):
        print("  (respuesta inesperada de /api/states)")
        return
    by_domain: dict[str, int] = {}
    samples: dict[str, str] = {}
    for s in data:
        eid = s.get("entity_id", "")
        dom = eid.split(".", 1)[0] if "." in eid else "otros"
        by_domain[dom] = by_domain.get(dom, 0) + 1
        samples.setdefault(dom, eid)
    print(f"\n  {len(data)} entidades en {len(by_domain)} dominios:")
    for dom in sorted(by_domain, key=lambda d: -by_domain[d]):
        print(f"    {dom:<16} {by_domain[dom]:>4}   (ej: {samples[dom]})")


def _diagnose(ha, base: str | None = None, token: str | None = None) -> bool:
    """Hace ping y muestra el inventario. Devuelve True si todo ok."""
    try:
        msg = ha.ping(base=base, token=token)
        print(f"  ✓ Conexión OK — {msg.get('message', msg)}")
    except RuntimeError as e:
        print(f"  ✗ {e}")
        return False
    # El inventario solo funciona con credenciales ya en el entorno.
    if base and token:
        os.environ["HA_BASE_URL"] = base
        os.environ["HA_TOKEN"] = token
    try:
        _print_inventory(ha)
    except RuntimeError as e:
        print(f"  (no se pudo listar entidades: {e})")
    return True


def cmd_status(ha) -> int:
    base, token = ha.config()
    if not base or not token:
        print("No hay credenciales guardadas. Corre: python tools/ha_setup.py")
        return 1
    print(f"Home Assistant en {base}")
    return 0 if _diagnose(ha) else 2


def cmd_setup(ha, url: str | None, token: str | None) -> int:
    interactive = url is None or token is None
    cfg_base, cfg_token = ha.config()
    if interactive:
        print("=== Wizard de conexión a Home Assistant ===\n")
        default = url or cfg_base or DEFAULT_URL
        url = input(f"URL de Home Assistant [{default}]: ").strip() or default
        if not token:
            if not cfg_token:
                print(
                    "\nNecesitas un Long-Lived Access Token. Cómo crearlo:\n"
                    f"  1. Abre {url} e inicia sesión.\n"
                    "  2. Clic en tu usuario (abajo a la izquierda) → pestaña 'Security'.\n"
                    "  3. Sección 'Long-Lived Access Tokens' → 'Create Token'.\n"
                    "  4. Ponle un nombre (p.ej. 'harness-home') y copia el token (solo se ve una vez).\n"
                )
            prompt = "Pega el token" + (" [enter = mantener el guardado]" if cfg_token else "") + ": "
            token = input(prompt).strip() or cfg_token
    url = (url or cfg_base or DEFAULT_URL).rstrip("/")
    if not token:
        print("✗ No se proporcionó token. Aborto.")
        return 1

    print(f"\nValidando conexión a {url} ...")
    try:
        ha.ping(base=url, token=token)
    except RuntimeError as e:
        print(f"  ✗ {e}")
        print("\nNo se guardó nada. Revisa URL/red/token y reintenta.")
        return 2
    print("  ✓ Token válido y API respondiendo.")

    saved = _save_env({"HA_BASE_URL": url, "HA_TOKEN": token})
    print(f"  ✓ Credenciales guardadas en {saved} (chmod 600).")

    os.environ["HA_BASE_URL"] = url
    os.environ["HA_TOKEN"] = token
    try:
        _print_inventory(ha)
    except RuntimeError as e:
        print(f"  (no se pudo listar entidades: {e})")

    print(
        "\nListo. Ahora el subagente `home` puede leer y controlar tu hogar:\n"
        '  python tools/loop.py "¿qué luces están encendidas?" --agent home\n'
        '  python tools/loop.py "apaga la luz del salón" --agent home   # pide confirmación (gated)\n'
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Wizard de conexión/diagnóstico de Home Assistant.")
    ap.add_argument("command", nargs="?", default="setup", choices=["setup", "status"],
                    help="setup (default): conectar/configurar; status: solo diagnóstico.")
    ap.add_argument("--url", help="URL de HA (modo no interactivo).")
    ap.add_argument("--token", help="Long-Lived Access Token (modo no interactivo).")
    args = ap.parse_args()
    ha = _ha()
    if args.command == "status":
        return cmd_status(ha)
    return cmd_setup(ha, args.url, args.token)


if __name__ == "__main__":
    raise SystemExit(main())

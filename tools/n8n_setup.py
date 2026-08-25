#!/usr/bin/env python3
"""n8n_setup.py — Wizard de conexión y diagnóstico del n8n del VPS.

Conecta el harness con tu instancia self-hosted: valida la API key contra la API
pública, guarda las credenciales en ~/.config/harness/.env (chmod 600, fuera de
iCloud) y te muestra qué tienes corriendo (workflows, activos, últimos errores).

Sin dependencias externas (urllib de la stdlib). Reutiliza el cliente HTTP de la
skill skills/n8n/tool.py, así no se duplica lógica de red.

Uso:
  python tools/n8n_setup.py                     # wizard interactivo (setup)
  python tools/n8n_setup.py status              # diagnóstico con lo ya guardado
  python tools/n8n_setup.py setup --url https://n8n.tudominio.cl --key n8n_api_XXX
"""
from __future__ import annotations

import argparse
import getpass
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from env_loader import env_path, load_env

    load_env()
except Exception:  # noqa: BLE001 — el wizard debe correr aun sin env previo
    def env_path() -> Path:
        return Path.home() / ".config" / "harness" / ".env"


def _n8n():
    """Carga el cliente de la skill como módulo (patrón de ha_setup.py)."""
    path = ROOT / "skills" / "n8n" / "tool.py"
    spec = importlib.util.spec_from_file_location("n8n_skill_tool", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _save_env(updates: dict[str, str]) -> Path:
    """Escribe/actualiza claves en ~/.config/harness/.env sin tocar las demás. chmod 600."""
    path = env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            key = raw.split("=", 1)[0].strip() if "=" in raw else ""
            if key in updates:
                continue  # se reescribe abajo con el valor nuevo
            lines.append(raw)
    for k, v in updates.items():
        lines.append(f"{k}={v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def cmd_setup(args) -> int:
    n8n = _n8n()
    base = args.url or input("URL de tu n8n (ej. https://n8n.tudominio.cl): ").strip()
    base = base.rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    if args.key:
        key = args.key
    else:
        print("\nCrea la API key en el editor: Settings → n8n API → Create an API key.")
        print("Se muestra una sola vez; no la pegues en un chat.")
        key = getpass.getpass("API key (no se muestra al escribir): ").strip()
    if not key:
        print("ERROR: API key vacía.", file=sys.stderr)
        return 2

    print(f"\nValidando contra {base} …")
    try:
        n8n.ping(base=base, key=key)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    path = _save_env({"N8N_BASE_URL": base, "N8N_API_KEY": key})
    print(f"OK. Credenciales guardadas en {path} (chmod 600).")
    print("Diagnóstico:\n")
    return cmd_status(args, base=base, key=key)


def cmd_status(args, *, base: str | None = None, key: str | None = None) -> int:
    n8n = _n8n()
    cfg_base, cfg_key = n8n.config()
    base, key = base or cfg_base, key or cfg_key
    if not base or not key:
        print("Sin credenciales guardadas. Corre: python tools/n8n_setup.py", file=sys.stderr)
        return 2
    try:
        wfs = n8n.list_workflows(base=base, key=key)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    activos = [w for w in wfs if w.get("active")]
    print(f"Instancia: {base}")
    print(f"Workflows: {len(wfs)} ({len(activos)} activos)")
    print(f"Webhooks:  {base}/webhook/<path>\n")
    for w in wfs[:20]:
        print(f"  [{w.get('id')}] {'●' if w.get('active') else '○'} {w.get('name')}")
    if len(wfs) > 20:
        print(f"  … y {len(wfs) - 20} más")

    try:
        errores = n8n.request("GET", "executions", params={"status": "error", "limit": 5},
                              base=base, key=key).get("data", [])
    except RuntimeError:
        errores = []
    if errores:
        print("\nÚltimas ejecuciones con error:")
        for e in errores:
            print(f"  [{e.get('id')}] wf {e.get('workflowId')} · {e.get('startedAt')}")
    else:
        print("\nSin ejecuciones fallidas recientes.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Wizard de conexión del n8n self-hosted.")
    sub = ap.add_subparsers(dest="cmd")
    p_setup = sub.add_parser("setup", help="conecta y guarda credenciales")
    p_setup.add_argument("--url", default=None)
    p_setup.add_argument("--key", default=None)
    sub.add_parser("status", help="diagnóstico con las credenciales guardadas")
    args = ap.parse_args()

    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd is None:  # sin subcomando: wizard interactivo
        args.url = args.key = None
    return cmd_setup(args)


if __name__ == "__main__":
    raise SystemExit(main())

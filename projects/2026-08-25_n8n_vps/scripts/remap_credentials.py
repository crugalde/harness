#!/usr/bin/env python3
"""remap_credentials.py — Reapunta los workflows exportados a las credenciales del VPS.

Problema que resuelve: al recrear una credencial en la instancia nueva, n8n le da un
**ID distinto**. Los workflows importados siguen apuntando al ID viejo (de Cloud) y
cada nodo aparece con "credential not found" hasta que lo reseleccionas a mano. Con
30 workflows eso son horas de clics.

Este script reescribe los JSON exportados cambiando el ID viejo por el nuevo,
emparejando por (tipo, nombre) de la credencial. Luego reimportas y todo queda
conectado.

Flujo:
  1. Crea las credenciales en el VPS con los MISMOS nombres (ver inventario_credenciales.md).
  2. En el VPS:  bash scripts/credenciales_map.sh > map.json
  3. Aquí:       python scripts/remap_credentials.py --dir export/workflows --map map.json
  4. Reimporta:  bash scripts/import_vps.sh export/workflows_remap

El mapa acepta dos formatos:
  - JSON: [{"id": "...", "name": "...", "type": "..."}, ...]   (salida de credenciales_map.sh)
  - CSV:  id,name,type                                          (una credencial por línea)
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path


def load_map(path: Path) -> list[dict[str, str]]:
    """Carga el mapa de credenciales del VPS (JSON o CSV) y normaliza las claves."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{path} está vacío: ¿corriste credenciales_map.sh en el VPS?")
    if text.startswith("["):
        rows = json.loads(text)
    else:
        rows = list(csv.DictReader(text.splitlines()))
    out: list[dict[str, str]] = []
    for row in rows:
        if not row:
            continue
        missing = {"id", "name", "type"} - set(row)
        if missing:
            raise ValueError(f"Fila sin campos {sorted(missing)}: {row}")
        out.append({"id": str(row["id"]), "name": str(row["name"]), "type": str(row["type"])})
    return out


def build_index(rows: list[dict[str, str]], loose: bool) -> dict[tuple[str, str] | str, str]:
    """Índice (tipo, nombre) → id nuevo. Con --loose añade nombre → id."""
    idx: dict[tuple[str, str] | str, str] = {}
    for r in rows:
        idx[(r["type"], r["name"])] = r["id"]
    if loose:
        by_name: dict[str, list[str]] = {}
        for r in rows:
            by_name.setdefault(r["name"], []).append(r["id"])
        for name, ids in by_name.items():
            if len(ids) == 1:  # ambiguo si el nombre se repite entre tipos: no adivinamos
                idx[name] = ids[0]
    return idx


def remap_workflow(wf: dict, idx: dict, loose: bool) -> tuple[int, list[str]]:
    """Reescribe los IDs de credenciales del workflow. Devuelve (cambios, no encontradas)."""
    changed = 0
    missing: list[str] = []
    for node in wf.get("nodes", []) or []:
        creds = node.get("credentials") or {}
        for cred_type, ref in creds.items():
            if not isinstance(ref, dict):
                continue
            name = ref.get("name", "")
            new_id = idx.get((cred_type, name)) or (idx.get(name) if loose else None)
            if new_id is None:
                missing.append(f"{wf.get('name', '?')} → {node.get('name', '?')}: {name} ({cred_type})")
                continue
            if ref.get("id") != new_id:
                ref["id"] = new_id
                changed += 1
    return changed, missing


def main() -> int:
    ap = argparse.ArgumentParser(description="Reapunta credenciales en los workflows exportados.")
    ap.add_argument("--dir", required=True, help="Directorio con los .json exportados")
    ap.add_argument("--map", required=True, help="Mapa de credenciales del VPS (JSON o CSV)")
    ap.add_argument("--out", default=None, help="Directorio de salida (default: <dir>_remap)")
    ap.add_argument("--in-place", action="store_true", help="Reescribe los archivos originales")
    ap.add_argument(
        "--loose",
        action="store_true",
        help="Empareja solo por nombre cuando el tipo no calza (útil si cambió el tipo de nodo)",
    )
    args = ap.parse_args()

    src = Path(args.dir).expanduser().resolve()
    if not src.is_dir():
        print(f"ERROR: no existe el directorio {src}", file=sys.stderr)
        return 2
    files = sorted(src.glob("*.json"))
    if not files:
        print(f"ERROR: no hay .json en {src}", file=sys.stderr)
        return 2

    try:
        rows = load_map(Path(args.map).expanduser())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR leyendo el mapa: {exc}", file=sys.stderr)
        return 2
    idx = build_index(rows, args.loose)
    print(f"Mapa: {len(rows)} credenciales en el VPS", file=sys.stderr)

    dst = src if args.in_place else Path(args.out or f"{src}_remap").expanduser().resolve()
    if dst != src:
        dst.mkdir(parents=True, exist_ok=True)

    total_changed = 0
    all_missing: list[str] = []
    for f in files:
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"  ! {f.name}: JSON inválido ({exc}); se copia sin tocar", file=sys.stderr)
            if dst != src:
                shutil.copy2(f, dst / f.name)
            continue
        changed, missing = remap_workflow(wf, idx, args.loose)
        total_changed += changed
        all_missing.extend(missing)
        (dst / f.name).write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nIDs de credencial reescritos: {total_changed}", file=sys.stderr)
    print(f"Salida: {dst}", file=sys.stderr)
    if all_missing:
        print(
            f"\nSin equivalente en el VPS ({len(all_missing)}) — créalas con el mismo nombre "
            "o reselecciónalas a mano en el editor:",
            file=sys.stderr,
        )
        for m in sorted(set(all_missing)):
            print(f"  - {m}", file=sys.stderr)
        return 1  # salida distinta de 0: queda trabajo manual pendiente
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

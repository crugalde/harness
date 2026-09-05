"""Skill publicar — lleva una revisión a Obsidian y/o a una database de Notion.

Envuelve `tools/publicar.py` para exponerlo al ToolRegistry. Import perezoso.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _motor():
    sys.path.insert(0, str(ROOT / "tools"))
    import publicar
    return publicar


def publicar_obsidian(args: dict) -> str:
    origen = args.get("origen", "").strip()
    vault = (args.get("vault") or os.environ.get("OBSIDIAN_VAULT", "")).strip()
    if not origen:
        return "ERROR: falta 'origen' (carpeta de paper_review o un .md)."
    if not vault:
        return "ERROR: falta 'vault' (o la variable OBSIDIAN_VAULT)."
    try:
        m = _motor()
        markdown, datos, carpeta = m.leer_revision(Path(origen))
        r = m.publicar_obsidian(
            markdown, datos, carpeta, vault=Path(vault),
            subcarpeta=args.get("subcarpeta") or os.environ.get(
                "OBSIDIAN_SUBCARPETA", "Revisiones"),
            tema=args.get("tema", ""), dry_run=bool(args.get("dry_run", False)))
    except (ImportError, RuntimeError, OSError) as e:
        return f"ERROR: {e}"
    return (f"OK: nota en {r['nota']} · {r['caracteres']:,} caracteres · "
            f"{len(r['adjuntos'])} adjuntos"
            f"{' · índice actualizado' if r['indice_actualizado'] else ''}"
            f"{' (dry-run: no se escribió)' if r['dry_run'] else ''}")


def publicar_notion(args: dict) -> str:
    origen = args.get("origen", "").strip()
    database = (args.get("database") or os.environ.get("NOTION_DATABASE_ID", "")).strip()
    token = os.environ.get("NOTION_TOKEN", "")
    dry = bool(args.get("dry_run", False))
    if not origen:
        return "ERROR: falta 'origen' (carpeta de paper_review o un .md)."
    if not database:
        return "ERROR: falta 'database' (o la variable NOTION_DATABASE_ID)."
    if not token and not dry:
        return "ERROR: falta NOTION_TOKEN en el entorno."
    try:
        m = _motor()
        markdown, datos, _ = m.leer_revision(Path(origen))
        r = m.publicar_notion(markdown, datos, database=database, token=token,
                              tema=args.get("tema", ""), dry_run=dry)
    except (ImportError, RuntimeError, OSError) as e:
        return f"ERROR: {e}"
    return (f"OK: {r['url']} · {r['bloques']} bloques · "
            f"propiedades rellenadas: {r['propiedades']}")


def register_skill(reg) -> None:
    comun = {"origen": {"type": "string", "description": "Carpeta de paper_review o un .md."},
             "tema": {"type": "string", "description": "Título; por defecto el de revision.json."},
             "dry_run": {"type": "boolean"}}
    reg.register(
        "publicar_obsidian",
        "Escribe una revisión como nota en una bóveda de Obsidian, con front-matter, "
        "adjuntos copiados y entrada en el índice.",
        {"type": "object",
         "properties": {**comun,
                        "vault": {"type": "string", "description": "Ruta de la bóveda."},
                        "subcarpeta": {"type": "string"}},
         "required": ["origen"]},
        publicar_obsidian)
    reg.register(
        "publicar_notion",
        "Crea una página en una database de Notion desde una revisión, rellenando las "
        "propiedades que la database realmente tiene.",
        {"type": "object",
         "properties": {**comun,
                        "database": {"type": "string", "description": "Id de la database."}},
         "required": ["origen"]},
        publicar_notion)

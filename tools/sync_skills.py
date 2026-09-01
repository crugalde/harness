#!/usr/bin/env python3
"""sync_skills.py — Publica las skills del repo donde Hermes las escanea.

El `skills-hub` de Hermes descubre skills escaneando carpetas del disco. Hay dos formas
de que vea las de este repo, y conviene entender cuál te sirve antes de correr nada:

1. **Apuntar el hub a `skills/` del repo** (preferida). Cero copias, cero deriva: un
   `git pull` basta para que el hub vea una skill nueva. No necesitas este script.
2. **Sincronizar** con este script, cuando el hub solo acepta un directorio fijo que ya
   usa para otras cosas. Copia (o enlaza) cada skill del repo al destino.

La sincronización es **conservadora por diseño**: escribe un manifiesto
`.harness-sync.json` en el destino y `--limpiar` solo borra lo que figure en él. Nunca
toca una carpeta que no haya creado este script, porque el destino es la carpeta de
skills de Hermes y ahí vive trabajo que no es de este repo.

Además **valida**: una skill sin `name` o sin `description` en el front-matter es una
skill que el hub indexa mal o directamente ignora, y el fallo es silencioso. Aquí se
reporta y no se sincroniza.

Uso:
  python tools/sync_skills.py --destino "C:/Users/Usuario/AppData/Local/hermes/skills"
  python tools/sync_skills.py --destino ... --dry-run     # ver qué haría
  python tools/sync_skills.py --destino ... --link        # enlaces en vez de copias
  python tools/sync_skills.py --destino ... --limpiar     # quitar las que ya no existen
  python tools/sync_skills.py --validar                   # solo revisar el repo
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
MANIFIESTO = ".harness-sync.json"
IGNORAR = {"__pycache__", ".pytest_cache", ".DS_Store"}

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_selector import _front_matter  # noqa: E402  (mismo parser que usa el selector)


# ---------------------------------------------------------------------------
def validar(directorio: Path = SKILLS) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Separa las skills publicables de las defectuosas. Devuelve (ok, problemas)."""
    ok: list[Path] = []
    problemas: list[tuple[Path, str]] = []
    for md in sorted(directorio.glob("*/SKILL.md")):
        fm = _front_matter(md.read_text(encoding="utf-8", errors="replace"))
        if not fm:
            problemas.append((md.parent, "sin front-matter `---` al inicio"))
        elif not fm.get("name"):
            problemas.append((md.parent, "falta `name:` en el front-matter"))
        elif not fm.get("description"):
            problemas.append((md.parent, "falta `description:` (el hub la usa para buscar)"))
        elif len(fm["description"]) < 40:
            problemas.append((md.parent, "`description:` demasiado corta para rankear bien"))
        else:
            ok.append(md.parent)
    return ok, problemas


def _copiar(origen: Path, destino: Path) -> None:
    if destino.is_symlink() or destino.is_file():
        destino.unlink()
    elif destino.is_dir():
        shutil.rmtree(destino)
    shutil.copytree(origen, destino,
                    ignore=shutil.ignore_patterns(*IGNORAR))


def _enlazar(origen: Path, destino: Path) -> str:
    """Enlace simbólico si el sistema lo permite; si no, copia. Devuelve qué hizo."""
    if destino.is_symlink() or destino.is_file():
        destino.unlink()
    elif destino.is_dir():
        shutil.rmtree(destino)
    try:
        destino.symlink_to(origen, target_is_directory=True)
        return "enlazada"
    except OSError:
        # Windows exige modo desarrollador o permisos de administrador para symlinks.
        _copiar(origen, destino)
        return "copiada (el sistema no permitió el enlace)"


def _leer_manifiesto(destino: Path) -> list[str]:
    f = destino / MANIFIESTO
    if not f.is_file():
        return []
    try:
        return list(json.loads(f.read_text(encoding="utf-8")).get("skills", []))
    except (json.JSONDecodeError, OSError):
        return []


def sincronizar(destino: Path, *, enlazar: bool = False, dry_run: bool = False,
                limpiar: bool = False) -> dict:
    ok, problemas = validar()
    previas = set(_leer_manifiesto(destino))
    acciones: list[str] = []

    if not dry_run:
        destino.mkdir(parents=True, exist_ok=True)

    for skill in ok:
        objetivo = destino / skill.name
        if dry_run:
            acciones.append(f"{'enlazaría' if enlazar else 'copiaría'} {skill.name}")
            continue
        estado = _enlazar(skill, objetivo) if enlazar else (_copiar(skill, objetivo) or "copiada")
        acciones.append(f"{skill.name}: {estado}")

    retiradas: list[str] = []
    if limpiar:
        vigentes = {s.name for s in ok}
        for nombre in sorted(previas - vigentes):
            objetivo = destino / nombre
            if not objetivo.exists():
                continue
            if dry_run:
                retiradas.append(f"quitaría {nombre}")
                continue
            if objetivo.is_symlink() or objetivo.is_file():
                objetivo.unlink()
            else:
                shutil.rmtree(objetivo)
            retiradas.append(nombre)

    if not dry_run:
        (destino / MANIFIESTO).write_text(
            json.dumps({"origen": str(SKILLS), "skills": sorted(s.name for s in ok)},
                       ensure_ascii=False, indent=2), encoding="utf-8")

    return {"sincronizadas": acciones, "problemas": problemas,
            "retiradas": retiradas, "destino": destino}


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Publica las skills del repo donde Hermes las escanea.")
    ap.add_argument("--destino", help="Carpeta de skills de Hermes.")
    ap.add_argument("--link", action="store_true",
                    help="Enlaces simbólicos en vez de copias (si el sistema los permite).")
    ap.add_argument("--dry-run", action="store_true", help="Mostrar sin escribir nada.")
    ap.add_argument("--limpiar", action="store_true",
                    help="Quitar del destino las skills del manifiesto que ya no existen.")
    ap.add_argument("--validar", action="store_true",
                    help="Solo revisar el front-matter de las skills del repo.")
    a = ap.parse_args()

    if a.validar or not a.destino:
        ok, problemas = validar()
        print(f"{len(ok)} skills publicables en {SKILLS}:")
        for s in ok:
            print(f"  OK  {s.name}")
        for s, motivo in problemas:
            print(f"  ✗   {s.name}: {motivo}")
        if not a.destino and not a.validar:
            print("\nPasa --destino para sincronizar, o apunta el hub de Hermes "
                  f"directamente a {SKILLS} (preferido: sin copias ni deriva).")
        return 1 if problemas else 0

    r = sincronizar(Path(a.destino).expanduser(), enlazar=a.link,
                    dry_run=a.dry_run, limpiar=a.limpiar)
    print(f"Destino: {r['destino']}{'  (dry-run)' if a.dry_run else ''}")
    for linea in r["sincronizadas"]:
        print(f"  {linea}")
    for nombre in r["retiradas"]:
        print(f"  retirada: {nombre}")
    for s, motivo in r["problemas"]:
        print(f"  ✗ NO sincronizada — {s.name}: {motivo}")
    if not a.dry_run:
        print(f"\nManifiesto en {r['destino'] / MANIFIESTO}. "
              "Reinicia Hermes o reindexa el hub para que las vea.")
    return 1 if r["problemas"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

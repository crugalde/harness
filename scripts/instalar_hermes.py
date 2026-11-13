#!/usr/bin/env python3
"""instalar_hermes.py — Genera e instala los perfiles de Hermes Agent desde este repo.

Fuente única: cada `.claude/agents/<id>.md` (los mismos subagentes de Claude Code) se
convierte en un perfil de Hermes con su SOUL.md, y `AGENTS.md` aporta la identidad del
perfil `orquestador`, que delega en los otros 4 vía `delegation.backend: profile_routes`
(plugin oficial `advanced-delegation`, requiere Hermes >= 0.22.5).

Todos los perfiles:
  - usan el mismo modelo local: el runtime llama.cpp que gestiona Hermes (`llamacpp`, por
    defecto) o un endpoint OpenAI-compatible propio como Ollama (`custom` + --base-url);
  - no tienen proveedor de respaldo en la nube (fallback_providers: []);
  - piden aprobación antes de escribir en su memoria (memory.write_approval: true);
  - arrancan en la raíz del repo (terminal.cwd), así cargan AGENTS.md como contexto;
  - leen las skills de .claude/skills (skills.external_dirs).
El orquestador limita los subagentes simultáneos (--max-hijos, default 2): con una sola GPU
todos comparten el mismo servidor y cada uno reserva su propio contexto de 64K.

Uso (PC con NVIDIA 16 GB + 64 GB RAM; ver scripts/diagnostico_pc.py):
    # 0) Descargar el modelo: hermes model -> Local models -> Qwen3.6 35B-A3B
    # 1) Solo generar y revisar (no toca Hermes):
    python3 scripts/instalar_hermes.py --modelo Qwen3.6-35B-A3B-UD-Q4_K_M --solo-generar
    # 2) Generar e instalar los 5 perfiles + el plugin de delegación:
    python3 scripts/instalar_hermes.py --modelo Qwen3.6-35B-A3B-UD-Q4_K_M --instalar-plugin
    # Con Ollama en vez del runtime de Hermes:
    python3 scripts/instalar_hermes.py --proveedor custom --modelo qwen36-64k \\
        --base-url http://localhost:11434/v1

El modelo debe tener >= 64K de contexto (Hermes lo exige al arrancar). Ver hermes/README.md.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _comun import RAIZ, log  # noqa: E402

AGENTES_DIR = RAIZ / ".claude" / "agents"
SKILLS_DIR = RAIZ / ".claude" / "skills"
HERMES_MIN = ">=0.22.5"
ORQUESTADOR = "orquestador"
PROVEEDORES = ("llamacpp", "custom")


@dataclass
class Perfil:
    nombre: str
    descripcion: str
    soul: str


def _q(texto: str) -> str:
    """Cadena YAML segura: un string JSON es un escalar YAML válido entre comillas dobles."""
    return json.dumps(texto, ensure_ascii=False)


def leer_agente(ruta: Path) -> Perfil:
    texto = ruta.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", texto, re.S)
    if not m:
        raise ValueError(f"{ruta.name}: falta el frontmatter ---")
    campos: dict[str, str] = {}
    for linea in m.group(1).splitlines():
        if ":" in linea:
            k, _, v = linea.partition(":")
            campos[k.strip()] = v.strip()
    nombre = campos.get("name", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", nombre):
        raise ValueError(f"{ruta.name}: 'name' inválido para un perfil de Hermes: {nombre!r}")
    if nombre != ruta.stem:
        raise ValueError(f"{ruta.name}: 'name' ({nombre}) debe coincidir con el nombre del archivo")
    return Perfil(nombre, campos.get("description", ""), m.group(2).strip() + "\n")


def leer_orquestador(agents_md: Path) -> Perfil:
    texto = agents_md.read_text(encoding="utf-8")
    m = re.search(r"^## 1\. Identidad\s*\n(.*?)(?=^## )", texto, re.S | re.M)
    if not m:
        raise ValueError("AGENTS.md: no se encontró la sección '## 1. Identidad'")
    soul = "# Orquestador científico\n\n" + m.group(1).strip() + "\n"
    return Perfil(ORQUESTADOR, "Orquestador científico: enruta, verifica e integra.", soul)


def primera_frase(texto: str, largo: int = 220) -> str:
    """Primera oración; si excede `largo`, se corta en el último espacio (nunca a media palabra)."""
    frase = re.split(r"(?<=[.])\s", texto, maxsplit=1)[0]
    if len(frase) <= largo:
        return frase
    return frase[: largo - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


def config_yaml(
    modelo: str,
    base_url: str,
    rutas: list[Perfil] | None = None,
    *,
    proveedor: str = "custom",
    max_hijos: int = 2,
) -> str:
    if proveedor == "llamacpp":
        bloque_modelo = [
            "model:",
            "  provider: llamacpp           # runtime llama.cpp gestionado por Hermes",
            f"  default: {_q(modelo)}",
            "local_runtime:",
            "  enabled: true                # arranca el servidor local; si ya corre, lo reutiliza",
        ]
    else:
        bloque_modelo = [
            "model:",
            "  provider: custom",
            f"  base_url: {_q(base_url)}",
            f"  default: {_q(modelo)}",
        ]
    lineas = [
        "# Generado por scripts/instalar_hermes.py — no editar a mano; regenerar.",
        *bloque_modelo,
        "fallback_providers: []          # local estricto: nada cae a la nube si el modelo falla",
        "memory:",
        "  write_approval: true          # el agente no aprende sin tu visto bueno",
        "terminal:",
        "  backend: local",
        f"  cwd: {_q(str(RAIZ))}",
        "skills:",
        "  external_dirs:",
        f"    - {_q(str(SKILLS_DIR))}",
    ]
    if rutas:
        lineas += [
            "delegation:",
            "  backend: profile_routes      # requiere el plugin advanced-delegation",
            f"  max_concurrent_children: {max_hijos}   # una GPU: pocos subagentes a la vez",
            "  backends:",
            "    profile_routes:",
            "      profiles:",
        ]
        for p in rutas:
            lineas += [
                f"        - name: {p.nombre}",
                f"          description: {_q(primera_frase(p.descripcion))}",
            ]
    return "\n".join(lineas) + "\n"


def distribution_yaml(perfil: Perfil, version: str) -> str:
    return (
        "\n".join(
            [
                f"name: {perfil.nombre}",
                f"version: {version}",
                f"description: {_q(primera_frase(perfil.descripcion, 200))}",
                f'hermes_requires: "{HERMES_MIN}"',
                "env_requires:",
                "  - name: ENTREZ_EMAIL",
                '    description: "Correo para NCBI/Unpaywall/OpenAlex (recomendado)"',
                "    required: false",
                '    default: ""',
            ]
        )
        + "\n"
    )


def version_repo() -> str:
    m = re.search(r"^version:\s*([\d.]+)", (RAIZ / "AGENTS.md").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "0.0.0"


def generar(
    salida: Path,
    modelo: str,
    modelo_orq: str,
    base_url: str,
    *,
    proveedor: str = "custom",
    max_hijos: int = 2,
) -> list[Perfil]:
    if proveedor not in PROVEEDORES:
        raise ValueError(f"Proveedor no soportado: {proveedor} (opciones: {PROVEEDORES})")
    if max_hijos < 1:
        raise ValueError("--max-hijos debe ser >= 1")
    agentes = [leer_agente(r) for r in sorted(AGENTES_DIR.glob("*.md"))]
    if not agentes:
        raise ValueError(f"No hay agentes en {AGENTES_DIR}")
    orq = leer_orquestador(RAIZ / "AGENTS.md")
    version = version_repo()
    if salida.exists():
        shutil.rmtree(salida)
    for perfil, mod, rutas in [(orq, modelo_orq, agentes)] + [(a, modelo, None) for a in agentes]:
        d = salida / perfil.nombre
        d.mkdir(parents=True)
        (d / "SOUL.md").write_text(perfil.soul, encoding="utf-8")
        texto = config_yaml(mod, base_url, rutas, proveedor=proveedor, max_hijos=max_hijos)
        (d / "config.yaml").write_text(texto, encoding="utf-8")
        (d / "distribution.yaml").write_text(distribution_yaml(perfil, version), encoding="utf-8")
    return [orq] + agentes


def _ejecutar(cmd: list[str]) -> bool:
    log.info("$ %s", " ".join(cmd))
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        log.error("falló (código %d): %s", r.returncode, " ".join(cmd))
    return r.returncode == 0


def instalar(salida: Path, perfiles: list[Perfil], plugin: bool) -> bool:
    if not shutil.which("hermes"):
        log.error("No encuentro 'hermes' en el PATH. Instálalo primero (ver hermes/README.md).")
        return False
    ok = True
    for p in perfiles:
        ok &= _ejecutar(
            ["hermes", "profile", "install", str(salida / p.nombre), "--name", p.nombre, "--alias"]
        )
    if plugin:
        ok &= _ejecutar(
            ["hermes", "-p", ORQUESTADOR, "plugins", "install", "advanced-delegation", "--enable"]
        )
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Genera e instala los perfiles de Hermes.")
    ap.add_argument("--modelo", required=True, help="Modelo local de los 5 perfiles (>=64K ctx)")
    ap.add_argument(
        "--modelo-orquestador",
        help="Modelo solo para el orquestador (default: --modelo). Con una GPU, evítalo",
    )
    ap.add_argument(
        "--proveedor",
        choices=PROVEEDORES,
        default="llamacpp",
        help="llamacpp = runtime local de Hermes (default); custom = Ollama u otro endpoint",
    )
    ap.add_argument(
        "--base-url",
        default="http://localhost:11434/v1",
        help="Endpoint OpenAI-compatible si --proveedor custom (default: Ollama local)",
    )
    ap.add_argument(
        "--max-hijos",
        type=int,
        default=2,
        help="Subagentes simultáneos del orquestador (default 2; GPU única)",
    )
    ap.add_argument(
        "--salida",
        default=str(RAIZ / "build" / "hermes"),
        help="Carpeta donde se generan los perfiles (default: build/hermes)",
    )
    ap.add_argument("--solo-generar", action="store_true", help="No ejecuta 'hermes'")
    ap.add_argument(
        "--instalar-plugin",
        action="store_true",
        help="Instala advanced-delegation en el perfil orquestador",
    )
    args = ap.parse_args(argv)

    salida = Path(args.salida).expanduser().resolve()
    modelo_orq = args.modelo_orquestador or args.modelo
    if modelo_orq != args.modelo:
        log.warning(
            "Dos modelos distintos (%s / %s): en una sola GPU no caben a la vez y el servidor "
            "los alternará en cada delegación. Usa uno solo salvo que tengas VRAM para ambos.",
            modelo_orq,
            args.modelo,
        )
    try:
        perfiles = generar(
            salida,
            args.modelo,
            modelo_orq,
            args.base_url,
            proveedor=args.proveedor,
            max_hijos=args.max_hijos,
        )
    except (ValueError, OSError) as exc:
        log.error("%s", exc)
        return 1
    print(
        f"{len(perfiles)} perfiles generados en {salida}: " + ", ".join(p.nombre for p in perfiles)
    )
    if args.solo_generar:
        print("Revisa los archivos y vuelve a ejecutar sin --solo-generar para instalar.")
        return 0
    if not instalar(salida, perfiles, args.instalar_plugin):
        return 1
    print(
        '\nListo. Prueba de humo:\n  orquestador chat\n  Pídele: "busca 5 papers sobre '
        'myasthenia gravis y efgartigimod y resume el más reciente"'
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

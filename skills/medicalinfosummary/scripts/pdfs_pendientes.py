#!/usr/bin/env python3
"""Gestiona los PDFs que el usuario debe aportar a mano.

Siempre queda un resto que ningún proxy consigue: ScienceDirect con antibot,
revistas sin acuerdo institucional, capítulos de libro. Ese resto no es ruido —
suelen ser los ECAs pivotales, justo las fuentes de las que salen las cifras.

Este script hace dos cosas según cómo se invoque:

  listar   Prioriza lo que falta y escribe pdfs/PENDIENTES.md con un nombre de
           archivo exacto para cada uno. El usuario arrastra los PDFs a esa
           carpeta con ese nombre y no hay ambigüedad sobre cuál es cuál.

  revisar  Detecta qué llegó, valida que sea un PDF real y no una página de
           error, y actualiza fuentes.json marcando `acceso: "manual"`.

Uso:
    python3 pdfs_pendientes.py listar  <dir-proyecto> [--top 12]
    python3 pdfs_pendientes.py revisar <dir-proyecto>

`<dir-proyecto>` es el que contiene `fuentes/fuentes.json`.
Solo biblioteca estándar.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

# Orden de prioridad: de qué fuentes salen las afirmaciones que hay que sostener.
PESO_ESTRATO = {
    "guias": 0,
    "enfoque_dirigido": 1,
    "revisiones_sistematicas": 2,
    "ensayos": 3,
    "revisiones": 4,
    "originales": 5,
}

# Editoriales que el proxy UC no logra automatizar (ver uc_library_fetcher/SKILL.md).
PREFIJOS_MANUAL = {
    "10.1016": "Elsevier/ScienceDirect — antibot, descarga manual",
    "10.1056": "NEJM — suele requerir clic manual",
    "10.6004": "NCCN — registro propio",
}


def _terminos(texto: str) -> set[str]:
    """Palabras significativas, sin operadores booleanos ni ruido corto."""
    stop = {"and", "or", "not", "the", "for", "with", "inhibitor", "inhibitors"}
    return {w for w in re.findall(r"[a-z]{4,}", texto.lower()) if w not in stop}


def relevancia(reg: dict, tema: str) -> int:
    """0 = el tema está en el título · 1 = solo en MeSH/abstract · 2 = ausente.

    El sort por relevancia de PubMed cuela trabajos tangenciales: una búsqueda de
    miastenia devuelve guías de timoma y de bloqueo neuromuscular en UCI. Pedirle
    al usuario que consiga ESOS a mano es hacerle perder el tiempo, así que van
    al fondo de la lista aunque su estrato sea alto.
    """
    t = _terminos(tema)
    if not t:
        return 0
    if t & _terminos(reg.get("titulo", "")):
        return 0
    resto = " ".join(reg.get("mesh", [])) + " " + reg.get("abstract", "")[:600]
    return 1 if t & _terminos(resto) else 2


def nombre_archivo(reg: dict) -> str:
    """Nombre estable y legible: primer-autor_año_pmid.pdf

    Los acentos se translitera n (García -> garcia), no se borran: eliminarlos
    produce nombres ilegibles como `garca` que el usuario no reconoce.
    """
    autores = reg.get("autores") or ["anon"]
    crudo = unicodedata.normalize("NFKD", autores[0].split()[0].lower())
    apellido = re.sub(r"[^a-z]", "", crudo.encode("ascii", "ignore").decode()) or "anon"
    return f"{apellido}_{reg.get('anio', 'sf')}_{reg['pmid']}.pdf"


def es_pdf_valido(p: Path) -> tuple[bool, str]:
    """Un HTML de error renombrado a .pdf es el fallo silencioso más común."""
    if not p.is_file():
        return False, "no existe"
    if p.stat().st_size < 20_000:
        return False, f"demasiado pequeño ({p.stat().st_size} B) — ¿página de error?"
    cabecera = p.open("rb").read(5)
    if cabecera[:4] != b"%PDF":
        return False, f"no es PDF (empieza con {cabecera!r})"
    return True, f"{p.stat().st_size // 1024} KB"


def cargar(dir_proyecto: Path) -> tuple[Path, dict]:
    f = dir_proyecto / "fuentes" / "fuentes.json"
    if not f.is_file():
        sys.exit(f"No encuentro {f}. ¿Corriste buscar_fuentes.py?")
    return f, json.loads(f.read_text(encoding="utf-8"))


def cmd_listar(dir_proyecto: Path, top: int) -> int:
    ruta_json, data = cargar(dir_proyecto)
    pdfs = dir_proyecto / "pdfs"
    pdfs.mkdir(parents=True, exist_ok=True)

    faltan = [s for s in data["fuentes"]
              if s.get("acceso") not in ("pmc", "oa", "manual")
              and not (pdfs / nombre_archivo(s)).is_file()]
    tema = data.get("tema", "")
    for s in faltan:
        s["_rel"] = relevancia(s, tema)
    # La relevancia manda sobre el estrato: una guía que no trata el tema no sirve.
    faltan.sort(key=lambda s: (s["_rel"], PESO_ESTRATO.get(s.get("estrato"), 9),
                               -int(s["anio"]) if s.get("anio", "").isdigit() else 0))

    en_tema = [s for s in faltan if s["_rel"] < 2]
    fuera = [s for s in faltan if s["_rel"] == 2]
    prioritarios = en_tema[:top]

    lineas = [
        f"# PDFs pendientes — {data['tema']}", "",
        f"{len(faltan)} fuentes sin texto completo; aquí las **{len(prioritarios)} más "
        f"relevantes** por estrato de evidencia.", "",
        "## Cómo aportarlas", "",
        f"1. Descarga el PDF desde el enlace de cada fila (usa el proxy UC en el navegador).",
        f"2. Guárdalo en `{pdfs}` **con el nombre exacto de la columna «Archivo»**.",
        "3. Avísame y corro `pdfs_pendientes.py revisar` para incorporarlas al análisis.", "",
        "No hace falta que estén todas: con las guías y los ensayos pivotales el informe ya",
        "se sostiene. Lo que no llegue se declara como «leído solo por abstract».", "",
        "## Prioritarias", "",
        "| # | Archivo | Estudio | Estrato | Por qué importa | Enlace |",
        "|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(prioritarios, 1):
        motivo = next((v for k, v in PREFIJOS_MANUAL.items()
                       if s.get("doi", "").startswith(k)), "paywall")
        titulo = s["titulo"].rstrip(".")[:70]
        enlace = s.get("url_texto") or s.get("url_pubmed", "")
        lineas.append(f"| {i} | `{nombre_archivo(s)}` | {titulo} | {s.get('estrato','')} "
                      f"| {motivo} | [abrir]({enlace}) |")

    if len(en_tema) > top:
        lineas += ["", "## Secundarias (opcionales)", ""]
        for s in en_tema[top:]:
            lineas.append(f"- `{nombre_archivo(s)}` — {s['titulo'].rstrip('.')[:70]} "
                          f"({s.get('estrato','')})")

    if fuera:
        lineas += ["", "## Probablemente fuera de tema — **no las busques**", "",
                   f"El término «{tema}» no aparece en su título ni en su indexación. "
                   "Llegaron por el orden de relevancia de PubMed. Revisa que efectivamente "
                   "no aporten y descártalas del informe:", ""]
        for s in fuera:
            lineas.append(f"- {s['titulo'].rstrip('.')[:78]} ({s.get('estrato','')}, "
                          f"PMID {s['pmid']})")

    destino = pdfs / "PENDIENTES.md"
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"{len(prioritarios)} prioritarias · {len(en_tema)} en tema · "
          f"{len(fuera)} descartables -> {destino}")
    print(f"Carpeta de destino para los PDFs: {pdfs}")
    return 0


def cmd_revisar(dir_proyecto: Path) -> int:
    ruta_json, data = cargar(dir_proyecto)
    pdfs = dir_proyecto / "pdfs"
    if not pdfs.is_dir():
        sys.exit(f"No existe {pdfs}. Corre primero el subcomando `listar`.")

    nuevos, invalidos = [], []
    for s in data["fuentes"]:
        if s.get("acceso") in ("pmc", "oa"):
            continue
        p = pdfs / nombre_archivo(s)
        if not p.exists():
            continue
        ok, detalle = es_pdf_valido(p)
        if ok:
            if s.get("acceso") != "manual":
                nuevos.append((s, detalle))
            s["acceso"] = "manual"
            s["ruta_pdf"] = str(p)
        else:
            invalidos.append((s, detalle))

    # Archivos sueltos que no corresponden a ninguna fuente cosechada.
    esperados = {nombre_archivo(s) for s in data["fuentes"]}
    huerfanos = [p.name for p in pdfs.glob("*.pdf") if p.name not in esperados]

    ruta_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nRevisión de {pdfs}\n" + "─" * 62)
    for s, d in nuevos:
        print(f"  [nuevo] {nombre_archivo(s)}  ({d})")
        print(f"          {s['titulo'][:64]}")
    for s, d in invalidos:
        print(f"  [MALO ] {nombre_archivo(s)}  → {d}")
    for h in huerfanos:
        print(f"  [suelto] {h} — nombre no coincide con ninguna fuente; renómbralo")

    total_ok = sum(1 for s in data["fuentes"]
                   if s.get("acceso") in ("pmc", "oa", "manual"))
    print("─" * 62)
    print(f"{len(nuevos)} incorporadas · {len(invalidos)} inválidas · {len(huerfanos)} sueltas")
    print(f"Texto completo disponible: {total_ok}/{len(data['fuentes'])} fuentes\n")
    return 1 if invalidos else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Gestiona PDFs aportados manualmente.")
    ap.add_argument("comando", choices=["listar", "revisar"])
    ap.add_argument("proyecto", help="Directorio que contiene fuentes/fuentes.json")
    ap.add_argument("--top", type=int, default=12, help="Cuántas priorizar (default 12)")
    a = ap.parse_args()
    d = Path(a.proyecto).expanduser()
    return cmd_listar(d, a.top) if a.comando == "listar" else cmd_revisar(d)


if __name__ == "__main__":
    sys.exit(main())

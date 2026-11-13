#!/usr/bin/env python3
"""fuentes_locales.py — Búsqueda en fuentes locales (agente 1): carpeta, Zotero y Obsidian.

Subcomandos:
  carpeta   Texto completo en PDF/DOCX/MD/TXT de una carpeta (con caché de extracción).
  zotero    Biblioteca Zotero: API local del escritorio (Zotero 7+, puerto 23119) y, si no
            responde, la API web (requiere ZOTERO_USER_ID + ZOTERO_API_KEY). Devuelve
            metadatos y la ruta local de los PDFs adjuntos cuando existe.
  obsidian  Notas .md de tu bóveda (OBSIDIAN_VAULT o --vault), con [[wikilink]] listo.
  guardar-obsidian  Copia un resumen/análisis a la bóveda. Nunca sobrescribe salvo
            --sobrescribir (gate de acción irreversible: el orquestador pide confirmación).

Uso:
    python3 scripts/fuentes_locales.py carpeta "efgartigimod MG-ADL" --ruta workspace/papers_locales
    python3 scripts/fuentes_locales.py zotero "myasthenia complement" --n 15
    python3 scripts/fuentes_locales.py obsidian "neuropatía de fibra fina"
    python3 scripts/fuentes_locales.py guardar-obsidian workspace/resumenes_papers/x.md \\
        --subcarpeta "Resumenes papers"

Añade --json a cualquier búsqueda para salida estructurada (la usan los agentes).

Configuración de Zotero: en el escritorio activa
  Ajustes > Avanzado > "Allow other applications on this computer to communicate with Zotero"
(el nombre exacto puede variar según versión). Prueba: curl http://localhost:23119/api/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _comun import RAIZ, http_get, load_env, log  # noqa: E402
from extraer_texto import EXTENSIONES, extraer  # noqa: E402

ZOTERO_LOCAL = "http://localhost:23119/api/users/0"
ZOTERO_WEB = "https://api.zotero.org/users/{uid}"
CACHE = RAIZ / "workspace" / ".cache" / "textos"
CONTEXTO = 160  # caracteres a cada lado del fragmento


# --------------------------------------------------------------------- utilidades


def _plano(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def terminos(query: str) -> list[str]:
    """Frases entre comillas se tratan como un término; el resto, palabra a palabra."""
    frases = re.findall(r'"([^"]+)"', query)
    resto = re.sub(r'"[^"]+"', " ", query)
    return [_plano(t) for t in frases + resto.split() if len(t) > 1]


def puntuar(texto: str, terms: list[str], todos: bool = True) -> tuple[int, int]:
    """(puntaje, posición del primer hallazgo). Puntaje 0 = no coincide."""
    plano = _plano(texto)
    conteos = [plano.count(t) for t in terms]
    if not terms or (todos and not all(conteos)) or not any(conteos):
        return 0, -1
    primero = min(plano.find(t) for t, c in zip(terms, conteos, strict=True) if c)
    return sum(conteos), primero


def fragmento(texto: str, pos: int) -> tuple[str, str]:
    """(fragmento, página) alrededor de `pos`; la página sale de la marca [p. N] previa."""
    if pos < 0:
        return "", ""
    ini, fin = max(0, pos - CONTEXTO), min(len(texto), pos + CONTEXTO)
    marcas = re.findall(r"\[p\. (\d+)\]", texto[:pos])
    frag = re.sub(r"\s+", " ", texto[ini:fin]).strip()
    return ("…" if ini else "") + frag + ("…" if fin < len(texto) else ""), (
        marcas[-1] if marcas else ""
    )


def _texto_con_cache(ruta: Path) -> tuple[str, list[str]]:
    """Extrae texto reutilizando una caché por (ruta, mtime, tamaño)."""
    st = ruta.stat()
    clave = hashlib.sha1(f"{ruta.resolve()}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()
    cache = CACHE / f"{clave}.json"
    if cache.is_file():
        datos = json.loads(cache.read_text(encoding="utf-8"))
        return datos["texto"], datos["advertencias"]
    doc = extraer(ruta)
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"texto": doc.texto, "advertencias": doc.advertencias}, ensure_ascii=False),
        encoding="utf-8",
    )
    return doc.texto, doc.advertencias


# ------------------------------------------------------------------------ carpeta


def buscar_carpeta(raiz: Path, query: str, n: int = 20, todos: bool = True) -> list[dict[str, Any]]:
    terms = terminos(query)
    if not raiz.is_dir():
        raise RuntimeError(f"No existe la carpeta: {raiz}")
    hallazgos: list[dict[str, Any]] = []
    for ruta in sorted(raiz.rglob("*")):
        if ruta.suffix.lower() not in EXTENSIONES or not ruta.is_file():
            continue
        if any(p.startswith(".") for p in ruta.relative_to(raiz).parts):
            continue
        try:
            texto, advertencias = _texto_con_cache(ruta)
        except RuntimeError as exc:
            log.warning("omito %s: %s", ruta.name, exc)
            continue
        puntaje, pos = puntuar(texto, terms, todos)
        if puntaje:
            frag, pagina = fragmento(texto, pos)
            hallazgos.append(
                {
                    "archivo": str(ruta),
                    "puntaje": puntaje,
                    "pagina": pagina,
                    "fragmento": frag,
                    "advertencias": advertencias,
                }
            )
    return sorted(hallazgos, key=lambda h: -h["puntaje"])[:n]


# ------------------------------------------------------------------------- zotero


def _zotero_base() -> tuple[str, dict[str, str], str]:
    """Prueba la API local; si no responde y hay credenciales web, usa la web."""
    sonda = http_get(f"{ZOTERO_LOCAL}/items/top", {"limit": 1, "format": "json"}, intentos=1)
    if sonda is not None:  # [] = biblioteca vacía pero API viva
        return ZOTERO_LOCAL, {}, "local"
    uid, clave = os.environ.get("ZOTERO_USER_ID"), os.environ.get("ZOTERO_API_KEY")
    if uid and clave:
        return ZOTERO_WEB.format(uid=uid), {"Zotero-API-Key": clave}, "web"
    raise RuntimeError(
        "Zotero no responde en localhost:23119 (¿está abierto y con la API local activada?) "
        "y no hay ZOTERO_USER_ID/ZOTERO_API_KEY para la API web."
    )


def _ruta_adjunto(adj: dict[str, Any]) -> str:
    datos = adj.get("data", {})
    modo = datos.get("linkMode", "")
    if modo in ("imported_file", "imported_url") and datos.get("filename"):
        base = Path(os.environ.get("ZOTERO_DATA_DIR", "~/Zotero")).expanduser()
        return str(base / "storage" / adj.get("key", "") / datos["filename"])
    if modo == "linked_file":
        return datos.get("path", "")  # 'attachments:...' es relativo al directorio base
    return ""


def parse_zotero_item(item: dict[str, Any]) -> dict[str, Any]:
    d = item.get("data", {})
    autores = [
        c.get("lastName") or c.get("name") or ""
        for c in d.get("creators", [])
        if c.get("creatorType", "author") == "author"
    ]
    anio = re.search(r"\b(1[89]\d\d|20\d\d)\b", d.get("date", ""))
    return {
        "zotero_key": item.get("key", ""),
        "titulo": d.get("title", ""),
        "autores": [a for a in autores if a],
        "anio": anio.group(1) if anio else "",
        "revista": d.get("publicationTitle", ""),
        "doi": (d.get("DOI") or "").lower(),
        "abstract": d.get("abstractNote", ""),
        "tags": [t.get("tag") for t in d.get("tags", []) if t.get("tag")],
        "pdfs": [],
    }


def buscar_zotero(query: str, n: int = 20) -> tuple[list[dict[str, Any]], str]:
    base, headers, modo = _zotero_base()
    params = {"q": query, "qmode": "everything", "limit": min(n, 100), "format": "json"}
    items = http_get(f"{base}/items/top", params, headers=headers) or []
    resultados = []
    for item in items:
        reg = parse_zotero_item(item)
        hijos = (
            http_get(
                f"{base}/items/{reg['zotero_key']}/children", {"format": "json"}, headers=headers
            )
            or []
        )
        for adj in hijos:
            datos = adj.get("data", {})
            if datos.get("itemType") == "attachment" and "pdf" in datos.get("contentType", ""):
                ruta = _ruta_adjunto(adj)
                if ruta:
                    reg["pdfs"].append(ruta)
        resultados.append(reg)
    return resultados, modo


# ----------------------------------------------------------------------- obsidian


def _vault(arg: str | None) -> Path:
    valor = arg or os.environ.get("OBSIDIAN_VAULT")
    if not valor:
        raise RuntimeError("Define OBSIDIAN_VAULT en tu .env o pasa --vault /ruta/a/la/boveda")
    ruta = Path(valor).expanduser()
    if not ruta.is_dir():
        raise RuntimeError(f"La bóveda no existe: {ruta}")
    return ruta


def buscar_obsidian(vault: Path, query: str, n: int = 20) -> list[dict[str, Any]]:
    terms = terminos(query)
    hallazgos = []
    for nota in vault.rglob("*.md"):
        relativa = nota.relative_to(vault)
        if any(p.startswith(".") for p in relativa.parts):
            continue  # .obsidian/, .trash/
        texto = nota.read_text(encoding="utf-8", errors="replace")
        puntaje, pos = puntuar(f"{nota.stem}\n{texto}", terms)
        if puntaje:
            frag, _ = fragmento(texto, max(0, pos - len(nota.stem) - 1))
            hallazgos.append(
                {
                    "nota": str(relativa),
                    "wikilink": f"[[{nota.stem}]]",
                    "puntaje": puntaje,
                    "fragmento": frag,
                }
            )
    return sorted(hallazgos, key=lambda h: -h["puntaje"])[:n]


def guardar_obsidian(
    archivo: Path, vault: Path, subcarpeta: str, sobrescribir: bool = False
) -> Path:
    if not archivo.is_file():
        raise RuntimeError(f"No existe el archivo a guardar: {archivo}")
    destino_dir = (vault / subcarpeta).resolve()
    if vault.resolve() not in destino_dir.parents and destino_dir != vault.resolve():
        raise RuntimeError("La subcarpeta debe quedar dentro de la bóveda.")
    destino = destino_dir / archivo.name
    if destino.exists() and not sobrescribir:
        raise FileExistsError(
            f"Ya existe {destino}. No se sobrescribe sin --sobrescribir (requiere tu confirmación)."
        )
    destino_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(archivo, destino)
    return destino


# --------------------------------------------------------------------------- CLI


def _imprimir(filas: list[dict[str, Any]], columnas: list[str], como_json: bool) -> None:
    if como_json:
        print(json.dumps(filas, ensure_ascii=False, indent=2))
        return
    if not filas:
        print("Sin coincidencias.")
        return
    print("| # | " + " | ".join(columnas) + " |")
    print("|---|" + "---|" * len(columnas))
    for i, f in enumerate(filas, 1):
        celdas = []
        for c in columnas:
            v = f.get(c, "")
            v = ", ".join(map(str, v[:3])) if isinstance(v, list) else str(v)
            celdas.append(v.replace("|", "/").replace("\n", " ")[:180])
        print(f"| {i} | " + " | ".join(celdas) + " |")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Búsqueda en carpeta local, Zotero y Obsidian.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("carpeta", help="Texto completo en una carpeta de PDF/DOCX/MD")
    c.add_argument("query")
    c.add_argument("--ruta", default=str(RAIZ / "workspace" / "papers_locales"))
    c.add_argument("--n", type=int, default=20)
    c.add_argument("--cualquiera", action="store_true", help="OR en vez de AND entre términos")
    c.add_argument("--json", action="store_true")

    z = sub.add_parser("zotero", help="Biblioteca Zotero (API local o web)")
    z.add_argument("query")
    z.add_argument("--n", type=int, default=20)
    z.add_argument("--json", action="store_true")

    o = sub.add_parser("obsidian", help="Notas de la bóveda de Obsidian")
    o.add_argument("query")
    o.add_argument("--vault")
    o.add_argument("--n", type=int, default=20)
    o.add_argument("--json", action="store_true")

    g = sub.add_parser("guardar-obsidian", help="Copia un .md a la bóveda (sin sobrescribir)")
    g.add_argument("archivo")
    g.add_argument("--vault")
    g.add_argument("--subcarpeta", default="Resumenes papers")
    g.add_argument("--sobrescribir", action="store_true")

    args = ap.parse_args(argv)
    load_env()
    try:
        if args.cmd == "carpeta":
            filas = buscar_carpeta(
                Path(args.ruta).expanduser(), args.query, args.n, todos=not args.cualquiera
            )
            _imprimir(filas, ["archivo", "pagina", "puntaje", "fragmento"], args.json)
        elif args.cmd == "zotero":
            filas, modo = buscar_zotero(args.query, args.n)
            log.info("Zotero vía API %s: %d ítems", modo, len(filas))
            _imprimir(filas, ["titulo", "autores", "anio", "doi", "pdfs"], args.json)
        elif args.cmd == "obsidian":
            filas = buscar_obsidian(_vault(args.vault), args.query, args.n)
            _imprimir(filas, ["wikilink", "nota", "puntaje", "fragmento"], args.json)
        else:
            destino = guardar_obsidian(
                Path(args.archivo).expanduser(),
                _vault(args.vault),
                args.subcarpeta,
                args.sobrescribir,
            )
            print(f"Guardado en {destino}")
    except FileExistsError as exc:
        log.error("%s", exc)
        return 2
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

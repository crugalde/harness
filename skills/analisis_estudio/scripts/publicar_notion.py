#!/usr/bin/env python3
"""publicar_notion.py — Publica la ficha crítica en Notion sin intervención humana.

Este es el paso que convierte a `analisis_estudio` en una skill que **termina sola**:
al invocarla, la ficha aparece como fila nueva en la base «Resumen de estudios»
(dentro de 📚 Biblioteca de Investigación), con sus trece propiedades pobladas y el
cuerpo completo renderizado. No pregunta dónde publicar: el destino es fijo.

Qué hace, en orden:

  1. **Valida** el `metadatos.json` contra el esquema **vivo** de la base. Un valor de
     `select` que no existe (una patología nueva, por ejemplo) **detiene la
     publicación** en vez de inventar la opción — es la regla que la propia base
     declara en la descripción de `Patología`.
  2. **Exige metadatos verificados.** Sin `verificado: true` no publica. Con
     `--sin-verificar` publica igual, pero estampa en la ficha el aviso de
     METADATOS NUNCA VERIFICADOS, para que el lector no confunda una ficha
     contrastada contra Crossref/PubMed con una que no lo está.
  3. **Es idempotente.** Busca por DOI/PMID antes de crear. Si la ficha ya existe,
     actualiza propiedades y reemplaza el cuerpo en lugar de duplicar la fila.
     Volver a correr la skill sobre el mismo paper no ensucia la base.
  4. **Enlaza de vuelta.** Si el paper venía de la base «Actualización de estudio»,
     escribe la URL de la ficha en su campo `Link de análisis` y lo marca cerrado.

Dos vías de salida, según lo que haya en el entorno:

  - **REST** (`NOTION_TOKEN` presente): publica directamente. Es la vía automática.
  - **MCP** (sin token): emite `payload_notion.json`, listo para `notion-create-pages`.
    El agente hace una sola llamada con ese payload — ninguna decisión pendiente.

Uso:
    python3 publicar_notion.py ficha.md --metadatos metadatos.json
    python3 publicar_notion.py ficha.md --metadatos metadatos.json --dry-run
    python3 publicar_notion.py ficha.md --metadatos metadatos.json --payload-mcp payload.json

Solo biblioteca estándar. `NOTION_TOKEN` se lee de ~/.config/harness/.env
(vía tools/env_loader.py) o del entorno. Nunca se pide por el chat ni se imprime.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from notion_md import a_bloques, trocear  # noqa: E402

try:                                       # el harness carga el .env fuera de iCloud
    from env_loader import load_env
    load_env()
except Exception:                          # sin env_loader seguimos con os.environ
    pass

API = "https://api.notion.com/v1"
VERSION_API = "2022-06-28"

# Destino fijo: base «Resumen de estudios» dentro de 📚 Biblioteca de Investigación.
# Se puede sobreescribir por entorno para pruebas, nunca por argumento suelto.
DB_RESUMEN = os.environ.get("NOTION_DB_RESUMEN", "19f24c9a-7dc8-4fee-93df-0d940f21f84d")
DB_ACTUALIZACION = os.environ.get("NOTION_DB_ACTUALIZACION", "615808d0-0fbb-4b89-92b4-5b8ae4e96fca")
DS_RESUMEN = os.environ.get("NOTION_DS_RESUMEN", "075ef50d-5a72-4feb-9a8e-4a7cec98d1b8")

AVISO_SIN_VERIFICAR = (
    '<callout icon="⚠️" color="red_bg">\n'
    "\t**METADATOS NUNCA VERIFICADOS.** No hay `metadatos.json` verificado para este "
    "trabajo: ni el diseño, ni el título, ni el año, ni la revista se contrastaron "
    "contra Crossref/PubMed. Trata cada dato de identificación como provisional.\n"
    "</callout>\n"
)

# metadatos.json -> propiedad de la base. El tipo decide cómo se serializa.
CAMPOS: list[tuple[str, str, str]] = [
    ("titulo", "Título", "title"),
    ("autor", "Autor", "rich_text"),
    ("revista", "Revista", "rich_text"),
    ("aporte", "Aporte", "rich_text"),
    ("anio", "Año", "number"),
    ("tipo_estudio", "Tipo de estudio", "select"),
    ("patologia", "Patología", "select"),
    ("area", "Área", "select"),
    ("aspecto", "Aspecto", "select"),
    ("calidad", "Calidad", "select"),
    ("archivo_local", "Archivo", "url"),
]
OBLIGATORIOS = ["titulo", "autor", "anio", "revista", "tipo_estudio",
                "patologia", "area", "aspecto", "calidad", "aporte"]


class ErrorPublicacion(RuntimeError):
    """Falla que debe detener la publicación con un mensaje accionable."""


# --------------------------------------------------------------------------- HTTP

def _peticion(metodo: str, ruta: str, token: str, cuerpo: dict | None = None) -> dict:
    datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8") if cuerpo is not None else None
    req = urllib.request.Request(f"{API}{ruta}", data=datos, method=metodo, headers={
        "Authorization": f"Bearer {token}",
        "Notion-Version": VERSION_API,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", "replace")[:600]
        # El token nunca se imprime; el mensaje de Notion sí, que es lo accionable.
        raise ErrorPublicacion(f"{metodo} {ruta} -> HTTP {e.code}: {detalle}") from None
    except urllib.error.URLError as e:
        raise ErrorPublicacion(f"{metodo} {ruta} -> sin conexión: {e.reason}") from None


def token_notion() -> str | None:
    for clave in ("NOTION_TOKEN", "NOTION_API_KEY", "NOTION_SECRET"):
        if os.environ.get(clave):
            return os.environ[clave]
    return None


# --------------------------------------------------------------------------- validación

def _opciones(esquema: dict, propiedad: str) -> list[str]:
    prop = esquema.get(propiedad, {})
    return [o["name"] for o in prop.get(prop.get("type", ""), {}).get("options", [])]


def _parecidos(valor: str, opciones: list[str], n: int = 3) -> list[str]:
    """Opciones más cercanas, para que el mensaje de error sea accionable."""
    import difflib
    return difflib.get_close_matches(valor, opciones, n=n, cutoff=0.4) or opciones[:n]


def validar(meta: dict, esquema: dict | None, *, sin_verificar: bool) -> list[str]:
    """Devuelve la lista de problemas. Vacía = se puede publicar."""
    problemas = []

    faltan = [c for c in OBLIGATORIOS if meta.get(c) in (None, "", [])]
    if faltan:
        problemas.append(
            f"faltan campos obligatorios en metadatos.json: {', '.join(faltan)}. "
            "«Patología» y «Aspecto» no se infieren: si el paper no los explicita, "
            "hay que preguntarle al usuario antes de publicar.")

    if not meta.get("doi") and not meta.get("pmid"):
        problemas.append("sin DOI ni PMID: la ficha quedaría sin enlace al estudio "
                         "y sin clave para detectar duplicados.")

    verificado = bool(meta.get("verificacion", {}).get("verificado"))
    if not verificado and not sin_verificar:
        problemas.append(
            "metadatos NO verificados contra Crossref/PubMed. Corre "
            "`verificar_metadatos.py` primero, o publica con --sin-verificar "
            "(la ficha saldrá con el aviso de metadatos no verificados).")

    if esquema:                                  # validación contra el esquema vivo
        for clave, propiedad, tipo in CAMPOS:
            if tipo != "select" or not meta.get(clave):
                continue
            opciones = _opciones(esquema, propiedad)
            if opciones and meta[clave] not in opciones:
                problemas.append(
                    f"«{meta[clave]}» no es una opción válida de «{propiedad}». "
                    f"Cercanas: {', '.join(_parecidos(meta[clave], opciones))}. "
                    "Añade la opción a la base antes de publicar; no la inventes aquí.")
    return problemas


# --------------------------------------------------------------------------- propiedades

def url_paper(meta: dict) -> str:
    if meta.get("doi"):
        doi = str(meta["doi"]).strip()
        return doi if doi.startswith("http") else f"https://doi.org/{doi}"
    return f"https://pubmed.ncbi.nlm.nih.gov/{str(meta['pmid']).strip()}/"


def propiedades(meta: dict) -> dict[str, Any]:
    """metadatos.json -> objeto `properties` de la API REST."""
    props: dict[str, Any] = {}
    for clave, propiedad, tipo in CAMPOS:
        valor = meta.get(clave)
        if valor in (None, "", []):
            continue
        if tipo in ("title", "rich_text"):
            props[propiedad] = {tipo: [{"type": "text", "text": {"content": str(valor)[:2000]}}]}
        elif tipo == "number":
            props[propiedad] = {"number": int(valor)}
        elif tipo == "select":
            props[propiedad] = {"select": {"name": str(valor)}}
        elif tipo == "url":
            props[propiedad] = {"url": str(valor)}
    props["Paper"] = {"url": url_paper(meta)}
    return props


def propiedades_mcp(meta: dict) -> dict[str, Any]:
    """Las mismas propiedades en el formato plano que espera notion-create-pages."""
    props = {propiedad: meta[clave] for clave, propiedad, _ in CAMPOS
             if meta.get(clave) not in (None, "", [])}
    props["Paper"] = url_paper(meta)
    return props


# --------------------------------------------------------------------------- Notion

def esquema_base(token: str, base: str) -> dict:
    return _peticion("GET", f"/databases/{base}", token).get("properties", {})


def buscar_existente(token: str, meta: dict) -> str | None:
    """Devuelve el page_id de la ficha ya publicada para este paper, si la hay."""
    filtro = {"filter": {"property": "Paper", "url": {"equals": url_paper(meta)}},
              "page_size": 1}
    res = _peticion("POST", f"/databases/{DB_RESUMEN}/query", token, filtro)
    filas = res.get("results", [])
    return filas[0]["id"] if filas else None


def _vaciar(token: str, page_id: str) -> int:
    """Archiva los bloques actuales. Reemplazar es la única forma de actualizar cuerpo.

    Pagina hasta agotar: la API devuelve 100 hijos por página, y una ficha larga
    pasa de 100 bloques. Borrar solo la primera página dejaría la mitad del cuerpo
    viejo debajo del nuevo — el fallo silencioso que rompe la idempotencia.
    """
    ids: list[str] = []
    cursor = None
    while True:
        ruta = f"/blocks/{page_id}/children?page_size=100"
        if cursor:
            ruta += f"&start_cursor={cursor}"
        pagina = _peticion("GET", ruta, token)
        ids += [b["id"] for b in pagina.get("results", [])]
        if not pagina.get("has_more"):
            break
        cursor = pagina.get("next_cursor")

    for bid in ids:
        _peticion("DELETE", f"/blocks/{bid}", token)
    return len(ids)


def publicar(token: str, meta: dict, bloques: list[dict], *, forzar_nueva: bool) -> tuple[str, str, bool]:
    """Crea o actualiza la ficha. Devuelve (page_id, url, era_actualizacion)."""
    lotes = trocear(bloques)
    existente = None if forzar_nueva else buscar_existente(token, meta)

    if existente:
        _vaciar(token, existente)
        _peticion("PATCH", f"/pages/{existente}", token,
                  {"properties": propiedades(meta),
                   "icon": {"type": "emoji", "emoji": meta.get("icono", "📄")}})
        for lote in lotes:
            if lote:
                _peticion("PATCH", f"/blocks/{existente}/children", token, {"children": lote})
        pagina = _peticion("GET", f"/pages/{existente}", token)
        return existente, pagina.get("url", ""), True

    pagina = _peticion("POST", "/pages", token, {
        "parent": {"database_id": DB_RESUMEN},
        "icon": {"type": "emoji", "emoji": meta.get("icono", "📄")},
        "properties": propiedades(meta),
        "children": lotes[0],
    })
    for lote in lotes[1:]:
        _peticion("PATCH", f"/blocks/{pagina['id']}/children", token, {"children": lote})
    return pagina["id"], pagina.get("url", ""), False


def enlazar_origen(token: str, meta: dict, url_ficha: str) -> str | None:
    """Escribe el `Link de análisis` en la fila de «Actualización de estudio».

    Cierra el circuito de la vigilancia semanal: el paper que se marcó para
    descargar queda con su ficha enlazada, sin tener que buscarla a mano.
    """
    fila = meta.get("origen_actualizacion_id")
    if not fila:
        if not meta.get("doi") and not meta.get("pmid"):
            return None
        # Esa base guarda el DOI a veces como URL y a veces pelado, según quién
        # creó la fila. Probamos las dos formas antes de darlo por no encontrado.
        candidatos = []
        if meta.get("doi"):
            doi = str(meta["doi"]).strip()
            candidatos += [url_paper(meta), doi.replace("https://doi.org/", "")]
        for clave in candidatos:
            res = _peticion("POST", f"/databases/{DB_ACTUALIZACION}/query", token,
                            {"filter": {"property": "DOI", "url": {"equals": clave}},
                             "page_size": 1})
            filas = res.get("results", [])
            if filas:
                fila = filas[0]["id"]
                break
        if not fila and meta.get("pmid"):
            res = _peticion("POST", f"/databases/{DB_ACTUALIZACION}/query", token,
                            {"filter": {"property": "PMID",
                                        "rich_text": {"equals": str(meta["pmid"])}},
                             "page_size": 1})
            filas = res.get("results", [])
            fila = filas[0]["id"] if filas else None
        if not fila:
            return None
    _peticion("PATCH", f"/pages/{fila}", token,
              {"properties": {"Link de análisis": {"url": url_ficha}}})
    return fila


# --------------------------------------------------------------------------- main

def cuerpo_ficha(ficha: Path, meta: dict, *, sin_verificar: bool) -> str:
    """Cuerpo de la ficha: sin el H1 (va en la propiedad título) y con el aviso si toca."""
    import re
    texto = ficha.read_text(encoding="utf-8")
    texto = re.sub(r"^#\s+.+\n+", "", texto, count=1)     # el H1 duplicaría el título
    verificado = bool(meta.get("verificacion", {}).get("verificado"))
    if not verificado and sin_verificar:
        texto = AVISO_SIN_VERIFICAR + "\n" + texto
    return texto


def main() -> int:
    ap = argparse.ArgumentParser(description="Publica la ficha crítica en Notion.")
    ap.add_argument("ficha", help="ficha.md generada por la skill")
    ap.add_argument("--metadatos", required=True, help="metadatos.json verificado")
    ap.add_argument("--dry-run", action="store_true",
                    help="valida y resume, sin escribir nada en Notion")
    ap.add_argument("--payload-mcp", metavar="ARCHIVO",
                    help="escribe el payload para notion-create-pages y termina")
    ap.add_argument("--sin-verificar", action="store_true",
                    help="publica con metadatos no verificados, estampando el aviso")
    ap.add_argument("--forzar-nueva", action="store_true",
                    help="crea fila nueva aunque ya exista una para este DOI/PMID")
    a = ap.parse_args()

    ficha = Path(a.ficha).expanduser()
    meta = json.loads(Path(a.metadatos).expanduser().read_text(encoding="utf-8"))
    token = token_notion()

    # El esquema vivo manda: una opción añadida ayer se acepta hoy sin tocar el código.
    # Se valida también en la vía MCP: ahí es donde una opción inventada más daño
    # hace, porque el conector la crea sin protestar y fragmenta el filtro.
    esquema = None
    if token:
        try:
            esquema = esquema_base(token, DB_RESUMEN)
        except ErrorPublicacion as e:
            print(f"[aviso] no pude leer el esquema de la base ({e}); "
                  f"valido solo lo obligatorio.", file=sys.stderr)

    problemas = validar(meta, esquema, sin_verificar=a.sin_verificar)
    if problemas:
        print("NO SE PUBLICA. Corrige esto primero:", file=sys.stderr)
        for p in problemas:
            print(f"  · {p}", file=sys.stderr)
        return 1

    cuerpo = cuerpo_ficha(ficha, meta, sin_verificar=a.sin_verificar)
    bloques = a_bloques(cuerpo)
    lotes = trocear(bloques)

    if a.payload_mcp:
        payload = {
            "parent": {"type": "data_source_id", "data_source_id": DS_RESUMEN},
            "pages": [{"properties": propiedades_mcp(meta),
                       "content": cuerpo,
                       "icon": meta.get("icono", "📄")}],
        }
        Path(a.payload_mcp).expanduser().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"payload MCP -> {a.payload_mcp} · llama notion-create-pages con este objeto")
        return 0

    if a.dry_run or not token:
        motivo = "--dry-run" if a.dry_run else "sin NOTION_TOKEN en el entorno"
        print(f"[{motivo}] validación OK, no se escribió nada.")
        print(f"  destino : «Resumen de estudios» ({DB_RESUMEN})")
        print(f"  título  : {meta['titulo']}")
        print(f"  paper   : {url_paper(meta)}")
        print(f"  cuerpo  : {len(bloques)} bloques · {len(lotes)} peticiones")
        if not token:
            print("  Para publicar solo: añade NOTION_TOKEN a ~/.config/harness/.env, "
                  "o usa --payload-mcp y publica por el conector.", file=sys.stderr)
        return 0 if a.dry_run else 2

    page_id, url, actualizada = publicar(token, meta, bloques, forzar_nueva=a.forzar_nueva)
    verbo = "ACTUALIZADA" if actualizada else "PUBLICADA"
    print(f"{verbo}: {url}")
    print(f"  {len(bloques)} bloques · {len(lotes)} peticiones · página {page_id}")

    try:
        if enlazar_origen(token, meta, url):
            print("  enlace de vuelta escrito en «Actualización de estudio»")
    except ErrorPublicacion as e:
        # La ficha ya está publicada: el back-link es accesorio y no debe tumbar el paso.
        print(f"  [aviso] no pude escribir el back-link: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ErrorPublicacion as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

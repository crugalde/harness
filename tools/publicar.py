#!/usr/bin/env python3
"""publicar.py — Lleva una revisión a sus destinos: bóveda Obsidian y database de Notion.

Toma la salida de `tools/paper_review.py` (`revision.md` + `revision.json`) —o cualquier
Markdown— y la publica. Los dos destinos son distintos por naturaleza y se tratan distinto:

- **Obsidian** es una carpeta de archivos. Publicar es escribir un `.md` con front-matter
  YAML, copiar los adjuntos donde la bóveda los busca, y enlazar la nota desde un índice.
  Todo local, verificable, reversible.
- **Notion** es una API. Publicar es crear una página en una database, mapeando los datos
  de `revision.json` a **propiedades** (para poder filtrar y ordenar después) y el cuerpo
  a bloques. Sin propiedades, una database es una lista de páginas: el valor está en que
  el tema, la fecha, el nº de artículos y los PMIDs sean campos, no texto.

Solo stdlib: Notion se habla por HTTP con `urllib`, igual que el motor local en
`tools/backends.py`. Nada que instalar.

Uso:
  python tools/publicar.py obsidian revision/ --vault "C:/Users/Usuario/Obsidian/neuro"
  python tools/publicar.py notion   revision/ --database <id>
  python tools/publicar.py ambos    revision/ --dry-run
Env: OBSIDIAN_VAULT, OBSIDIAN_SUBCARPETA, NOTION_TOKEN, NOTION_DATABASE_ID
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from env_loader import load_env
    load_env()
except Exception:                                   # el harness corre sin .env local
    pass

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
MAX_BLOQUES_POR_LLAMADA = 100                       # límite de la API de Notion
MAX_TEXTO_POR_BLOQUE = 1900                         # el límite duro es 2000; margen


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
def leer_revision(origen: Path) -> tuple[str, dict, Path]:
    """Acepta una carpeta de `paper_review` o un `.md` suelto.

    Devuelve (markdown, datos, carpeta). `datos` viene de `revision.json` cuando existe;
    es lo que permite rellenar propiedades de Notion en vez de publicar un muro de texto.
    """
    origen = Path(origen).expanduser()
    if origen.is_file() and origen.suffix.lower() == ".md":
        return origen.read_text(encoding="utf-8"), {}, origen.parent
    if not origen.is_dir():
        raise RuntimeError(f"No existe (o no es .md ni carpeta): {origen}")

    md = origen / "revision.md"
    if not md.is_file():
        candidatos = sorted(origen.glob("*.md"))
        if not candidatos:
            raise RuntimeError(f"No hay ningún .md en {origen}")
        md = candidatos[0]
    datos = {}
    js = origen / "revision.json"
    if js.is_file():
        try:
            datos = json.loads(js.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"  aviso: {js.name} ilegible ({e}); publico sin propiedades",
                  file=sys.stderr)
    return md.read_text(encoding="utf-8"), datos, origen


def pmids_de(datos: dict) -> list[str]:
    """PMIDs verificados de la corrida. Solo los que la tool devolvió (R2)."""
    out: list[str] = []
    for paper in datos.get("papers", []):
        for p in (paper.get("ficha") or {}).get("pmids_citados") or []:
            if str(p) not in out:
                out.append(str(p))
    return out


# ---------------------------------------------------------------------------
# Obsidian
# ---------------------------------------------------------------------------
def slug(texto: str, tope: int = 80) -> str:
    """Nombre de archivo seguro en Windows y macOS, sin tildes ni caracteres prohibidos."""
    nfkd = unicodedata.normalize("NFKD", texto or "")
    limpio = "".join(c for c in nfkd if not unicodedata.combining(c))
    limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", limpio)
    limpio = re.sub(r"\s+", " ", limpio).strip(" .")
    return (limpio[:tope].strip() or "revision")


def front_matter(datos: dict, tema: str, origen: Path) -> str:
    """Front-matter YAML: lo que hace la nota buscable y filtrable dentro de la bóveda."""
    campos: list[str] = ["---", f'titulo: "{tema}"',
                         f"fecha: {datos.get('fecha') or date.today().isoformat()}",
                         "tipo: revision-literatura", "tags: [neuro, revision, paper]"]
    if datos.get("papers"):
        campos.append(f"articulos: {len(datos['papers'])}")
    pmids = pmids_de(datos)
    if pmids:
        campos.append("pmids: [" + ", ".join(pmids) + "]")
    modelos = datos.get("modelos") or {}
    if modelos:
        campos.append(f'modelos: "ficha={modelos.get("ficha","?")}, '
                      f'sintesis={modelos.get("sintesis","?")}"')
    if datos.get("costo_usd_estimado") is not None:
        campos.append(f"costo_usd: {datos['costo_usd_estimado']}")
    campos.append(f'origen: "{origen}"')
    campos.append("---")
    return "\n".join(campos) + "\n\n"


def publicar_obsidian(markdown: str, datos: dict, origen: Path, *, vault: Path,
                      subcarpeta: str = "Revisiones", tema: str = "",
                      indice: str = "Revisiones.md", dry_run: bool = False) -> dict:
    """Escribe la nota y sus adjuntos en la bóveda. No toca nada fuera de `subcarpeta`.

    Las imágenes se copian a `<subcarpeta>/adjuntos/` y los enlaces del Markdown se
    reescriben a esa ruta: si se dejaran apuntando a `imagenes/`, la nota se vería bien
    en el editor de origen y con las figuras rotas dentro de Obsidian, que es el sitio
    donde alguien la va a leer.
    """
    vault = Path(vault).expanduser()
    if not vault.is_dir():
        raise RuntimeError(f"La bóveda no existe: {vault}")

    tema = tema or datos.get("tema") or "Revisión de literatura"
    destino_dir = vault / subcarpeta
    adjuntos_dir = destino_dir / "adjuntos"
    nombre = f"{datos.get('fecha') or date.today().isoformat()} {slug(tema)}.md"
    nota = destino_dir / nombre

    # --- adjuntos: copiar y reescribir los enlaces ---
    copiados: list[str] = []
    img_origen = origen / "imagenes"
    cuerpo = markdown
    if img_origen.is_dir():
        for img in sorted(p for p in img_origen.iterdir() if p.is_file()):
            # Sin espacios: `![](ruta con espacios.png)` no es Markdown válido y la
            # figura se ve rota dentro de Obsidian, aunque el archivo esté copiado.
            unico = f"{slug(tema, 40).replace(' ', '-')}-{img.name}"
            if not dry_run:
                adjuntos_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(img, adjuntos_dir / unico)
            cuerpo = cuerpo.replace(f"imagenes/{img.name}", f"adjuntos/{unico}")
            copiados.append(unico)

    texto = front_matter(datos, tema, origen) + cuerpo
    if not dry_run:
        destino_dir.mkdir(parents=True, exist_ok=True)
        nota.write_text(texto, encoding="utf-8")

    # --- índice: un enlace por nota, sin duplicar si se republica ---
    enlace = f"- [[{nombre[:-3]}]] — {date.today().isoformat()}"
    ruta_indice = destino_dir / indice
    indice_tocado = False
    if not dry_run:
        previo = ruta_indice.read_text(encoding="utf-8") if ruta_indice.is_file() else \
            f"# {subcarpeta}\n\nNotas publicadas por el harness.\n\n"
        if f"[[{nombre[:-3]}]]" not in previo:
            ruta_indice.write_text(previo.rstrip() + "\n" + enlace + "\n", encoding="utf-8")
            indice_tocado = True

    return {"nota": nota, "adjuntos": copiados, "indice": ruta_indice,
            "indice_actualizado": indice_tocado, "caracteres": len(texto),
            "dry_run": dry_run}


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------
def _notion(metodo: str, ruta: str, payload: dict | None, token: str) -> dict:
    req = urllib.request.Request(
        f"{NOTION_API}{ruta}",
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Authorization": f"Bearer {token}",
                 "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"},
        method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = e.read()[:500].decode("utf-8", "replace")
        raise RuntimeError(f"Notion respondió {e.code}: {detalle}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"No pude hablar con Notion: {e}") from e


def _trozos(texto: str, tope: int = MAX_TEXTO_POR_BLOQUE) -> list[str]:
    """Parte un texto largo en trozos que la API acepta, cortando por espacios."""
    if len(texto) <= tope:
        return [texto]
    out, resto = [], texto
    while len(resto) > tope:
        corte = resto.rfind(" ", 0, tope)
        corte = corte if corte > tope // 2 else tope
        out.append(resto[:corte])
        resto = resto[corte:].lstrip()
    if resto:
        out.append(resto)
    return out


def markdown_a_bloques(markdown: str) -> list[dict]:
    """Markdown -> bloques de Notion. Cubre lo que produce `paper_review`.

    Encabezados, viñetas, citas, tablas (como bloque de código, que preserva la
    alineación mejor que una tabla de Notion mal mapeada) y párrafos. Lo que no reconoce
    va como párrafo: se prefiere texto plano legible a perder contenido.
    """
    def rich(t: str) -> list[dict]:
        return [{"type": "text", "text": {"content": t}}]

    bloques: list[dict] = []
    buffer_tabla: list[str] = []

    def cerrar_tabla():
        if buffer_tabla:
            texto_tabla = "\n".join(buffer_tabla)[:MAX_TEXTO_POR_BLOQUE]
            bloques.append({"object": "block", "type": "code",
                            "code": {"language": "markdown",
                                     "rich_text": rich(texto_tabla)}})
            buffer_tabla.clear()

    for linea in markdown.splitlines():
        s = linea.rstrip()
        if s.startswith("|"):
            buffer_tabla.append(s)
            continue
        cerrar_tabla()
        if not s.strip() or s.startswith("<!--"):
            continue
        if s.startswith("### "):
            bloques.append({"object": "block", "type": "heading_3",
                            "heading_3": {"rich_text": rich(s[4:])}})
        elif s.startswith("## "):
            bloques.append({"object": "block", "type": "heading_2",
                            "heading_2": {"rich_text": rich(s[3:])}})
        elif s.startswith("# "):
            bloques.append({"object": "block", "type": "heading_1",
                            "heading_1": {"rich_text": rich(s[2:])}})
        elif s.startswith(("- ", "* ")):
            item = s[2:][:MAX_TEXTO_POR_BLOQUE]
            bloques.append({"object": "block", "type": "bulleted_list_item",
                            "bulleted_list_item": {"rich_text": rich(item)}})
        elif s.startswith("> "):
            bloques.append({"object": "block", "type": "quote",
                            "quote": {"rich_text": rich(s[2:][:MAX_TEXTO_POR_BLOQUE])}})
        else:
            for trozo in _trozos(s):
                bloques.append({"object": "block", "type": "paragraph",
                                "paragraph": {"rich_text": rich(trozo)}})
    cerrar_tabla()
    return bloques


# Rol semántico -> nombres de propiedad que lo pueden representar, en orden de
# preferencia. Se comprueban contra el esquema real: si la database no tiene ninguno,
# ese dato simplemente no se publica. Los nombres salen de la database
# "📄 Revisión de Literatura" del usuario; los alias en inglés son por portabilidad.
MAPA_PROPIEDADES: dict[str, tuple[str, tuple[str, ...]]] = {
    "fecha":    ("date",         ("Fecha publicación", "Fecha", "Date")),
    "pmids":    ("rich_text",    ("PMID", "PMIDs", "pmid")),
    "resumen":  ("rich_text",    ("Puntos a destacar", "Abstract", "Resumen")),
    "notas":    ("rich_text",    ("Notas personales", "Notas", "Notes")),
    "autores":  ("rich_text",    ("Autores", "Authors")),
    "enlace":   ("url",          ("Link de análisis", "DOI/Link", "URL")),
    "tipo":     ("select",       ("Tipo de publicación", "Tipo", "Type")),
    "temas":    ("multi_select", ("Temas", "Tags", "Etiquetas")),
}


def _opciones(prop: dict) -> set[str]:
    """Opciones ya existentes de un select/multi_select."""
    tipo = prop.get("type")
    return {o.get("name") for o in (prop.get(tipo, {}) or {}).get("options", [])}


def propiedades_notion(esquema: dict, datos: dict, tema: str,
                       resumen: str = "") -> dict:
    """Mapea la revisión al esquema real de la database.

    Dos reglas que evitan corromper una database curada a mano:

    1. **Solo se rellena lo que existe, con el tipo que tiene.** Una propiedad inventada
       o con el tipo cambiado hace que la API rechace la página entera.
    2. **Nunca se inventan opciones de select.** Enviar un valor nuevo a un `select` crea
       la opción en la database. Publicar con etiquetas improvisadas ensuciaría la lista
       de Temas de forma permanente y silenciosa, así que solo se usan las que ya están.
    """
    props_db = esquema.get("properties", {})
    valores: dict = {}

    # El título es obligatorio y su nombre lo decide la database.
    titulo = next((n for n, p in props_db.items() if p.get("type") == "title"), None)
    if not titulo:
        return {}
    valores[titulo] = {"title": [{"type": "text", "text": {"content": tema[:2000]}}]}

    def nombre_de(rol: str) -> tuple[str, str] | None:
        tipo, candidatos = MAPA_PROPIEDADES[rol]
        for n in candidatos:
            if props_db.get(n, {}).get("type") == tipo:
                return n, tipo
        return None

    def texto(rol: str, contenido: str):
        par = nombre_de(rol)
        if par and contenido:
            valores[par[0]] = {"rich_text": [{"type": "text",
                                              "text": {"content": contenido[:2000]}}]}

    if (par := nombre_de("fecha")):
        valores[par[0]] = {"date": {"start": datos.get("fecha") or date.today().isoformat()}}
    texto("pmids", ", ".join(pmids_de(datos)))
    texto("resumen", resumen)
    modelos = datos.get("modelos") or {}
    if modelos or datos.get("costo_usd_estimado") is not None:
        texto("notas", f"Generado por el harness · ficha={modelos.get('ficha','?')} · "
                       f"síntesis={modelos.get('sintesis','?')} · "
                       f"{len(datos.get('papers', []))} artículos · "
                       f"costo est. USD {datos.get('costo_usd_estimado', 0):.4f}")

    # select / multi_select: solo opciones que ya existen.
    if (par := nombre_de("tipo")):
        for candidata in ("Revisión", "Revision", "Otro"):
            if candidata in _opciones(props_db[par[0]]):
                valores[par[0]] = {"select": {"name": candidata}}
                break
    if (par := nombre_de("temas")):
        existentes = _opciones(props_db[par[0]])
        elegidas = [t for t in ("Revisión Sistemática", "Neurología", "Neuromuscular")
                    if t in existentes]
        if elegidas:
            valores[par[0]] = {"multi_select": [{"name": t} for t in elegidas]}
    return valores


def _aporte_neto(markdown: str) -> str:
    """Extrae la sección 'Aporte neto' de la síntesis, para la propiedad de resumen.

    Es la sección que responde 'qué sabemos ahora que no sabíamos'; en una vista de
    database es lo único que cabe y lo único que se lee de pasada.
    """
    m = re.search(r"^##\s*Aporte neto\s*$(.*?)(?=^##\s|\Z)", markdown,
                  re.MULTILINE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:2000]


def publicar_notion(markdown: str, datos: dict, *, database: str, token: str,
                    tema: str = "", dry_run: bool = False) -> dict:
    """Crea la página en la database. Devuelve su URL."""
    tema = tema or datos.get("tema") or "Revisión de literatura"
    bloques = markdown_a_bloques(markdown)

    if dry_run:
        return {"url": "(dry-run: no se creó nada)", "bloques": len(bloques),
                "propiedades": "(sin consultar el esquema)", "dry_run": True}

    esquema = _notion("GET", f"/databases/{database}", None, token)
    props = propiedades_notion(esquema, datos, tema, resumen=_aporte_neto(markdown))
    if not props:
        raise RuntimeError("La database no expone ninguna propiedad reconocible "
                           "(¿está compartida con la integración?)")

    pagina = _notion("POST", "/pages",
                     {"parent": {"database_id": database}, "properties": props,
                      "children": bloques[:MAX_BLOQUES_POR_LLAMADA]}, token)

    # El resto de los bloques va en tandas: la API solo acepta 100 por llamada.
    restantes = bloques[MAX_BLOQUES_POR_LLAMADA:]
    for i in range(0, len(restantes), MAX_BLOQUES_POR_LLAMADA):
        _notion("PATCH", f"/blocks/{pagina['id']}/children",
                {"children": restantes[i:i + MAX_BLOQUES_POR_LLAMADA]}, token)

    return {"url": pagina.get("url", ""), "bloques": len(bloques),
            "propiedades": sorted(props), "dry_run": False}


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Publica una revisión en Obsidian y/o Notion.")
    ap.add_argument("destino", choices=["obsidian", "notion", "ambos"])
    ap.add_argument("origen", help="Carpeta de paper_review, o un .md suelto.")
    ap.add_argument("--tema", default="", help="Título (por defecto, el de revision.json).")
    ap.add_argument("--vault", default=os.environ.get("OBSIDIAN_VAULT", ""),
                    help="Ruta de la bóveda Obsidian (o env OBSIDIAN_VAULT).")
    ap.add_argument("--subcarpeta", default=os.environ.get("OBSIDIAN_SUBCARPETA", "Revisiones"),
                    help="Subcarpeta dentro de la bóveda.")
    ap.add_argument("--database", default=os.environ.get("NOTION_DATABASE_ID", ""),
                    help="Id de la database de Notion (o env NOTION_DATABASE_ID).")
    ap.add_argument("--dry-run", action="store_true", help="Mostrar sin escribir ni publicar.")
    a = ap.parse_args()

    try:
        markdown, datos, carpeta = leer_revision(Path(a.origen))
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    tema = a.tema or datos.get("tema") or Path(a.origen).name
    fallos = 0

    if a.destino in ("obsidian", "ambos"):
        if not a.vault:
            print("ERROR: falta --vault (o OBSIDIAN_VAULT).", file=sys.stderr)
            fallos += 1
        else:
            try:
                r = publicar_obsidian(markdown, datos, carpeta, vault=Path(a.vault),
                                      subcarpeta=a.subcarpeta, tema=tema, dry_run=a.dry_run)
                print(f"Obsidian{' (dry-run)' if a.dry_run else ''}: {r['nota']}")
                print(f"  {r['caracteres']:,} caracteres · {len(r['adjuntos'])} adjuntos"
                      f"{' · índice actualizado' if r['indice_actualizado'] else ''}")
            except RuntimeError as e:
                print(f"ERROR Obsidian: {e}", file=sys.stderr)
                fallos += 1

    if a.destino in ("notion", "ambos"):
        token = os.environ.get("NOTION_TOKEN", "")
        if not a.database or not (token or a.dry_run):
            print("ERROR: falta --database y/o NOTION_TOKEN en el entorno.", file=sys.stderr)
            fallos += 1
        else:
            try:
                r = publicar_notion(markdown, datos, database=a.database, token=token,
                                    tema=tema, dry_run=a.dry_run)
                print(f"Notion{' (dry-run)' if a.dry_run else ''}: {r['url']}")
                print(f"  {r['bloques']} bloques · propiedades: {r['propiedades']}")
            except RuntimeError as e:
                print(f"ERROR Notion: {e}", file=sys.stderr)
                fallos += 1

    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
